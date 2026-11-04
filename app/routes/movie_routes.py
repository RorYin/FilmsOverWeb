from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, timezone, timedelta
import secrets
from app.database import get_db, desc, Session, utc_now
from app.models import Movie, Series, Episode, WatchProgress, User, MovieSharePin
from app.auth import get_current_user, require_role, decode_access_token, create_access_token

router = APIRouter(tags=["Movies & Library"])
templates = Jinja2Templates(directory="app/templates")

def parse_res_num(r_str: Optional[str]) -> int:
    r = (r_str or "").lower()
    if "4k" in r or "2160" in r or "uhd" in r:
        return 2160
    elif "1080" in r or "fhd" in r:
        return 1080
    elif "720" in r or "hd" in r:
        return 720
    elif "480" in r or "sd" in r:
        return 480
    return 1080

def get_quality_versions(movie: Movie, db: Session):
    """
    Finds all available quality/resolution versions of the same movie in Google Drive library.
    Matches primarily by tmdb_id, or by normalized title and year.
    Returns list of dicts ordered from highest quality (4K/2160p) down to 1080p, 720p, etc.
    """
    if movie.tmdb_id:
        matches = db.query(Movie).filter(Movie.tmdb_id == movie.tmdb_id).all()
    elif movie.title and movie.year:
        matches = db.query(Movie).filter(
            Movie.title.ilike(movie.title.strip()),
            Movie.year == movie.year
        ).all()
    else:
        matches = db.query(Movie).filter(
            Movie.title.ilike(movie.title.strip())
        ).all()

    # Sort descending by resolution number, then by file size
    matches = sorted(
        matches,
        key=lambda m: (parse_res_num(m.resolution), m.file_size or 0),
        reverse=True
    )

    versions = []
    for m in matches:
        res_num = parse_res_num(m.resolution)
        size_gb = round(m.file_size / (1024 * 1024 * 1024), 2) if m.file_size else None
        size_str = f"{size_gb} GB" if size_gb else ""
        res_label = m.resolution or "HD"

        versions.append({
            "id": m.id,
            "resolution": res_label,
            "quality_val": res_num,
            "file_size": size_str,
            "codec": m.codec or "",
            "file_name": m.file_name,
            "gdrive_file_id": m.gdrive_file_id,
            "is_active": (m.id == movie.id)
        })

    return versions

def deduplicate_movies(movies_list):
    """
    Deduplicates multiple resolution files of the same movie for clean catalog views,
    keeping the highest quality version as primary.
    """
    seen = {}
    for m in movies_list:
        key = m.tmdb_id if m.tmdb_id else (m.title.lower().strip(), m.year)
        if key not in seen:
            seen[key] = m
        else:
            prev = seen[key]
            if (parse_res_num(m.resolution), m.file_size or 0) > (parse_res_num(prev.resolution), prev.file_size or 0):
                seen[key] = m
    return list(seen.values())

@router.get("/", response_class=HTMLResponse)
async def home_library(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # Continue Watching (supports both movies and TV episodes)
    continue_watching_records = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.completed == False,
        WatchProgress.position_seconds > 10
    ).order_by(desc(WatchProgress.updated_at)).limit(10).all()

    continue_watching = []
    for cw in continue_watching_records:
        if cw.is_episode and cw.episode:
            ep = cw.episode
            ser = ep.series
            series_title = ser.title if ser else "TV Series"
            percent = int((cw.position_seconds / cw.duration_seconds) * 100) if cw.duration_seconds > 0 else 0
            continue_watching.append({
                "is_episode": True,
                "episode": ep,
                "series": ser,
                "title": f"{series_title} - S{ep.season_number:02d}E{ep.episode_number:02d}",
                "subtitle": ep.title or f"Episode {ep.episode_number}",
                "watch_url": f"/watch/episode/{ep.id}",
                "poster_path": ep.still_path or (ser.poster_path if ser else None),
                "progress_percent": min(percent, 100),
                "position_seconds": cw.position_seconds
            })
        elif cw.movie:
            percent = int((cw.position_seconds / cw.duration_seconds) * 100) if cw.duration_seconds > 0 else 0
            continue_watching.append({
                "is_episode": False,
                "movie": cw.movie,
                "title": cw.movie.title,
                "subtitle": f"{cw.movie.year}" if cw.movie.year else "",
                "watch_url": f"/watch/{cw.movie.id}",
                "poster_path": cw.movie.poster_path,
                "progress_percent": min(percent, 100),
                "position_seconds": cw.position_seconds
            })

    # Recently Added Movies (deduplicated by title/TMDB)
    all_recent = deduplicate_movies(db.query(Movie).order_by(desc(Movie.created_at)).all())
    recently_added = all_recent[:15]

    # Recently Added TV Series
    all_series = db.query(Series).order_by(desc(Series.created_at)).all()
    recent_series = all_series[:15]

    # Top 10 recently added movies for rotating Hero Billboard (prefer movies with backdrop/poster)
    hero_movies = [m for m in all_recent if (m.backdrop_path or m.poster_path)][:10]
    if not hero_movies and all_recent:
        hero_movies = all_recent[:10]
    hero_movie = hero_movies[0] if hero_movies else None

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "hero_movie": hero_movie,
            "hero_movies": hero_movies,
            "continue_watching": continue_watching,
            "recently_added": recently_added,
            "recent_series": recent_series
        }
    )

