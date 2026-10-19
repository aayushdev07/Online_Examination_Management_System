from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import Name, Password, Username


class RegisterRequest(BaseModel):
    student_name: Name
    email: EmailStr = Field(max_length=255)
    username: Username
    password: Password


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=72)
    account_type: Literal["STUDENT", "STAFF"] = "STUDENT"


class StudentUpdate(BaseModel):
    student_name: Name | None = None
    email: EmailStr | None = Field(default=None, max_length=255)
    password: Password | None = None


class StaffCreate(BaseModel):
    faculty_name: Name
    email: EmailStr = Field(max_length=255)
    username: Username
    password: Password
    role: Literal["FACULTY", "ADMIN"] = "FACULTY"


class StaffUpdate(BaseModel):
    faculty_name: Name | None = None
    email: EmailStr | None = Field(default=None, max_length=255)
    password: Password | None = None
    role: Literal["FACULTY", "ADMIN"] | None = None
