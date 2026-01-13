from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import Test, TestQuestion, Course, Question, Attempt

router = APIRouter(tags=["test-questions"])


def has_perm(current: dict, perm: str) -> bool:
    return perm in current["permissions"]


async def get_test_or_404(session: AsyncSession, test_id: int) -> Test:
    res = await session.execute(select(Test).where(Test.id == test_id, Test.is_deleted == False))  # noqa: E712
    test = res.scalar_one_or_none()
    if not test:
        http_error(404, "Not found")
    return test


async def get_course_or_404(session: AsyncSession, course_id: int) -> Course:
    res = await session.execute(select(Course).where(Course.id == course_id, Course.is_deleted == False))  # noqa: E712
    course = res.scalar_one_or_none()
    if not course:
        http_error(404, "Not found")
    return course


async def ensure_can_edit_test(session: AsyncSession, current: dict, test: Test):
    # По таблице "Тесты": изменения доступны по умолчанию для преподавателя дисциплины, иначе по permission. [file:32]
    course = await get_course_or_404(session, test.course_id)

    # Если тест уже имеет попытки — менять состав/порядок нельзя. [file:32]
    res = await session.execute(select(func.count(Attempt.id)).where(Attempt.test_id == test.id))
    attempts_cnt = int(res.scalar_one() or 0)
    if attempts_cnt > 0:
        http_error(400, "Bad Request", {"message": "Test has attempts, modification forbidden"})

    if course.teacher_id == current["user_id"]:
        return

    # Права из таблицы "Тесты" (они у вас в скрине как test:quest:add/del/update). [file:32]
    http_error(403, "Forbidden", {"message": "Not allowed by default; need permission"})


def parse_csv_ids(csv: str) -> list[int]:
    try:
        parts = [p.strip() for p in csv.split(",") if p.strip()]
        return [int(p) for p in parts]
    except Exception:
        http_error(400, "Bad Request", {"message": "Invalid CSV of ids"})


@router.post("/test_question_add")
async def test_question_add(
    test_id: int,
    question_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: добавить вопрос в тест — test:quest:add (или по умолчанию преподавателю дисциплины). [file:32]
    test = await get_test_or_404(session, test_id)

    # Проверка прав по умолчанию + запрет, если были попытки. [file:32]
    await ensure_can_edit_test(session, current, test)

    # Если не учитель по умолчанию, то нужен permission:
    course = await get_course_or_404(session, test.course_id)
    if course.teacher_id != current["user_id"] and not has_perm(current, "test:quest:add"):
        http_error(403, "Forbidden", {"required_permission": "test:quest:add"})

    # Вопрос должен существовать и быть не удалён. [file:30][file:32]
    res = await session.execute(select(Question).where(Question.id == question_id, Question.is_deleted == False))  # noqa: E712
    q = res.scalar_one_or_none()
    if not q:
        http_error(404, "Not found", {"message": "Question not found"})

    # position = max(position)+1
    res = await session.execute(
        select(func.max(TestQuestion.position)).where(TestQuestion.test_id == test_id)
    )
    max_pos = res.scalar_one()
    next_pos = int(max_pos) + 1 if max_pos is not None else 0

    session.add(TestQuestion(test_id=test_id, question_id=question_id, position=next_pos))

    try:
        await session.commit()
    except Exception:
        # Чаще всего это UniqueViolation (question уже есть в тесте, или позиция занята) => 400. [web:190][web:185]
        await session.rollback()
        http_error(400, "Bad Request", {"message": "Question already in test or position conflict"})

    return {"status": "ok", "position": next_pos}


@router.post("/test_question_del")
async def test_question_del(
    test_id: int,
    question_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: удалить вопрос из теста — test:quest:del + запрет если есть попытки. [file:32]
    test = await get_test_or_404(session, test_id)
    await ensure_can_edit_test(session, current, test)

    course = await get_course_or_404(session, test.course_id)
    if course.teacher_id != current["user_id"] and not has_perm(current, "test:quest:del"):
        http_error(403, "Forbidden", {"required_permission": "test:quest:del"})

    res = await session.execute(
        select(TestQuestion).where(
            TestQuestion.test_id == test_id,
            TestQuestion.question_id == question_id,
        )
    )
    tq = res.scalar_one_or_none()
    if not tq:
        http_error(404, "Not found")

    await session.delete(tq)
    await session.commit()
    return {"status": "ok"}


@router.post("/test_question_order")
async def test_question_order(
    test_id: int,
    questionIdsCsv: str,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: изменить порядок — test:quest:update + запрет если есть попытки. [file:32]
    test = await get_test_or_404(session, test_id)
    await ensure_can_edit_test(session, current, test)

    course = await get_course_or_404(session, test.course_id)
    if course.teacher_id != current["user_id"] and not has_perm(current, "test:quest:update"):
        http_error(403, "Forbidden", {"required_permission": "test:quest:update"})

    new_order = parse_csv_ids(questionIdsCsv)

    # Проверим, что список совпадает с текущим набором вопросов в тесте (иначе можно “потерять” вопросы).
    res = await session.execute(select(TestQuestion.question_id).where(TestQuestion.test_id == test_id))
    current_ids = [r.question_id for r in res.all()]

    if sorted(current_ids) != sorted(new_order):
        http_error(400, "Bad Request", {"message": "Order list must contain exactly the same question ids as in test"})

    # Обновляем позиции: 0..n-1
    # (простым циклом; позже можно оптимизировать батчем)
    for pos, qid in enumerate(new_order):
        await session.execute(
            TestQuestion.__table__.update()
            .where(TestQuestion.test_id == test_id, TestQuestion.question_id == qid)
            .values(position=pos)
        )

    await session.commit()
    return {"status": "ok"}
