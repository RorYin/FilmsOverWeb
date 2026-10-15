import httpx
from typing import Optional, Dict, Any, Tuple
from app.database import Session
from app.config import settings
from app.models import SystemSetting, Movie

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

# In-Memory Cache to minimize TMDB API calls
_TMDB_CACHE: Dict[str, Dict[str, Any]] = {}

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

LANGUAGE_MAP = {
    "ta": "Tamil", "kn": "Kannada", "te": "Telugu", "ml": "Malayalam",
    "hi": "Hindi", "en": "English", "fr": "French", "es": "Spanish",
    "de": "German", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "ru": "Russian", "pt": "Portuguese", "bn": "Bengali",
    "mr": "Marathi", "pa": "Punjabi", "gu": "Gujarati", "ur": "Urdu"
}

def resolve_language_name(code: Optional[str], spoken_languages: list) -> str:
    if not code:
        return "English"
    code_clean = code.lower().strip()
    for sp in spoken_languages:
        if sp.get("iso_639_1") == code_clean:
            return sp.get("english_name") or sp.get("name") or code_clean.capitalize()
    return LANGUAGE_MAP.get(code_clean, code_clean.capitalize())

async def enrich_movie_data(title: str, year: Optional[int] = None, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Search and fetch rich metadata from TMDB with memory and DB-level caching.
    """
    cache_key = f"{title.strip().lower()}_{year or 0}"
    if cache_key in _TMDB_CACHE and _TMDB_CACHE[cache_key].get("tmdb_id"):
        return _TMDB_CACHE[cache_key]

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
        "trailer_url": None,
        "original_language": "English"
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

    # Process language
    orig_lang_code = details.get("original_language")
    spoken_list = details.get("spoken_languages", [])
    resolved_lang = resolve_language_name(orig_lang_code, spoken_list)

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

    enriched = {
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
        "trailer_url": trailer_url,
        "original_language": resolved_lang
    }

    # Cache result
    _TMDB_CACHE[cache_key] = enriched
    return enriched

async def enrich_all_missing_movies(db_factory):
    """
    Scans the database and fetches TMDB posters and details for any movies that
    are missing them (e.g. added before TMDB API key was saved).
    Skips movies that are already enriched with valid tmdb_id to conserve API calls.
    """
    from app.parser import parse_filename
    db = db_factory()
    try:
        api_key = get_active_tmdb_key(db)
        if not api_key:
            print("[TMDB ENRICH] No TMDB key found. Skipping.")
            return 0

        # Find movies needing enrichment
        candidates = db.query(Movie).filter(
            (Movie.tmdb_id == None) | 
            (Movie.poster_path == None) | 
            (Movie.poster_path.like("%poster-placeholder%"))
        ).all()

        if not candidates:
            print("[TMDB ENRICH] All movies already have TMDB metadata cached.")
            return 0

        print(f"[TMDB ENRICH] Found {len(candidates)} movies to enrich from TMDB...")
        updated_count = 0
        for m in candidates:
            parsed = parse_filename(m.file_name)
            meta = await enrich_movie_data(parsed["title"], parsed["year"], api_key)
            if meta.get("tmdb_id"):
                m.tmdb_id = meta["tmdb_id"]
                m.title = meta["title"]
                m.original_title = meta["original_title"]
                m.year = meta["year"]
                m.overview = meta["overview"]
                m.tagline = meta["tagline"]
                m.poster_path = meta["poster_path"]
                m.backdrop_path = meta["backdrop_path"]
                m.rating = meta["rating"]
                m.vote_count = meta["vote_count"]
                m.duration = meta["duration"]
                m.genres = meta["genres"]
                m.cast = meta["cast"]
                m.director = meta["director"]
                m.trailer_url = meta["trailer_url"]
                m.original_language = meta.get("original_language", "English")
                updated_count += 1
                print(f"[TMDB ENRICH] Enriched: '{m.title}' ({m.year}) - Poster: {m.poster_path}")

        db.commit()
        print(f"[TMDB ENRICH] Successfully enriched {updated_count} movies.")
        return updated_count
    except Exception as e:
        print(f"[TMDB ENRICH] Error during enrichment: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


# ==========================================
# TV Shows & Web Series TMDB Integration
# ==========================================

_TMDB_TV_CACHE: Dict[str, Dict[str, Any]] = {}
_TMDB_SEASON_CACHE: Dict[str, Dict[str, Any]] = {}

async def search_tv_tmdb(title: str, year: Optional[int] = None, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None

    headers = {"Accept": "application/json"}
    params = {
        "api_key": api_key,
        "query": title,
        "include_adult": "false"
    }
    if year:
        params["first_air_date_year"] = str(year)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{TMDB_BASE_URL}/search/tv", params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return results[0]
                if year:
                    del params["first_air_date_year"]
                    resp2 = await client.get(f"{TMDB_BASE_URL}/search/tv", params=params, headers=headers)
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        results2 = data2.get("results", [])
                        if results2:
                            return results2[0]
        except Exception as e:
            print(f"[TMDB] Search TV error for '{title}': {e}")
    return None

async def fetch_tv_full_details(tmdb_id: int, api_key: str) -> Optional[Dict[str, Any]]:
    params = {
        "api_key": api_key,
        "append_to_response": "credits,videos"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{TMDB_BASE_URL}/tv/{tmdb_id}", params=params)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[TMDB] TV Details fetch error for ID {tmdb_id}: {e}")
    return None

async def fetch_season_details(tmdb_id: int, season_num: int, api_key: str) -> Optional[Dict[str, Any]]:
    cache_key = f"{tmdb_id}_s{season_num}"
    if cache_key in _TMDB_SEASON_CACHE:
        return _TMDB_SEASON_CACHE[cache_key]

    params = {"api_key": api_key}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{TMDB_BASE_URL}/tv/{tmdb_id}/season/{season_num}", params=params)
            if resp.status_code == 200:
                data = resp.json()
                _TMDB_SEASON_CACHE[cache_key] = data
                return data
        except Exception as e:
            print(f"[TMDB] Season details fetch error for TV {tmdb_id} S{season_num}: {e}")
    return None

async def enrich_series_data(title: str, year: Optional[int] = None, api_key: Optional[str] = None) -> Dict[str, Any]:
    cache_key = f"{title.strip().lower()}_{year or 0}"
    if cache_key in _TMDB_TV_CACHE and _TMDB_TV_CACHE[cache_key].get("tmdb_id"):
        return _TMDB_TV_CACHE[cache_key]

    default_meta = {
        "tmdb_id": None,
        "title": title,
        "original_title": title,
        "year": year,
        "overview": "No overview available for this series yet.",
        "tagline": "",
        "poster_path": "/static/img/poster-placeholder.png",
        "backdrop_path": None,
        "rating": 0.0,
        "vote_count": 0,
        "genres": "TV Series",
        "cast": "",
        "creator": "",
        "original_language": "English",
        "total_seasons": 1,
        "total_episodes": 0
    }

    if not api_key:
        return default_meta

    search_result = await search_tv_tmdb(title, year, api_key)
    if not search_result:
        return default_meta

    tmdb_id = search_result["id"]
    details = await fetch_tv_full_details(tmdb_id, api_key)

    if not details:
        poster = f"{TMDB_IMAGE_BASE}/w500{search_result.get('poster_path')}" if search_result.get("poster_path") else default_meta["poster_path"]
        backdrop = f"{TMDB_IMAGE_BASE}/original{search_result.get('backdrop_path')}" if search_result.get("backdrop_path") else None
        first_air = search_result.get("first_air_date") or ""
        air_year = int(first_air[:4]) if len(first_air) >= 4 and first_air[:4].isdigit() else year

        enriched = {
            "tmdb_id": tmdb_id,
            "title": search_result.get("name") or title,
            "original_title": search_result.get("original_name") or title,
            "year": air_year,
            "overview": search_result.get("overview") or default_meta["overview"],
            "tagline": "",
            "poster_path": poster,
            "backdrop_path": backdrop,
            "rating": round(search_result.get("vote_average", 0.0), 1),
            "vote_count": search_result.get("vote_count", 0),
            "genres": "TV Series",
            "cast": "",
            "creator": "",
            "original_language": search_result.get("original_language", "en").capitalize(),
            "total_seasons": 1,
            "total_episodes": 0
        }
        _TMDB_TV_CACHE[cache_key] = enriched
        return enriched

    poster = f"{TMDB_IMAGE_BASE}/w500{details.get('poster_path')}" if details.get("poster_path") else default_meta["poster_path"]
    backdrop = f"{TMDB_IMAGE_BASE}/original{details.get('backdrop_path')}" if details.get("backdrop_path") else None
    first_air = details.get("first_air_date") or ""
    air_year = int(first_air[:4]) if len(first_air) >= 4 and first_air[:4].isdigit() else year

    genres_list = [g.get("name") for g in details.get("genres", []) if g.get("name")]
    genres_str = ", ".join(genres_list) if genres_list else "TV Series"

    credits = details.get("credits", {})
    cast_members = [c.get("name") for c in credits.get("cast", [])[:5] if c.get("name")]
    cast_str = ", ".join(cast_members)

    creators = [c.get("name") for c in details.get("created_by", []) if c.get("name")]
    creator_str = ", ".join(creators)

    spoken_langs = details.get("spoken_languages", [])
    orig_lang = resolve_language_name(details.get("original_language"), spoken_langs)

    enriched = {
        "tmdb_id": tmdb_id,
        "title": details.get("name") or title,
        "original_title": details.get("original_name") or title,
        "year": air_year,
        "overview": details.get("overview") or default_meta["overview"],
        "tagline": details.get("tagline") or "",
        "poster_path": poster,
        "backdrop_path": backdrop,
        "rating": round(details.get("vote_average", 0.0), 1),
        "vote_count": details.get("vote_count", 0),
        "genres": genres_str,
        "cast": cast_str,
        "creator": creator_str,
        "original_language": orig_lang,
        "total_seasons": details.get("number_of_seasons", 1),
        "total_episodes": details.get("number_of_episodes", 0)
    }
    _TMDB_TV_CACHE[cache_key] = enriched
    return enriched

async def enrich_episode_data(series_tmdb_id: Optional[int], season_num: int, episode_num: int, fallback_title: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    default_meta = {
        "title": fallback_title or f"Episode {episode_num}",
        "overview": "",
        "still_path": "",
        "air_date": "",
        "rating": 0.0,
        "duration": 0
    }

    if not series_tmdb_id or not api_key:
        return default_meta

    season_data = await fetch_season_details(series_tmdb_id, season_num, api_key)
    if not season_data:
        return default_meta

    for ep in season_data.get("episodes", []):
        if ep.get("episode_number") == episode_num:
            still = f"{TMDB_IMAGE_BASE}/w780{ep.get('still_path')}" if ep.get("still_path") else ""
            return {
                "title": ep.get("name") or default_meta["title"],
                "overview": ep.get("overview") or "",
                "still_path": still,
                "air_date": ep.get("air_date") or "",
                "rating": round(ep.get("vote_average", 0.0), 1),
                "duration": int(ep.get("runtime") or 0)
            }

    return default_meta
