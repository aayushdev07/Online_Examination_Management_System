"""Student and staff account management."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_admin, require_staff
from app.core.errors import ApiError
from app.core.security import hash_password
from app.db.engines import get_session
from app.db.models import Attempt, Exam, FacultyAdmin, Student
from app.schemas.common import page_params
from app.schemas.users import StaffCreate, StaffUpdate, StudentUpdate

router = APIRouter(prefix="/api", tags=["users"])


def _student_dict(s: Student, attempts: int | None = None) -> dict:
    data = {"student_id": s.student_id, "student_name": s.student_name, "email": s.email,
            "username": s.username, "created_at": s.created_at}
    if attempts is not None:
        data["attempt_count"] = attempts
    return data


def _staff_dict(f: FacultyAdmin, exams: int | None = None) -> dict:
    data = {"faculty_admin_id": f.faculty_admin_id, "faculty_name": f.faculty_name, "email": f.email,
            "username": f.username, "role": f.role, "created_at": f.created_at}
    if exams is not None:
        data["exam_count"] = exams
    return data


# --------------------------------------------------------------------------- students
@router.get("/students")
def list_students(search: str | None = Query(default=None, max_length=100), page: int = 1, page_size: int = 25,
                  _: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    page, page_size, offset = page_params(page, page_size)
    attempts = (select(func.count()).select_from(Attempt)
                .where(Attempt.student_id == Student.student_id).correlate(Student).scalar_subquery())
    query = select(Student, attempts.label("attempts"))
    count_query = select(func.count()).select_from(Student)
    if search:
        pattern = f"%{search.strip()}%"
        condition = or_(Student.student_name.like(pattern), Student.email.like(pattern),
                        Student.username.like(pattern))
        query, count_query = query.where(condition), count_query.where(condition)
    rows = session.execute(query.order_by(Student.student_id).limit(page_size).offset(offset)).all()
    return {"items": [_student_dict(s, n) for s, n in rows], "total": session.scalar(count_query),
            "page": page, "page_size": page_size}


@router.get("/students/{student_id}")
def get_student(student_id: int, current: CurrentUser = Depends(get_current_user),
                session: Session = Depends(get_session)):
    if current.is_student and current.id != student_id:
        raise ApiError(403, "forbidden", "Students can only view their own profile.")
    student = session.get(Student, student_id)
    if student is None:
        raise ApiError(404, "not_found", f"Student {student_id} does not exist.")
    attempts = session.scalar(select(func.count()).select_from(Attempt).where(Attempt.student_id == student_id))
    return _student_dict(student, attempts)


@router.put("/students/{student_id}")
def update_student(student_id: int, body: StudentUpdate, current: CurrentUser = Depends(get_current_user),
                   session: Session = Depends(get_session)):
    if not (current.is_admin or (current.is_student and current.id == student_id)):
        raise ApiError(403, "forbidden", "Only the student or an administrator can edit this profile.")
    student = session.get(Student, student_id)
    if student is None:
        raise ApiError(404, "not_found", f"Student {student_id} does not exist.")
    if body.student_name is not None:
        student.student_name = body.student_name
    if body.email is not None:
        student.email = body.email.lower()
    if body.password is not None:
        student.password_hash = hash_password(body.password)
    session.commit()
    return _student_dict(student)


@router.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: int, _: CurrentUser = Depends(require_admin), session: Session = Depends(get_session)):
    """Fails with 409 (FK error 1451) when the student has attempts — the
    database protects exam history from being orphaned."""
    student = session.get(Student, student_id)
    if student is None:
        raise ApiError(404, "not_found", f"Student {student_id} does not exist.")
    session.delete(student)
    session.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- staff
@router.get("/staff")
def list_staff(_: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    exams = (select(func.count()).select_from(Exam)
             .where(Exam.created_by == FacultyAdmin.faculty_admin_id).correlate(FacultyAdmin).scalar_subquery())
    rows = session.execute(select(FacultyAdmin, exams.label("exams")).order_by(FacultyAdmin.faculty_admin_id)).all()
    return [_staff_dict(f, n) for f, n in rows]


@router.post("/staff", status_code=201)
def create_staff(body: StaffCreate, _: CurrentUser = Depends(require_admin), session: Session = Depends(get_session)):
    staff = FacultyAdmin(faculty_name=body.faculty_name, email=body.email.lower(), username=body.username,
                         password_hash=hash_password(body.password), role=body.role)
    session.add(staff)
    session.commit()
    return _staff_dict(staff)


@router.put("/staff/{staff_id}")
def update_staff(staff_id: int, body: StaffUpdate, current: CurrentUser = Depends(require_staff),
                 session: Session = Depends(get_session)):
    if not current.is_admin and current.id != staff_id:
        raise ApiError(403, "forbidden", "Faculty can only edit their own account.")
    if body.role is not None and not current.is_admin:
        raise ApiError(403, "forbidden", "Only an administrator can change roles.")
    staff = session.get(FacultyAdmin, staff_id)
    if staff is None:
        raise ApiError(404, "not_found", f"Staff account {staff_id} does not exist.")
    if body.role is not None and body.role != "ADMIN" and staff.role == "ADMIN":
        admins = session.scalar(select(func.count()).select_from(FacultyAdmin).where(FacultyAdmin.role == "ADMIN"))
        if admins <= 1:
            raise ApiError(409, "last_admin", "At least one administrator account must remain.")
    for field in ("faculty_name", "role"):
        value = getattr(body, field)
        if value is not None:
            setattr(staff, field, value)
    if body.email is not None:
        staff.email = body.email.lower()
    if body.password is not None:
        staff.password_hash = hash_password(body.password)
    session.commit()
    return _staff_dict(staff)


@router.delete("/staff/{staff_id}", status_code=204)
def delete_staff(staff_id: int, current: CurrentUser = Depends(require_admin), session: Session = Depends(get_session)):
    if staff_id == current.id:
        raise ApiError(409, "self_delete", "You cannot delete your own account.")
    staff = session.get(FacultyAdmin, staff_id)
    if staff is None:
        raise ApiError(404, "not_found", f"Staff account {staff_id} does not exist.")
    session.delete(staff)
    session.commit()  # exams/questions authored by the account block this via FK -> 409
    return Response(status_code=204)
