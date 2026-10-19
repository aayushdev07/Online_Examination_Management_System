"""Schema explorer, table viewer, query-plan viewer and stored-routine runner."""

from __future__ import annotations

import re
import time
from typing import Literal

import pymysql
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import CurrentUser, require_staff
from app.core.config import get_settings
from app.core.errors import ApiError, mysql_error_parts
from app.db.initializer import READ_ONLY_ROUTINES
from app.db.sql_script import split_statements
from app.services import metadata, sql_log
from app.services.lab.executor import LabSessions, run_statement, to_json

router = APIRouter(prefix="/api/db", tags=["database"])

Database = Literal["main", "lab"]
HIDDEN_COLUMNS = {"password_hash"}
BLOCKED_ROUTINES = ("sp_generate_bulk_data", "sp_seed_exam_attempts")   # heavy seed utilities


@router.get("/schema")
def schema(database: Database = "main", _: CurrentUser = Depends(require_staff)):
    return metadata.schema(database)


@router.get("/objects")
def objects(database: Database = "main", _: CurrentUser = Depends(require_staff)):
    return metadata.objects(database)


@router.get("/tables/{table}/rows")
def table_rows(table: str, database: Database = "main", page: int = 1, page_size: int = Query(default=25, le=200),
               sort: str | None = None, direction: Literal["asc", "desc"] = "asc",
               _: CurrentUser = Depends(require_staff)):
    db, columns, pk = metadata.table_columns(database, table)
    _, _, data_engine = metadata.resolve(database)
    page = max(1, page)
    page_size = max(1, page_size)
    order_col = sort if sort in columns else (pk[0] if pk else columns[0])
    q = metadata.quote_ident
    select_list = ", ".join(
        f"'(hidden)' AS {q(c)}" if c in HIDDEN_COLUMNS else q(c) for c in columns)
    sql = (f"SELECT {select_list} FROM {q(db)}.{q(table)} ORDER BY {q(order_col)} {direction.upper()} "
           "LIMIT :limit OFFSET :offset")
    started = time.perf_counter()
    with data_engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": page_size, "offset": (page - 1) * page_size}).all()
        total = conn.execute(text(f"SELECT COUNT(*) FROM {q(db)}.{q(table)}")).scalar()
    return {"database": db, "table": table, "columns": columns, "primary_key": pk,
            "rows": [[to_json(v) for v in r] for r in rows], "total": total, "page": page,
            "page_size": page_size, "sort": order_col, "direction": direction,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "hidden_columns": [c for c in columns if c in HIDDEN_COLUMNS]}


# --------------------------------------------------------------------------- EXPLAIN
class ExplainRequest(BaseModel):
    database: Database = "main"
    sql: str = Field(min_length=1, max_length=5000)
    analyze: bool = False


_READ_ONLY_FORBIDDEN = re.compile(
    r"\b(INTO|FOR\s+UPDATE|FOR\s+SHARE|LOCK\s+IN|SLEEP|BENCHMARK|GET_LOCK|LOAD_FILE)\b", re.IGNORECASE)


def _single_select(sql: str) -> str:
    try:
        statements = split_statements(sql, allow_delimiter_command=False)
    except ValueError as exc:
        raise ApiError(422, "sql_parse_error", str(exc)) from None
    if len(statements) != 1:
        raise ApiError(422, "single_statement", "Provide exactly one SELECT statement.")
    statement = statements[0].sql
    first = (re.findall(r"[A-Za-z]+", statement[:30]) or [""])[0].upper()
    if first not in ("SELECT", "WITH", "TABLE"):
        raise ApiError(422, "select_only", "The plan viewer only explains SELECT queries.")
    bare = re.sub(r"'(?:\\.|''|[^'\\])*'", "''", statement)
    if _READ_ONLY_FORBIDDEN.search(bare):
        raise ApiError(422, "select_only", "INTO, locking reads and sleep/benchmark functions are not allowed here.")
    return statement


