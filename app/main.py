from fastapi import FastAPI
from app.api.health import router as health_router
from app.api.users import router as users_router
from app.api.courses import router as courses_router
from app.api.tests_in_course import router as course_tests_router
from app.api.questions import router as questions_router
from app.api.test_questions import router as test_questions_router
from app.api.attempts import router as attempts_router
from app.api.answers import router as answers_router
from app.api.teacher_tests import router as teacher_tests_router
from app.api.users_full import router as users_full_router
from app.api.notifications import router as notifications_router


app = FastAPI(title="Main Module (Testing Logic)")

app.include_router(health_router)
app.include_router(users_router)
app.include_router(courses_router)
app.include_router(course_tests_router)
app.include_router(questions_router)
app.include_router(test_questions_router)
app.include_router(attempts_router)
app.include_router(answers_router)
app.include_router(teacher_tests_router)
app.include_router(users_full_router)
app.include_router(notifications_router)