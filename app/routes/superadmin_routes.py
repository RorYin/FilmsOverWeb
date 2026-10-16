from fastapi import APIRouter, Request, Depends, Form, HTTPException, BackgroundTasks, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import secrets
from app.database import get_db, desc, Session
from app.models import User, SystemSetting, TvLoginCode
from app.config import settings
from app.auth import get_current_user, require_role, get_password_hash
from app.mailer import send_guest_welcome_email, get_smtp_config

router = APIRouter(prefix="/superadmin", tags=["SuperAdmin Settings"])
templates = Jinja2Templates(directory="app/templates")

superadmin_only = require_role(["superadmin"])

def get_setting_val(key: str, db: Session, default: str = "") -> str:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row and row.value is not None and row.value.strip():
        return row.value.strip()
    return default

def set_setting_val(key: str, val: str, db: Session):
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row:
        row = SystemSetting(key=key, value=val)
        db.add(row)
    else:
        row.value = val
    db.commit()

@router.get("/settings", response_class=HTMLResponse)
async def settings_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    current_settings = {
        "tmdb_api_key": get_setting_val("tmdb_api_key", db, settings.TMDB_API_KEY),
        "google_api_key": get_setting_val("google_api_key", db, settings.GOOGLE_API_KEY),
        "google_service_account_json": get_setting_val("google_service_account_json", db, settings.GOOGLE_SERVICE_ACCOUNT_JSON),
        "cloudflare_worker_url": get_setting_val("cloudflare_worker_url", db, settings.CLOUDFLARE_WORKER_URL),
        "resend_api_key": get_setting_val("resend_api_key", db, getattr(settings, "RESEND_API_KEY", "")),
        "resend_from_email": get_setting_val("resend_from_email", db, getattr(settings, "RESEND_FROM_EMAIL", "")),
        "smtp_host": get_setting_val("smtp_host", db, getattr(settings, "SMTP_HOST", "smtp.gmail.com")),
        "smtp_port": get_setting_val("smtp_port", db, str(getattr(settings, "SMTP_PORT", 465))),
        "smtp_user": get_setting_val("smtp_user", db, getattr(settings, "SMTP_USER", "")),
        "smtp_password": get_setting_val("smtp_password", db, getattr(settings, "SMTP_PASSWORD", "")),
        "smtp_use_ssl": get_setting_val("smtp_use_ssl", db, "true" if getattr(settings, "SMTP_USE_SSL", True) else "false")
    }
    return templates.TemplateResponse(
        request=request,
        name="superadmin/settings.html",
        context={
            "user": user,
            "settings": current_settings,
            "setup_complete": request.query_params.get("setup_complete") == "1",
            "success": request.query_params.get("saved") == "1",
            "enriched": request.query_params.get("enriched") == "1",
            "test_result": None
        }
    )

