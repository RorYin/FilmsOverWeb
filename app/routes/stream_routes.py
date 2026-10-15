import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Movie, User, WatchProgress
from app.auth import get_current_user
from app.gdrive import get_google_credentials_info, get_access_token, DRIVE_V3_FILES_URL

router = APIRouter(tags=["Streaming"])

def get_stream_headers_and_url(file_id: str, client_range: str, db: Session):
    api_key, sa_info = get_google_credentials_info(db)
    upstream_headers = {}
    
    if client_range:
        upstream_headers["Range"] = client_range

    if sa_info:
        token = get_access_token(sa_info)
        if token:
            upstream_headers["Authorization"] = f"Bearer {token}"
            url = f"{DRIVE_V3_FILES_URL}/{file_id}?alt=media"
            return url, upstream_headers

    if api_key:
        url = f"{DRIVE_V3_FILES_URL}/{file_id}?alt=media&key={api_key}"
        return url, upstream_headers

    # Fallback to direct download URL
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    return url, upstream_headers

@router.get("/stream/{movie_id}")
async def stream_movie(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    High-performance video streaming proxy with HTTP 206 Range support.
    Streams directly from Google Drive in full quality (HEVC, AV1, 4K UHD).
    """
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    range_header = request.headers.get("range", "")
    url, upstream_headers = get_stream_headers_and_url(movie.gdrive_file_id, range_header, db)

    # Establish streaming client with follow_redirects
    client = httpx.AsyncClient(follow_redirects=True, timeout=None)
    try:
        req = client.build_request("GET", url, headers=upstream_headers)
        r = await client.send(req, stream=True)

        if r.status_code not in (200, 206):
            await r.aclose()
            await client.aclose()
            # If Google returned 403/404, provide descriptive error
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Google Drive stream error ({r.status_code}). Ensure the file is accessible or credentials are valid."
            )

        # Build downstream response headers
        response_headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": movie.mime_type or r.headers.get("content-type", "video/mp4"),
        }

        if "content-range" in r.headers:
            response_headers["Content-Range"] = r.headers["content-range"]
        if "content-length" in r.headers:
            response_headers["Content-Length"] = r.headers["content-length"]

        status_code = r.status_code

        async def stream_generator():
            try:
                async for chunk in r.aiter_bytes(chunk_size=256 * 1024):  # 256KB chunks for smooth playback
                    yield chunk
            finally:
                await r.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_generator(),
            status_code=status_code,
            headers=response_headers
        )

    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Failed to connect to Google Drive upstream: {str(exc)}")

@router.post("/api/movies/{movie_id}/progress")
async def update_watch_progress(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Save user's playback position to resume later."""
    data = await request.json()
    position = float(data.get("position", 0.0))
    duration = float(data.get("duration", 0.0))

    if duration <= 0:
        return JSONResponse({"status": "ignored"})

    progress = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.movie_id == movie_id
    ).first()

    completed = (position / duration) >= 0.92 if duration > 0 else False

    if not progress:
        progress = WatchProgress(
            user_id=user.id,
            movie_id=movie_id,
            position_seconds=position,
            duration_seconds=duration,
            completed=completed
        )
        db.add(progress)
    else:
        progress.position_seconds = position
        progress.duration_seconds = duration
        progress.completed = completed

    db.commit()
    return JSONResponse({"status": "ok", "completed": completed})
