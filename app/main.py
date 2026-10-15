from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, Response
from app.database import engine, Base, SessionLocal
from app.auth import init_default_users
from app.routes import auth_routes, movie_routes, stream_routes, admin_routes, superadmin_routes

import asyncio
from app.config import settings
from app.models import DriveFolder
from app.gdrive import extract_folder_id, fetch_folder_metadata
from app.routes.admin_routes import perform_sync_folder

async def init_default_folders(db: SessionLocal):
    folder_url = settings.DEFAULT_DRIVE_FOLDER_URL
    if not folder_url:
        return
    folder_id = extract_folder_id(folder_url)
    if not folder_id:
        return
    existing = db.query(DriveFolder).filter(DriveFolder.folder_id == folder_id).first()
    if not existing:
        meta = await fetch_folder_metadata(folder_id, db)
        name = meta.get("name") or "GDFlix (Cinema Vault)"
        folder = DriveFolder(
            folder_id=folder_id,
            folder_name=name,
            folder_url=folder_url
        )
        db.add(folder)
        db.commit()
        db.refresh(folder)
        print(f"[STARTUP] Registered default Google Drive folder: {folder.folder_name} ({folder_id})")
        asyncio.create_task(perform_sync_folder(folder.id, SessionLocal))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist, default users and default Google Drive folder are configured
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_default_users(db)
        await init_default_folders(db)
        from app.tmdb import enrich_all_missing_movies
        asyncio.create_task(enrich_all_missing_movies(SessionLocal))
    finally:
        db.close()
    yield
    # Shutdown logic if any

app = FastAPI(
    title="FilmsOverWeb - Cloud Cinema OTT",
    description="Stream movies directly from Google Drive in full quality (HEVC, AV1) with TMDB metadata enrichment and role-based access.",
    version="1.0.0",
    lifespan=lifespan
)

# Mount Static Assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("app/static/img/favicon.ico")

# Health check endpoints for Render, cloud port scanners, and container probes
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/ping", methods=["GET", "HEAD"], include_in_schema=False)
async def health_check():
    return Response(content="ok", media_type="text/plain", status_code=200)

@app.head("/", include_in_schema=False)
async def head_root():
    return Response(content="", media_type="text/html", status_code=200)

# Mount Routers
app.include_router(auth_routes.router)
app.include_router(movie_routes.router)
app.include_router(stream_routes.router)
app.include_router(admin_routes.router)
app.include_router(superadmin_routes.router)

# Custom exception handler for 401s on web requests
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return RedirectResponse(url=f"/login?next={request.url.path}")
