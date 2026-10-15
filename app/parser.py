import re
from typing import Dict, Any

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
