from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from app.database import get_db, desc, Session
from app.models import Movie, WatchProgress, User
from app.auth import get_current_user

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
    # Featured Hero Movie (highest rated with backdrop, or newest)
    hero_movie = db.query(Movie).filter(Movie.backdrop_path != None).order_by(desc(Movie.rating)).first()
    if not hero_movie:
        hero_movie = db.query(Movie).order_by(desc(Movie.created_at)).first()

    # Continue Watching
    continue_watching_records = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.completed == False,
        WatchProgress.position_seconds > 10
    ).order_by(desc(WatchProgress.updated_at)).limit(10).all()

    continue_watching = []
    for cw in continue_watching_records:
        if cw.movie:
            percent = int((cw.position_seconds / cw.duration_seconds) * 100) if cw.duration_seconds > 0 else 0
            continue_watching.append({
                "movie": cw.movie,
                "progress_percent": min(percent, 100),
                "position_seconds": cw.position_seconds
            })

    # Recently Added (deduplicated by title/TMDB)
    recently_added = deduplicate_movies(db.query(Movie).order_by(desc(Movie.created_at)).all())[:15]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "hero_movie": hero_movie,
            "continue_watching": continue_watching,
            "recently_added": recently_added
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
    user_token = create_access_token({"sub": user.email, "role": user.role})

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
            "google_api_key": google_api_key
        }
    )

