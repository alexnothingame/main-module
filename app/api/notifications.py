from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.errors import http_error
from app.db.session import get_session
from app.db.models import Notification

router = APIRouter(tags=["notifications"])


@router.get("/notification")
async def notification_get(
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # В сценарии Telegram: бот запрашивает /notification с access токеном пользователя. [file:26]
    res = await session.execute(
        select(Notification.id, Notification.payload, Notification.created_at)
        .where(Notification.user_id == current["user_id"])
        .order_by(Notification.id)
    )
    rows = res.all()
    return [
        {"id": r.id, "payload": r.payload, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.post("/notification_delete")
async def notification_delete(
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # В сценарии Telegram: если уведомления есть, бот просит удалить уведомления пользователя. [file:26]
    await session.execute(
        Notification.__table__.delete().where(Notification.user_id == current["user_id"])
    )
    await session.commit()
    return {"status": "ok"}