@router.post("/explain")
def explain(body: ExplainRequest, current: CurrentUser = Depends(require_staff)):
    s = get_settings()
    statement = _single_select(body.sql)
    account = "reader" if body.database == "main" else "lab"
    target = s.db_name if body.database == "main" else s.lab_db_name
    sessions = LabSessions(s)
    plans, logs = {}, []
    try:
        conn = sessions.get(account)
        variants = [("table", f"EXPLAIN {statement}"), ("tree", f"EXPLAIN FORMAT=TREE {statement}")]
        if body.analyze:
            variants.append(("analyze", f"EXPLAIN ANALYZE {statement}"))
        for key, sql in variants:
            started = time.perf_counter()
            try:
                outcome = run_statement(conn, sql, None, s.sql_max_rows)
            except pymysql.MySQLError as exc:
                errno, message = mysql_error_parts(exc)
                logs.append(sql_log.LogEntry("EXPLAIN", "EXPLAIN", target, sql, "ERROR", current.role, current.id,
                                             duration_ms=(time.perf_counter() - started) * 1000,
                                             error_code=errno, error_message=message))
                raise ApiError(422, "explain_failed", message, {"mysql_errno": errno}) from None
            plans[key] = {**outcome.result_sets[0], "duration_ms": round(outcome.duration_ms, 3)}
            logs.append(sql_log.LogEntry("EXPLAIN", "EXPLAIN", target, sql, "SUCCESS", current.role, current.id,
                                         rows_returned=outcome.rows_returned, duration_ms=outcome.duration_ms))
    finally:
        sessions.close()
        sql_log.write(logs)
    return {"database": target, "account": s.db_readonly_user if account == "reader" else s.db_lab_user,
            "statement": statement, "plans": plans}


# --------------------------------------------------------------------------- routines
class CallRequest(BaseModel):
    database: Database = "main"
    args: list[str | int | float | None] = Field(default_factory=list, max_length=20)


@router.post("/routines/{name}/call")
def call_routine(name: str, body: CallRequest, current: CurrentUser = Depends(require_staff)):
    s = get_settings()
    if name in BLOCKED_ROUTINES:
        raise ApiError(403, "routine_blocked", "Seed generators cannot be run from the explorer.")
    if body.database == "main" and name.lower() not in {r[1].lower() for r in READ_ONLY_ROUTINES}:
        raise ApiError(403, "routine_not_allowed",
                       "On the main database only read-only routines may be executed (through the read-only "
                       "account). Run data-changing routines against the lab database.")
    sig = metadata.routine_signature(body.database, name)
    in_params = [p for p in sig["parameters"] if p["mode"] in ("IN", "INOUT") or sig["type"] == "FUNCTION"]
    if len(body.args) != len(in_params):
        raise ApiError(422, "validation_error",
                       f"{name} expects {len(in_params)} input argument(s), got {len(body.args)}.")
    if any(p["mode"] == "INOUT" for p in sig["parameters"]):
        raise ApiError(422, "unsupported", "INOUT parameters are not supported by the explorer.")
    q = metadata.quote_ident
    if sig["type"] == "FUNCTION":
        statements = [f"SELECT {q(name)}({', '.join(['%s'] * len(body.args))}) AS result"]
    else:
        # IN parameters are bound values; OUT parameters go to session variables read afterwards
        values = ["%s" if p["mode"] == "IN" else f"@out_{p['name']}" for p in sig["parameters"]]
        outs = [f"@out_{p['name']} AS {q(p['name'])}" for p in sig["parameters"] if p["mode"] == "OUT"]
        statements = [f"CALL {q(name)}({', '.join(values)})"]
        if outs:
            statements.append(f"SELECT {', '.join(outs)}")

    account = "reader" if body.database == "main" else "lab"
    target = sig["database"]
    sessions = LabSessions(s)
    result_sets, logs = [], []
    started = time.perf_counter()
    try:
        conn = sessions.get(account)
        for idx, sql in enumerate(statements):
            args = tuple(body.args) if idx == 0 else ()
            shown = sql % tuple(conn.literal(a) for a in args) if args else sql
            t0 = time.perf_counter()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, args or None)
                    while True:
                        if cur.description:
                            rows = cur.fetchall()
                            result_sets.append({"columns": [d[0] for d in cur.description],
                                                "rows": [[to_json(v) for v in r] for r in rows[:s.sql_max_rows]],
                                                "row_count": len(rows), "truncated": len(rows) > s.sql_max_rows})
                        if not cur.nextset():
                            break
                logs.append(sql_log.LogEntry("PROCEDURES", "PROCEDURE", target, shown, "SUCCESS", current.role,
                                             current.id, duration_ms=(time.perf_counter() - t0) * 1000,
                                             rows_returned=sum(r["row_count"] for r in result_sets)))
            except pymysql.MySQLError as exc:
                errno, message = mysql_error_parts(exc)
                logs.append(sql_log.LogEntry("PROCEDURES", "PROCEDURE", target, shown, "ERROR", current.role,
                                             current.id, duration_ms=(time.perf_counter() - t0) * 1000,
                                             error_code=errno, error_message=message))
                return {"status": "error", "routine": name, "database": target, "statements": statements,
                        "error": {"code": errno, "message": message}, "result_sets": result_sets,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3)}
    finally:
        sessions.close()
        sql_log.write(logs)
    return {"status": "success", "routine": name, "database": target, "statements": statements,
            "result_sets": result_sets, "duration_ms": round((time.perf_counter() - started) * 1000, 3)}
