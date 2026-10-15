from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.database import engine, Base, SessionLocal
from app.auth import init_default_users
from app.routes import auth_routes, movie_routes, stream_routes, admin_routes, superadmin_routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist and default users are configured
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_default_users(db)
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
