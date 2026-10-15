from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from app.database import get_db, desc, asc, Session
from app.models import Series, Episode, WatchProgress, User, SystemSetting
from app.auth import get_current_user
from app.config import settings

router = APIRouter(tags=["TV Series & Shows"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/series", response_class=HTMLResponse)
async def browse_series(
    request: Request,
    q: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    query = db.query(Series)

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        query = query.filter(
            (Series.title.ilike(search_term)) |
            (Series.cast.ilike(search_term)) |
            (Series.creator.ilike(search_term))
        )

    if genre and genre.strip():
        query = query.filter(Series.genres.ilike(f"%{genre.strip()}%"))

    if sort == "rating":
        query = query.order_by(desc(Series.rating))
    elif sort == "year":
        query = query.order_by(desc(Series.year))
    elif sort == "title":
        query = query.order_by(Series.title.asc())
    else:
        query = query.order_by(desc(Series.created_at))

    all_series = query.all()

    # Extract all distinct genres across series for the filter bar
    all_genres = set()
    for s in db.query(Series).all():
        if s.genres:
            for g in s.genres.split(","):
                clean_g = g.strip()
                if clean_g and clean_g != "TV Series":
                    all_genres.add(clean_g)

    return templates.TemplateResponse(
        request=request,
        name="series_browse.html",
        context={
            "user": user,
            "series_list": all_series,
            "genres": sorted(list(all_genres)),
            "active_genre": genre,
            "search_query": q,
            "active_sort": sort
        }
    )

@router.get("/series/{series_id}", response_class=HTMLResponse)
async def series_detail(
    series_id: int,
    request: Request,
    season: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="TV Series not found")

    all_episodes = series.episodes
    seasons = series.seasons
    active_season = season if season and season in seasons else (seasons[0] if seasons else 1)

    season_episodes = [e for e in all_episodes if e.season_number == active_season]

    # Map user progress for each episode in this season
    episode_progress = {}
    for ep in season_episodes:
        prog = db.query(WatchProgress).filter(
            WatchProgress.user_id == user.id,
            WatchProgress.episode_id == ep.id
        ).first()
        if prog:
            pct = int((prog.position_seconds / prog.duration_seconds) * 100) if prog.duration_seconds > 0 else 0
            episode_progress[ep.id] = {
                "percent": min(100, pct),
                "position": prog.position_seconds,
                "completed": prog.completed
            }

    # Find continue watching / resume episode for this series
    resume_episode = None
    for ep in all_episodes:
        prog = db.query(WatchProgress).filter(
            WatchProgress.user_id == user.id,
            WatchProgress.episode_id == ep.id,
            WatchProgress.completed == False,
            WatchProgress.position_seconds > 10
        ).first()
        if prog:
            resume_episode = ep
            break
    if not resume_episode and all_episodes:
        resume_episode = all_episodes[0]

    return templates.TemplateResponse(
        request=request,
        name="series_detail.html",
        context={
            "user": user,
            "series": series,
            "seasons": seasons,
            "active_season": active_season,
            "episodes": season_episodes,
            "episode_progress": episode_progress,
            "resume_episode": resume_episode
        }
    )

@router.get("/watch/episode/{episode_id}", response_class=HTMLResponse)
async def watch_episode_player(
    episode_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    series = episode.series
    if not series:
        raise HTTPException(status_code=404, detail="Series not found for this episode")

    progress = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.episode_id == episode.id
    ).first()

    initial_time = progress.position_seconds if progress and not progress.completed else 0.0

    from app.auth import create_access_token
    user_token = create_access_token({"sub": user.email, "role": user.role})

    # Find Next Episode and Previous Episode in sequence
    all_series_episodes = series.episodes
    next_episode = None
    prev_episode = None
    for i, ep in enumerate(all_series_episodes):
        if ep.id == episode.id:
            if i + 1 < len(all_series_episodes):
                next_episode = all_series_episodes[i + 1]
            if i - 1 >= 0:
                prev_episode = all_series_episodes[i - 1]
            break

    # Season episodes for quick episode switcher
    season_episodes = [e for e in all_series_episodes if e.season_number == episode.season_number]

    cf_worker_row = db.query(SystemSetting).filter(SystemSetting.key == "cloudflare_worker_url").first()
    cloudflare_worker_url = cf_worker_row.value.strip() if cf_worker_row and cf_worker_row.value else settings.CLOUDFLARE_WORKER_URL

    google_api_key_row = db.query(SystemSetting).filter(SystemSetting.key == "google_api_key").first()
    google_api_key = google_api_key_row.value.strip() if google_api_key_row and google_api_key_row.value else settings.GOOGLE_API_KEY

    return templates.TemplateResponse(
        request=request,
        name="watch_episode.html",
        context={
            "user": user,
            "series": series,
            "episode": episode,
            "initial_time": initial_time,
            "user_token": user_token,
            "next_episode": next_episode,
            "prev_episode": prev_episode,
            "season_episodes": season_episodes,
            "cloudflare_worker_url": cloudflare_worker_url,
            "google_api_key": google_api_key
        }
    )
