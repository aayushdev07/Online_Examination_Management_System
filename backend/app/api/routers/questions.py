"""Question bank CRUD (staff only)."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_staff
from app.core.errors import ApiError
from app.db.engines import get_session
from app.db.models import Attempt, ExamQuestion, Question
from app.schemas.common import page_params
from app.schemas.exams import QuestionIn

router = APIRouter(prefix="/api/questions", tags=["questions"])


def _usage_subquery():
    return (select(func.count()).select_from(ExamQuestion)
            .where(ExamQuestion.question_id == Question.question_id).correlate(Question).scalar_subquery())


def _question_dict(q: Question, usage: int | None = None) -> dict:
    data = {c.name: getattr(q, c.name) for c in Question.__table__.columns}
    if usage is not None:
        data["usage_count"] = usage
    return data


def _get(session: Session, question_id: int) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise ApiError(404, "not_found", f"Question {question_id} does not exist.")
    return question


def _check_owner(question: Question, user: CurrentUser) -> None:
    if user.role == "FACULTY" and question.created_by != user.id:
        raise ApiError(403, "forbidden", "Only the question's author or an administrator can change it.")


@router.get("")
def list_questions(question_type: str | None = Query(default=None,
                                                     pattern="^(MCQ|TRUE_FALSE|SHORT_ANSWER|LONG_ANSWER)$"),
                   search: str | None = Query(default=None, max_length=100), unassigned: bool = False,
                   page: int = 1, page_size: int = 50,
                   _: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    page, page_size, offset = page_params(page, page_size, max_size=200)
    usage = _usage_subquery()
    conditions = []
    if question_type:
        conditions.append(Question.question_type == question_type)
    if search:
        conditions.append(Question.question_text.like(f"%{search.strip()}%"))
    if unassigned:
        conditions.append(~exists().where(ExamQuestion.question_id == Question.question_id))
    query = select(Question, usage.label("usage")).where(*conditions).order_by(Question.question_id)
    total = session.scalar(select(func.count()).select_from(Question).where(*conditions))
    rows = session.execute(query.limit(page_size).offset(offset)).all()
    return {"items": [_question_dict(q, n) for q, n in rows], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_question(body: QuestionIn, current: CurrentUser = Depends(require_staff),
                    session: Session = Depends(get_session)):
    question = Question(created_by=current.id, **body.model_dump())
    session.add(question)
    session.commit()
    return _question_dict(question, 0)


@router.get("/{question_id}")
def get_question(question_id: int, _: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    question = _get(session, question_id)
    usage = session.scalar(select(func.count()).select_from(ExamQuestion)
                           .where(ExamQuestion.question_id == question_id))
    return _question_dict(question, usage)


@router.put("/{question_id}")
def update_question(question_id: int, body: QuestionIn, current: CurrentUser = Depends(require_staff),
                    session: Session = Depends(get_session)):
    question = _get(session, question_id)
    _check_owner(question, current)
    attempted = session.scalar(
        select(func.count()).select_from(ExamQuestion)
        .join(Attempt, Attempt.exam_id == ExamQuestion.exam_id)
        .where(ExamQuestion.question_id == question_id))
    if attempted:
        raise ApiError(409, "question_in_use",
                       "This question belongs to an exam that students have attempted; "
                       "editing it would change graded work. Create a new question instead.")
    for field, value in body.model_dump().items():
        setattr(question, field, value)
    session.commit()
    return _question_dict(question)


@router.delete("/{question_id}", status_code=204)
def delete_question(question_id: int, current: CurrentUser = Depends(require_staff),
                    session: Session = Depends(get_session)):
    question = _get(session, question_id)
    _check_owner(question, current)
    session.delete(question)
    session.commit()   # still assigned to an exam -> FK (1451) -> 409
    return Response(status_code=204)
