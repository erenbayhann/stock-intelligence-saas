import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, Depends, HTTPException, status

from app.core.config import Settings, get_settings

ADMIN_COOKIE_NAME = "admin_session"
JWT_ALGORITHM = "HS256"


def verify_admin_password(password: str, settings: Settings) -> bool:
    """Constant-time compare (spec §16/§22) — never logged, never compared
    with plain ==, which leaks timing information about how many leading
    characters matched.
    """
    if not settings.admin_password:
        return False
    return hmac.compare_digest(password, settings.admin_password)


def create_admin_session_token(settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=settings.admin_session_ttl_minutes),
    }
    return jwt.encode(payload, settings.admin_jwt_secret, algorithm=JWT_ALGORITHM)


def _verify_admin_session_token(token: str, settings: Settings) -> bool:
    try:
        jwt.decode(token, settings.admin_jwt_secret, algorithms=[JWT_ALGORITHM])
        return True
    except jwt.PyJWTError:
        return False


def require_admin(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency gating every /admin/* route (spec §16) — stateless,
    verified by JWT expiry + signature only, no server-side session table.
    """
    if not admin_session or not _verify_admin_session_token(admin_session, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