@router.post("/settings/save")
async def save_settings(
    request: Request,
    background_tasks: BackgroundTasks,
    tmdb_api_key: str = Form(""),
    google_api_key: str = Form(""),
    google_service_account_json: str = Form(""),
    cloudflare_worker_url: str = Form(""),
    resend_api_key: str = Form(""),
    resend_from_email: str = Form(""),
    smtp_host: str = Form("smtp.gmail.com"),
    smtp_port: str = Form("465"),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_ssl: str = Form("true"),
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    set_setting_val("tmdb_api_key", tmdb_api_key.strip(), db)
    set_setting_val("google_api_key", google_api_key.strip(), db)
    set_setting_val("google_service_account_json", google_service_account_json.strip(), db)
    set_setting_val("cloudflare_worker_url", cloudflare_worker_url.strip().rstrip("/"), db)
    set_setting_val("resend_api_key", resend_api_key.strip(), db)
    set_setting_val("resend_from_email", resend_from_email.strip(), db)
    set_setting_val("smtp_host", smtp_host.strip(), db)
    set_setting_val("smtp_port", smtp_port.strip(), db)
    set_setting_val("smtp_user", smtp_user.strip(), db)
    set_setting_val("smtp_password", smtp_password.strip().replace(" ", ""), db)
    set_setting_val("smtp_use_ssl", "true" if smtp_use_ssl in ("true", "on", "1") else "false", db)

    # Automatically trigger enrichment for any movies missing TMDB data in background
    if tmdb_api_key.strip():
        from app.database import SessionLocal
        from app.tmdb import enrich_all_missing_movies
        background_tasks.add_task(enrich_all_missing_movies, SessionLocal)

    return RedirectResponse(url="/superadmin/settings?saved=1", status_code=status.HTTP_302_FOUND)

@router.post("/settings/enrich-tmdb")
async def trigger_enrich_tmdb(
    background_tasks: BackgroundTasks,
    user: User = Depends(superadmin_only)
):
    from app.database import SessionLocal
    from app.tmdb import enrich_all_missing_movies
    background_tasks.add_task(enrich_all_missing_movies, SessionLocal)
    return RedirectResponse(url="/superadmin/settings?enriched=1", status_code=status.HTTP_302_FOUND)

@router.post("/settings/test-email")
async def test_email(
    request: Request,
    test_to: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    base_url = str(request.base_url).rstrip("/")
    ok, msg = send_guest_welcome_email(
        guest_email=test_to.strip().lower(),
        guest_name="Test User",
        password="TestPassword@123",
        login_url=f"{base_url}/login",
        db=db
    )
    
    current_settings = {
        "tmdb_api_key": get_setting_val("tmdb_api_key", db, ""),
        "google_api_key": get_setting_val("google_api_key", db, ""),
        "google_service_account_json": get_setting_val("google_service_account_json", db, ""),
        "cloudflare_worker_url": get_setting_val("cloudflare_worker_url", db, settings.CLOUDFLARE_WORKER_URL),
        "resend_api_key": get_setting_val("resend_api_key", db, getattr(settings, "RESEND_API_KEY", "")),
        "resend_from_email": get_setting_val("resend_from_email", db, getattr(settings, "RESEND_FROM_EMAIL", "")),
        "smtp_host": get_setting_val("smtp_host", db, "smtp.gmail.com"),
        "smtp_port": get_setting_val("smtp_port", db, "465"),
        "smtp_user": get_setting_val("smtp_user", db, ""),
        "smtp_password": get_setting_val("smtp_password", db, ""),
        "smtp_use_ssl": get_setting_val("smtp_use_ssl", db, "true")
    }

    return templates.TemplateResponse(
        request=request,
        name="superadmin/settings.html",
        context={
            "user": user,
            "settings": current_settings,
            "success": False,
            "test_result": {"success": ok, "message": msg}
        }
    )

@router.get("/admins", response_class=HTMLResponse)
async def list_admins(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    admins = db.query(User).filter(User.role.in_(["admin", "superadmin"])).order_by(User.role.desc(), User.created_at.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="superadmin/admins.html",
        context={
            "user": user,
            "admins": admins,
            "error": None
        }
    )

@router.post("/admins/create")
async def create_admin(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    role: str = Form("admin"),
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    clean_email = email.strip().lower()
    existing = db.query(User).filter(User.email == clean_email).first()
    if existing:
        admins = db.query(User).filter(User.role.in_(["admin", "superadmin"])).all()
        return templates.TemplateResponse(
            request=request,
            name="superadmin/admins.html",
            context={
                "user": user,
                "admins": admins,
                "error": f"User '{clean_email}' already exists."
            },
            status_code=400
        )

    assigned_role = "superadmin" if role == "superadmin" else "admin"
    new_admin = User(
        email=clean_email,
        name=name.strip(),
        hashed_password=get_password_hash(password),
        role=assigned_role,
        is_active=True
    )
    db.add(new_admin)
    db.commit()

    return RedirectResponse(url="/superadmin/admins", status_code=status.HTTP_302_FOUND)

@router.post("/admins/{admin_id}/delete")
async def delete_admin(
    admin_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    # Prevent self-deletion
    if admin_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own superadmin account.")

    admin_to_del = db.query(User).filter(User.id == admin_id).first()
    if admin_to_del:
        db.delete(admin_to_del)
        db.commit()
    return RedirectResponse(url="/superadmin/admins", status_code=status.HTTP_302_FOUND)


# --- 5-Digit TV Access Codes Management (Only SuperAdmin) ---

def generate_unique_tv_code(db: Session) -> str:
    """Generates an unguessable 5-digit numeric code from 10000 to 99999."""
    for _ in range(200):
        code_str = str(secrets.randbelow(90000) + 10000)
        existing = db.query(TvLoginCode).filter(
            TvLoginCode.code == code_str,
            TvLoginCode.is_used == False
        ).first()
        if not existing:
            return code_str
    return str(secrets.randbelow(90000) + 10000)

@router.get("/tv-codes", response_class=HTMLResponse)
async def list_tv_codes(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    codes = db.query(TvLoginCode).order_by(desc(TvLoginCode.created_at)).all()
    created_code = request.query_params.get("created")
    deleted = request.query_params.get("deleted") == "1"

    active_count = len([c for c in codes if not c.is_used])
    used_count = len([c for c in codes if c.is_used])

    return templates.TemplateResponse(
        request=request,
        name="superadmin/tv_codes.html",
        context={
            "user": user,
            "codes": codes,
            "active_count": active_count,
            "used_count": used_count,
            "created_code": created_code,
            "deleted": deleted
        }
    )

@router.post("/tv-codes/generate")
async def generate_tv_code_action(
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    new_code = generate_unique_tv_code(db)
    tv_code_obj = TvLoginCode(
        code=new_code,
        created_by_id=user.id,
        is_used=False
    )
    db.add(tv_code_obj)
    db.commit()
    return RedirectResponse(url=f"/superadmin/tv-codes?created={new_code}", status_code=status.HTTP_302_FOUND)

@router.post("/tv-codes/{code_id}/delete")
async def delete_tv_code_action(
    code_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    code_to_del = db.query(TvLoginCode).filter(TvLoginCode.id == code_id).first()
    if code_to_del:
        db.delete(code_to_del)
        db.commit()
    return RedirectResponse(url="/superadmin/tv-codes?deleted=1", status_code=status.HTTP_302_FOUND)

