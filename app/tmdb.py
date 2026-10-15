import httpx
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.config import settings
from app.models import SystemSetting

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

def get_active_tmdb_key(db: Optional[Session] = None) -> str:
    if db:
        setting = db.query(SystemSetting).filter(SystemSetting.key == "tmdb_api_key").first()
        if setting and setting.value and setting.value.strip():
            return setting.value.strip()
    return settings.TMDB_API_KEY.strip()

async def search_movie_tmdb(title: str, year: Optional[int] = None, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None

    headers = {"Accept": "application/json"}
    params = {
        "api_key": api_key,
        "query": title,
        "include_adult": "false"
    }
    if year:
        params["year"] = str(year)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{TMDB_BASE_URL}/search/movie", params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return results[0]
                # If no result with year, try searching without year
                if year:
                    del params["year"]
                    resp2 = await client.get(f"{TMDB_BASE_URL}/search/movie", params=params, headers=headers)
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        results2 = data2.get("results", [])
                        if results2:
                            return results2[0]
        except Exception as e:
            print(f"[TMDB] Search error for '{title}': {e}")
    return None

async def fetch_movie_full_details(tmdb_id: int, api_key: str) -> Optional[Dict[str, Any]]:
    params = {
        "api_key": api_key,
        "append_to_response": "credits,videos"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{TMDB_BASE_URL}/movie/{tmdb_id}", params=params)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[TMDB] Details fetch error for ID {tmdb_id}: {e}")
    return None

async def enrich_movie_data(title: str, year: Optional[int] = None, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Search and fetch rich metadata from TMDB. Falls back gracefully if TMDB key is missing or search yields no results.
    """
    default_meta = {
        "tmdb_id": None,
        "title": title,
        "original_title": title,
        "year": year,
        "overview": "No overview available for this title yet. Add TMDB API key in settings to fetch detailed synopses, posters, and cast.",
        "tagline": "",
        "poster_path": "/static/img/poster-placeholder.png",
        "backdrop_path": "/static/img/hero-placeholder.jpg",
        "rating": 7.5,
        "vote_count": 0,
        "duration": 120,
        "genres": "Drama, Cinema",
        "cast": "",
        "director": "",
        "trailer_url": None
    }

    if not api_key:
        return default_meta

    search_result = await search_movie_tmdb(title, year, api_key)
    if not search_result:
        return default_meta

    tmdb_id = search_result.get("id")
    details = await fetch_movie_full_details(tmdb_id, api_key)
    if not details:
        details = search_result

    # Process posters and backdrops
    poster = details.get("poster_path")
    poster_url = f"{TMDB_IMAGE_BASE}/w500{poster}" if poster else default_meta["poster_path"]

    backdrop = details.get("backdrop_path")
    backdrop_url = f"{TMDB_IMAGE_BASE}/original{backdrop}" if backdrop else default_meta["backdrop_path"]

    # Process genres
    genres_list = [g.get("name") for g in details.get("genres", []) if g.get("name")]
    genres_str = ", ".join(genres_list) if genres_list else "Cinema"

    # Process credits
    cast_list = []
    director = ""
    credits = details.get("credits", {})
    if credits:
        cast_list = [actor.get("name") for actor in credits.get("cast", [])[:5] if actor.get("name")]
        for crew in credits.get("crew", []):
            if crew.get("job") == "Director":
                director = crew.get("name", "")
                break

    # Process trailer
    trailer_url = None
    videos = details.get("videos", {}).get("results", [])
    for vid in videos:
        if vid.get("site") == "YouTube" and vid.get("type") in ("Trailer", "Teaser"):
            trailer_url = f"https://www.youtube.com/watch?v={vid.get('key')}"
            break

    release_date = details.get("release_date", "")
    release_year = year
    if release_date and len(release_date) >= 4:
        try:
            release_year = int(release_date[:4])
        except ValueError:
            pass

    return {
        "tmdb_id": tmdb_id,
        "title": details.get("title") or title,
        "original_title": details.get("original_title") or title,
        "year": release_year,
        "overview": details.get("overview") or default_meta["overview"],
        "tagline": details.get("tagline") or "",
        "poster_path": poster_url,
        "backdrop_path": backdrop_url,
        "rating": round(float(details.get("vote_average", 0.0)), 1),
        "vote_count": int(details.get("vote_count", 0)),
        "duration": int(details.get("runtime") or 120),
        "genres": genres_str,
        "cast": ", ".join(cast_list),
        "director": director,
        "trailer_url": trailer_url
    }
