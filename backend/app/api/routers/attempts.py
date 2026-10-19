"""Attempt lifecycle: view, save answers, submit, result, manual grading."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_staff
from app.db.engines import get_session
from app.schemas.attempts import GradeRequest, SaveAnswersRequest
from app.schemas.common import page_params
from app.services import exam_workflow as wf

router = APIRouter(prefix="/api/attempts", tags=["attempts"])


@router.get("")
def list_attempts(exam_id: int | None = None,
                  status: str | None = Query(default=None, pattern="^(IN_PROGRESS|SUBMITTED|EVALUATED)$"),
                  page: int = 1, page_size: int = 50,
                  current: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    """Students see their own attempts; staff can filter all attempts."""
    page, page_size, offset = page_params(page, page_size)
    where = ["(:exam_id IS NULL OR a.exam_id = :exam_id)", "(:status IS NULL OR a.status = :status)"]
    params = {"exam_id": exam_id, "status": status, "limit": page_size, "offset": offset}
    if current.is_student:
        where.append("a.student_id = :sid")
        params["sid"] = current.id
    clause = " AND ".join(where)
    released = "e.results_released = 1" if current.is_student else "TRUE"
    rows = session.execute(text(f"""
        SELECT a.attempt_id, a.exam_id, e.title AS exam_title, e.subject, a.student_id, s.student_name,
               a.status, a.started_at, a.submitted_at, e.results_released,
               IF({released}, r.percentage, NULL)    AS percentage,
               IF({released}, r.result_status, NULL) AS result_status
          FROM attempt a
          JOIN exam e    ON e.exam_id = a.exam_id
          JOIN student s ON s.student_id = a.student_id
          LEFT JOIN result r ON r.attempt_id = a.attempt_id
         WHERE {clause}
         ORDER BY a.started_at DESC, a.attempt_id DESC
         LIMIT :limit OFFSET :offset"""), params).mappings().all()
    total = session.scalar(text(f"SELECT COUNT(*) FROM attempt a WHERE {clause}"), params)
    items = [{**r, "results_released": bool(r["results_released"])} for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{attempt_id}")
def get_attempt(attempt_id: int, current: CurrentUser = Depends(get_current_user),
                session: Session = Depends(get_session)):
    return wf.attempt_detail(session, current, attempt_id)


@router.put("/{attempt_id}/answers")
def save_answers(attempt_id: int, body: SaveAnswersRequest, current: CurrentUser = Depends(get_current_user),
                 session: Session = Depends(get_session)):
    return wf.save_answers(session, current, attempt_id, body.answers)


@router.post("/{attempt_id}/submit")
def submit(attempt_id: int, current: CurrentUser = Depends(get_current_user),
           session: Session = Depends(get_session)):
    return wf.submit_attempt(session, current, attempt_id)


@router.get("/{attempt_id}/result")
def result(attempt_id: int, current: CurrentUser = Depends(get_current_user),
           session: Session = Depends(get_session)):
    return wf.get_result(session, current, attempt_id)


@router.post("/{attempt_id}/grade")
def grade(attempt_id: int, body: GradeRequest, current: CurrentUser = Depends(require_staff),
          session: Session = Depends(get_session)):
    return wf.grade_attempt(session, current, attempt_id, body.grades)