@router.get("/movies", response_class=HTMLResponse)
async def browse_movies(
    request: Request,
    q: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    codec: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    query = db.query(Movie)

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        query = query.filter(
            (Movie.title.ilike(search_term)) |
            (Movie.cast.ilike(search_term)) |
            (Movie.director.ilike(search_term))
        )

    if genre and genre.strip():
        query = query.filter(Movie.genres.ilike(f"%{genre.strip()}%"))

    if codec and codec.strip():
        query = query.filter(Movie.codec == codec.strip())

    if sort == "rating":
        query = query.order_by(desc(Movie.rating))
    elif sort == "year":
        query = query.order_by(desc(Movie.year))
    elif sort == "title":
        query = query.order_by(Movie.title.asc())
    else:
        query = query.order_by(desc(Movie.created_at))

    movies = deduplicate_movies(query.all())

    # Collect all available genres for filter bar
    all_movies = db.query(Movie).all()
    genres_set = set()
    for m in all_movies:
        if m.genres:
            for g in m.genres.split(","):
                g_clean = g.strip()
                if g_clean:
                    genres_set.add(g_clean)

    return templates.TemplateResponse(
        request=request,
        name="movies.html",
        context={
            "user": user,
            "movies": movies,
            "q": q or "",
            "selected_genre": genre or "",
            "selected_codec": codec or "",
            "selected_sort": sort or "newest",
            "all_genres": sorted(list(genres_set))
        }
    )

@router.get("/movie/{movie_id}", response_class=HTMLResponse)
async def movie_detail(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    # Check user watch progress
    progress = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.movie_id == movie.id
    ).first()

    # Available quality versions in Google Drive
    quality_versions = get_quality_versions(movie, db)

    # Related movies (same genre)
    related = []
    if movie.genres:
        first_genre = movie.genres.split(",")[0].strip()
        raw_related = db.query(Movie).filter(
            Movie.id != movie.id,
            Movie.genres.ilike(f"%{first_genre}%")
        ).all()
        related = deduplicate_movies(raw_related)[:6]

    return templates.TemplateResponse(
        request=request,
        name="movie_detail.html",
        context={
            "user": user,
            "movie": movie,
            "progress": progress,
            "quality_versions": quality_versions,
            "related_movies": related
        }
    )

@router.get("/watch/{movie_id}", response_class=HTMLResponse)
async def watch_player(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    progress = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.movie_id == movie.id
    ).first()

    initial_time = progress.position_seconds if progress and not progress.completed else 0.0

    from app.auth import create_access_token
    from datetime import timedelta
    token_data = {"sub": user.email, "role": user.role}
    if getattr(user, "is_shared", False):
        token_data["is_shared"] = True
        token_data["shared_movie_id"] = movie.id
        token_data["share_token"] = getattr(user, "share_token", "")
    user_token = create_access_token(
        token_data,
        expires_delta=timedelta(hours=48) if getattr(user, "is_shared", False) else None
    )

    # Check if movie container or audio needs universal transmuxing
    filename_upper = movie.file_name.upper()
    is_mkv = movie.file_name.lower().endswith(".mkv")
    has_multichannel_audio = any(x in filename_upper for x in ["DD+", "DDP", "DTS", "TRUEHD", "ATMOS", "AC3", "EAC3"])
    needs_transmux = is_mkv or has_multichannel_audio

    # All available quality/resolution versions of this movie in Google Drive
    quality_versions = get_quality_versions(movie, db)

    from app.models import SystemSetting
    from app.config import settings
    cf_worker_row = db.query(SystemSetting).filter(SystemSetting.key == "cloudflare_worker_url").first()
    cloudflare_worker_url = cf_worker_row.value.strip() if cf_worker_row and cf_worker_row.value else settings.CLOUDFLARE_WORKER_URL

    google_api_key_row = db.query(SystemSetting).filter(SystemSetting.key == "google_api_key").first()
    google_api_key = google_api_key_row.value.strip() if google_api_key_row and google_api_key_row.value else settings.GOOGLE_API_KEY

    from app.gdrive import get_gdrive_access_token
    gdrive_access_token = get_gdrive_access_token(db)

    return templates.TemplateResponse(
        request=request,
        name="watch.html",
        context={
            "user": user,
            "movie": movie,
            "initial_time": initial_time,
            "user_token": user_token,
            "needs_transmux": needs_transmux,
            "quality_versions": quality_versions,
            "cloudflare_worker_url": cloudflare_worker_url,
            "google_api_key": google_api_key,
            "gdrive_access_token": gdrive_access_token or ""
        }
    )


# --- SuperAdmin Movie Share & 4-Digit PIN Access ---

def cleanup_expired_share_pins(db: Session):
    """Purge any share pin entries older than 48 hours."""
    now = utc_now()
    pins = db.query(MovieSharePin).all()
    changed = False
    for p in pins:
        if p.expires_at and p.expires_at < now:
            db.delete(p)
            changed = True
    if changed:
        db.commit()

@router.post("/api/superadmin/movies/{movie_id}/share")
async def generate_movie_share(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(["superadmin"]))
):
    """
    SuperAdmin generates a single-use shareable link with embedded PIN for this movie.
    The link stays active until hit by a recipient, which automatically unlocks 48-hour access on their browser,
    and immediately deletes the PIN backend-wide.
    """
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    cleanup_expired_share_pins(db)

    # 4-digit numeric PIN: "0000" to "9999"
    pin_code = f"{secrets.randbelow(10000):04d}"
    # Cryptographically secure URL-safe share token
    share_token = secrets.token_urlsafe(20)

    share_record = MovieSharePin(
        share_token=share_token,
        movie_id=movie.id,
        pin_code=pin_code,
        created_by_id=user.id,
        created_at=utc_now(),
        expires_at=None
    )
    db.add(share_record)
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    relative_url = f"/share/{share_token}?pin={pin_code}"
    share_url = f"{base_url}{relative_url}"

    return JSONResponse({
        "success": True,
        "share_token": share_token,
        "share_url": share_url,
        "relative_url": relative_url,
        "pin_code": pin_code,
        "movie_title": movie.title,
        "movie_year": movie.year
    })

