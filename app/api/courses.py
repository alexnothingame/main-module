from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import Course, CourseEnrollment

router = APIRouter(tags=["courses"])


def has_perm(current: dict, perm: str) -> bool:
    return perm in current["permissions"]


def is_teacher_of(course: Course, user_id: int) -> bool:
    return course.teacher_id == user_id


@router.get("/courses_list")
async def courses_list(
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: список дисциплин разрешён по умолчанию (“+”). [file:29]
    res = await session.execute(
        select(Course.id, Course.name, Course.description, Course.teacher_id)
        .where(Course.is_deleted == False)  # noqa: E712
        .order_by(Course.id)
    )
    return [
        {"id": r.id, "name": r.name, "description": r.description, "teacher_id": r.teacher_id}
        for r in res.all()
    ]


@router.get("/course_get")
async def course_get(
    course_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: просмотр инфо о дисциплине разрешён по умолчанию (“+”). [file:29]
    res = await session.execute(select(Course).where(Course.id == course_id, Course.is_deleted == False))  # noqa: E712
    course = res.scalar_one_or_none()
    if not course:
        http_error(404, "Not found")

    return {
        "id": course.id,
        "name": course.name,
        "description": course.description,
        "teacher_id": course.teacher_id,
    }


@router.post("/course_create")
async def course_create(
    name: str,
    description: str,
    teacher_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: создать дисциплину требует permission course:add. [file:27]
    if not has_perm(current, "course:add"):
        http_error(403, "Forbidden", {"required_permission": "course:add"})

    course = Course(name=name, description=description, teacher_id=teacher_id)
    session.add(course)
    await session.commit()
    await session.refresh(course)
    return {"id": course.id}


@router.post("/course_update")
async def course_update(
    course_id: int,
    name: str,
    description: str,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: update — по умолчанию только для своей дисциплины, иначе нужен course:info:write. [file:29]
    res = await session.execute(select(Course).where(Course.id == course_id, Course.is_deleted == False))  # noqa: E712
    course = res.scalar_one_or_none()
    if not course:
        http_error(404, "Not found")

    if not is_teacher_of(course, current["user_id"]) and not has_perm(current, "course:info:write"):
        http_error(403, "Forbidden", {"required_permission": "course:info:write"})

    course.name = name
    course.description = description
    await session.commit()
    return {"status": "ok"}


@router.post("/course_delete")
async def course_delete(
    course_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: удалить — по умолчанию для своей дисциплины, иначе нужен course:del. [file:27]
    res = await session.execute(select(Course).where(Course.id == course_id, Course.is_deleted == False))  # noqa: E712
    course = res.scalar_one_or_none()
    if not course:
        http_error(404, "Not found")

    if not is_teacher_of(course, current["user_id"]) and not has_perm(current, "course:del"):
        http_error(403, "Forbidden", {"required_permission": "course:del"})

    course.is_deleted = True
    await session.commit()
    return {"status": "ok"}


@router.get("/course_students")
async def course_students(
    course_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: список студентов — по умолчанию для своей дисциплины, иначе permission course:userList. [file:29]
    res = await session.execute(select(Course).where(Course.id == course_id, Course.is_deleted == False))  # noqa: E712
    course = res.scalar_one_or_none()
    if not course:
        http_error(404, "Not found")

    if not is_teacher_of(course, current["user_id"]) and not has_perm(current, "course:userList"):
        http_error(403, "Forbidden", {"required_permission": "course:userList"})

    res = await session.execute(
        select(CourseEnrollment.user_id).where(CourseEnrollment.course_id == course_id)
    )
    return [r.user_id for r in res.all()]


@router.post("/course_student_add")
async def course_student_add(
    course_id: int,
    user_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: “записать пользователя на дисциплину” — + себе, - другим, либо permission course:user:add. [file:29]
    if user_id != current["user_id"] and not has_perm(current, "course:user:add"):
        http_error(403, "Forbidden", {"required_permission": "course:user:add"})

    session.add(CourseEnrollment(course_id=course_id, user_id=user_id))
    await session.commit()
    return {"status": "ok"}


@router.post("/course_student_del")
async def course_student_del(
    course_id: int,
    user_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # По таблице: “отчислить” — + себя, - других, либо permission course:user:del. [file:27]
    if user_id != current["user_id"] and not has_perm(current, "course:user:del"):
        http_error(403, "Forbidden", {"required_permission": "course:user:del"})

    await session.execute(
        CourseEnrollment.__table__.delete().where(
            CourseEnrollment.course_id == course_id,
            CourseEnrollment.user_id == user_id,
        )
    )
    await session.commit()
    return {"status": "ok"}
