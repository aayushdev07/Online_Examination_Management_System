"""Writes rows to sql_execution_log (metadata only: no passwords, tokens or answer content)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import insert

from app.core.context import current_request_id
from app.core.errors import sanitize_message
from app.db.engines import app_engine
from app.db.models import SqlExecutionLog

log = logging.getLogger("oems.sql_log")
MAX_STATEMENT_CHARS = 5000


@dataclass
class LogEntry:
    category: str
    execution_mode: str
    target_db: str
    statement_text: str
    status: str
    user_role: str
    user_id: int | None
    example_id: str | None = None
    rows_returned: int = 0
    rows_affected: int = 0
    duration_ms: float = 0.0
    error_code: int | None = None
    error_message: str | None = None


def write(entries: list[LogEntry]) -> None:
    """Best effort: a logging failure must never break the user's request."""
    if not entries:
        return
    rows = [{
        "request_id": current_request_id()[:64],
        "user_role": e.user_role, "user_id": e.user_id, "example_id": e.example_id,
        "category": e.category[:40], "execution_mode": e.execution_mode, "target_db": e.target_db,
        "statement_text": e.statement_text[:MAX_STATEMENT_CHARS], "status": e.status,
        "rows_returned": max(0, int(e.rows_returned)), "rows_affected": int(e.rows_affected),
        "duration_ms": round(max(0.0, e.duration_ms), 3), "error_code": e.error_code,
        "error_message": sanitize_message(e.error_message, 500) if e.error_message else None,
    } for e in entries]
    try:
        with app_engine().begin() as conn:
            conn.execute(insert(SqlExecutionLog), rows)
    except Exception:  # noqa: BLE001
        log.exception("could not write sql_execution_log")
