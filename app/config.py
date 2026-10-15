import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent

class AppConfig(BaseModel):
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'films_over_web.db'}")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "films-over-web-super-secret-key-change-me-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Google Drive Defaults
    DEFAULT_DRIVE_FOLDER_URL: str = os.getenv("DEFAULT_DRIVE_FOLDER_URL", "https://drive.google.com/drive/folders/1JeQk11TthFV5QgfkBtnrbrQHbZn1x5YT?usp=sharing")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_SERVICE_ACCOUNT_JSON: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    
    # TMDB Defaults
    TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")

    # Gmail SMTP Automation Defaults
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER: str = os.getenv("SMTP_USER", "drmnbot@gmail.com")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_SSL: bool = os.getenv("SMTP_USE_SSL", "true").lower() in ("true", "1", "yes")

    # Initial SuperAdmin
    DEFAULT_SUPERADMIN_EMAIL: str = os.getenv("DEFAULT_SUPERADMIN_EMAIL", "drmnbot@gmail.com")
    DEFAULT_SUPERADMIN_PASSWORD: str = os.getenv("DEFAULT_SUPERADMIN_PASSWORD", "SuperAdmin@2026")

settings = AppConfig()
