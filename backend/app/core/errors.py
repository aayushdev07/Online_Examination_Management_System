"""Consistent error responses.

Every error has the shape
    {"error": {"code": str, "message": str, "details": any, "request_id": str}}
Database errors are translated into safe, useful messages; internal details
(stack traces, connection strings, credentials) never reach the client.
"""

import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import current_request_id

log = logging.getLogger("oems.errors")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details, "request_id": current_request_id()}}


_SECRET_PATTERNS = [
    re.compile(r"(password|passwd|pwd)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"mysql\+\w+://[^\s]+", re.IGNORECASE),
]


def sanitize_message(message: str, limit: int = 500) -> str:
    text = str(message)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:limit]


def mysql_error_parts(exc: BaseException) -> tuple[int | None, str]:
    """Extract (errno, message) from a PyMySQL / SQLAlchemy DB error."""
    orig = getattr(exc, "orig", exc)
    args = getattr(orig, "args", ())
    if len(args) >= 2 and isinstance(args[0], int):
        return args[0], sanitize_message(args[1])
    return None, sanitize_message(str(orig))


# MySQL error numbers -> (HTTP status, error code)
_MYSQL_STATUS = {
    1062: (409, "duplicate_value"),
    1451: (409, "row_referenced"),       # parent row still referenced (FK)
    1217: (409, "row_referenced"),       # same, older message form
    1452: (409, "foreign_key_violation"),
    1216: (409, "foreign_key_violation"),
    3819: (422, "check_violation"),
    1048: (422, "not_null_violation"),
    1644: (409, "rule_violation"),       # SIGNAL from a trigger / procedure
    1406: (422, "value_too_long"),
    1265: (422, "invalid_value"),
    1366: (422, "invalid_value"),
}


def db_error_to_api(exc: DBAPIError) -> ApiError:
    errno, message = mysql_error_parts(exc)
    status, code = _MYSQL_STATUS.get(errno, (500, "database_error"))
    if isinstance(exc, OperationalError) and errno in (2003, 2006, 2013, 1045, 1040):
        status, code = 503, "database_unavailable"
        message = "The database is not reachable right now."
    return ApiError(status, code, message, {"mysql_errno": errno})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
                   for err in exc.errors()]
        message = "; ".join(f"{d['field']}: {d['message']}" for d in details[:3]) or "Invalid request"
        return JSONResponse(error_body("validation_error", message, details), status_code=422)

    @app.exception_handler(IntegrityError)
    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError):
        api = db_error_to_api(exc)
        if api.status_code >= 500:
            log.error("database error", extra={"mysql_errno": api.details["mysql_errno"]}, exc_info=exc)
        return JSONResponse(error_body(api.code, api.message, api.details), status_code=api.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(error_body("internal_error", "An unexpected error occurred."), status_code=500)
