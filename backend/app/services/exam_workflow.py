"""Examination workflow: start an attempt, save answers, submit, grade, finalize.

Integrity rules are enforced twice on purpose: here (clear error messages) and
in MySQL (constraints, triggers, sp_finalize_attempt) so the data stays
consistent even if another client bypasses this service.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.errors import ApiError
from app.db.models import Answer, Attempt, Exam, ExamQuestion, Question, Result

GRACE_SECONDS = 30            # network latency allowance when saving the last answers
AUTO_GRADED = ("MCQ", "TRUE_FALSE", "SHORT_ANSWER")


def db_now(session: Session) -> datetime:
    """Time according to MySQL — every exam-window decision uses the database clock."""
    return session.scalar(text("SELECT NOW()"))


def normalize(value: str | None) -> str:
    return " ".join((value or "").split()).lower()


def attempt_end_time(attempt: Attempt, exam: Exam) -> datetime:
    return min(attempt.started_at + timedelta(minutes=exam.duration_minutes), exam.deadline)


def question_count(session: Session, exam_id: int) -> int:
    return session.scalar(select(func.count()).select_from(ExamQuestion).where(ExamQuestion.exam_id == exam_id))


def availability(exam: Exam, now: datetime, n_questions: int) -> tuple[bool, str]:
    if exam.status == "CANCELLED":
        return False, "This exam was cancelled."
    if exam.status != "ACTIVE":
        return False, f"This exam is {exam.status.lower()}."
    if now < exam.exam_date:
        return False, "The exam window has not opened yet."
    if now > exam.deadline:
        return False, "The exam window has closed."
    if n_questions == 0:
        return False, "No questions have been assigned yet."
    return True, "Open"


def _load_attempt(session: Session, attempt_id: int, *, lock: bool = False) -> Attempt:
    query = select(Attempt).where(Attempt.attempt_id == attempt_id)
    if lock:
        # row lock: concurrent save/submit/grade requests on the same attempt serialize here
        query = query.with_for_update(of=Attempt)
    attempt = session.scalar(query)
    if attempt is None:
        raise ApiError(404, "not_found", f"Attempt {attempt_id} does not exist.")
    return attempt


def _check_owner(attempt: Attempt, user: CurrentUser) -> None:
    if user.is_student and attempt.student_id != user.id:
        raise ApiError(403, "forbidden", "This attempt belongs to another student.")


def _exam_questions(session: Session, exam_id: int) -> list[ExamQuestion]:
    return list(session.scalars(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
                                .order_by(ExamQuestion.question_order)))


# --------------------------------------------------------------------------- start
def start_attempt(session: Session, user: CurrentUser, exam_id: int) -> tuple[Attempt, bool]:
    """Returns (attempt, created). Re-opening an IN_PROGRESS attempt resumes it."""
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ApiError(404, "not_found", f"Exam {exam_id} does not exist.")

    existing = session.scalar(select(Attempt).where(Attempt.student_id == user.id, Attempt.exam_id == exam_id))
    if existing is not None:
        if existing.status != "IN_PROGRESS":
            raise ApiError(409, "already_submitted", "You have already submitted this exam.")
        return existing, False

    now = db_now(session)
    ok, reason = availability(exam, now, question_count(session, exam_id))
    if not ok:
        raise ApiError(409, "exam_not_open", reason)

    attempt = Attempt(student_id=user.id, exam_id=exam_id, started_at=now, status="IN_PROGRESS")
    session.add(attempt)
    try:
        session.commit()
    except IntegrityError:
        # two "start" clicks raced: UNIQUE(student_id, exam_id) let only one insert win
        session.rollback()
        existing = session.scalar(select(Attempt).where(Attempt.student_id == user.id, Attempt.exam_id == exam_id))
        if existing is None:
            raise
        return existing, False
    return attempt, True


# --------------------------------------------------------------------------- read
def attempt_detail(session: Session, user: CurrentUser, attempt_id: int) -> dict:
    attempt = _load_attempt(session, attempt_id)
    _check_owner(attempt, user)
    exam = attempt.exam
    now = db_now(session)
    end = attempt_end_time(attempt, exam)
    answers = {a.question_id: a for a in session.scalars(select(Answer).where(Answer.attempt_id == attempt_id))}
    result = session.scalar(select(Result).where(Result.attempt_id == attempt_id))

    reveal = user.is_staff or (bool(exam.results_released) and attempt.status == "EVALUATED")
    questions = []
    for eq in _exam_questions(session, exam.exam_id):
        q = eq.question
        answer = answers.get(q.question_id)
        item = {"question_id": q.question_id, "question_order": eq.question_order,
                "question_text": q.question_text, "question_type": q.question_type,
                "options": q.options, "marks": eq.marks_assigned,
                "selected_answer": answer.selected_answer if answer else None}
        if reveal:
            item["correct_answer"] = q.correct_answer
            item["marks_obtained"] = answer.marks_obtained if answer else None
        questions.append(item)

    data = {
        "attempt_id": attempt.attempt_id, "status": attempt.status,
        "student": {"student_id": attempt.student.student_id, "student_name": attempt.student.student_name},
        "exam": {"exam_id": exam.exam_id, "title": exam.title, "subject": exam.subject,
                 "duration_minutes": exam.duration_minutes, "total_marks": exam.total_marks,
                 "deadline": exam.deadline, "results_released": bool(exam.results_released)},
        "started_at": attempt.started_at, "submitted_at": attempt.submitted_at,
        "ends_at": end, "server_now": now,
        "seconds_remaining": max(0, int((end - now).total_seconds())) if attempt.status == "IN_PROGRESS" else 0,
        "answers_revealed": reveal,
        "questions": questions,
        "result": None,
    }
    if result is not None and (user.is_staff or exam.results_released):
        data["result"] = _result_dict(result, exam)
    return data


def _result_dict(result: Result, exam: Exam) -> dict:
    return {"result_id": result.result_id, "marks_obtained": result.marks_obtained,
            "total_marks": exam.total_marks, "percentage": result.percentage,
            "result_status": result.result_status, "pass_percentage": exam.pass_percentage,
            "evaluated_at": result.evaluated_at}


def get_result(session: Session, user: CurrentUser, attempt_id: int) -> dict:
    attempt = _load_attempt(session, attempt_id)
    _check_owner(attempt, user)
    if user.is_student and not attempt.exam.results_released:
        raise ApiError(403, "results_not_released", "Results for this exam have not been released yet.")
    result = session.scalar(select(Result).where(Result.attempt_id == attempt_id))
    if result is None:
        status = "waiting for manual grading" if attempt.status == "SUBMITTED" else "not submitted yet"
        raise ApiError(404, "result_not_ready", f"No result yet: the attempt is {status}.")
    return {"attempt_id": attempt_id, "exam_title": attempt.exam.title,
            "student_name": attempt.student.student_name, **_result_dict(result, attempt.exam)}


# --------------------------------------------------------------------------- save
def save_answers(session: Session, user: CurrentUser, attempt_id: int, answers: list) -> dict:
    with session.begin():
        attempt = _load_attempt(session, attempt_id, lock=True)
        _check_owner(attempt, user)
        if not user.is_student:
            raise ApiError(403, "forbidden", "Only the student can answer an attempt.")
        if attempt.status != "IN_PROGRESS":
            raise ApiError(409, "already_submitted", "This attempt has been submitted; answers are locked.")
        now = db_now(session)
        if now > attempt_end_time(attempt, attempt.exam) + timedelta(seconds=GRACE_SECONDS):
            raise ApiError(409, "time_over", "Time is over for this attempt. Submit it to finish.")

        assigned = {eq.question_id: eq.question for eq in _exam_questions(session, attempt.exam_id)}
        existing = {a.question_id: a for a in session.scalars(select(Answer).where(Answer.attempt_id == attempt_id))}
        saved = 0
        for item in answers:
            question = assigned.get(item.question_id)
            if question is None:
                raise ApiError(422, "invalid_question",
                               f"Question {item.question_id} is not part of this exam.")
            value = _validated_answer(question, item.selected_answer)
            row = existing.get(item.question_id)
            if row is None:
                session.add(Answer(attempt_id=attempt_id, exam_id=attempt.exam_id, question_id=item.question_id,
                                   selected_answer=value, answered_at=now))
            elif row.selected_answer != value:
                row.selected_answer = value
                row.answered_at = now
            saved += 1
    return {"attempt_id": attempt_id, "saved": saved, "saved_at": now}


def _validated_answer(question: Question, value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if question.question_type == "MCQ":
        if value not in (question.options or []):
            raise ApiError(422, "invalid_option", f"'{value}' is not an option of question {question.question_id}.")
    elif question.question_type == "TRUE_FALSE":
        value = value.upper()
        if value not in ("TRUE", "FALSE"):
            raise ApiError(422, "invalid_option", "True/false questions accept TRUE or FALSE.")
    return value


# --------------------------------------------------------------------------- submit
def auto_grade(question: Question, marks_assigned: Decimal, answer: str | None) -> Decimal | None:
    """Marks for one answer, or None when a human must grade it."""
    if answer is None or not answer.strip():
        return Decimal("0")
    if question.question_type in AUTO_GRADED:
        return marks_assigned if normalize(answer) == normalize(question.correct_answer) else Decimal("0")
    return None  # LONG_ANSWER with content


def submit_attempt(session: Session, user: CurrentUser, attempt_id: int) -> dict:
    """One transaction: lock -> fill unanswered -> grade -> SUBMITTED -> (result).
    A second, concurrent submit waits on the row lock and then sees SUBMITTED."""
    with session.begin():
        attempt = _load_attempt(session, attempt_id, lock=True)
        _check_owner(attempt, user)
        if not user.is_student:
            raise ApiError(403, "forbidden", "Only the student can submit an attempt.")
        if attempt.status != "IN_PROGRESS":
            raise ApiError(409, "already_submitted", "This attempt has already been submitted.")

        now = db_now(session)
        existing = {a.question_id: a for a in session.scalars(select(Answer).where(Answer.attempt_id == attempt_id))}
        exam_questions = _exam_questions(session, attempt.exam_id)
        for eq in exam_questions:
            if eq.question_id not in existing:
                row = Answer(attempt_id=attempt_id, exam_id=attempt.exam_id, question_id=eq.question_id,
                             selected_answer=None, answered_at=now)
                session.add(row)
                existing[eq.question_id] = row
        session.flush()  # answers must be inserted while the attempt is still IN_PROGRESS (trigger rule)

        attempt.status = "SUBMITTED"
        attempt.submitted_at = now
        session.flush()

        pending = 0
        for eq in exam_questions:
            row = existing[eq.question_id]
            row.marks_obtained = auto_grade(eq.question, eq.marks_assigned, row.selected_answer)
            pending += row.marks_obtained is None
        session.flush()

        if pending == 0:
            session.execute(text("CALL sp_finalize_attempt(:attempt_id)"), {"attempt_id": attempt_id})
    session.refresh(attempt)
    return {"attempt_id": attempt_id, "status": attempt.status, "submitted_at": attempt.submitted_at,
            "pending_manual_grading": pending, "results_released": bool(attempt.exam.results_released)}


# --------------------------------------------------------------------------- grade
def grade_attempt(session: Session, user: CurrentUser, attempt_id: int, grades: list) -> dict:
    with session.begin():
        attempt = _load_attempt(session, attempt_id, lock=True)
        if attempt.status != "SUBMITTED":
            raise ApiError(409, "not_gradable",
                           "Only SUBMITTED attempts can be graded "
                           f"(this one is {attempt.status}).")
        if user.role == "FACULTY" and attempt.exam.created_by != user.id:
            raise ApiError(403, "forbidden", "Only the exam's author or an administrator can grade it.")
        marks = {eq.question_id: eq.marks_assigned for eq in _exam_questions(session, attempt.exam_id)}
        rows = {a.question_id: a for a in session.scalars(select(Answer).where(Answer.attempt_id == attempt_id))}
        for item in grades:
            if item.question_id not in rows:
                raise ApiError(422, "invalid_question", f"Question {item.question_id} is not in this attempt.")
            if item.marks_obtained > marks[item.question_id]:
                raise ApiError(422, "marks_too_high",
                               f"Question {item.question_id} is worth at most {marks[item.question_id]} marks.")
            rows[item.question_id].marks_obtained = item.marks_obtained
        session.flush()
        remaining = sum(1 for r in rows.values() if r.marks_obtained is None)
        if remaining == 0:
            session.execute(text("CALL sp_finalize_attempt(:attempt_id)"), {"attempt_id": attempt_id})
    session.refresh(attempt)
    return {"attempt_id": attempt_id, "status": attempt.status, "ungraded_remaining": remaining}
