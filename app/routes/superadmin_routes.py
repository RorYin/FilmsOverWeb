from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, SystemSetting
from app.auth import get_current_user, require_role, get_password_hash
from app.mailer import send_guest_welcome_email, get_smtp_config

router = APIRouter(prefix="/superadmin", tags=["SuperAdmin Settings"])
templates = Jinja2Templates(directory="app/templates")

superadmin_only = require_role(["superadmin"])

def get_setting_val(key: str, db: Session, default: str = "") -> str:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return row.value if row and row.value is not None else default

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
        "tmdb_api_key": get_setting_val("tmdb_api_key", db, ""),
        "google_api_key": get_setting_val("google_api_key", db, ""),
        "google_service_account_json": get_setting_val("google_service_account_json", db, ""),
        "smtp_host": get_setting_val("smtp_host", db, "smtp.gmail.com"),
        "smtp_port": get_setting_val("smtp_port", db, "465"),
        "smtp_user": get_setting_val("smtp_user", db, "drmnbot@gmail.com"),
        "smtp_password": get_setting_val("smtp_password", db, ""),
        "smtp_use_ssl": get_setting_val("smtp_use_ssl", db, "true")
    }
    return templates.TemplateResponse(
        request=request,
        name="superadmin/settings.html",
        context={
            "user": user,
            "settings": current_settings,
            "success": request.query_params.get("saved") == "1",
            "test_result": None
        }
    )

@router.post("/settings/save")
async def save_settings(
    request: Request,
    tmdb_api_key: str = Form(""),
    google_api_key: str = Form(""),
    google_service_account_json: str = Form(""),
    smtp_host: str = Form("smtp.gmail.com"),
    smtp_port: str = Form("465"),
    smtp_user: str = Form("drmnbot@gmail.com"),
    smtp_password: str = Form(""),
    smtp_use_ssl: str = Form("true"),
    db: Session = Depends(get_db),
    user: User = Depends(superadmin_only)
):
    set_setting_val("tmdb_api_key", tmdb_api_key.strip(), db)
    set_setting_val("google_api_key", google_api_key.strip(), db)
    set_setting_val("google_service_account_json", google_service_account_json.strip(), db)
    set_setting_val("smtp_host", smtp_host.strip(), db)
    set_setting_val("smtp_port", smtp_port.strip(), db)
    set_setting_val("smtp_user", smtp_user.strip(), db)
    set_setting_val("smtp_password", smtp_password.strip(), db)
    set_setting_val("smtp_use_ssl", "true" if smtp_use_ssl in ("true", "on", "1") else "false", db)

    return RedirectResponse(url="/superadmin/settings?saved=1", status_code=status.HTTP_302_FOUND)

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
        "smtp_host": get_setting_val("smtp_host", db, "smtp.gmail.com"),
        "smtp_port": get_setting_val("smtp_port", db, "465"),
        "smtp_user": get_setting_val("smtp_user", db, "drmnbot@gmail.com"),
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
