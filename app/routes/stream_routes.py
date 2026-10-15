import os
import asyncio
import subprocess
from typing import Tuple, Optional
import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, status, Response
from fastapi.responses import StreamingResponse, JSONResponse
from app.database import get_db, Session
from app.models import Movie, User, WatchProgress, Episode
from app.auth import get_current_user, get_current_user_optional, create_access_token
from app.gdrive import get_google_credentials_info, get_access_token, DRIVE_V3_FILES_URL

router = APIRouter(tags=["Streaming"])

# 8 MB chunks for responsive seeking and fast buffering without Google Drive quota/freeze limits
STREAM_CHUNK_SIZE = 8 * 1024 * 1024

def parse_and_bound_range(range_header: Optional[str], total_size: int) -> Tuple[int, int]:
    """Parse HTTP Range header and bound to STREAM_CHUNK_SIZE bytes to prevent Google Drive Quota HTML errors."""
    if not range_header or not range_header.startswith("bytes="):
        return 0, min(STREAM_CHUNK_SIZE - 1, total_size - 1) if total_size > 0 else STREAM_CHUNK_SIZE - 1

    parts = range_header[6:].split("-")
    try:
        start = int(parts[0]) if parts[0] else 0
    except ValueError:
        start = 0

    if len(parts) > 1 and parts[1]:
        try:
            req_end = int(parts[1])
            if total_size > 0:
                end = min(req_end, start + STREAM_CHUNK_SIZE - 1, total_size - 1)
            else:
                end = min(req_end, start + STREAM_CHUNK_SIZE - 1)
        except ValueError:
            end = min(start + STREAM_CHUNK_SIZE - 1, total_size - 1) if total_size > 0 else start + STREAM_CHUNK_SIZE - 1
    else:
        end = min(start + STREAM_CHUNK_SIZE - 1, total_size - 1) if total_size > 0 else start + STREAM_CHUNK_SIZE - 1

    return max(0, start), max(start, end)

def get_stream_headers_and_url(file_id: str, client_range: str, db: Session) -> Tuple[str, dict]:
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

    # Direct download URL for public/shared files
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    return url, upstream_headers

async def stream_gdrive_range(movie: Movie, range_header: Optional[str], db: Session):
    total_size = movie.file_size or 0
    start, end = parse_and_bound_range(range_header, total_size)

    url, upstream_headers = get_stream_headers_and_url(movie.gdrive_file_id, f"bytes={start}-{end}", db)

    client = httpx.AsyncClient(follow_redirects=True, timeout=30.0)
    try:
        req = client.build_request("GET", url, headers=upstream_headers)
        r = await client.send(req, stream=True)

        if r.status_code not in (200, 206):
            await r.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Google Drive stream error ({r.status_code})."
            )

        # Infer Content-Type
        mime = movie.mime_type
        if not mime or mime == "video/mp4":
            if movie.file_name.lower().endswith(".mkv"):
                mime = "video/x-matroska"
            elif movie.file_name.lower().endswith(".webm"):
                mime = "video/webm"
            else:
                mime = "video/mp4"

        # If total_size was 0, extract it from upstream content-range if available
        if total_size <= 0 and "content-range" in r.headers:
            try:
                total_size = int(r.headers["content-range"].split("/")[-1])
            except Exception:
                pass

        content_range = f"bytes {start}-{end}/{total_size if total_size > 0 else '*'}"
        content_length = str(end - start + 1)

        response_headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": content_range,
            "Content-Length": content_length,
            "Content-Type": mime,
            "Cache-Control": "public, max-age=3600"
        }

        async def stream_generator():
            try:
                async for chunk in r.aiter_bytes(chunk_size=128 * 1024):
                    yield chunk
            finally:
                await r.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_generator(),
            status_code=206,
            headers=response_headers
        )
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Failed to connect to Google Drive upstream: {str(exc)}")

