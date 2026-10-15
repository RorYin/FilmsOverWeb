from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from app.config import settings
from app.database import get_db, Session
from app.models import User

COOKIE_NAME = "fow_token"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except Exception:
        return None

def get_token_from_request(request: Request) -> Optional[str]:
    # Check Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    # Check query parameter (e.g. for VLC, external player, or media streams)
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    # Check HTTP-only cookie
    return request.cookies.get(COOKIE_NAME)

def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = get_token_from_request(request)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    email = payload.get("sub")
    if not email:
        return None
    return db.query(User).filter(User.email == email, User.is_active == True).first()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        # Check if requesting JSON or HTML
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": f"/login?next={request.url.path}"}
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce password change for users flagged with must_change_password
    path = request.url.path
    if user.must_change_password and not path.startswith("/change-password") and not path.startswith("/logout") and not path.startswith("/static"):
        accept = request.headers.get("accept", "")
        if "text/html" in accept or request.method == "GET":
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/change-password"}
            )

    return user

def require_role(roles: list[str]):
    def role_checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of roles: {', '.join(roles)}"
            )
        return user
    return role_checker

def init_default_users(db: Session):
    """Ensure at least one superadmin exists with the configured credentials."""
    target_email = settings.SUPERADMIN_EMAIL
    target_password = settings.SUPERADMIN_PASSWORD
    is_env_set = settings.SUPERADMIN_ENV_SET

    # Check if legacy default superadmin exists and migrate
    old_default = db.query(User).filter(User.email == "drmnbot@gmail.com").first()
    if old_default:
        old_default.email = target_email
        old_default.hashed_password = get_password_hash(target_password)
        old_default.must_change_password = not is_env_set
        db.commit()
        print(f"[AUTH] Migrated legacy default SuperAdmin to ({target_email}) with must_change_password={not is_env_set}")

    existing_superadmin = db.query(User).filter(User.role == "superadmin").first()
    if existing_superadmin:
        if is_env_set:
            # If explicit SuperAdmin environment variables are set, enforce them and bypass password change
            needs_update = False
            if existing_superadmin.email != target_email:
                existing_superadmin.email = target_email
                needs_update = True
            if not verify_password(target_password, existing_superadmin.hashed_password):
                existing_superadmin.hashed_password = get_password_hash(target_password)
                needs_update = True
            if existing_superadmin.must_change_password:
                existing_superadmin.must_change_password = False
                needs_update = True
            if needs_update:
                db.commit()
                print(f"[AUTH] Configured SuperAdmin ({target_email}) from environment variables with must_change_password=False")
    else:
        existing_user = db.query(User).filter(User.email == target_email).first()
        if existing_user:
            existing_user.role = "superadmin"
            existing_user.hashed_password = get_password_hash(target_password)
            existing_user.must_change_password = not is_env_set
            db.commit()
            print(f"[AUTH] Promoted existing user {target_email} to SuperAdmin with must_change_password={not is_env_set}.")
        else:
            default_admin = User(
                email=target_email,
                name="Super Administrator",
                hashed_password=get_password_hash(target_password),
                role="superadmin",
                must_change_password=(not is_env_set),
                is_active=True
            )
            db.add(default_admin)
            db.commit()
            print(f"[AUTH] Created SuperAdmin ({target_email}) with must_change_password={not is_env_set}")