@router.get("/share/{token}", response_class=HTMLResponse)
async def view_shared_movie(
    token: str,
    request: Request,
    pin: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Public entry point for a shared movie link.
    If the URL includes the 4-digit PIN (?pin=...), on first hit it:
    1. Unlocks lossless streaming on this browser for 48 hours (sets cookies).
    2. Immediately expires and deletes the PIN/link from the backend database.
    If already unlocked on this browser, renders with an active 48-hour pass.
    If not in DB and no active cookie, shows share_expired.html.
    """
    cleanup_expired_share_pins(db)

    # Check if this browser already has a valid 48-hour share cookie for this share/movie
    cookie_token = (
        request.cookies.get(f"fow_share_{token}") or
        request.cookies.get("fow_share_token") or
        request.query_params.get("share_token")
    )
    unlocked_payload = None
    if cookie_token:
        payload = decode_access_token(cookie_token)
        if payload and payload.get("is_shared") and (payload.get("share_token") == token or payload.get("shared_movie_id")):
            unlocked_payload = payload

    # If this browser already redeemed the PIN and has an active 48h cookie
    if unlocked_payload:
        movie_id = unlocked_payload.get("shared_movie_id")
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")

        shared_user = User(
            id=0,
            name="Shared Guest",
            email=unlocked_payload.get("sub", "shared_viewer@guest"),
            role="guest",
            is_active=True,
            must_change_password=False
        )
        setattr(shared_user, "is_shared", True)
        setattr(shared_user, "shared_movie_id", movie.id)
        setattr(shared_user, "share_token", token)

        quality_versions = get_quality_versions(movie, db)

        return templates.TemplateResponse(
            request=request,
            name="movie_detail.html",
            context={
                "user": shared_user,
                "movie": movie,
                "progress": None,
                "quality_versions": quality_versions,
                "related_movies": [],
                "is_share_page": True,
                "is_unlocked": True,
                "share_token": token
            }
        )

    # If not yet unlocked on this browser, look up the share in the DB
    share = db.query(MovieSharePin).filter(MovieSharePin.share_token == token).first()

    # If not found in DB and no cookie, the link either was already used on another browser or manually deleted
    if not share:
        return templates.TemplateResponse(
            request=request,
            name="share_expired.html",
            context={"request": request},
            status_code=404
        )

    if share.expires_at and share.expires_at < utc_now():
        db.delete(share)
        db.commit()
        return templates.TemplateResponse(
            request=request,
            name="share_expired.html",
            context={"request": request},
            status_code=410
        )

    movie = db.query(Movie).filter(Movie.id == share.movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    # If the URL contains the PIN and matches, immediately auto-unlock and consume/delete the PIN!
    if pin and str(pin).strip() == str(share.pin_code).strip():
        movie_id = share.movie_id
        # Consume and delete immediately from backend DB upon first hit
        db.delete(share)
        db.commit()

        # Create 48-hour access token for this browser
        share_payload = {
            "sub": f"shared_viewer_{token[:10]}",
            "role": "guest",
            "is_shared": True,
            "shared_movie_id": movie_id,
            "share_token": token
        }
        access_token = create_access_token(share_payload, expires_delta=timedelta(hours=48))
        max_age_48h = 48 * 3600

        shared_user = User(
            id=0,
            name="Shared Guest",
            email=f"shared_viewer_{token[:10]}",
            role="guest",
            is_active=True,
            must_change_password=False
        )
        setattr(shared_user, "is_shared", True)
        setattr(shared_user, "shared_movie_id", movie.id)
        setattr(shared_user, "share_token", token)

        quality_versions = get_quality_versions(movie, db)

        resp = templates.TemplateResponse(
            request=request,
            name="movie_detail.html",
            context={
                "user": shared_user,
                "movie": movie,
                "progress": None,
                "quality_versions": quality_versions,
                "related_movies": [],
                "is_share_page": True,
                "is_unlocked": True,
                "share_token": token
            }
        )
        resp.set_cookie(key=f"fow_share_{token}", value=access_token, max_age=max_age_48h, httponly=True, samesite="lax")
        resp.set_cookie(key=f"fow_share_movie_{movie_id}", value=access_token, max_age=max_age_48h, httponly=True, samesite="lax")
        resp.set_cookie(key="fow_share_token", value=access_token, max_age=max_age_48h, httponly=True, samesite="lax")
        return resp

    # If PIN was not in URL or incorrect, render locked details page where user can enter PIN manually
    shared_user = User(
        id=0,
        name="Shared Guest",
        email="guest@shared.link",
        role="guest",
        is_active=True,
        must_change_password=False
    )
    setattr(shared_user, "is_shared", True)
    setattr(shared_user, "shared_movie_id", movie.id)
    setattr(shared_user, "share_token", token)

    quality_versions = get_quality_versions(movie, db)

    return templates.TemplateResponse(
        request=request,
        name="movie_detail.html",
        context={
            "user": shared_user,
            "movie": movie,
            "progress": None,
            "quality_versions": quality_versions,
            "related_movies": [],
            "is_share_page": True,
            "is_unlocked": False,
            "share_token": token
        }
    )

@router.get("/share/{token}/{pin}", response_class=HTMLResponse)
async def view_shared_movie_path(
    token: str,
    pin: str,
    request: Request,
    db: Session = Depends(get_db)
):
    return await view_shared_movie(token=token, request=request, pin=pin, db=db)

@router.post("/api/share/{token}/verify")
async def verify_share_pin(
    token: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Validates the 4-digit PIN for a shared movie.
    Upon first correct entry:
    1. The PIN and share record are immediately EXPIRED & DELETED from database.
    2. A 48-hour secure authorization cookie is set for this browser.
    3. No other device or browser can ever reuse the PIN.
    """
    data = await request.json()
    entered_pin = str(data.get("pin", "")).strip()

    cleanup_expired_share_pins(db)

    share = db.query(MovieSharePin).filter(MovieSharePin.share_token == token).first()
    if not share:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "detail": "This share link has expired or has already been redeemed on another browser/device."
            }
        )

    if share.expires_at and share.expires_at < utc_now():
        db.delete(share)
        db.commit()
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "detail": "This share PIN has expired (48-hour validity limit)."
            }
        )

    if share.pin_code != entered_pin:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "detail": "Incorrect 4-digit PIN code. Please check and try again."
            }
        )

    # PIN matches! Immediately delete from backend database so it can never be used again.
    movie_id = share.movie_id
    db.delete(share)
    db.commit()

    # Create 48-hour browser access token
    share_payload = {
        "sub": f"shared_viewer_{token[:10]}",
        "role": "guest",
        "is_shared": True,
        "shared_movie_id": movie_id,
        "share_token": token
    }
    access_token = create_access_token(share_payload, expires_delta=timedelta(hours=48))

    max_age_48h = 48 * 3600

    resp = JSONResponse({
        "success": True,
        "message": "PIN verified successfully! 48-hour access enabled on this browser.",
        "token": access_token,
        "movie_id": movie_id,
        "watch_url": f"/watch/{movie_id}?share_token={access_token}"
    })

    # Set cookies on browser
    resp.set_cookie(
        key=f"fow_share_{token}",
        value=access_token,
        max_age=max_age_48h,
        httponly=True,
        samesite="lax"
    )
    resp.set_cookie(
        key=f"fow_share_movie_{movie_id}",
        value=access_token,
        max_age=max_age_48h,
        httponly=True,
        samesite="lax"
    )
    resp.set_cookie(
        key="fow_share_token",
        value=access_token,
        max_age=max_age_48h,
        httponly=True,
        samesite="lax"
    )

    return resp


