import os
import re
import json
import httpx
from typing import List, Dict, Any, Optional, Tuple
from app.database import Session
from app.config import settings
from app.models import SystemSetting
from app.parser import is_video_file

DRIVE_V3_FILES_URL = "https://www.googleapis.com/drive/v3/files"

def extract_folder_id(input_str: str) -> Optional[str]:
    """
    Extracts Google Drive folder ID from a URL or raw ID string.
    Examples:
      - https://drive.google.com/drive/folders/1ABCxyz-123_456?usp=sharing -> 1ABCxyz-123_456
      - 1ABCxyz-123_456 -> 1ABCxyz-123_456
      - https://drive.google.com/drive/u/0/folders/1ABCxyz-123_456 -> 1ABCxyz-123_456
    """
    cleaned = input_str.strip()
    # Check folder URL pattern
    match = re.search(r'folders/([a-zA-Z0-9_-]{15,})', cleaned)
    if match:
        return match.group(1)
    
    # Check if raw ID pattern
    match_id = re.match(r'^[a-zA-Z0-9_-]{15,}$', cleaned)
    if match_id:
        return match_id.group(0)
    
    return None

def _parse_service_account_json(sa_str: str) -> Optional[dict]:
    if not sa_str or not sa_str.strip():
        return None
    cleaned = sa_str.strip()

    # 1. Check if it's a file path to a JSON file
    if (cleaned.endswith(".json") or os.path.exists(cleaned)) and os.path.isfile(cleaned):
        try:
            with open(cleaned, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[GDRIVE] Error loading service account JSON file '{cleaned}': {e}")

    # 2. Try parsing directly as a JSON string
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 3. Try base64 decoding (for single-line env vars on Render/Heroku)
    try:
        import base64
        decoded = base64.b64decode(cleaned).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        pass

    print("[GDRIVE] Warning: Could not parse Service Account JSON string or file path.")
    return None

def get_google_credentials_info(db: Optional[Session] = None) -> Tuple[Optional[str], Optional[dict]]:
    """
    Returns (api_key, service_account_info_dict)
    Prioritizes DB setting if set and non-empty, otherwise falls back to environment variable in settings.
    """
    api_key = settings.GOOGLE_API_KEY
    sa_json_str = settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if db:
        api_key_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_api_key").first()
        if api_key_setting and api_key_setting.value and api_key_setting.value.strip():
            api_key = api_key_setting.value.strip()

        sa_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_service_account_json").first()
        if sa_setting and sa_setting.value and sa_setting.value.strip():
            sa_json_str = sa_setting.value.strip()

    sa_info = _parse_service_account_json(sa_json_str) if sa_json_str else None

    return api_key, sa_info

def get_access_token(sa_info: dict) -> Optional[str]:
    """Generate bearer token from service account info."""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        creds.refresh(Request())
        return creds.token
    except Exception as e:
        print(f"[GDRIVE] Failed to obtain access token from service account: {e}")
        return None

_cached_sa_token: Optional[str] = None
_cached_sa_expiry: float = 0.0

def get_gdrive_access_token(db: Optional[Session] = None) -> Optional[str]:
    """Generate or return cached bearer token from service account info."""
    global _cached_sa_token, _cached_sa_expiry
    import time
    if _cached_sa_token and time.time() < (_cached_sa_expiry - 300):
        return _cached_sa_token

    _, sa_info = get_google_credentials_info(db)
    if not sa_info:
        return None

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        creds.refresh(Request())
        _cached_sa_token = creds.token
        if creds.expiry:
            _cached_sa_expiry = creds.expiry.timestamp()
        else:
            _cached_sa_expiry = time.time() + 3500
        return _cached_sa_token
    except Exception as e:
        print(f"[GDRIVE] Failed to obtain cached access token from service account: {e}")
        return None

async def scrape_public_drive_folder(root_folder_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
    """
    Extracts video files directly from a public Google Drive folder page and its subfolders
    without needing an API key or service account.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    video_files = []
    seen_ids = set()
    queue = [(root_folder_id, [])]
    scanned_folders = set()

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        while queue:
            folder_id, folder_path = queue.pop(0)
            if folder_id in scanned_folders or len(folder_path) > max_depth:
                continue
            scanned_folders.add(folder_id)

            url = f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    if folder_id == root_folder_id:
                        raise RuntimeError(f"Google Drive returned HTTP {resp.status_code} for root folder {root_folder_id}")
                    continue

                html = resp.text
                cleaned_html = html.replace(r'\x22', '"').replace(r'\x5b', '[').replace(r'\x5d', ']').replace(r'\/', '/')

                # Match video files: ["FILE_ID", ["FOLDER_ID"], "FILE_NAME", "MIME_TYPE", ..., SIZE]
                pattern = rf'\["([a-zA-Z0-9_-]{{25,40}})",\["{re.escape(folder_id)}"\]\s*,\s*"([^"]+\.(?:mkv|mp4|webm|avi|mov|m4v))"\s*,\s*"(video/[^"]+)"(?:,[^,]*){{8,12}},(\d{{7,13}})'
                matches = re.findall(pattern, cleaned_html, re.IGNORECASE)

                for file_id, name, mime, size_str in matches:
                    if file_id not in seen_ids:
                        seen_ids.add(file_id)
                        video_files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": mime,
                            "size": int(size_str),
                            "folder_path": list(folder_path)
                        })

                # Fallback pattern without size
                simple_pattern = rf'\["([a-zA-Z0-9_-]{{25,40}})",\["{re.escape(folder_id)}"\]\s*,\s*"([^"]+\.(?:mkv|mp4|webm|avi|mov|m4v))"'
                simple_matches = re.findall(simple_pattern, cleaned_html, re.IGNORECASE)
                for file_id, name in simple_matches:
                    if file_id not in seen_ids:
                        seen_ids.add(file_id)
                        video_files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": "video/mp4",
                            "size": 0,
                            "folder_path": list(folder_path)
                        })

                # Match subfolders: ["FOLDER_ID", ["PARENT_ID"], "FOLDER_NAME", "application/vnd.google-apps.folder" ...]
                subfolder_pattern = rf'\["([a-zA-Z0-9_-]{{25,40}})",\["{re.escape(folder_id)}"\]\s*,\s*"([^"]+)"\s*,\s*"application/vnd\.google-apps\.folder"'
                subfolders = re.findall(subfolder_pattern, cleaned_html, re.IGNORECASE)
                for sub_id, sub_name in subfolders:
                    if sub_id not in scanned_folders and len(folder_path) < max_depth:
                        queue.append((sub_id, folder_path + [sub_name.strip()]))

            except Exception as e:
                print(f"[GDRIVE] Error scraping public folder {folder_id}: {e}")
                if folder_id == root_folder_id:
                    raise

    return video_files

async def list_files_in_drive_folder(root_folder_id: str, db: Optional[Session] = None, max_depth: int = 3) -> List[Dict[str, Any]]:
    """
    Lists all video files in a Google Drive folder and its subfolders (for TV Series/Season structures).
    Supports Service Account, API Key, or public folder listing fallback.
    """
    api_key, sa_info = get_google_credentials_info(db)
    
    # If no API credentials configured, use direct public folder scraper
    if not sa_info and not api_key:
        print(f"[GDRIVE] No credentials configured. Using recursive public folder scraper for {root_folder_id}...")
        return await scrape_public_drive_folder(root_folder_id, max_depth=max_depth)

    headers = {}
    if sa_info:
        token = get_access_token(sa_info)
        if token:
            headers["Authorization"] = f"Bearer {token}"

    video_files = []
    seen_ids = set()
    queue = [(root_folder_id, [])]
    scanned_folders = set()

    async with httpx.AsyncClient(timeout=25.0) as client:
        while queue:
            folder_id, folder_path = queue.pop(0)
            if folder_id in scanned_folders or len(folder_path) > max_depth:
                continue
            scanned_folders.add(folder_id)

            params = {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": "nextPageToken, files(id, name, mimeType, size)",
                "pageSize": 1000
            }
            if not sa_info and api_key:
                params["key"] = api_key

            page_token = None
            while True:
                if page_token:
                    params["pageToken"] = page_token

                try:
                    resp = await client.get(DRIVE_V3_FILES_URL, params=params, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        files = data.get("files", [])
                        for f in files:
                            fid = f.get("id")
                            name = f.get("name", "")
                            mime = f.get("mimeType", "")
                            
                            if mime == "application/vnd.google-apps.folder":
                                if fid not in scanned_folders and len(folder_path) < max_depth:
                                    queue.append((fid, folder_path + [name.strip()]))
                            elif "video/" in mime or is_video_file(name):
                                if fid not in seen_ids:
                                    seen_ids.add(fid)
                                    video_files.append({
                                        "id": fid,
                                        "name": name,
                                        "mimeType": mime or "video/mp4",
                                        "size": int(f.get("size") or 0),
                                        "folder_path": list(folder_path)
                                    })
                        page_token = data.get("nextPageToken")
                        if not page_token:
                            break
                    else:
                        print(f"[GDRIVE] API listing returned status {resp.status_code}. Falling back to public scraper...")
                        return await scrape_public_drive_folder(root_folder_id, max_depth=max_depth)
                except Exception as e:
                    print(f"[GDRIVE] API Exception: {e}. Falling back to public scraper...")
                    return await scrape_public_drive_folder(root_folder_id, max_depth=max_depth)

    return video_files

async def fetch_folder_metadata(folder_id: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """Fetch folder name and details."""
    api_key, sa_info = get_google_credentials_info(db)
    if sa_info or api_key:
        headers = {}
        params = {"fields": "id, name"}
        if sa_info:
            token = get_access_token(sa_info)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif api_key:
            params["key"] = api_key

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(f"{DRIVE_V3_FILES_URL}/{folder_id}", params=params, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                print(f"[GDRIVE] Error fetching folder metadata {folder_id}: {e}")

    # Fallback to scraping title from public webpage
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                match = re.search(r'<title>(.*?)(?:\s*-\s*Google Drive)?</title>', resp.text, re.IGNORECASE)
                if match:
                    folder_name = match.group(1).replace("- Google Drive", "").strip()
                    if folder_name and "google drive" not in folder_name.lower():
                        return {"id": folder_id, "name": folder_name}
    except Exception:
        pass

    return {"id": folder_id, "name": f"Drive Folder ({folder_id[:8]}...)"}
