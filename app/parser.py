import re
from typing import Dict, Any, Optional, List

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts"}

def is_video_file(filename: str) -> bool:
    name_lower = filename.lower()
    return any(name_lower.endswith(ext) for ext in VIDEO_EXTENSIONS)

def parse_filename(filename: str) -> Dict[str, Any]:
    """
    Parses a movie filename to extract clean title, release year, resolution, and video codec.
    """
    # Strip file extension
    base_name = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', filename)
    
    # Detect Codec
    codec = "Unknown"
    if re.search(r'\b(hevc|h[._-]?265|x265)\b', base_name, re.IGNORECASE):
        codec = "HEVC"
    elif re.search(r'\b(av1|av01)\b', base_name, re.IGNORECASE):
        codec = "AV1"
    elif re.search(r'\b(h[._-]?264|x264|avc)\b', base_name, re.IGNORECASE):
        codec = "H.264"
    elif re.search(r'\b(vp9)\b', base_name, re.IGNORECASE):
        codec = "VP9"

    # Detect Resolution
    resolution = "1080p"
    if re.search(r'\b(2160p|4k|uhd)\b', base_name, re.IGNORECASE):
        resolution = "4K UHD"
    elif re.search(r'\b(1080p|1080i|fhd)\b', base_name, re.IGNORECASE):
        resolution = "1080p"
    elif re.search(r'\b(720p|hd)\b', base_name, re.IGNORECASE):
        resolution = "720p"
    elif re.search(r'\b(480p|sd)\b', base_name, re.IGNORECASE):
        resolution = "480p"

    # Detect Year (1900 - 2099)
    year = None
    year_match = re.search(r'[\(\[\.\s_-](19\d{2}|20\d{2})[\)\]\.\s_-]', base_name)
    if year_match:
        year = int(year_match.group(1))
        # Title is generally everything before the year
        title_part = base_name[:year_match.start()]
    else:
        # Check if year is at the end of the string
        end_year_match = re.search(r'[\(\[\.\s_-](19\d{2}|20\d{2})$', base_name)
        if end_year_match:
            year = int(end_year_match.group(1))
            title_part = base_name[:end_year_match.start()]
        else:
            title_part = base_name

    # Clean up title: replace separators with spaces
    title = re.sub(r'[\._]', ' ', title_part)
    # Remove bracketed metadata like [1080p] or (BluRay)
    title = re.sub(r'\[.*?\]|\(.*?\)', '', title)
    
    # Strip common scene tags if they appeared before year
    scene_tags = r'\b(bluray|remux|web-dl|webrip|hdr|hdr10|dvdrip|brrip|hdtv|internal|proper|repack)\b'
    title = re.sub(scene_tags, '', title, flags=re.IGNORECASE)
    
    # Clean whitespace and strip
    title = re.sub(r'\s+', ' ', title).strip()

    if not title:
        title = base_name.replace('.', ' ').strip()

    return {
        "title": title,
        "year": year,
        "codec": codec,
        "resolution": resolution,
        "raw_name": filename
    }

