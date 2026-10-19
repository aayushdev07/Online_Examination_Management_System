from decimal import Decimal

from pydantic import BaseModel, Field


class AnswerIn(BaseModel):
    question_id: int = Field(gt=0)
    selected_answer: str | None = Field(default=None, max_length=5000)


class SaveAnswersRequest(BaseModel):
    answers: list[AnswerIn] = Field(min_length=1, max_length=200)


class GradeItem(BaseModel):
    question_id: int = Field(gt=0)
    marks_obtained: Decimal = Field(ge=0, le=1000, decimal_places=2)


class GradeRequest(BaseModel):
    grades: list[GradeItem] = Field(min_length=1, max_length=200)
