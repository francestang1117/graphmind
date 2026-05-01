"""JWT authentication for local accounts.

Implemented:
- register / login / me endpoints for the first protected API layer
- short-lived HS256 access tokens
- 7-day opaque refresh tokens
- Redis refresh-token storage when available, with in-process fallback for dev
- bcrypt password hashing when passlib is installed, with PBKDF2 fallback

This is intentionally still an MVP: user records live in memory until the
database module owns account persistence.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.core.config import settings

log = logging.getLogger(__name__)
router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    auto_error=False,
)

try:
    import bcrypt as _bcrypt_backend
except Exception:  # pragma: no cover - bcrypt is optional in local fallback mode
    _bcrypt_backend = None

try:
    from passlib.context import CryptContext

    _pwd_ctx = CryptContext(
        schemes=["bcrypt"],
        deprecated="auto",
        bcrypt__rounds=settings.BCRYPT_ROUNDS,
    )
except Exception:  # pragma: no cover - exercised only when passlib is absent
    _pwd_ctx = None
    log.warning("passlib[bcrypt] is not installed; using PBKDF2 fallback for local auth")


# ── API schemas ───────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str
    password: str
    name: str = ""


class UserPublic(BaseModel):
    id: str
    email: str
    name: str
    created_at: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Local stores ──────────────────────────────────────────────────────────────

@dataclass
class UserRecord:
    id: str
    email: str
    name: str
    hashed_password: str
    created_at: str


@dataclass
class RefreshRecord:
    user_id: str
    expires_at: datetime


_users: dict[str, UserRecord] = {}
_refresh_tokens: dict[str, RefreshRecord] = {}


# ── Password helpers ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """Hash a password. bcrypt is preferred; PBKDF2 keeps local dev dependency-light."""
    if _bcrypt_backend:
        digest = _bcrypt_backend.hashpw(
            password.encode("utf-8"),
            _bcrypt_backend.gensalt(rounds=settings.BCRYPT_ROUNDS),
        )
        return f"bcrypt${digest.decode('utf-8')}"

    if _pwd_ctx:
        try:
            return _pwd_ctx.hash(password)
        except Exception as exc:
            log.warning("passlib bcrypt failed, using PBKDF2 fallback: %s", exc)

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000)
    return f"pbkdf2_sha256${salt}${base64.urlsafe_b64encode(digest).decode()}"


def _verify_password(password: str, hashed: str) -> bool:
    if hashed.startswith("bcrypt$") and _bcrypt_backend:
        expected = hashed.removeprefix("bcrypt$").encode("utf-8")
        return bool(_bcrypt_backend.checkpw(password.encode("utf-8"), expected))

    if _pwd_ctx and not hashed.startswith("pbkdf2_sha256$"):
        try:
            return _pwd_ctx.verify(password, hashed)
        except Exception:
            return False

    try:
        _, salt, expected = hashed.split("$", 2)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000)
        actual = base64.urlsafe_b64encode(digest).decode()
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    header = {"alg": settings.JWT_ALGORITHM, "typ": "JWT"}
    unsigned = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(payload).encode())}"
    signature = hmac.new(settings.SECRET_KEY.encode(), unsigned.encode(), hashlib.sha256).digest()
    return f"{unsigned}.{_b64url(signature)}"


def _decode_access_token(token: str) -> str:
    try:
        header_raw, payload_raw, signature_raw = token.split(".")
        unsigned = f"{header_raw}.{payload_raw}"
        expected = hmac.new(settings.SECRET_KEY.encode(), unsigned.encode(), hashlib.sha256).digest()
        actual = _b64url_decode(signature_raw)
        if not hmac.compare_digest(expected, actual):
            raise ValueError("bad signature")

        header = json.loads(_b64url_decode(header_raw))
        if header.get("alg") != settings.JWT_ALGORITHM:
            raise ValueError("unsupported algorithm")

        payload = json.loads(_b64url_decode(payload_raw))
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")

        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("missing subject")
        return user_id
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


# ── Refresh token storage ─────────────────────────────────────────────────────

async def _redis_client():
    """Return a Redis client when redis-py is installed and reachable."""
    try:
        import redis.asyncio as aioredis

        return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


async def _store_refresh_token(token: str, user_id: str) -> None:
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    client = await _redis_client()
    if client:
        try:
            await client.setex(f"refresh:{token}", ttl, user_id)
            await client.aclose()
            return
        except Exception as exc:
            log.warning("Redis refresh token storage failed, using local fallback: %s", exc)

    _refresh_tokens[token] = RefreshRecord(
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
    )


async def _get_refresh_user_id(token: str) -> Optional[str]:
    client = await _redis_client()
    if client:
        try:
            user_id = await client.get(f"refresh:{token}")
            await client.aclose()
            if user_id:
                return user_id
        except Exception as exc:
            log.warning("Redis refresh token lookup failed, using local fallback: %s", exc)

    record = _refresh_tokens.get(token)
    if not record:
        return None
    if record.expires_at < datetime.now(timezone.utc):
        _refresh_tokens.pop(token, None)
        return None
    return record.user_id


async def _revoke_refresh_token(token: str) -> None:
    client = await _redis_client()
    if client:
        try:
            await client.delete(f"refresh:{token}")
            await client.aclose()
        except Exception:
            pass
    _refresh_tokens.pop(token, None)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    clean = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
        raise HTTPException(status_code=422, detail="Invalid email address")
    return clean


def _public_user(user: UserRecord) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
    )


async def current_user(token: str = Depends(oauth2_scheme)) -> UserRecord:
    """Resolve the authenticated user from the Bearer access token."""
    return _user_from_token(token)


async def current_user_or_dev(token: Optional[str] = Depends(optional_oauth2_scheme)) -> UserRecord:
    """Return authenticated user, or local-dev user while auth UI is not built yet."""
    if token:
        return _user_from_token(token)
    if settings.AUTH_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _ensure_dev_user()


# Backward-compatible name for modules that still import get_current_user.
get_current_user = current_user


def _user_from_token(token: str) -> UserRecord:
    user_id = _decode_access_token(token)
    user = next((item for item in _users.values() if item.id == user_id), None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _ensure_dev_user() -> UserRecord:
    """Stable local user used only while AUTH_REQUIRED=false."""
    email = "local@example.com"
    if email not in _users:
        _users[email] = UserRecord(
            id="local-dev",
            email=email,
            name="Local Dev",
            hashed_password="",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    return _users[email]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate) -> TokenPair:
    """Create a local account and return both access and refresh tokens."""
    email = _normalize_email(body.email)
    if email in _users:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    user = UserRecord(
        id=uuid.uuid4().hex,
        email=email,
        name=body.name.strip(),
        hashed_password=_hash_password(body.password),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _users[email] = user

    access_token = _create_access_token(user.id)
    refresh_token = _create_refresh_token()
    await _store_refresh_token(refresh_token, user.id)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenPair)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenPair:
    """Authenticate with email + password. Swagger's Authorize form uses username=email."""
    email = _normalize_email(form.username)
    user = _users.get(email)
    if not user or not _verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = _create_access_token(user.id)
    refresh_token = _create_refresh_token()
    await _store_refresh_token(refresh_token, user.id)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessToken)
async def refresh_token(body: RefreshRequest) -> AccessToken:
    """Exchange a valid refresh token for a new short-lived access token."""
    user_id = await _get_refresh_user_id(body.refresh_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    return AccessToken(access_token=_create_access_token(user_id))


@router.post("/logout")
async def logout(body: RefreshRequest, _: UserRecord = Depends(current_user)) -> dict[str, str]:
    """Invalidate one refresh token. The client should also discard its access token."""
    await _revoke_refresh_token(body.refresh_token)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserPublic)
async def me(user: UserRecord = Depends(current_user)) -> UserPublic:
    """Return the current authenticated user."""
    return _public_user(user)
