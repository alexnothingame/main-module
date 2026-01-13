from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import Attempt, Answer, Test, Course

router = APIRouter(tags=["answers"])


async def get_attempt_or_404(session: AsyncSession, attempt_id: int) -> Attempt:
    res = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = res.scalar_one_or_none()
    if not attempt:
        http_error(404, "Not found")
    return attempt


@router.get("/answers_get")
async def answers_get(
    attempt_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица "Ответы": свои ответы или преподаватель курса. [file:30]
    attempt = await get_attempt_or_404(session, attempt_id)

    if attempt.user_id != current["user_id"]:
        res = await session.execute(
            select(Course.teacher_id)
            .join(Test, Test.course_id == Course.id)
            .where(
                Test.id == attempt.test_id,
                Test.is_deleted == False,   # noqa: E712
                Course.is_deleted == False, # noqa: E712
            )
        )
        teacher_id = res.scalar_one_or_none()
        if teacher_id != current["user_id"]:
            http_error(403, "Forbidden")

    res = await session.execute(
        select(Answer.id, Answer.question_id, Answer.answer_index)
        .where(Answer.attempt_id == attempt_id)
        .order_by(Answer.id)
    )
    return [{"id": r.id, "question_id": r.question_id, "answer_index": r.answer_index} for r in res.all()]


@router.post("/answer_update")
async def answer_update(
    answer_id: int,
    index: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица "Ответы": менять можно только пока попытка in_progress. [file:30]
    if index < 0:
        http_error(400, "Bad Request", {"message": "index must be >= 0 (use answer_delete to reset to -1)"})

    res = await session.execute(select(Answer).where(Answer.id == answer_id))
    ans = res.scalar_one_or_none()
    if not ans:
        http_error(404, "Not found")

    attempt = await get_attempt_or_404(session, ans.attempt_id)
    if attempt.user_id != current["user_id"]:
        http_error(403, "Forbidden")

    if attempt.status != "in_progress":
        http_error(400, "Bad Request", {"message": "Attempt already finished"})

    ans.answer_index = index
    await session.commit()
    return {"status": "ok"}


@router.post("/answer_delete")
async def answer_delete(
    answer_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица "Ответы": delete = поставить -1, только пока попытка in_progress. [file:30]
    res = await session.execute(select(Answer).where(Answer.id == answer_id))
    ans = res.scalar_one_or_none()
    if not ans:
        http_error(404, "Not found")

    attempt = await get_attempt_or_404(session, ans.attempt_id)
    if attempt.user_id != current["user_id"]:
        http_error(403, "Forbidden")

    if attempt.status != "in_progress":
        http_error(400, "Bad Request", {"message": "Attempt already finished"})

    ans.answer_index = -1
    await session.commit()
    return {"status": "ok"}
