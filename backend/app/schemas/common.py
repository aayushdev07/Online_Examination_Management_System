"""Shared request-validation helpers."""

import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,50}$")


def _username(value: str) -> str:
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("3-50 characters: letters, digits, '.' or '_'")
    return value


def _password(value: str) -> str:
    if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
        raise ValueError("must contain at least one letter and one digit")
    return value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Username = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_username)]
# bcrypt uses at most 72 bytes of input
Password = Annotated[str, StringConstraints(min_length=8, max_length=72), AfterValidator(_password)]


def page_params(page: int, page_size: int, max_size: int = 100) -> tuple[int, int, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), max_size)
    return page, page_size, (page - 1) * page_size
