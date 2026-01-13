from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    Integer, BigInteger, String, Text, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    full_name = Column(Text, nullable=False)
    email = Column(Text, unique=True, nullable=True)
    is_blocked = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String, primary_key=True)
    __table_args__ = (
        CheckConstraint("role in ('student','teacher','admin')", name="chk_user_roles_role"),
    )


class Course(Base):
    __tablename__ = "courses"

    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=False, server_default="")
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    is_deleted = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"

    course_id = Column(BigInteger, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Question(Base):
    __tablename__ = "questions"

    id = Column(BigInteger, primary_key=True)
    author_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    is_deleted = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QuestionVersion(Base):
    __tablename__ = "question_versions"

    question_id = Column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    version = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    options = Column(ARRAY(Text), nullable=False)
    correct_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("version >= 1", name="chk_qv_version"),
        CheckConstraint("correct_index >= 0", name="chk_qv_correct_ge0"),
        CheckConstraint("array_length(options,1) >= 2", name="chk_qv_opts_len"),
        CheckConstraint("correct_index < array_length(options,1)", name="chk_qv_correct_lt_len"),
    )


class Test(Base):
    __tablename__ = "tests"

    id = Column(BigInteger, primary_key=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False)
    name = Column(Text, nullable=False)
    author_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="false")
    is_deleted = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TestQuestion(Base):
    __tablename__ = "test_questions"

    test_id = Column(BigInteger, ForeignKey("tests.id", ondelete="CASCADE"), primary_key=True)
    question_id = Column(BigInteger, ForeignKey("questions.id"), primary_key=True)
    position = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("test_id", "position", name="uq_test_questions_position"),
        CheckConstraint("position >= 0", name="chk_tq_pos"),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(BigInteger, primary_key=True)
    test_id = Column(BigInteger, ForeignKey("tests.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("test_id", "user_id", name="uq_attempts_test_user"),
        CheckConstraint("status in ('in_progress','finished')", name="chk_attempts_status"),
    )

from sqlalchemy import ForeignKeyConstraint

class AttemptQuestion(Base):
    __tablename__ = "attempt_questions"

    attempt_id = Column(BigInteger, ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True)
    question_id = Column(BigInteger, primary_key=True)
    question_version = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("attempt_id", "position", name="uq_attempt_questions_position"),
        CheckConstraint("position >= 0", name="chk_aq_pos"),
        ForeignKeyConstraint(
            ["question_id", "question_version"],
            ["question_versions.question_id", "question_versions.version"],
            name="fk_aq_question_version",
        ),
    )


class Answer(Base):
    __tablename__ = "answers"

    id = Column(BigInteger, primary_key=True)
    attempt_id = Column(BigInteger, ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(BigInteger, nullable=False)
    question_version = Column(Integer, nullable=False)
    answer_index = Column(Integer, nullable=False, server_default="-1")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_answers_attempt_question"),
        CheckConstraint("answer_index >= -1", name="chk_answers_idx"),
        ForeignKeyConstraint(
            ["question_id", "question_version"],
            ["question_versions.question_id", "question_versions.version"],
            name="fk_answers_question_version",
        ),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

