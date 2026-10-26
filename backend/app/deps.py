"""FastAPI dependencies: authentication and role based access control."""

from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .constants import ROLE_ADMIN
from .database import USERS, coll
from .security import decode_access_token
from .utils import serialize

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated or session expired",
    headers={"WWW-Authenticate": "Bearer"},
)

_USER_TTL_S = 20.0
_user_cache: dict[str, tuple[float, dict]] = {}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_ERROR

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise CREDENTIALS_ERROR

    user_id = str(payload["sub"])
    cached = _user_cache.get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    document = await coll(USERS).find_one({"user_id": user_id})
    if not document or not document.get("active", True):
        _user_cache.pop(user_id, None)
        raise CREDENTIALS_ERROR

    user = serialize(document) or {}
    user.pop("password_hash", None)
    _user_cache[user_id] = (time.monotonic() + _USER_TTL_S, user)
    return user


async def get_download_user(
    request: Request,
    token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Accept the normal Bearer header or ?token= so a browser can save a file."""
    raw = credentials.credentials if credentials and credentials.credentials else ""
    if not raw and token:
        raw = token
    if not raw:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            raw = header[7:]
    if not raw:
        raise CREDENTIALS_ERROR
    return await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw))


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an Administrator account",
        )
    return user
