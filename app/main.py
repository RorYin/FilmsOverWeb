from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, Response
from app.database import engine, Base, SessionLocal
from app.auth import init_default_users
from app.routes import auth_routes, movie_routes, series_routes, stream_routes, admin_routes, superadmin_routes

import os
import re
import asyncio
from app.config import settings
from app.models import DriveFolder
from app.gdrive import extract_folder_id, fetch_folder_metadata
from app.routes.admin_routes import perform_sync_folder

async def init_default_folders(db: SessionLocal):
    raw_urls = os.getenv("DRIVE_FOLDER_URLS") or settings.DEFAULT_DRIVE_FOLDER_URL or ""
    if not raw_urls.strip():
        return

    url_list = [u.strip() for u in re.split(r'[,;\n\r]+', raw_urls) if u.strip()]

    for folder_url in url_list:
        folder_id = extract_folder_id(folder_url)
        if not folder_id:
            continue
        existing = db.query(DriveFolder).filter(DriveFolder.folder_id == folder_id).first()
        if not existing:
            meta = await fetch_folder_metadata(folder_id, db)
            name = meta.get("name") or f"Drive Folder ({folder_id[:8]}...)"
            folder = DriveFolder(
                folder_id=folder_id,
                folder_name=name,
                folder_url=folder_url
            )
            db.add(folder)
            db.commit()
            db.refresh(folder)
            print(f"[STARTUP] Registered Google Drive folder: {folder.folder_name} ({folder_id})")
            asyncio.create_task(perform_sync_folder(folder.id, SessionLocal))

def init_default_settings(db: SessionLocal):
    """Sync environment variables into system_settings if not already set or empty in DB."""
    from app.models import SystemSetting
    env_keys = {
        "google_api_key": settings.GOOGLE_API_KEY,
        "google_service_account_json": settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        "tmdb_api_key": settings.TMDB_API_KEY,
        "cloudflare_worker_url": settings.CLOUDFLARE_WORKER_URL,
        "resend_api_key": getattr(settings, "RESEND_API_KEY", ""),
        "resend_from_email": getattr(settings, "RESEND_FROM_EMAIL", ""),
        "smtp_user": getattr(settings, "SMTP_USER", ""),
        "smtp_password": getattr(settings, "SMTP_PASSWORD", ""),
    }
    updated = False
    for key, val in env_keys.items():
        if val and val.strip():
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if not row:
                db.add(SystemSetting(key=key, value=val.strip()))
                updated = True
            elif not row.value or not row.value.strip():
                row.value = val.strip()
                updated = True
    if updated:
        db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist, default users and default Google Drive folder are configured
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_default_users(db)
        init_default_settings(db)
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

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Content-Length", "Accept-Ranges", "Content-Type", "Content-Disposition"]
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
app.include_router(series_routes.router)
app.include_router(stream_routes.router)
app.include_router(admin_routes.router)
app.include_router(superadmin_routes.router)

# Custom exception handler for 401s on web requests
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return RedirectResponse(url=f"/login?next={request.url.path}")
