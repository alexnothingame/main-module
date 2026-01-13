from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_permission
from app.db.session import get_session
from app.db.models import User

router = APIRouter(prefix="", tags=["users"])

@router.get("/users_list")
async def users_list(
    _=Depends(require_permission("user:list:read")),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(User.id, User.full_name).order_by(User.id))
    rows = res.all()
    return [{"id": r.id, "full_name": r.full_name} for r in rows]
