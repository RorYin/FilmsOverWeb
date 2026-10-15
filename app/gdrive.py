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

def get_google_credentials_info(db: Optional[Session] = None) -> Tuple[Optional[str], Optional[dict]]:
    """
    Returns (api_key, service_account_info_dict)
    """
    api_key = settings.GOOGLE_API_KEY
    sa_json_str = settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if db:
        api_key_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_api_key").first()
        if api_key_setting and api_key_setting.value:
            api_key = api_key_setting.value.strip()

        sa_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_service_account_json").first()
        if sa_setting and sa_setting.value:
            sa_json_str = sa_setting.value.strip()

    sa_info = None
    if sa_json_str:
        try:
            sa_info = json.loads(sa_json_str)
        except Exception as e:
            print(f"[GDRIVE] Error parsing service account JSON: {e}")

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

async def scrape_public_drive_folder(folder_id: str) -> List[Dict[str, Any]]:
    """
    Extracts video files directly from a public Google Drive folder page
    without needing an API key or service account.
    """
    url = f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    video_files = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

            html = resp.text
            cleaned_html = html.replace(r'\x22', '"').replace(r'\x5b', '[').replace(r'\x5d', ']').replace(r'\/', '/')

            # Match: ["FILE_ID", ["FOLDER_ID"], "FILE_NAME", "MIME_TYPE", ..., SIZE]
            pattern = rf'\["([a-zA-Z0-9_-]{{25,40}})",\["{re.escape(folder_id)}"\]\s*,\s*"([^"]+\.(?:mkv|mp4|webm|avi|mov|m4v))"\s*,\s*"(video/[^"]+)"(?:,[^,]*){{8,12}},(\d{{7,13}})'
            matches = re.findall(pattern, cleaned_html, re.IGNORECASE)

            for file_id, name, mime, size_str in matches:
                if file_id not in seen_ids:
                    seen_ids.add(file_id)
                    video_files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": mime,
                        "size": int(size_str)
                    })

            # Fallback pattern without size
            if not video_files:
                simple_pattern = rf'\["([a-zA-Z0-9_-]{{25,40}})",\["{re.escape(folder_id)}"\]\s*,\s*"([^"]+\.(?:mkv|mp4|webm|avi|mov|m4v))"'
                simple_matches = re.findall(simple_pattern, cleaned_html, re.IGNORECASE)
                for file_id, name in simple_matches:
                    if file_id not in seen_ids:
                        seen_ids.add(file_id)
                        video_files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": "video/mp4",
                            "size": 0
                        })
        except Exception as e:
            print(f"[GDRIVE] Error scraping public folder {folder_id}: {e}")

    return video_files

async def list_files_in_drive_folder(folder_id: str, db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Lists all video files in a Google Drive folder.
    Supports Service Account, API Key, or public folder listing fallback.
    """
    api_key, sa_info = get_google_credentials_info(db)
    
    # If no API credentials configured, use direct public folder scraper
    if not sa_info and not api_key:
        print(f"[GDRIVE] No credentials configured. Using public folder scraper for {folder_id}...")
        return await scrape_public_drive_folder(folder_id)

    headers = {}
    params = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)",
        "pageSize": 1000
    }

    if sa_info:
        token = get_access_token(sa_info)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif api_key:
        params["key"] = api_key

    video_files = []
    page_token = None

    async with httpx.AsyncClient(timeout=25.0) as client:
        while True:
            if page_token:
                params["pageToken"] = page_token

            try:
                resp = await client.get(DRIVE_V3_FILES_URL, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    files = data.get("files", [])
                    for f in files:
                        name = f.get("name", "")
                        mime = f.get("mimeType", "")
                        if "video/" in mime or is_video_file(name):
                            video_files.append({
                                "id": f.get("id"),
                                "name": name,
                                "mimeType": mime or "video/mp4",
                                "size": int(f.get("size") or 0)
                            })
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
                else:
                    print(f"[GDRIVE] API listing returned status {resp.status_code}. Falling back to public scraper...")
                    return await scrape_public_drive_folder(folder_id)
            except Exception as e:
                print(f"[GDRIVE] API Exception: {e}. Falling back to public scraper...")
                return await scrape_public_drive_folder(folder_id)

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
