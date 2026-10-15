from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException, BackgroundTasks, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.database import get_db, Session
from app.models import User, DriveFolder, Movie
from app.auth import get_current_user, require_role, get_password_hash
from app.gdrive import extract_folder_id, list_files_in_drive_folder, fetch_folder_metadata
from app.parser import parse_filename
from app.tmdb import enrich_movie_data, get_active_tmdb_key
from app.mailer import generate_secure_password, send_guest_welcome_email

router = APIRouter(prefix="/admin", tags=["Admin Portal"])
templates = Jinja2Templates(directory="app/templates")

# Role dependency: Admin or SuperAdmin
admin_only = require_role(["admin", "superadmin"])

@router.get("/folders", response_class=HTMLResponse)
async def list_folders(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    folders = db.query(DriveFolder).all()
    total_movies = db.query(Movie).count()
    return templates.TemplateResponse(
        request=request,
        name="admin/folders.html",
        context={
            "user": user,
            "folders": folders,
            "total_movies": total_movies,
            "message": None,
            "error": None
        }
    )

@router.post("/folders/add")
async def add_folder(
    request: Request,
    folder_input: str = Form(...),
    custom_name: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    folder_id = extract_folder_id(folder_input)
    if not folder_id:
        folders = db.query(DriveFolder).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/folders.html",
            context={
                "user": user,
                "folders": folders,
                "total_movies": db.query(Movie).count(),
                "error": "Invalid Google Drive folder URL or ID. Please provide a valid link."
            },
            status_code=400
        )

    # Check if already added
    existing = db.query(DriveFolder).filter(DriveFolder.folder_id == folder_id).first()
    if existing:
        folders = db.query(DriveFolder).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/folders.html",
            context={
                "user": user,
                "folders": folders,
                "total_movies": db.query(Movie).count(),
                "error": f"Folder '{existing.folder_name or folder_id}' is already registered."
            },
            status_code=400
        )

    # Fetch folder title from Google Drive or use custom name
    meta = await fetch_folder_metadata(folder_id, db)
    folder_name = custom_name.strip() if custom_name and custom_name.strip() else meta.get("name", f"Drive Folder ({folder_id[:8]})")

    new_folder = DriveFolder(
        folder_id=folder_id,
        folder_name=folder_name,
        folder_url=folder_input.strip(),
        created_by_id=user.id
    )
    db.add(new_folder)
    db.commit()

    return RedirectResponse(url="/admin/folders", status_code=status.HTTP_302_FOUND)

@router.post("/folders/{folder_id}/delete")
async def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    folder = db.query(DriveFolder).filter(DriveFolder.id == folder_id).first()
    if folder:
        db.delete(folder)
        db.commit()
    return RedirectResponse(url="/admin/folders", status_code=status.HTTP_302_FOUND)

