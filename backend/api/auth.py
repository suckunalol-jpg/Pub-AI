import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

import bcrypt

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.database import get_db
from db.models import ApiKey, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Permanent owners — cannot be demoted
OWNER_USERNAMES = {"obinofue1", "miz_lean"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

ALGORITHM = "HS256"


# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "user"


class ApiKeyCreate(BaseModel):
    name: str
    platform: str = "web"


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    key_prefix: str
    name: str
    platform: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    raw_key: str  # Only returned at creation time
    key: str  # Alias exposed to frontend


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: Optional[str]
    role: str

    model_config = {"from_attributes": True}


class UserListItem(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleUpdateRequest(BaseModel):
    role: str  # "admin" or "user"


class PasswordResetRequest(BaseModel):
    username: str
    new_password: str


# ---------- Helpers ----------

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user_from_token(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_user_from_api_key(
    api_key: str,
    db: AsyncSession,
) -> User:
    """Validate an API key and return the associated user."""
    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    key_record = result.scalar_one_or_none()
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Update last used
    key_record.last_used_at = datetime.utcnow()

    result = await db.execute(select(User).where(User.id == key_record.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found for API key")
    return user


async def require_admin(
    user: User = Depends(get_current_user_from_token),
) -> User:
    """Dependency that ensures the current user is an admin or owner."""
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------- Routes ----------

@router.post("/register", response_model=UserResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check duplicate username
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    assigned_role = "owner" if req.username in OWNER_USERNAMES else "user"
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=assigned_role,
    )
    db.add(user)
    await db.flush()
    return user


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, role=user.role or "user")


@router.post("/api-keys", response_model=ApiKeyCreatedResponse)
async def create_api_key(
    req: ApiKeyCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    raw_key = f"{settings.API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_record = ApiKey(
        user_id=user.id,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        name=req.name,
        platform=req.platform,
    )
    db.add(key_record)
    await db.flush()

    return ApiKeyCreatedResponse(
        id=key_record.id,
        key_prefix=key_record.key_prefix,
        name=key_record.name,
        platform=key_record.platform,
        is_active=key_record.is_active,
        created_at=key_record.created_at,
        raw_key=raw_key,
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    key_record = result.scalar_one_or_none()
    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")
    key_record.is_active = False
    return {"detail": "API key revoked"}


# ---------- User Management ----------

@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user_from_token)):
    """Return current user info."""
    return user


@router.get("/users", response_model=list[UserListItem])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users. Admin/owner only."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    req: RoleUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's role. Admin/owner only. Cannot change owner roles."""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Cannot change owner roles
    if target_user.username in OWNER_USERNAMES:
        raise HTTPException(status_code=403, detail="Cannot change owner roles")

    # Cannot change another owner's role (safety check)
    if target_user.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot change owner roles")

    target_user.role = req.role
    await db.flush()
    return {"detail": f"Role updated to {req.role}", "user_id": str(user_id), "role": req.role}


@router.post("/owner-reset")
async def owner_reset_password(req: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Reset password for owner accounts only. No auth required."""
    if req.username not in OWNER_USERNAMES:
        raise HTTPException(status_code=403, detail="Only owner accounts can use this endpoint")
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")

    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Register first.")

    user.hashed_password = hash_password(req.new_password)
    await db.flush()
    return {"detail": f"Password reset for {req.username}"}
