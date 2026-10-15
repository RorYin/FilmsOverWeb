from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="guest", nullable=False)  # "superadmin", "admin", "guest"
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

    watch_history = relationship("WatchProgress", back_populates="user", cascade="all, delete-orphan")

class DriveFolder(Base):
    __tablename__ = "drive_folders"

    id = Column(Integer, primary_key=True, index=True)
    folder_id = Column(String(255), unique=True, index=True, nullable=False)
    folder_name = Column(String(255), nullable=True)
    folder_url = Column(String(1024), nullable=True)
    movie_count = Column(Integer, default=0)
    last_synced_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    movies = relationship("Movie", back_populates="folder", cascade="all, delete-orphan")

class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, index=True)
    gdrive_file_id = Column(String(255), unique=True, index=True, nullable=False)
    folder_id = Column(Integer, ForeignKey("drive_folders.id"), nullable=True)
    file_name = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100), default="video/mp4")
    
    # Technical specs extracted from filename or metadata
    codec = Column(String(50), default="Unknown")  # e.g., "HEVC", "AV1", "H.264"
    resolution = Column(String(50), default="1080p")  # e.g., "4K UHD", "1080p", "720p"
    
    # TMDB & Meta Information
    tmdb_id = Column(Integer, nullable=True)
    title = Column(String(500), index=True, nullable=False)
    original_title = Column(String(500), nullable=True)
    year = Column(Integer, nullable=True)
    overview = Column(Text, nullable=True)
    tagline = Column(String(500), nullable=True)
    poster_path = Column(String(1024), nullable=True)
    backdrop_path = Column(String(1024), nullable=True)
    rating = Column(Float, default=0.0)
    vote_count = Column(Integer, default=0)
    duration = Column(Integer, default=0)  # Runtime in minutes
    genres = Column(String(500), default="")  # e.g., "Action, Sci-Fi"
    cast = Column(String(1000), default="")   # Top actors
    director = Column(String(255), default="")
    trailer_url = Column(String(1024), nullable=True)
    original_language = Column(String(50), default="English")

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    folder = relationship("DriveFolder", back_populates="movies")
    watch_history = relationship("WatchProgress", back_populates="movie", cascade="all, delete-orphan")

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class WatchProgress(Base):
    __tablename__ = "watch_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    position_seconds = Column(Float, default=0.0)
    duration_seconds = Column(Float, default=0.0)
    completed = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="watch_history")
    movie = relationship("Movie", back_populates="watch_history")
