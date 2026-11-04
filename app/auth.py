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
    # Check share_token query param
    share_token_param = request.query_params.get("share_token")
    if share_token_param:
        return share_token_param
    # Check HTTP-only cookie
    fow_token = request.cookies.get(COOKIE_NAME)
    if fow_token:
        return fow_token

    # Check shared token cookies
    share_cookie = request.cookies.get("fow_share_token")
    if share_cookie:
        return share_cookie

    # Check movie-specific cookie if path contains movie id
    path_parts = request.url.path.strip("/").split("/")
    if len(path_parts) >= 2 and path_parts[0] in ["watch", "stream", "movie", "api"]:
        try:
            m_id = path_parts[1].split(".")[0]
            movie_cookie = request.cookies.get(f"fow_share_movie_{m_id}")
            if movie_cookie:
                return movie_cookie
        except Exception:
            pass

    # Check any fow_share_ cookie in request
    for c_name, c_val in request.cookies.items():
        if c_name.startswith("fow_share_"):
            return c_val

    return None

def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = get_token_from_request(request)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None

    # Handle ephemeral 48h shared viewer access
    if payload.get("is_shared"):
        shared_user = User(
            id=0,
            email=payload.get("sub", "shared_viewer@guest"),
            name="Shared Guest",
            role="guest",
            is_active=True,
            must_change_password=False
        )
        setattr(shared_user, "is_shared", True)
        setattr(shared_user, "shared_movie_id", payload.get("shared_movie_id"))
        setattr(shared_user, "shared_gdrive_file_id", payload.get("shared_gdrive_file_id"))
        setattr(shared_user, "shared_file_name", payload.get("shared_file_name"))
        setattr(shared_user, "movie_title", payload.get("movie_title", ""))
        setattr(shared_user, "share_token", payload.get("share_token", ""))
        return shared_user

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

    # Restrict shared pass viewers strictly to the single shared movie and its media stream
    if getattr(user, "is_shared", False):
        path = request.url.path
        allowed = False
        if path.startswith("/static") or path.startswith("/share"):
            allowed = True
        elif path.startswith("/movie/") or path.startswith("/watch/") or path.startswith("/stream/") or path.startswith("/api/movies/"):
            path_parts = path.strip("/").split("/")
            if len(path_parts) >= 2:
                try:
                    target_id = int(path_parts[1].split(".")[0])
                    if target_id == getattr(user, "shared_movie_id", None):
                        allowed = True
                    else:
                        from app.models import Movie
                        target_m = db.query(Movie).filter(Movie.id == target_id).first()
                        if target_m:
                            shared_gid = getattr(user, "shared_gdrive_file_id", None)
                            shared_fname = getattr(user, "shared_file_name", None)
                            if shared_gid and target_m.gdrive_file_id == shared_gid:
                                allowed = True
                            elif shared_fname and target_m.file_name == shared_fname:
                                allowed = True
                except ValueError:
                    pass

        if not allowed:
            accept = request.headers.get("accept", "")
            if "text/html" in accept or request.method == "GET":
                raise HTTPException(
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                    headers={"Location": f"/login?next={request.url.path}"}
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Shared pass is restricted exclusively to the shared movie."
            )
        return user

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

    # Ensure default guest user exists with must_change_password=False
    guest_email = "guest@filmsoverweb.com"
    guest_password = "guest@123"
    guest_user = db.query(User).filter(User.email == guest_email).first()
    if not guest_user:
        guest_user = User(
            email=guest_email,
            name="Guest User",
            hashed_password=get_password_hash(guest_password),
            role="guest",
            must_change_password=False,
            is_active=True
        )
        db.add(guest_user)
        db.commit()
        print(f"[AUTH] Created default Guest user ({guest_email}) with must_change_password=False")
    else:
        needs_guest_update = False
        if not verify_password(guest_password, guest_user.hashed_password):
            guest_user.hashed_password = get_password_hash(guest_password)
            needs_guest_update = True
        if guest_user.must_change_password:
            guest_user.must_change_password = False
            needs_guest_update = True
        if not guest_user.is_active:
            guest_user.is_active = True
            needs_guest_update = True
        if needs_guest_update:
            db.commit()
            print(f"[AUTH] Ensured default Guest user ({guest_email}) is active with must_change_password=False")
