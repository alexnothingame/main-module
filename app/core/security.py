import os
from typing import Any

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.db.session import get_session
from app.db.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="unused")

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = os.environ.get("JWT_ALGO", "HS256")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # 1) Decode/validate access JWT
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        http_error(401, "Unauthorized")

    # 2) Extract identity (нужен user_id или sub)
    user_id = payload.get("user_id") or payload.get("sub")
    if user_id is None:
        http_error(401, "Unauthorized", {"reason": "Missing user_id/sub in access token"})

    # 3) Extract permissions
    permissions = payload.get("permissions")
    if not isinstance(permissions, list):
        permissions = []

    # 4) Check blocked in DB (418)
    res = await session.execute(select(User).where(User.id == int(user_id)))
    user = res.scalar_one_or_none()
    if user is None:
        # Вариант политики: либо 401 (неизвестный пользователь), либо 403.
        http_error(401, "Unauthorized", {"reason": "Unknown user"})

    if user.is_blocked:
        http_error(418, "Blocked")

    return {
        "user_id": user.id,
        "permissions": set(permissions),
    }


def require_permission(perm: str):
    async def _dep(current=Depends(get_current_user)):
        if perm not in current["permissions"]:
            http_error(403, "Forbidden", {"required_permission": perm})
        return current
    return _dep
