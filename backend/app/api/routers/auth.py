"""Registration, login and the current-user endpoint."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.engines import get_session
from app.db.models import FacultyAdmin, Student
from app.schemas.users import LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])
login_limiter = RateLimiter(get_settings().login_rate_limit_per_minute)

# verifying against a real hash keeps the response time similar for unknown users
_DUMMY_HASH = hash_password("timing-equaliser-0")


def _token_response(user_id: int, role: str, name: str, username: str, email: str) -> dict:
    token, expires_in = create_access_token(user_id, role, name)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in,
            "user": {"id": user_id, "role": role, "name": name, "username": username, "email": email}}


@router.post("/register", status_code=201)
def register(body: RegisterRequest, session: Session = Depends(get_session)):
    """Student self-registration. Duplicate email/username is rejected by the
    UNIQUE constraints and reported as 409."""
    student = Student(student_name=body.student_name, email=body.email.lower(), username=body.username,
                      password_hash=hash_password(body.password))
    session.add(student)
    session.commit()
    return _token_response(student.student_id, "STUDENT", student.student_name, student.username, student.email)


@router.post("/login")
def login(body: LoginRequest, request: Request, session: Session = Depends(get_session)):
    client = request.client.host if request.client else "unknown"
    login_limiter.check(f"{client}:{body.username.lower()}")

    identifier = body.username.strip()
    if body.account_type == "STUDENT":
        user = session.scalar(select(Student).where(or_(Student.username == identifier,
                                                        Student.email == identifier.lower())))
        if user and verify_password(body.password, user.password_hash):
            return _token_response(user.student_id, "STUDENT", user.student_name, user.username, user.email)
    else:
        user = session.scalar(select(FacultyAdmin).where(or_(FacultyAdmin.username == identifier,
                                                             FacultyAdmin.email == identifier.lower())))
        if user and verify_password(body.password, user.password_hash):
            return _token_response(user.faculty_admin_id, user.role, user.faculty_name, user.username, user.email)
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
    raise ApiError(401, "invalid_credentials", "Incorrect username or password.")


@router.get("/me")
def me(current: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if current.is_student:
        user = session.get(Student, current.id)
        if user is None:
            raise ApiError(401, "unauthorized", "Account no longer exists.")
        return {"id": user.student_id, "role": "STUDENT", "name": user.student_name,
                "username": user.username, "email": user.email, "created_at": user.created_at}
    staff = session.get(FacultyAdmin, current.id)
    if staff is None:
        raise ApiError(401, "unauthorized", "Account no longer exists.")
    return {"id": staff.faculty_admin_id, "role": staff.role, "name": staff.faculty_name,
            "username": staff.username, "email": staff.email, "created_at": staff.created_at}
