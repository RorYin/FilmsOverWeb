from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.auth import verify_password, get_password_hash, create_access_token, COOKIE_NAME, get_current_user_optional
from app.mailer import generate_secure_password, send_password_reset_email

router = APIRouter(tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        if user.must_change_password:
            return RedirectResponse(url="/change-password", status_code=status.HTTP_302_FOUND)
        return RedirectResponse(url=next or "/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": next, "error": None}
    )

@router.post("/login")
async def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"next": next, "error": "Invalid email address or password."},
            status_code=400
        )
    
    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"next": next, "error": "Your account has been deactivated."},
            status_code=403
        )

    # Generate JWT
    token = create_access_token({"sub": user.email, "role": user.role, "name": user.name})
    
    # If the user is flagged to change password, route straight to /change-password
    if user.must_change_password:
        target_url = "/change-password"
    else:
        target_url = next if next.startswith("/") and not next.startswith("/change-password") else "/"

    response = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,  # 7 days
        samesite="lax",
        secure=False  # Allow local HTTP testing
    )
    return response

@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/change-password", status_code=status.HTTP_302_FOUND)
    
    return templates.TemplateResponse(
        request=request,
        name="change_password.html",
        context={
            "user": user,
            "is_first_time": user.must_change_password,
            "error": None,
            "success": None
        }
    )

@router.post("/change-password")
async def change_password_action(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Validate current password
    if not verify_password(current_password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={
                "user": user,
                "is_first_time": user.must_change_password,
                "error": "The current (or temporary) password you entered is incorrect."
            },
            status_code=400
        )

    # Validate new password match
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={
                "user": user,
                "is_first_time": user.must_change_password,
                "error": "New password and confirmation password do not match."
            },
            status_code=400
        )

    # Validate password length
    if len(new_password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={
                "user": user,
                "is_first_time": user.must_change_password,
                "error": "New password must be at least 8 characters long."
            },
            status_code=400
        )

    # Prevent reusing same temporary password
    if verify_password(new_password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={
                "user": user,
                "is_first_time": user.must_change_password,
                "error": "New password cannot be the same as your old temporary password."
            },
            status_code=400
        )

    # Apply new password and clear first-time change flag
    user.hashed_password = get_password_hash(new_password)
    user.must_change_password = False
    db.commit()

    # Redirect to home with notification
    return RedirectResponse(url="/?password_changed=1", status_code=status.HTTP_302_FOUND)

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"error": None, "success": None, "sent_email": None}
    )

@router.post("/forgot-password")
async def forgot_password_action(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    clean_email = email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "error": f"No account found with email '{clean_email}'. Please check your spelling or contact your administrator.",
                "success": None,
                "sent_email": None
            },
            status_code=400
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "error": "This account is currently deactivated. Please contact your administrator.",
                "success": None,
                "sent_email": None
            },
            status_code=403
        )

    # Auto-generate a new temporary password
    new_temp_pw = generate_secure_password(length=12)
    user.hashed_password = get_password_hash(new_temp_pw)
    user.must_change_password = True
    db.commit()

    # Build login URL
    base_url = str(request.base_url).rstrip("/")
    login_url = f"{base_url}/login"

    # Send reset email
    ok, mail_msg = send_password_reset_email(
        user_email=user.email,
        user_name=user.name,
        temp_password=new_temp_pw,
        login_url=login_url,
        db=db
    )

    if not ok:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "error": f"Temporary password was generated, but email dispatch failed: {mail_msg}",
                "success": None,
                "sent_email": clean_email
            },
            status_code=500
        )

    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={
            "error": None,
            "success": f"A new temporary password has been dispatched to {clean_email}! Check your inbox, sign in, and you will be prompted to choose your permanent password.",
            "sent_email": clean_email
        }
    )

@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(COOKIE_NAME)
    return response
