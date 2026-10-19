"""SQLAlchemy ORM mappings of the OEMS tables.

The schema itself is owned by database/schema.sql (applied through Alembic);
these classes only map onto it. Constraints, triggers and procedures live in
MySQL so they hold no matter which client writes the data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, text, DateTime, Enum, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

UINT = INTEGER(unsigned=True)


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "student"

    student_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    student_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class FacultyAdmin(Base):
    __tablename__ = "faculty_admin"

    faculty_admin_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    faculty_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(Enum("FACULTY", "ADMIN", name="role"), server_default=text("FACULTY"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class Exam(Base):
    __tablename__ = "exam"

    exam_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(UINT, ForeignKey("faculty_admin.faculty_admin_id"))
    title: Mapped[str] = mapped_column(String(150))
    subject: Mapped[str] = mapped_column(String(100))
    exam_date: Mapped[datetime] = mapped_column(DateTime)
    deadline: Mapped[datetime] = mapped_column(DateTime)
    duration_minutes: Mapped[int] = mapped_column(UINT)
    total_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default=text("0.00"))
    pass_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("40.00"))
    results_released: Mapped[int] = mapped_column(TINYINT(1), server_default=text("0"))
    status: Mapped[str] = mapped_column(
        Enum("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED", name="exam_status"), server_default=text("SCHEDULED"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    creator: Mapped[FacultyAdmin] = relationship(lazy="joined")


class Question(Base):
    __tablename__ = "question"

    question_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(UINT, ForeignKey("faculty_admin.faculty_admin_id"))
    question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(
        Enum("MCQ", "TRUE_FALSE", "SHORT_ANSWER", "LONG_ANSWER", name="question_type"))
    options: Mapped[list | None] = mapped_column(JSON(none_as_null=True), nullable=True)  # SQL NULL, not JSON null
    marks: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ExamQuestion(Base):
    __tablename__ = "exam_question"

    exam_id: Mapped[int] = mapped_column(UINT, ForeignKey("exam.exam_id"), primary_key=True)
    question_id: Mapped[int] = mapped_column(UINT, ForeignKey("question.question_id"), primary_key=True)
    question_order: Mapped[int] = mapped_column(UINT)
    marks_assigned: Mapped[Decimal] = mapped_column(Numeric(6, 2))

    question: Mapped[Question] = relationship(lazy="joined")


class Attempt(Base):
    __tablename__ = "attempt"

    attempt_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(UINT, ForeignKey("student.student_id"))
    exam_id: Mapped[int] = mapped_column(UINT, ForeignKey("exam.exam_id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("IN_PROGRESS", "SUBMITTED", "EVALUATED", name="attempt_status"), server_default=text("IN_PROGRESS"))

    exam: Mapped[Exam] = relationship(lazy="joined")
    student: Mapped[Student] = relationship(lazy="joined")


class Answer(Base):
    __tablename__ = "answer"
    __table_args__ = (
        ForeignKeyConstraint(["attempt_id", "exam_id"], ["attempt.attempt_id", "attempt.exam_id"]),
        ForeignKeyConstraint(["exam_id", "question_id"], ["exam_question.exam_id", "exam_question.question_id"]),
    )

    answer_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(UINT, ForeignKey("attempt.attempt_id"))
    exam_id: Mapped[int] = mapped_column(UINT)
    question_id: Mapped[int] = mapped_column(UINT, ForeignKey("question.question_id"))
    selected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    marks_obtained: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class Result(Base):
    __tablename__ = "result"

    result_id: Mapped[int] = mapped_column(UINT, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(UINT, ForeignKey("attempt.attempt_id"), unique=True)
    marks_obtained: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    result_status: Mapped[str] = mapped_column(Enum("PASS", "FAIL", name="result_status"))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ExamAudit(Base):
    __tablename__ = "exam_audit"

    audit_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(UINT)
    action: Mapped[str] = mapped_column(Enum("INSERT", "UPDATE", "DELETE", name="audit_action"))
    changed_columns: Mapped[str | None] = mapped_column(String(200))
    old_title: Mapped[str | None] = mapped_column(String(150))
    new_title: Mapped[str | None] = mapped_column(String(150))
    old_exam_date: Mapped[datetime | None] = mapped_column(DateTime)
    new_exam_date: Mapped[datetime | None] = mapped_column(DateTime)
    old_duration: Mapped[int | None] = mapped_column(UINT)
    new_duration: Mapped[int | None] = mapped_column(UINT)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    db_user: Mapped[str] = mapped_column(String(288))
    changed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3))


class SqlExecutionLog(Base):
    __tablename__ = "sql_execution_log"

    log_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64))
    user_role: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(UINT, nullable=True)
    example_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str] = mapped_column(String(40))
    execution_mode: Mapped[str] = mapped_column(
        Enum("EXAMPLE", "CLEANUP", "FREEFORM", "EXPLAIN", "PROCEDURE", "REPORT", "RESET", name="exec_mode"))
    target_db: Mapped[str] = mapped_column(String(64))
    statement_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Enum("SUCCESS", "ERROR", "REJECTED", name="exec_status"))
    rows_returned: Mapped[int] = mapped_column(UINT, server_default=text("0"))
    rows_affected: Mapped[int] = mapped_column(BIGINT, server_default=text("0"))
    duration_ms: Mapped[Decimal] = mapped_column(Numeric(10, 3), server_default=text("0"))
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), server_default=text("CURRENT_TIMESTAMP(3)"))
