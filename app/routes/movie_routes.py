from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from app.database import get_db
from app.models import Movie, WatchProgress, User
from app.auth import get_current_user

router = APIRouter(tags=["Movies & Library"])
templates = Jinja2Templates(directory="app/templates")

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

    # Recently Added
    recently_added = db.query(Movie).order_by(desc(Movie.created_at)).limit(15).all()

    # Top Rated
    top_rated = db.query(Movie).order_by(desc(Movie.rating)).limit(15).all()

    # Distinct Genres
    all_movies = db.query(Movie).all()
    genres_set = set()
    for m in all_movies:
        if m.genres:
            for g in m.genres.split(","):
                g_clean = g.strip()
                if g_clean:
                    genres_set.add(g_clean)

    # Group by major genres
    genre_sections = []
    for genre in sorted(list(genres_set))[:5]:
        movies_in_genre = [m for m in all_movies if m.genres and genre in m.genres][:12]
        if movies_in_genre:
            genre_sections.append({"genre": genre, "movies": movies_in_genre})

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "hero_movie": hero_movie,
            "continue_watching": continue_watching,
            "recently_added": recently_added,
            "top_rated": top_rated,
            "genre_sections": genre_sections,
            "all_genres": sorted(list(genres_set))
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

    movies = query.all()

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

    # Related movies (same genre)
    related = []
    if movie.genres:
        first_genre = movie.genres.split(",")[0].strip()
        related = db.query(Movie).filter(
            Movie.id != movie.id,
            Movie.genres.ilike(f"%{first_genre}%")
        ).limit(6).all()

    return templates.TemplateResponse(
        request=request,
        name="movie_detail.html",
        context={
            "user": user,
            "movie": movie,
            "progress": progress,
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

    return templates.TemplateResponse(
        request=request,
        name="watch.html",
        context={
            "user": user,
            "movie": movie,
            "initial_time": initial_time
        }
    )
