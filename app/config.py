import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent

def _resolve_superadmin_email() -> str:
    for k in ("SuperAdminEmail", "SUPERADMIN_EMAIL", "SUPERADMINEMAIL", "DEFAULT_SUPERADMIN_EMAIL"):
        v = os.getenv(k)
        if v and v.strip():
            return v.strip()
    return "test@gmail.com"

def _resolve_superadmin_password() -> str:
    for k in ("SuperAdminPassword", "SUPERADMIN_PASSWORD", "SUPERADMINPASSWORD", "DEFAULT_SUPERADMIN_PASSWORD"):
        v = os.getenv(k)
        if v and v.strip():
            return v.strip()
    return "1q2w3e4r5t"

def _is_superadmin_env_set() -> bool:
    for k in ("SuperAdminEmail", "SUPERADMIN_EMAIL", "SUPERADMINEMAIL", "SuperAdminPassword", "SUPERADMIN_PASSWORD", "SUPERADMINPASSWORD"):
        v = os.getenv(k)
        if v and v.strip():
            return True
    return False

def _resolve_env_var(keys: tuple, default: str = "") -> str:
    for k in keys:
        v = os.getenv(k)
        if v and v.strip():
            return v.strip()
    return default

class AppConfig(BaseModel):
    DATABASE_FILE: str = os.getenv("DATABASE_FILE", str(BASE_DIR / "films_over_web.json"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'films_over_web.db'}")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "films-over-web-super-secret-key-change-me-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Google Drive Defaults
    DEFAULT_DRIVE_FOLDER_URL: str = _resolve_env_var(("DEFAULT_DRIVE_FOLDER_URL", "DRIVE_FOLDER_URL", "DRIVE_FOLDER_URLS"), "")
    GOOGLE_API_KEY: str = _resolve_env_var(("GOOGLE_API_KEY", "GOOGLEAPIKEY", "GoogleApiKey", "DRIVE_API_KEY", "GDRIVE_API_KEY"), "")
    GOOGLE_SERVICE_ACCOUNT_JSON: str = _resolve_env_var(("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLESERVICEACCOUNTJSON", "GoogleServiceAccountJson", "SERVICE_ACCOUNT_JSON", "GDRIVE_SERVICE_ACCOUNT_JSON"), "")
    
    # TMDB Defaults
    TMDB_API_KEY: str = _resolve_env_var(("TMDB_API_KEY", "TMDBAPIKEY", "TmdbApiKey"), "")

    # Cloudflare Stream Worker (Option B: Zero-Bandwidth Direct Client Streaming)
    CLOUDFLARE_WORKER_URL: str = _resolve_env_var(("CLOUDFLARE_WORKER_URL", "CLOUDFLAREWORKERURL", "CloudflareWorkerUrl", "CF_WORKER_URL"), "")

    # Email Automation Defaults (Resend HTTPS API or Gmail SMTP)
    RESEND_API_KEY: str = _resolve_env_var(("RESEND_API_KEY", "RESENDAPIKEY", "ResendApiKey"), "")
    RESEND_FROM_EMAIL: str = _resolve_env_var(("RESEND_FROM_EMAIL", "RESENDFROMEMAIL", "ResendFromEmail"), "")
    SMTP_HOST: str = _resolve_env_var(("SMTP_HOST", "SMTPHOST"), "smtp.gmail.com")
    SMTP_PORT: int = int(_resolve_env_var(("SMTP_PORT", "SMTPPORT"), "465"))
    SMTP_USER: str = _resolve_env_var(("SMTP_USER", "SMTPUSER"), "")
    SMTP_PASSWORD: str = _resolve_env_var(("SMTP_PASSWORD", "SMTPPASSWORD"), "")
    SMTP_USE_SSL: bool = _resolve_env_var(("SMTP_USE_SSL", "SMTPUSESSL"), "true").lower() in ("true", "1", "yes")

    # SuperAdmin Configuration
    SUPERADMIN_EMAIL: str = _resolve_superadmin_email()
    SUPERADMIN_PASSWORD: str = _resolve_superadmin_password()
    SUPERADMIN_ENV_SET: bool = _is_superadmin_env_set()
    DEFAULT_SUPERADMIN_EMAIL: str = _resolve_superadmin_email()
    DEFAULT_SUPERADMIN_PASSWORD: str = _resolve_superadmin_password()

settings = AppConfig()