def clean_media_title(text: str) -> str:
    """Removes separators, release group tags, resolutions, and brackets from a raw title string."""
    t = re.sub(r'[\._]', ' ', text)
    t = re.sub(r'\[.*?\]|\(.*?\)', '', t)
    scene_tags = r'\b(2160p|1080p|1080i|720p|480p|4k|uhd|fhd|hd|hevc|h[._-]?265|x265|av1|h[._-]?264|x264|bluray|remux|web-dl|webrip|hdr|hdr10|dvdrip|brrip|hdtv|internal|proper|repack|aac|ac3|dts|ddp|dd\+|atmos)\b'
    t = re.sub(scene_tags, '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def parse_episode_info(filename: str, folder_path: list = None) -> Optional[Dict[str, Any]]:
    """
    Detects if a file is an episode of a TV/Web Series and extracts Series Title,
    Season Number, Episode Number, Episode Title, Codec, and Resolution.

    Supports:
      - Direct filename episode tags: 'S01E02', 's1e2', '1x02', '01x05'
      - Nested folder structures: 'Series/Season 01/01 - Pilot.mkv' or 'Series/Episode 01.mkv'
    Returns None if the file is a standalone movie.
    """
    if not is_video_file(filename):
        return None

    base_name = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', filename)
    folder_path = folder_path or []
    parent_folder = folder_path[-1] if len(folder_path) >= 1 else ""
    grandparent_folder = folder_path[-2] if len(folder_path) >= 2 else ""

    # Common Codec & Resolution extraction
    parsed_tech = parse_filename(filename)
    codec = parsed_tech["codec"]
    resolution = parsed_tech["resolution"]

    season_num = None
    episode_num = None
    series_name_raw = ""
    episode_name_raw = ""

    # 1. Match S01E02 or S1E2 or 1x02 in filename
    s_e_match = re.search(r'[\. _\-\[]s(\d{1,2})e(\d{1,3})[\. _\-\]]', ' ' + base_name + ' ', re.IGNORECASE)
    x_match = None
    if not s_e_match:
        x_match = re.search(r'[\. _\-\[](\d{1,2})x(\d{1,3})[\. _\-\]]', ' ' + base_name + ' ', re.IGNORECASE)

    if s_e_match:
        season_num = int(s_e_match.group(1))
        episode_num = int(s_e_match.group(2))
        series_name_raw = base_name[:s_e_match.start()].strip(" ._-[]()")
        episode_name_raw = base_name[s_e_match.end() - 1:].strip(" ._-[]()")
    elif x_match:
        season_num = int(x_match.group(1))
        episode_num = int(x_match.group(2))
        series_name_raw = base_name[:x_match.start()].strip(" ._-[]()")
        episode_name_raw = base_name[x_match.end() - 1:].strip(" ._-[]()")
    else:
        # 2. Check if parent folder is Season folder (e.g., 'Season 1', 'Season 02', 'S1')
        season_folder_match = re.search(r'\b(?:Season|Series|S)\s*(\d{1,2})\b', parent_folder, re.IGNORECASE)
        if season_folder_match:
            season_num = int(season_folder_match.group(1))
            # Find episode number in filename (e.g., '01 - Pilot', 'Episode 01', 'E01')
            ep_file_match = re.search(r'(?:^|[\. _\-\[])(?:Episode|Ep|E)?\s*(\d{1,3})(?:[\. _\-\]]|$)', base_name, re.IGNORECASE)
            if ep_file_match:
                episode_num = int(ep_file_match.group(1))
                episode_name_raw = base_name[ep_file_match.end():].strip(" ._-[]()")
                series_name_raw = grandparent_folder or parent_folder

    if season_num is None or episode_num is None:
        return None

    # Determine series title
    series_title = ""
    # Check if grandparent or parent folder holds the show name
    if grandparent_folder and not re.search(r'\b(?:Season|Series|S)\s*\d+\b', grandparent_folder, re.IGNORECASE):
        series_title = clean_media_title(grandparent_folder)
    elif parent_folder and not re.search(r'\b(?:Season|Series|S)\s*\d+\b', parent_folder, re.IGNORECASE):
        series_title = clean_media_title(parent_folder)
    
    if not series_title and series_name_raw:
        # Check if year is in series_name_raw
        year_match = re.search(r'[\(\[\.\s_-](19\d{2}|20\d{2})[\)\]\.\s_-]?', series_name_raw)
        if year_match:
            series_title = clean_media_title(series_name_raw[:year_match.start()])
        else:
            series_title = clean_media_title(series_name_raw)

    if not series_title:
        series_title = parent_folder or "Unknown Series"

    # Year detection
    year = None
    y_match = re.search(r'[\(\[\.\s_-](19\d{2}|20\d{2})[\)\]\.\s_-]?', filename)
    if y_match:
        year = int(y_match.group(1))

    # Clean episode title
    clean_ep_title = clean_media_title(episode_name_raw)
    if not clean_ep_title or clean_ep_title.isdigit():
        clean_ep_title = f"Episode {episode_num}"

    return {
        "is_episode": True,
        "series_title": series_title,
        "season_number": season_num,
        "episode_number": episode_num,
        "episode_title": clean_ep_title,
        "year": year,
        "codec": codec,
        "resolution": resolution,
        "raw_name": filename
    }
