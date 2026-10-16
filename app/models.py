from datetime import datetime, timezone
from app.database import (
    Base, Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, utc_now, get_json_db
)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), default="")
    name = Column(String(255), default="")
    hashed_password = Column(String(255), default="")
    role = Column(String(50), default="guest")  # "superadmin", "admin", "guest"
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

    @property
    def watch_history(self):
        return [p for p in get_json_db().get_collection(WatchProgress) if p.user_id == self.id]


class DriveFolder(Base):
    __tablename__ = "drive_folders"

    id = Column(Integer, primary_key=True)
    folder_id = Column(String(255), default="")
    folder_name = Column(String(255), default="")
    folder_url = Column(String(1024), default="")
    movie_count = Column(Integer, default=0)
    last_synced_at = Column(DateTime, default=None)
    created_by_id = Column(Integer, default=None)
    created_at = Column(DateTime, default=utc_now)

    @property
    def movies(self):
        return [m for m in get_json_db().get_collection(Movie) if m.folder_id == self.id]


    @property
    def series(self):
        return [s for s in get_json_db().get_collection(Series) if s.folder_id == self.id]

    @property
    def episodes(self):
        return [e for e in get_json_db().get_collection(Episode) if e.folder_id == self.id]


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True)
    gdrive_file_id = Column(String(255), default="")
    folder_id = Column(Integer, default=None)
    file_name = Column(String(500), default="")
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100), default="video/mp4")
    
    # Technical specs extracted from filename or metadata
    codec = Column(String(50), default="Unknown")  # e.g., "HEVC", "AV1", "H.264"
    resolution = Column(String(50), default="1080p")  # e.g., "4K UHD", "1080p", "720p"
    
    # TMDB & Meta Information
    tmdb_id = Column(Integer, default=None)
    title = Column(String(500), default="")
    original_title = Column(String(500), default="")
    year = Column(Integer, default=None)
    overview = Column(Text, default="")
    tagline = Column(String(500), default="")
    poster_path = Column(String(1024), default="")
    backdrop_path = Column(String(1024), default="")
    rating = Column(Float, default=0.0)
    vote_count = Column(Integer, default=0)
    duration = Column(Integer, default=0)  # Runtime in minutes
    genres = Column(String(500), default="")  # e.g., "Action, Sci-Fi"
    cast = Column(String(1000), default="")   # Top actors
    director = Column(String(255), default="")
    trailer_url = Column(String(1024), default=None)
    original_language = Column(String(50), default="English")

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now)

    @property
    def folder(self):
        return get_json_db().get_by_id(DriveFolder, self.folder_id)

    @property
    def watch_history(self):
        return [p for p in get_json_db().get_collection(WatchProgress) if p.movie_id == self.id]


class Series(Base):
    __tablename__ = "series"

    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, default=None)
    title = Column(String(500), default="")
    original_title = Column(String(500), default="")
    year = Column(Integer, default=None)
    tmdb_id = Column(Integer, default=None)
    overview = Column(Text, default="")
    tagline = Column(String(500), default="")
    poster_path = Column(String(1024), default="")
    backdrop_path = Column(String(1024), default="")
    rating = Column(Float, default=0.0)
    vote_count = Column(Integer, default=0)
    genres = Column(String(500), default="")
    cast = Column(String(1000), default="")
    creator = Column(String(255), default="")
    original_language = Column(String(50), default="English")
    total_seasons = Column(Integer, default=1)
    total_episodes = Column(Integer, default=0)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now)

    @property
    def folder(self):
        return get_json_db().get_by_id(DriveFolder, self.folder_id)

    @property
    def episodes(self):
        eps = [e for e in get_json_db().get_collection(Episode) if e.series_id == self.id]
        return sorted(eps, key=lambda x: (x.season_number, x.episode_number))

    @property
    def seasons(self):
        distinct_seasons = sorted(list({e.season_number for e in self.episodes}))
        return distinct_seasons if distinct_seasons else [1]


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True)
    series_id = Column(Integer, default=None)
    folder_id = Column(Integer, default=None)
    season_number = Column(Integer, default=1)
    episode_number = Column(Integer, default=1)
    title = Column(String(500), default="")
    overview = Column(Text, default="")
    still_path = Column(String(1024), default="")
    air_date = Column(String(50), default="")
    rating = Column(Float, default=0.0)
    duration = Column(Integer, default=0)  # Runtime in minutes

    gdrive_file_id = Column(String(255), default="")
    file_name = Column(String(500), default="")
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100), default="video/mp4")
    codec = Column(String(50), default="Unknown")
    resolution = Column(String(50), default="1080p")

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now)

    @property
    def series(self):
        return get_json_db().get_by_id(Series, self.series_id)

    @property
    def folder(self):
        return get_json_db().get_by_id(DriveFolder, self.folder_id)

    @property
    def watch_history(self):
        return [p for p in get_json_db().get_collection(WatchProgress) if p.episode_id == self.id]


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, default=None)
    updated_at = Column(DateTime, default=utc_now)


class WatchProgress(Base):
    __tablename__ = "watch_progress"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, default=None)
    movie_id = Column(Integer, default=None)
    episode_id = Column(Integer, default=None)
    position_seconds = Column(Float, default=0.0)
    duration_seconds = Column(Float, default=0.0)
    completed = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=utc_now)

    @property
    def user(self):
        return get_json_db().get_by_id(User, self.user_id)

    @property
    def movie(self):
        return get_json_db().get_by_id(Movie, self.movie_id) if self.movie_id else None

    @property
    def episode(self):
        return get_json_db().get_by_id(Episode, self.episode_id) if self.episode_id else None

    @property
    def is_episode(self):
        return self.episode_id is not None


class TvLoginCode(Base):
    __tablename__ = "tv_login_codes"

    id = Column(Integer, primary_key=True)
    code = Column(String(10), default="")  # 5-digit numeric code, e.g. "49201"
    created_by_id = Column(Integer, default=None)
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime, default=None)
    created_at = Column(DateTime, default=utc_now)

    @property
    def created_by(self):
        return get_json_db().get_by_id(User, self.created_by_id)

