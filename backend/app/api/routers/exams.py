"""Examinations, question assignment, release rules and the exam audit trail."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_staff, require_student
from app.core.errors import ApiError
from app.db.engines import get_session
from app.db.models import Attempt, Exam, ExamAudit, ExamQuestion, Question
from app.schemas.exams import AssignQuestion, ExamCreate, ExamUpdate, ReleaseRequest, UpdateAssignment
from app.services import exam_workflow as wf

router = APIRouter(prefix="/api/exams", tags=["exams"])

STAFF_COLUMNS = ", ".join(f"v.{c}" for c in (
    "exam_id", "title", "subject", "status", "exam_date", "deadline", "duration_minutes", "total_marks",
    "pass_percentage", "results_released", "created_by_name", "question_count", "attempt_count", "submitted_count"))


def _get_exam(session: Session, exam_id: int) -> Exam:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ApiError(404, "not_found", f"Exam {exam_id} does not exist.")
    return exam


def _check_can_edit(exam: Exam, user: CurrentUser) -> None:
    if user.role == "FACULTY" and exam.created_by != user.id:
        raise ApiError(403, "forbidden", "Only the exam's author or an administrator can change it.")


def _attempt_count(session: Session, exam_id: int) -> int:
    return session.scalar(select(func.count()).select_from(Attempt).where(Attempt.exam_id == exam_id))


def _overview(session: Session, exam_id: int) -> dict:
    row = session.execute(text(f"SELECT {STAFF_COLUMNS}, e.created_by FROM exam_overview v "
                               "JOIN exam e ON e.exam_id = v.exam_id WHERE v.exam_id = :id"),
                          {"id": exam_id}).mappings().one()
    data = dict(row)
    data["results_released"] = bool(data["results_released"])
    return data


# --------------------------------------------------------------------------- exams
@router.get("")
def list_exams(status: str | None = Query(default=None, pattern="^(SCHEDULED|ACTIVE|COMPLETED|CANCELLED)$"),
               mine: bool = False, current: CurrentUser = Depends(get_current_user),
               session: Session = Depends(get_session)):
    now = wf.db_now(session)
    if current.is_staff:
        sql = (f"SELECT {STAFF_COLUMNS}, e.created_by FROM exam_overview v JOIN exam e ON e.exam_id = v.exam_id "
               "WHERE (:status IS NULL OR v.status = :status) AND (:mine = 0 OR e.created_by = :uid) "
               "ORDER BY v.exam_date DESC")
        rows = session.execute(text(sql), {"status": status, "mine": int(mine), "uid": current.id}).mappings().all()
        return [{**r, "results_released": bool(r["results_released"])} for r in rows]

    # students: every non-cancelled exam with their own attempt (LEFT JOIN keeps exams not attempted)
    sql = """
        SELECT e.exam_id, e.title, e.subject, e.status, e.exam_date, e.deadline, e.duration_minutes,
               e.total_marks, e.pass_percentage, e.results_released, f.faculty_name AS created_by_name,
               (SELECT COUNT(*) FROM exam_question eq WHERE eq.exam_id = e.exam_id) AS question_count,
               a.attempt_id, a.status AS attempt_status, a.started_at, a.submitted_at,
               IF(e.results_released = 1, r.percentage, NULL)    AS percentage,
               IF(e.results_released = 1, r.result_status, NULL) AS result_status
          FROM exam e
          JOIN faculty_admin f ON f.faculty_admin_id = e.created_by
          LEFT JOIN attempt a  ON a.exam_id = e.exam_id AND a.student_id = :sid
          LEFT JOIN result r   ON r.attempt_id = a.attempt_id
         WHERE e.status <> 'CANCELLED' AND (:status IS NULL OR e.status = :status)
         ORDER BY e.exam_date DESC"""
    rows = session.execute(text(sql), {"sid": current.id, "status": status}).mappings().all()
    items = []
    for r in rows:
        item = dict(r)
        item["results_released"] = bool(item["results_released"])
        open_now = (r["status"] == "ACTIVE" and r["exam_date"] <= now <= r["deadline"] and r["question_count"] > 0)
        item["can_start"] = open_now and r["attempt_id"] is None
        item["can_resume"] = r["attempt_status"] == "IN_PROGRESS"
        items.append(item)
    return items


@router.post("", status_code=201)
def create_exam(body: ExamCreate, current: CurrentUser = Depends(require_staff),
                session: Session = Depends(get_session)):
    exam = Exam(created_by=current.id, **body.model_dump())
    session.add(exam)
    session.commit()   # trg_exam_after_insert writes the first audit row
    return _overview(session, exam.exam_id)


@router.get("/{exam_id}")
def get_exam(exam_id: int, current: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    if current.is_student and exam.status == "CANCELLED":
        raise ApiError(404, "not_found", f"Exam {exam_id} does not exist.")
    return _overview(session, exam_id)


@router.put("/{exam_id}")
def update_exam(exam_id: int, body: ExamUpdate, current: CurrentUser = Depends(require_staff),
                session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    _check_can_edit(exam, current)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(exam, field, value)
    # the schema validates partial input; the combined window is checked here and again by CHECK constraints
    if exam.deadline <= exam.exam_date:
        raise ApiError(422, "validation_error", "deadline must be after the exam start (exam_date)")
    if (exam.deadline - exam.exam_date).total_seconds() / 60 < exam.duration_minutes:
        raise ApiError(422, "validation_error", "the exam window must be at least duration_minutes long")
    session.commit()   # trg_exam_after_update records changed columns in exam_audit
    return _overview(session, exam_id)


@router.delete("/{exam_id}", status_code=204)
def delete_exam(exam_id: int, current: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    _check_can_edit(exam, current)
    if _attempt_count(session, exam_id):
        raise ApiError(409, "exam_has_attempts", "Students have attempted this exam; cancel it instead of deleting.")
    # one transaction: remove assignments, then the exam (FKs are NO ACTION, nothing cascades silently)
    session.execute(ExamQuestion.__table__.delete().where(ExamQuestion.exam_id == exam_id))
    session.delete(exam)
    session.commit()
    return Response(status_code=204)


@router.post("/{exam_id}/release")
def release_results(exam_id: int, body: ReleaseRequest, current: CurrentUser = Depends(require_staff),
                    session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    _check_can_edit(exam, current)
    exam.results_released = int(body.released)
    session.commit()
    return _overview(session, exam_id)


# --------------------------------------------------------------------------- questions of an exam
@router.get("/{exam_id}/questions")
def exam_questions(exam_id: int, current: CurrentUser = Depends(get_current_user),
                   session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    if current.is_student:
        attempt = session.scalar(select(Attempt).where(Attempt.exam_id == exam_id,
                                                       Attempt.student_id == current.id))
        if attempt is None:
            raise ApiError(403, "forbidden", "Start the exam to see its questions.")
    show_key = current.is_staff
    rows = session.scalars(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
                           .order_by(ExamQuestion.question_order)).all()
    return {"exam_id": exam.exam_id, "title": exam.title, "total_marks": exam.total_marks,
            "questions": [{"question_id": eq.question_id, "question_order": eq.question_order,
                           "marks_assigned": eq.marks_assigned, "question_text": eq.question.question_text,
                           "question_type": eq.question.question_type, "options": eq.question.options,
                           **({"correct_answer": eq.question.correct_answer,
                               "bank_marks": eq.question.marks} if show_key else {})}
                          for eq in rows]}


def _guard_assignment_change(session: Session, exam: Exam, user: CurrentUser) -> None:
    _check_can_edit(exam, user)
    if _attempt_count(session, exam.exam_id):
        raise ApiError(409, "exam_has_attempts",
                       "Questions cannot change after students have started this exam.")


@router.post("/{exam_id}/questions", status_code=201)
def assign_question(exam_id: int, body: AssignQuestion, current: CurrentUser = Depends(require_staff),
                    session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    _guard_assignment_change(session, exam, current)
    question = session.get(Question, body.question_id)
    if question is None:
        raise ApiError(404, "not_found", f"Question {body.question_id} does not exist.")
    order = body.question_order or (session.scalar(
        select(func.coalesce(func.max(ExamQuestion.question_order), 0)).where(ExamQuestion.exam_id == exam_id)) + 1)
    session.add(ExamQuestion(exam_id=exam_id, question_id=body.question_id, question_order=order,
                             marks_assigned=body.marks_assigned or question.marks))
    session.commit()   # duplicate assignment -> PK violation -> 409; total_marks updated by trigger
    return _overview(session, exam_id)


@router.put("/{exam_id}/questions/{question_id}")
def update_assignment(exam_id: int, question_id: int, body: UpdateAssignment,
                      current: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    _guard_assignment_change(session, exam, current)
    row = session.get(ExamQuestion, (exam_id, question_id))
    if row is None:
        raise ApiError(404, "not_found", f"Question {question_id} is not assigned to exam {exam_id}.")
    if body.question_order is not None:
        row.question_order = body.question_order
    if body.marks_assigned is not None:
        row.marks_assigned = body.marks_assigned
    session.commit()   # order clash -> UNIQUE(exam_id, question_order) -> 409
    return _overview(session, exam_id)


@router.delete("/{exam_id}/questions/{question_id}", status_code=204)
def remove_assignment(exam_id: int, question_id: int, current: CurrentUser = Depends(require_staff),
                      session: Session = Depends(get_session)):
    exam = _get_exam(session, exam_id)
    _guard_assignment_change(session, exam, current)
    row = session.get(ExamQuestion, (exam_id, question_id))
    if row is None:
        raise ApiError(404, "not_found", f"Question {question_id} is not assigned to exam {exam_id}.")
    session.delete(row)
    session.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- attempts / audit
@router.post("/{exam_id}/attempts")
def start_attempt(exam_id: int, response: Response, current: CurrentUser = Depends(require_student),
                  session: Session = Depends(get_session)):
    attempt, created = wf.start_attempt(session, current, exam_id)
    response.status_code = 201 if created else 200
    return {"attempt_id": attempt.attempt_id, "status": attempt.status, "started_at": attempt.started_at,
            "resumed": not created}


@router.get("/{exam_id}/attempts")
def exam_attempts(exam_id: int, _: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    _get_exam(session, exam_id)
    sql = """
        SELECT a.attempt_id, a.student_id, s.student_name, s.email, a.status, a.started_at, a.submitted_at,
               r.marks_obtained, r.percentage, r.result_status,
               (SELECT COUNT(*) FROM answer an WHERE an.attempt_id = a.attempt_id
                                                AND an.marks_obtained IS NULL)    AS ungraded_answers
          FROM attempt a
          JOIN student s     ON s.student_id = a.student_id
          LEFT JOIN result r ON r.attempt_id = a.attempt_id
         WHERE a.exam_id = :exam_id
         ORDER BY (a.status = 'SUBMITTED') DESC, a.submitted_at DESC, a.attempt_id
         LIMIT 500"""
    return session.execute(text(sql), {"exam_id": exam_id}).mappings().all()


@router.get("/{exam_id}/audit")
def exam_audit(exam_id: int, _: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    rows = session.scalars(select(ExamAudit).where(ExamAudit.exam_id == exam_id)
                           .order_by(ExamAudit.changed_at.desc(), ExamAudit.audit_id.desc()).limit(200)).all()
    return [{c.name: getattr(r, c.name) for c in ExamAudit.__table__.columns} for r in rows]
