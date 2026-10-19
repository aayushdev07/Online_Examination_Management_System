from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

ExamStatus = Literal["SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"]
QuestionType = Literal["MCQ", "TRUE_FALSE", "SHORT_ANSWER", "LONG_ANSWER"]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


def _check_window(exam_date, deadline, duration) -> None:
    if exam_date is None or deadline is None:
        return
    if deadline <= exam_date:
        raise ValueError("deadline must be after the exam start (exam_date)")
    if duration is not None and (deadline - exam_date).total_seconds() / 60 < duration:
        raise ValueError("the exam window (exam_date to deadline) must be at least duration_minutes long")


class ExamCreate(BaseModel):
    title: Title
    subject: Subject
    exam_date: datetime
    deadline: datetime
    duration_minutes: int = Field(gt=0, le=600)
    pass_percentage: Decimal = Field(default=Decimal("40"), ge=0, le=100, decimal_places=2)
    status: ExamStatus = "SCHEDULED"

    @model_validator(mode="after")
    def _window(self):
        _check_window(self.exam_date, self.deadline, self.duration_minutes)
        return self


class ExamUpdate(BaseModel):
    title: Title | None = None
    subject: Subject | None = None
    exam_date: datetime | None = None
    deadline: datetime | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=600)
    pass_percentage: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    status: ExamStatus | None = None


class ReleaseRequest(BaseModel):
    released: bool


class AssignQuestion(BaseModel):
    question_id: int = Field(gt=0)
    question_order: int | None = Field(default=None, gt=0, le=1000)
    marks_assigned: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=2)


class UpdateAssignment(BaseModel):
    question_order: int | None = Field(default=None, gt=0, le=1000)
    marks_assigned: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=2)


class QuestionIn(BaseModel):
    question_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    question_type: QuestionType
    options: list[OptionText] | None = Field(default=None, max_length=8)
    marks: Decimal = Field(gt=0, le=1000, decimal_places=2)
    correct_answer: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None

    @model_validator(mode="after")
    def _by_type(self):
        t = self.question_type
        if t == "MCQ":
            if not self.options or len(self.options) < 2:
                raise ValueError("an MCQ needs at least 2 options")
            if len({o.lower() for o in self.options}) != len(self.options):
                raise ValueError("MCQ options must be unique")
            if self.correct_answer not in self.options:
                raise ValueError("correct_answer must be exactly one of the options")
        else:
            if self.options:
                raise ValueError("only MCQ questions have options")
            self.options = None
        if t == "TRUE_FALSE":
            answer = (self.correct_answer or "").upper()
            if answer not in ("TRUE", "FALSE"):
                raise ValueError("correct_answer must be TRUE or FALSE")
            self.correct_answer = answer
        if t == "SHORT_ANSWER" and not self.correct_answer:
            raise ValueError("a short-answer question needs a correct_answer")
        if t == "LONG_ANSWER" and self.correct_answer == "":
            self.correct_answer = None  # optional model answer for the grader
        return self
