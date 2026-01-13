from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import Course, CourseEnrollment, Test

router = APIRouter(tags=["course-tests"])


def has_perm(current: dict, perm: str) -> bool:
    return perm in current["permissions"]


async def get_course_or_404(session: AsyncSession, course_id: int) -> Course:
    res = await session.execute(
        select(Course).where(Course.id == course_id, Course.is_deleted == False)  # noqa: E712
    )
    course = res.scalar_one_or_none()
    if not course:
        http_error(404, "Not found")
    return course


async def is_enrolled(session: AsyncSession, course_id: int, user_id: int) -> bool:
    res = await session.execute(
        select(CourseEnrollment).where(
            CourseEnrollment.course_id == course_id,
            CourseEnrollment.user_id == user_id,
        )
    )
    return res.scalar_one_or_none() is not None


def is_teacher(course: Course, user_id: int) -> bool:
    return course.teacher_id == user_id


@router.get("/course_tests")
async def course_tests(
    course_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: список тестов дисциплины
    # + для своей дисциплины
    # + для чужих, если записан
    # - для чужих (если не записан)
    # и permission: course:testList [file:29]
    course = await get_course_or_404(session, course_id)

    allowed = is_teacher(course, current["user_id"])
    if not allowed:
        allowed = await is_enrolled(session, course_id, current["user_id"])
    if not allowed and not has_perm(current, "course:testList"):
        http_error(403, "Forbidden", {"required_permission": "course:testList"})

    res = await session.execute(
        select(Test.id, Test.name)
        .where(Test.course_id == course_id, Test.is_deleted == False)  # noqa: E712
        .order_by(Test.id)
    )
    return [{"id": r.id, "name": r.name} for r in res.all()]


@router.get("/course_test_get")
async def course_test_get(
    course_id: int,
    test_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: посмотреть информацию о тесте (активен/нет)
    # те же правила доступа, что и список тестов, permission: course:test:read [file:29]
    course = await get_course_or_404(session, course_id)

    allowed = is_teacher(course, current["user_id"])
    if not allowed:
        allowed = await is_enrolled(session, course_id, current["user_id"])
    if not allowed and not has_perm(current, "course:test:read"):
        http_error(403, "Forbidden", {"required_permission": "course:test:read"})

    res = await session.execute(
        select(Test).where(
            Test.id == test_id,
            Test.course_id == course_id,
            Test.is_deleted == False,  # noqa: E712
        )
    )
    test = res.scalar_one_or_none()
    if not test:
        http_error(404, "Not found")

    return {"id": test.id, "course_id": test.course_id, "name": test.name, "is_active": test.is_active}


@router.post("/course_test_add")
async def course_test_add(
    course_id: int,
    title: str,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: добавить тест в дисциплину
    # + для своей дисциплины, - для чужих, permission: course:test:add [file:29]
    course = await get_course_or_404(session, course_id)

    if not is_teacher(course, current["user_id"]) and not has_perm(current, "course:test:add"):
        http_error(403, "Forbidden", {"required_permission": "course:test:add"})

    test = Test(course_id=course_id, name=title, author_id=current["user_id"], is_active=False, is_deleted=False)
    session.add(test)
    await session.commit()
    await session.refresh(test)
    return {"id": test.id}


@router.post("/course_test_del")
async def course_test_del(
    course_id: int,
    test_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: удалить тест (soft delete)
    # + для своей дисциплины, - для чужих, permission: course:test:del [file:29]
    course = await get_course_or_404(session, course_id)

    if not is_teacher(course, current["user_id"]) and not has_perm(current, "course:test:del"):
        http_error(403, "Forbidden", {"required_permission": "course:test:del"})

    res = await session.execute(
        select(Test).where(
            Test.id == test_id,
            Test.course_id == course_id,
            Test.is_deleted == False,  # noqa: E712
        )
    )
    test = res.scalar_one_or_none()
    if not test:
        http_error(404, "Not found")

    test.is_deleted = True
    await session.commit()
    return {"status": "ok"}


@router.post("/course_test_active")
async def course_test_active(
    course_id: int,
    test_id: int,
    active: bool,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: активировать/деактивировать
    # + для своей дисциплины, - для чужих, permission: course:test:write [file:29]
    course = await get_course_or_404(session, course_id)

    if not is_teacher(course, current["user_id"]) and not has_perm(current, "course:test:write"):
        http_error(403, "Forbidden", {"required_permission": "course:test:write"})

    res = await session.execute(
        select(Test).where(
            Test.id == test_id,
            Test.course_id == course_id,
            Test.is_deleted == False,  # noqa: E712
        )
    )
    test = res.scalar_one_or_none()
    if not test:
        http_error(404, "Not found")

    test.is_active = active
    await session.commit()
    return {"status": "ok"}
