"""SQL Command Center API: example catalog, execution, history, lab reset."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin, require_staff
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter
from app.db.engines import get_session
from app.schemas.common import page_params
from app.services.lab import executor
from app.services.lab.catalog import CATEGORIES, catalog
from app.services.lab.policy import MAX_SQL_CHARS

router = APIRouter(prefix="/api/sql", tags=["sql-lab"])
execute_limiter = RateLimiter(get_settings().sql_rate_limit_per_minute)


class ExecuteRequest(BaseModel):
    example_id: str | None = Field(default=None, max_length=80)
    params: dict[str, str | int | float] | None = None
    action: Literal["run", "cleanup"] = "run"
    confirm: bool = False
    sql: str | None = Field(default=None, max_length=MAX_SQL_CHARS)


@router.get("/config")
def config(_: CurrentUser = Depends(require_staff)):
    s = get_settings()
    return {"main_database": s.db_name, "lab_database": s.lab_db_name,
            "accounts": {"reader": s.db_readonly_user, "lab": s.db_lab_user, "dcl": s.db_dcl_user},
            "freeform_enabled": s.sql_freeform_enabled, "max_rows": s.sql_max_rows,
            "timeout_seconds": s.sql_timeout_seconds, "rate_limit_per_minute": s.sql_rate_limit_per_minute,
            "max_sql_chars": MAX_SQL_CHARS}


@router.get("/examples")
def examples(current: CurrentUser = Depends(require_staff)):
    items = [e.public() | {"allowed": executor.ROLE_RANK[current.role] >= executor.ROLE_RANK[e.min_role]}
             for e in catalog().values()]
    return {"categories": [{"id": c, "title": t, "description": d,
                            "count": sum(1 for e in items if e["category"] == c)} for c, t, d in CATEGORIES],
            "examples": items}


@router.post("/execute")
def execute(body: ExecuteRequest, current: CurrentUser = Depends(require_staff)):
    execute_limiter.check(f"{current.role}:{current.id}")
    if body.sql is not None:
        if body.example_id:
            raise ApiError(422, "validation_error", "Send either example_id or sql, not both.")
        return executor.run_freeform(body.sql, current.role, current.id, confirm=body.confirm)
    if not body.example_id:
        raise ApiError(422, "validation_error", "example_id or sql is required.")
    example = catalog().get(body.example_id)
    if example is None:
        raise ApiError(404, "not_found", f"Unknown example '{body.example_id}'.")
    return executor.run_example(example, current.role, current.id, body.params,
                                cleanup=body.action == "cleanup", confirm=body.confirm)


@router.get("/history")
def history(status: str | None = Query(default=None, pattern="^(SUCCESS|ERROR|REJECTED)$"),
            category: str | None = Query(default=None, max_length=40),
            mode: str | None = Query(default=None, pattern="^(EXAMPLE|CLEANUP|FREEFORM|EXPLAIN|PROCEDURE|REPORT|RESET)$"),
            page: int = 1, page_size: int = 50,
            _: CurrentUser = Depends(require_staff), session: Session = Depends(get_session)):
    page, page_size, offset = page_params(page, page_size, max_size=200)
    clause = ("(:status IS NULL OR status = :status) AND (:category IS NULL OR category = :category) "
              "AND (:mode IS NULL OR execution_mode = :mode)")
    params = {"status": status, "category": category, "mode": mode}
    rows = session.execute(text(f"""
        SELECT log_id, request_id, user_role, user_id, example_id, category, execution_mode, target_db,
               statement_text, status, rows_returned, rows_affected, duration_ms, error_code, error_message,
               executed_at
          FROM sql_execution_log WHERE {clause}
         ORDER BY executed_at DESC, log_id DESC LIMIT :limit OFFSET :offset"""),
                           {**params, "limit": page_size, "offset": offset}).mappings().all()
    total = session.scalar(text(f"SELECT COUNT(*) FROM sql_execution_log WHERE {clause}"), params)
    summary = session.execute(text(
        "SELECT status, COUNT(*) AS n, ROUND(AVG(duration_ms), 3) AS avg_ms FROM sql_execution_log GROUP BY status"
    )).mappings().all()
    return {"items": rows, "total": total, "page": page, "page_size": page_size, "summary": summary}


@router.post("/lab/reset")
def reset_lab(current: CurrentUser = Depends(require_admin)):
    return executor.reset_lab(current.role, current.id)
