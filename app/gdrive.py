import re
import json
import httpx
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
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

async def list_files_in_drive_folder(folder_id: str, db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Lists all video files in a Google Drive folder.
    Supports Service Account, API Key, or public folder listing.
    """
    api_key, sa_info = get_google_credentials_info(db)
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
                    error_msg = resp.text
                    print(f"[GDRIVE] Error listing folder {folder_id}: Status {resp.status_code} - {error_msg}")
                    break
            except Exception as e:
                print(f"[GDRIVE] Exception listing folder {folder_id}: {e}")
                break

    return video_files

async def fetch_folder_metadata(folder_id: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """Fetch folder name and details."""
    api_key, sa_info = get_google_credentials_info(db)
    headers = {}
    params = {
        "fields": "id, name"
    }
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
    return {"id": folder_id, "name": f"Folder {folder_id[:8]}..."}
