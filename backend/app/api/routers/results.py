"""Results and analytical reports (reports run through the read-only account)."""

from __future__ import annotations

import re
import time
from functools import lru_cache

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_staff
from app.core.config import DATABASE_DIR, get_settings
from app.core.errors import ApiError, db_error_to_api, mysql_error_parts
from app.db.engines import get_session, reader_engine
from app.db.sql_script import split_statements
from app.schemas.common import page_params
from app.services import sql_log

router = APIRouter(prefix="/api", tags=["results"])

_HEADER = re.compile(r"^-- @report (\S+) \| (.+?) \| (.+)$", re.MULTILINE)


@lru_cache
def load_reports() -> dict[str, dict]:
    """Parse database/reports.sql into {id: {title, description, sql}}."""
    text_ = (DATABASE_DIR / "reports.sql").read_text(encoding="utf-8")
    headers = list(_HEADER.finditer(text_))
    reports = {}
    for i, match in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text_)
        statements = split_statements(text_[match.end():end], allow_delimiter_command=False)
        if len(statements) != 1:
            raise RuntimeError(f"report {match.group(1)} must contain exactly one statement")
        reports[match.group(1)] = {"id": match.group(1), "title": match.group(2).strip(),
                                   "description": match.group(3).strip(), "sql": statements[0].sql}
    return reports


@router.get("/results")
def list_results(exam_id: int | None = None, search: str | None = None, page: int = 1, page_size: int = 25,
                 current: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    page, page_size, offset = page_params(page, page_size)
    where, params = ["(:exam_id IS NULL OR exam_id = :exam_id)"], {"exam_id": exam_id}
    if current.is_student:
        where += ["student_id = :sid", "results_released = 1"]
        params["sid"] = current.id
    if search:
        where.append("(student_name LIKE :search OR email LIKE :search)")
        params["search"] = f"%{search.strip()[:100]}%"
    clause = " AND ".join(where)
    rows = session.execute(text(f"SELECT * FROM student_result_view WHERE {clause} "
                                "ORDER BY evaluated_at DESC, result_id DESC LIMIT :limit OFFSET :offset"),
                           {**params, "limit": page_size, "offset": offset}).mappings().all()
    total = session.scalar(text(f"SELECT COUNT(*) FROM student_result_view WHERE {clause}"), params)
    return {"items": [{**r, "results_released": bool(r["results_released"])} for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/results/performance")
def exam_performance(_: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    return session.execute(text("SELECT * FROM exam_performance_view ORDER BY exam_id")).mappings().all()


@router.get("/reports")
def list_reports(_: CurrentUser = Depends(require_staff)):
    return [{k: r[k] for k in ("id", "title", "description", "sql")} for r in load_reports().values()]


@router.get("/reports/{report_id}")
def run_report(report_id: str, current: CurrentUser = Depends(require_staff)):
    report = load_reports().get(report_id)
    if report is None:
        raise ApiError(404, "not_found", f"Unknown report '{report_id}'.")
    started = time.perf_counter()
    entry = sql_log.LogEntry(category="REPORT", execution_mode="REPORT", target_db=get_settings().db_name,
                             statement_text=report["sql"], status="SUCCESS", user_role=current.role,
                             user_id=current.id, example_id=report_id)
    try:
        with reader_engine().connect() as conn:
            result = conn.execute(text(report["sql"]))
            columns = list(result.keys())
            rows = [list(r) for r in result.fetchmany(get_settings().sql_max_rows)]
    except DBAPIError as exc:
        entry.status, (entry.error_code, entry.error_message) = "ERROR", mysql_error_parts(exc)
        entry.duration_ms = (time.perf_counter() - started) * 1000
        sql_log.write([entry])
        raise db_error_to_api(exc) from None
    entry.duration_ms = (time.perf_counter() - started) * 1000
    entry.rows_returned = len(rows)
    sql_log.write([entry])
    return {**report, "columns": columns, "rows": rows, "row_count": len(rows),
            "duration_ms": round(entry.duration_ms, 3), "account": get_settings().db_readonly_user}
