from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import (
    Attempt, Answer, AttemptQuestion, Test, TestQuestion, QuestionVersion
)

router = APIRouter(tags=["attempts"])


@router.post("/attempt_create")
async def attempt_create(
    test_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # 1) Тест должен существовать, не удалён
    res = await session.execute(select(Test).where(Test.id == test_id, Test.is_deleted == False))  # noqa: E712
    test = res.scalar_one_or_none()
    if not test:
        http_error(404, "Not found")

    # 2) Тест должен быть активным (иначе пройти нельзя) [file:29][file:31]
    if not test.is_active:
        http_error(400, "Bad Request", {"message": "Test is not active"})

    user_id = current["user_id"]

    # 3) Попытка одна на user+test (у вас unique). Если уже есть — вернём её.
    res = await session.execute(select(Attempt).where(Attempt.test_id == test_id, Attempt.user_id == user_id))
    existing = res.scalar_one_or_none()
    if existing:
        return {"id": existing.id}

    # 4) Создаём Attempt
    attempt = Attempt(test_id=test_id, user_id=user_id, status="in_progress")
    session.add(attempt)
    await session.flush()  # получаем attempt.id

    # 5) Берём вопросы теста в порядке position
    res = await session.execute(
        select(TestQuestion.question_id, TestQuestion.position)
        .where(TestQuestion.test_id == test_id)
        .order_by(TestQuestion.position)
    )
    tq_rows = res.all()
    if not tq_rows:
        http_error(400, "Bad Request", {"message": "Test has no questions"})

    # 6) Для каждого вопроса фиксируем последнюю версию на момент старта попытки [file:31]
    for (question_id, position) in tq_rows:
        res = await session.execute(
            select(func.max(QuestionVersion.version)).where(QuestionVersion.question_id == question_id)
        )
        last_ver = res.scalar_one()
        if last_ver is None:
            http_error(400, "Bad Request", {"message": f"Question {question_id} has no versions"})

        aq = AttemptQuestion(
            attempt_id=attempt.id,
            question_id=question_id,
            question_version=int(last_ver),
            position=position,
        )
        session.add(aq)

        # 7) Автоматически создаём ответ с -1 [file:30][file:31]
        ans = Answer(
            attempt_id=attempt.id,
            question_id=question_id,
            question_version=int(last_ver),
            answer_index=-1,
        )
        session.add(ans)

    await session.commit()
    return {"id": attempt.id}


@router.get("/attempt_get")
async def attempt_get(
    attempt_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # ТЗ: попытка хранит список вопросов(с версиями), ответы, статус. [file:31]
    res = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = res.scalar_one_or_none()
    if not attempt:
        http_error(404, "Not found")

    # Доступ: по умолчанию только владелец (тот кто проходит). [file:31]
    if attempt.user_id != current["user_id"]:
        http_error(403, "Forbidden")

    res = await session.execute(
        select(AttemptQuestion.question_id, AttemptQuestion.question_version, AttemptQuestion.position)
        .where(AttemptQuestion.attempt_id == attempt_id)
        .order_by(AttemptQuestion.position)
    )
    questions = [
        {"question_id": r.question_id, "version": r.question_version, "position": r.position}
        for r in res.all()
    ]

    res = await session.execute(
        select(Answer.id, Answer.question_id, Answer.answer_index)
        .where(Answer.attempt_id == attempt_id)
        .order_by(Answer.id)
    )
    answers = [
        {"answer_id": r.id, "question_id": r.question_id, "answer_index": r.answer_index}
        for r in res.all()
    ]

    return {
        "id": attempt.id,
        "test_id": attempt.test_id,
        "user_id": attempt.user_id,
        "status": attempt.status,
        "questions": questions,
        "answers": answers,
    }


@router.post("/attempt_finish")
async def attempt_finish(
    attempt_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = res.scalar_one_or_none()
    if not attempt:
        http_error(404, "Not found")

    if attempt.user_id != current["user_id"]:
        http_error(403, "Forbidden")

    if attempt.status == "finished":
        return {"status": "ok"}  # идемпотентно

    attempt.status = "finished"
    # finished_at можно заполнить на уровне БД default/trigger, но сейчас просто не трогаем.
    await session.commit()
    return {"status": "ok"}
