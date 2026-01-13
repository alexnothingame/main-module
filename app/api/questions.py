from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.errors import http_error
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.models import Question, QuestionVersion
from app.db.models import Attempt, AttemptQuestion
from app.core import perms

router = APIRouter(tags=["questions"])


def has_perm(current: dict, perm: str) -> bool:
    return perm in current["permissions"]


@router.get("/questions_list")
async def questions_list(
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: list — + свои, - чужие, либо quest:list:read [file:30]
    # Для списка показываем только последнюю версию каждого вопроса.
    # Это делаем через подзапрос max(version).
    latest = (
        select(
            QuestionVersion.question_id.label("qid"),
            func.max(QuestionVersion.version).label("vmax"),
        )
        .group_by(QuestionVersion.question_id)
        .subquery()
    )

    stmt = (
        select(
            Question.id,
            Question.author_id,
            QuestionVersion.version,
            QuestionVersion.title,
        )
        .join(latest, latest.c.qid == Question.id)
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == latest.c.qid)
            & (QuestionVersion.version == latest.c.vmax),
        )
        .where(Question.is_deleted == False)  # noqa: E712
        .order_by(Question.id)
    )

    # Ограничение “свои/чужие”
    if not has_perm(current, perms.QUEST_LIST_READ):
        stmt = stmt.where(Question.author_id == current["user_id"])

    res = await session.execute(stmt)
    rows = res.all()
    return [
        {
            "id": r.id,
            "version": r.version,
            "author_id": r.author_id,
            "title": r.title,
        }
        for r in rows
    ]


@router.get("/question_get")
async def question_get(
    id: int,
    version: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(Question).where(Question.id == id, Question.is_deleted == False)  # noqa: E712
    )
    q = res.scalar_one_or_none()
    if not q:
        http_error(404, "Not found")

    # Проверка доступа: автор или permission, либо студент с попыткой, содержащей эту версию. [file:30][file:31]
    if q.author_id != current["user_id"] and not has_perm(current, "quest:read"):
        res = await session.execute(
            select(func.count(Attempt.id))
            .join(AttemptQuestion, AttemptQuestion.attempt_id == Attempt.id)
            .where(
                Attempt.user_id == current["user_id"],
                AttemptQuestion.question_id == id,
                AttemptQuestion.question_version == version,
            )
        )
        cnt = int(res.scalar_one() or 0)
        if cnt == 0:
            http_error(403, "Forbidden", {"required_permission": "quest:read"})

    res = await session.execute(
        select(QuestionVersion).where(
            QuestionVersion.question_id == id,
            QuestionVersion.version == version,
        )
    )
    v = res.scalar_one_or_none()
    if not v:
        http_error(404, "Not found")

    return {
        "id": id,
        "version": version,
        "title": v.title,
        "text": v.body,
        "options": v.options,
        "correctIndex": v.correct_index,
        "author_id": q.author_id,
    }


@router.post("/question_create")
async def question_create(
    title: str,
    text: str,
    optionsCsv: str,
    correctIndex: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: create — permission quest:create (по умолчанию “-”). [file:30]
    if not has_perm(current, perms.QUEST_CREATE):
        http_error(403, "Forbidden", {"required_permission": perms.QUEST_CREATE})

    options = [o.strip() for o in optionsCsv.split(",") if o.strip()]
    if len(options) < 2:
        http_error(400, "Bad Request", {"message": "Need at least 2 options"})
    if correctIndex < 0 or correctIndex >= len(options):
        http_error(400, "Bad Request", {"message": "correctIndex out of range"})

    q = Question(author_id=current["user_id"], is_deleted=False)
    session.add(q)
    await session.flush()  # чтобы получить q.id без commit (нормальная практика) [web:167]

    v = QuestionVersion(
        question_id=q.id,
        version=1,
        title=title,
        body=text,
        options=options,
        correct_index=correctIndex,
    )
    session.add(v)
    await session.commit()
    return {"id": q.id, "version": 1}


@router.post("/question_update")
async def question_update(
    id: int,
    title: str,
    text: str,
    optionsCsv: str,
    correctIndex: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: update (создаёт новую версию) — + свои, - чужие, permission quest:update. [file:30]
    res = await session.execute(select(Question).where(Question.id == id, Question.is_deleted == False))  # noqa: E712
    q = res.scalar_one_or_none()
    if not q:
        http_error(404, "Not found")

    if q.author_id != current["user_id"] and not has_perm(current, perms.QUEST_UPDATE):
        http_error(403, "Forbidden", {"required_permission": perms.QUEST_UPDATE})

    options = [o.strip() for o in optionsCsv.split(",") if o.strip()]
    if len(options) < 2:
        http_error(400, "Bad Request", {"message": "Need at least 2 options"})
    if correctIndex < 0 or correctIndex >= len(options):
        http_error(400, "Bad Request", {"message": "correctIndex out of range"})

    # next_version = max(version)+1
    res = await session.execute(
        select(func.max(QuestionVersion.version)).where(QuestionVersion.question_id == id)
    )
    current_max = res.scalar_one() or 0
    next_version = int(current_max) + 1

    v = QuestionVersion(
        question_id=id,
        version=next_version,
        title=title,
        body=text,
        options=options,
        correct_index=correctIndex,
    )
    session.add(v)
    await session.commit()
    return {"id": id, "version": next_version}


@router.post("/question_delete")
async def question_delete(
    id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Таблица: delete — + свой, - чужой, и если вопрос используется в тестах (даже удалённых) — нельзя. [file:30]
    # Пока реализуем soft delete и проверку “свой/permission”; запрет “используется в тестах” сделаем на следующем этапе (когда добавим test_questions API). [file:30][file:32]
    res = await session.execute(select(Question).where(Question.id == id, Question.is_deleted == False))  # noqa: E712
    q = res.scalar_one_or_none()
    if not q:
        http_error(404, "Not found")

    if q.author_id != current["user_id"] and not has_perm(current, perms.QUEST_DEL):
        http_error(403, "Forbidden", {"required_permission": perms.QUEST_DEL})

    q.is_deleted = True
    await session.commit()
    return {"status": "ok"}
