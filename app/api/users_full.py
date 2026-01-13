from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import (
    User, UserRole, CourseEnrollment, Course, Test, Attempt
)
from app.core import perms

router = APIRouter(tags=["users"])


def has_perm(current: dict, perm: str) -> bool:
    return perm in current["permissions"]


async def get_user_or_404(session: AsyncSession, user_id: int) -> User:
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        http_error(404, "Not found")
    return user


# /users_list уже есть, но можно оставить тут дубль или перенести
@router.get("/users_list")
async def users_list(
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: список пользователей требует user:list:read. [file:28]
    if not has_perm(current, perms.USER_LIST_READ):
        http_error(403, "Forbidden", {"required_permission": perms.USER_LIST_READ})

    res = await session.execute(select(User.id, User.full_name).order_by(User.id))
    return [{"id": r.id, "full_name": r.full_name} for r in res.all()]


@router.get("/user_get")
async def user_get(
    id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: посмотреть ФИО: + о себе, + о другом (то есть всем). [file:28]
    u = await get_user_or_404(session, id)
    return {"id": u.id, "full_name": u.full_name}


@router.post("/user_fullname_set")
async def user_fullname_set(
    id: int,
    fullName: str,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: изменить ФИО: + себе, - другому; permission user:fullName:write. [file:28]
    if id != current["user_id"] and not has_perm(current, perms.USER_FULLNAME_WRITE):
        http_error(403, "Forbidden", {"required_permission": perms.USER_FULLNAME_WRITE})

    u = await get_user_or_404(session, id)
    u.full_name = fullName
    await session.commit()
    return {"status": "ok"}


@router.get("/user_roles_get")
async def user_roles_get(
    id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: смотреть роли — по умолчанию “-” и для своих/чужих, permission user:roles:read. [file:28]
    if not has_perm(current, perms.USER_ROLES_READ):
        http_error(403, "Forbidden", {"required_permission": perms.USER_ROLES_READ})

    await get_user_or_404(session, id)
    res = await session.execute(select(UserRole.role).where(UserRole.user_id == id).order_by(UserRole.role))
    return {"user_id": id, "roles": [r.role for r in res.all()]}


@router.post("/user_roles_set")
async def user_roles_set(
    id: int,
    rolesCsv: str,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: изменить роли — по умолчанию “-”, permission user:roles:write. [file:28]
    if not has_perm(current, "user:roles:write"):
        http_error(403, "Forbidden", {"required_permission": "user:roles:write"})

    await get_user_or_404(session, id)

    roles = [r.strip().lower() for r in rolesCsv.split(",") if r.strip()]
    allowed = {"student", "teacher", "admin"}
    if any(r not in allowed for r in roles):
        http_error(400, "Bad Request", {"message": f"roles must be subset of {sorted(list(allowed))}"})

    # Простая реализация: очищаем и вставляем заново
    await session.execute(UserRole.__table__.delete().where(UserRole.user_id == id))
    for r in roles:
        session.add(UserRole(user_id=id, role=r))

    await session.commit()
    return {"status": "ok"}


@router.get("/user_block_get")
async def user_block_get(
    id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: смотреть блокировку — по умолчанию “-”, permission user:block:read. [file:28]
    if not has_perm(current, perms.USER_BLOCK_READ):
        http_error(403, "Forbidden", {"required_permission": perms.USER_BLOCK_READ})

    u = await get_user_or_404(session, id)
    return {"user_id": id, "is_blocked": u.is_blocked}


@router.post("/user_block_set")
async def user_block_set(
    id: int,
    blocked: bool,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: блокировать/разблокировать — - себя, - другого, permission user:block:write. [file:28]
    if not has_perm(current, perms.USER_BLOCK_WRITE):
        http_error(403, "Forbidden", {"required_permission": perms.USER_BLOCK_WRITE})

    if id == current["user_id"]:
        http_error(403, "Forbidden", {"message": "Cannot block/unblock yourself"})

    u = await get_user_or_404(session, id)
    u.is_blocked = bool(blocked)
    await session.commit()
    return {"status": "ok"}


@router.get("/user_data")
async def user_data(
    id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица Users: “курсы/оценки/тесты” — + о себе, - о другом; permission user:data:read. [file:28]
    if id != current["user_id"] and not has_perm(current, perms.USER_DATA_READ):
        http_error(403, "Forbidden", {"required_permission": perms.USER_DATA_READ})

    await get_user_or_404(session, id)

    # Курсы, на которые записан пользователь
    res = await session.execute(
        select(Course.id, Course.name)
        .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
        .where(CourseEnrollment.user_id == id, Course.is_deleted == False)  # noqa: E712
        .order_by(Course.id)
    )
    courses = [{"id": r.id, "name": r.name} for r in res.all()]

    # Тесты пользователя = тесты, по которым есть попытка (попытка уникальна) [file:31]
    res = await session.execute(
        select(Test.id, Test.name, Attempt.status)
        .join(Attempt, Attempt.test_id == Test.id)
        .where(Attempt.user_id == id, Test.is_deleted == False)  # noqa: E712
        .order_by(Test.id)
    )
    tests = [{"id": r.id, "name": r.name, "attempt_status": r.status} for r in res.all()]

    # Оценки пока не считаем здесь (можно позже подтянуть формулу из test_user_grade)
    return {"user_id": id, "courses": courses, "tests": tests}