@router.get("/stream/{movie_id}")
async def stream_movie(
    movie_id: int,
    request: Request,
    ss: float = 0.0,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Unified Cinema Streaming Engine:
    - Automatically supports all video & audio formats (Dolby 5.1, E-AC3, DTS, DTS-HD MA, etc.)
    - Automatically remuxes MKV and multichannel audio to browser-supported fMP4 with -c:v copy (100% lossless 4K)
    - Automatically handles seeking via ?ss={seconds} so only the requested play head is buffered
    """
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    fn = movie.file_name.upper()
    is_mkv = movie.file_name.lower().endswith(".mkv")
    has_audio_codecs = any(x in fn for x in ["DD+", "DDP", "DTS", "TRUEHD", "ATMOS", "AC3", "EAC3"])

    if is_mkv or has_audio_codecs or ss > 0.0:
        return await transmux_movie(movie_id, request, ss, db, user)
    else:
        return await stream_gdrive_range(movie, request.headers.get("range"), db)

@router.get("/stream/raw/{movie_id}")
async def stream_raw(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Internal raw stream endpoint with bounded range requests for ffmpeg remuxing."""
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    return await stream_gdrive_range(movie, request.headers.get("range"), db)

@router.get("/stream/transmux/{movie_id}")
async def transmux_movie(
    movie_id: int,
    request: Request,
    ss: float = 0.0,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Universal Transmuxing Stream:
    - Zero re-encoding for video (-c:v copy) -> 100% Full 4K HEVC / AV1 Lossless Quality
    - Realtime audio transcoding (-c:a aac -ac 6 -b:a 384k) -> Full Dolby 5.1, E-AC3, DTS, DTS-HD MA, TrueHD
    - Remuxes MKV -> Fragmented MP4 for 100% native browser compatibility
    - Fast playhead seeking via ?ss={seconds}
    """
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    # Generate internal auth token
    auth_token = create_access_token({"sub": user.email, "role": user.role})
    port = request.url.port or 8000
    host = request.url.hostname or "127.0.0.1"
    raw_url = f"http://127.0.0.1:{port}/stream/raw/{movie.id}?token={auth_token}"

    cmd = ["ffmpeg", "-v", "error"]
    if ss > 0.5:
        cmd.extend(["-noaccurate_seek", "-ss", f"{ss:.2f}"])

    cmd.extend([
        "-probesize", "2M",
        "-analyzeduration", "2M",
        "-i", raw_url,
        "-c:v", "copy",
        "-c:a", "aac",
        "-ac", "6",
        "-b:a", "384k",
        "-avoid_negative_ts", "make_zero",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1"
    ])

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=256 * 1024
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start ffmpeg remuxer: {e}")

    async def ffmpeg_stream_generator():
        loop = asyncio.get_event_loop()
        try:
            while True:
                chunk = await loop.run_in_executor(None, proc.stdout.read, 128 * 1024)
                if not chunk:
                    break
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as err:
            print(f"[TRANSMUX] Stream interrupted: {err}")
        finally:
            try:
                if proc.poll() is None:
                    proc.kill()
                    await loop.run_in_executor(None, proc.wait)
            except Exception:
                pass

    return StreamingResponse(
        ffmpeg_stream_generator(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@router.get("/stream/playlist/{movie_id}.m3u")
async def generate_vlc_m3u(
    movie_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Generates an M3U playlist file for 1-click native VLC / MPV / PotPlayer streaming."""
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    auth_token = create_access_token({"sub": user.email, "role": user.role})
    base_url = str(request.base_url).rstrip("/")
    stream_url = f"{base_url}/stream/{movie.id}?token={auth_token}"

    clean_title = "".join(c for c in movie.title if c.isalnum() or c in (" ", "-", "_")).strip()
    m3u_content = (
        f"#EXTM3U\n"
        f"#EXTINF:-1,{clean_title} ({movie.year or 'Movie'}) [{movie.resolution} {movie.codec}]\n"
        f"{stream_url}\n"
    )

    return Response(
        content=m3u_content,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": f'attachment; filename="{clean_title}.m3u"'
        }
    )

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

@router.get("/stream/episode/raw/{episode_id}")
async def stream_episode_raw(
    episode_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    return await stream_gdrive_range(episode, request.headers.get("range"), db)

@router.post("/api/episodes/{episode_id}/progress")
async def update_episode_watch_progress(
    episode_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Save user's playback position for a TV series episode."""
    data = await request.json()
    position = float(data.get("position", 0.0))
    duration = float(data.get("duration", 0.0))

    if duration <= 0:
        return JSONResponse({"status": "ignored"})

    progress = db.query(WatchProgress).filter(
        WatchProgress.user_id == user.id,
        WatchProgress.episode_id == episode_id
    ).first()

    completed = (position / duration) >= 0.92 if duration > 0 else False

    if not progress:
        progress = WatchProgress(
            user_id=user.id,
            episode_id=episode_id,
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
