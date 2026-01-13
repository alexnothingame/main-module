from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import (
    Test, Course, Attempt, Answer, QuestionVersion
)

router = APIRouter(tags=["teacher-tests"])


def has_perm(current: dict, perm: str) -> bool:
    return perm in current["permissions"]


async def get_test_course(session: AsyncSession, test_id: int):
    res = await session.execute(
        select(Test, Course)
        .join(Course, Course.id == Test.course_id)
        .where(Test.id == test_id, Test.is_deleted == False, Course.is_deleted == False)  # noqa: E712
    )
    row = res.first()
    if not row:
        http_error(404, "Not found")
    return row[0], row[1]


def ensure_teacher_or_perm(course: Course, current: dict, perm: str):
    # По умолчанию преподаватель своей дисциплины имеет доступ. [file:32]
    if course.teacher_id == current["user_id"]:
        return
    if not has_perm(current, perm):
        http_error(403, "Forbidden", {"required_permission": perm})


@router.get("/test_attempts")
async def test_attempts(
    test_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: "Посмотреть список пользователей прошедших тест" -> test:answer:read. [file:32]
    test, course = await get_test_course(session, test_id)
    ensure_teacher_or_perm(course, current, "test:answer:read")

    res = await session.execute(
        select(Attempt.id, Attempt.user_id, Attempt.status)
        .where(Attempt.test_id == test.id)
        .order_by(Attempt.id)
    )
    return [{"attempt_id": r.id, "user_id": r.user_id, "status": r.status} for r in res.all()]


@router.get("/test_user_grade")
async def test_user_grade(
    test_id: int,
    user_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: "Посмотреть оценку пользователя" -> test:answer:read (препод по умолчанию тоже). [file:32]
    test, course = await get_test_course(session, test_id)
    ensure_teacher_or_perm(course, current, "test:answer:read")

    # Находим попытку пользователя по этому тесту (она уникальна). [file:31]
    res = await session.execute(
        select(Attempt).where(Attempt.test_id == test.id, Attempt.user_id == user_id)
    )
    attempt = res.scalar_one_or_none()
    if not attempt:
        http_error(404, "Not found", {"message": "User has no attempt for this test"})

    # total = количество ответов в попытке
    res = await session.execute(
        select(func.count(Answer.id)).where(Answer.attempt_id == attempt.id)
    )
    total = int(res.scalar_one() or 0)

    if total == 0:
        return {"test_id": test.id, "user_id": user_id, "attempt_id": attempt.id, "correct": 0, "total": 0, "grade_percent": 0}

    # correct = count(answer_index == correct_index) по версии вопроса
    res = await session.execute(
        select(func.count(Answer.id))
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == Answer.question_id)
            & (QuestionVersion.version == Answer.question_version),
        )
        .where(
            Answer.attempt_id == attempt.id,
            Answer.answer_index != -1,
            Answer.answer_index == QuestionVersion.correct_index,
        )
    )
    correct = int(res.scalar_one() or 0)

    grade_percent = int(round(100 * correct / total))

    return {
        "test_id": test.id,
        "user_id": user_id,
        "attempt_id": attempt.id,
        "correct": correct,
        "total": total,
        "grade_percent": grade_percent,
    }


@router.get("/test_user_answers")
async def test_user_answers(
    test_id: int,
    user_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: "Посмотреть ответы пользователя" -> test:answer:read. [file:32]
    # Там сказано: вернуть массив, где "Ответ" = текст вопроса и текст ответа. [file:32]
    test, course = await get_test_course(session, test_id)
    ensure_teacher_or_perm(course, current, "test:answer:read")

    res = await session.execute(
        select(Attempt).where(Attempt.test_id == test.id, Attempt.user_id == user_id)
    )
    attempt = res.scalar_one_or_none()
    if not attempt:
        http_error(404, "Not found", {"message": "User has no attempt for this test"})

    # Достаём ответы и тексты через join на QuestionVersion
    res = await session.execute(
        select(
            Answer.question_id,
            Answer.question_version,
            Answer.answer_index,
            QuestionVersion.title,
            QuestionVersion.body,
            QuestionVersion.options,
            QuestionVersion.correct_index,
        )
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == Answer.question_id)
            & (QuestionVersion.version == Answer.question_version),
        )
        .where(Answer.attempt_id == attempt.id)
        .order_by(Answer.id)
    )

    out = []
    for r in res.all():
        chosen_text = None
        if r.answer_index is not None and r.answer_index >= 0 and r.answer_index < len(r.options):
            chosen_text = r.options[r.answer_index]

        out.append(
            {
                "question_id": r.question_id,
                "version": r.question_version,
                "question_title": r.title,
                "question_text": r.body,
                "answer_index": r.answer_index,
                "answer_text": chosen_text,  # None если -1
                "correct_index": r.correct_index,
            }
        )

    return {
        "test_id": test.id,
        "user_id": user_id,
        "attempt_id": attempt.id,
        "answers": out,
    }