async def perform_sync_folder(folder_db_id: int, db_factory):
    """Background task to sync movies from Google Drive folder and enrich via TMDB."""
    db = db_factory()
    try:
        folder = db.query(DriveFolder).filter(DriveFolder.id == folder_db_id).first()
        if not folder:
            return

        print(f"[SYNC] Starting scan for Google Drive Folder '{folder.folder_name}' ({folder.folder_id})...")
        files = await list_files_in_drive_folder(folder.folder_id, db)
        print(f"[SYNC] Found {len(files)} video files in folder.")

        tmdb_key = get_active_tmdb_key(db)

        synced_count = 0
        for f in files:
            gdrive_file_id = f["id"]
            filename = f["name"]

            # Check if movie already indexed
            movie = db.query(Movie).filter(Movie.gdrive_file_id == gdrive_file_id).first()
            if not movie:
                # Parse filename for title, year, codec, resolution
                parsed = parse_filename(filename)
                
                # Fetch TMDB metadata
                meta = await enrich_movie_data(parsed["title"], parsed["year"], tmdb_key)

                movie = Movie(
                    gdrive_file_id=gdrive_file_id,
                    folder_id=folder.id,
                    file_name=filename,
                    file_size=f.get("size", 0),
                    mime_type=f.get("mimeType", "video/mp4"),
                    codec=parsed["codec"],
                    resolution=parsed["resolution"],
                    tmdb_id=meta["tmdb_id"],
                    title=meta["title"],
                    original_title=meta["original_title"],
                    year=meta["year"],
                    overview=meta["overview"],
                    tagline=meta["tagline"],
                    poster_path=meta["poster_path"],
                    backdrop_path=meta["backdrop_path"],
                    rating=meta["rating"],
                    vote_count=meta["vote_count"],
                    duration=meta["duration"],
                    genres=meta["genres"],
                    cast=meta["cast"],
                    director=meta["director"],
                    trailer_url=meta["trailer_url"],
                    original_language=meta.get("original_language", "English")
                )
                db.add(movie)
                synced_count += 1
            else:
                # Update folder linkage if changed
                if movie.folder_id != folder.id:
                    movie.folder_id = folder.id

        folder.movie_count = db.query(Movie).filter(Movie.folder_id == folder.id).count()
        folder.last_synced_at = datetime.now(timezone.utc)
        db.commit()
        print(f"[SYNC] Successfully synced folder '{folder.folder_name}'. Added {synced_count} new movies.")
    except Exception as e:
        print(f"[SYNC] Error during folder sync: {e}")
        db.rollback()
    finally:
        db.close()

@router.post("/folders/{folder_id}/sync")
async def sync_folder(
    folder_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    from app.database import SessionLocal
    folder = db.query(DriveFolder).filter(DriveFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    background_tasks.add_task(perform_sync_folder, folder.id, SessionLocal)
    return RedirectResponse(url="/admin/folders?synced=started", status_code=status.HTTP_302_FOUND)

# --- Guest Management with Gmail Automation ---

@router.get("/guests", response_class=HTMLResponse)
async def list_guests(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    guests = db.query(User).filter(User.role == "guest").order_by(User.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/guests.html",
        context={
            "user": user,
            "guests": guests,
            "new_credentials": None,
            "mail_status": None,
            "error": None
        }
    )

@router.post("/guests/create")
async def create_guest(
    request: Request,
    email: str = Form(...),
    name: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    clean_email = email.strip().lower()
    
    # Check if user already exists
    existing = db.query(User).filter(User.email == clean_email).first()
    if existing:
        guests = db.query(User).filter(User.role == "guest").order_by(User.created_at.desc()).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/guests.html",
            context={
                "user": user,
                "guests": guests,
                "error": f"A user with email '{clean_email}' already exists with role '{existing.role}'."
            },
            status_code=400
        )

    # Auto-generate secure password
    raw_password = generate_secure_password(length=12)
    hashed = get_password_hash(raw_password)

    new_guest = User(
        email=clean_email,
        name=name.strip() if name and name.strip() else "Guest User",
        hashed_password=hashed,
        role="guest",
        is_active=True,
        must_change_password=True
    )
    db.add(new_guest)
    db.commit()
    db.refresh(new_guest)

    # Determine login URL for the guest
    base_url = str(request.base_url).rstrip("/")
    login_url = f"{base_url}/login"

    # Send Welcome Email using Google Mail automation (drmnbot@gmail.com)
    mail_ok, mail_msg = send_guest_welcome_email(
        guest_email=clean_email,
        guest_name=new_guest.name,
        password=raw_password,
        login_url=login_url,
        db=db
    )

    guests = db.query(User).filter(User.role == "guest").order_by(User.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/guests.html",
        context={
            "user": user,
            "guests": guests,
            "new_credentials": {
                "email": clean_email,
                "password": raw_password,
                "name": new_guest.name,
                "login_url": login_url
            },
            "mail_status": {
                "success": mail_ok,
                "message": mail_msg
            },
            "error": None
        }
    )

@router.post("/guests/{guest_id}/delete")
async def delete_guest(
    guest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    guest = db.query(User).filter(User.id == guest_id, User.role == "guest").first()
    if guest:
        db.delete(guest)
        db.commit()
    return RedirectResponse(url="/admin/guests", status_code=status.HTTP_302_FOUND)
