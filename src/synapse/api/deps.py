"""FastAPI dependency injection."""
from __future__ import annotations
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.db.base import get_session
from synapse.db import repositories as repo
from synapse.db.models import User
from synapse.api.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_db(session: AsyncSession = Depends(get_session)) -> AsyncSession:
    yield session


def get_graph(request: Request):
    return request.app.state.graph


def get_alert_queue(request: Request):
    return request.app.state.alerts


# ── Authentication ──────────────────────────────────────────────────────────

async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the Bearer JWT and load the authenticated user."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(creds.credentials)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await repo.get_user(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    return user


def require_role(*allowed_roles: str):
    """Dependency factory — only let the listed roles through."""
    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(allowed_roles)}",
            )
        return user
    return _checker
