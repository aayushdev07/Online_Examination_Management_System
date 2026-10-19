"""Executes DBMS-Lab examples and free-form lab SQL against real MySQL sessions.

Safety model
  * The database account is the primary security boundary: each example runs
    with the least-privileged account that can do it (reader / lab / dcl).
  * Every run gets private, un-pooled sessions that are closed afterwards; an
    unfinished transaction is therefore rolled back by MySQL.
  * One statement per execute() call (multi-statements are disabled in the
    driver), a per-session max_execution_time, a socket timeout and a row cap.
  * Values supplied by users are bound parameters, never string concatenation.
"""

from __future__ import annotations

import datetime as dt
import secrets
import statistics
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal

import pymysql
from pymysql.converters import escape_item

from app.core.config import Settings, get_settings
from app.core.errors import ApiError, sanitize_message
from app.core.metrics import metrics
from app.core.context import current_request_id
from app.db.initializer import DEMO_DCL_USER
from app.services import sql_log
from app.services.lab.model import Example, Param, Step

ROLE_RANK = {"STUDENT": 0, "FACULTY": 1, "ADMIN": 2}
SECRET_PARAMS = ("demo_password",)
_demo_password = secrets.token_urlsafe(18) + "aA1!"   # per-process, never returned to clients


# --------------------------------------------------------------------------- value helpers
def to_json(value):
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat(sep=" ") if isinstance(value, dt.datetime) else value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + value.hex()
    return str(value)


def coerce_params(example: Example, supplied: dict | None) -> dict:
    supplied = supplied or {}
    unknown = set(supplied) - {p.name for p in example.params}
    if unknown:
        raise ApiError(422, "validation_error", f"Unknown parameter(s): {', '.join(sorted(unknown))}")
    return {p.name: _coerce(p, supplied.get(p.name, p.default)) for p in example.params}


def _coerce(param: Param, value):
    try:
        if param.type == "int":
            value = int(value)
        elif param.type == "decimal":
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValueError
        else:
            value = str(value)
            if not value or len(value) > param.max_length:
                raise ApiError(422, "validation_error",
                               f"{param.label}: 1-{param.max_length} characters required.")
            return value
    except (TypeError, ValueError, ArithmeticError):
        raise ApiError(422, "validation_error", f"{param.label}: expected a {param.type} value.") from None
    if param.min is not None and value < param.min or param.max is not None and value > param.max:
        raise ApiError(422, "validation_error", f"{param.label}: must be between {param.min} and {param.max}.")
    return value


def uses_params(sql: str) -> bool:
    return "%(" in sql


def render(sql: str, params: dict) -> str:
    """Human-readable SQL with literal values (secrets masked) — for display/logging only."""
    if not uses_params(sql):
        return sql
    shown = {k: ("********" if k in SECRET_PARAMS else v) for k, v in params.items()}
    return sql % {k: escape_item(v, "utf8mb4") for k, v in shown.items()}


# --------------------------------------------------------------------------- sessions
class LabSessions:
    """Opens one private MySQL session per connection key used by a run."""

    def __init__(self, settings: Settings):
        self.s = settings
        self._conns: dict[str, pymysql.Connection] = {}

    def get(self, key: str) -> pymysql.Connection:
        if key not in self._conns:
            self._conns[key] = self._open(key.split("#")[0])
        return self._conns[key]

    def _open(self, account: str) -> pymysql.Connection:
        s = self.s
        accounts = {
            "reader": (s.db_readonly_user, s.db_readonly_password.get_secret_value(), s.db_name),
            "lab": (s.db_lab_user, s.db_lab_password.get_secret_value(), s.lab_db_name),
            "dcl": (s.db_dcl_user, s.db_dcl_password.get_secret_value(), s.lab_db_name),
            # the demo account may have no database privilege at all, so no default schema
            "demo": (DEMO_DCL_USER, _demo_password, None),
        }
        user, password, database = accounts[account]
        conn = pymysql.connect(host=s.db_host, port=s.db_port, user=user, password=password, database=database,
                               charset="utf8mb4", autocommit=True, connect_timeout=5,
                               read_timeout=s.sql_timeout_seconds + 5, write_timeout=s.sql_timeout_seconds + 5)
        with conn.cursor() as cur:
            cur.execute("SET SESSION max_execution_time = %s", (s.sql_timeout_seconds * 1000,))
        return conn

    def close(self) -> None:
        for conn in self._conns.values():
            try:
                conn.close()  # MySQL rolls back any transaction left open
            except Exception:  # noqa: BLE001
                pass
        self._conns.clear()


# --------------------------------------------------------------------------- statement execution
@dataclass
class Outcome:
    result_sets: list[dict] = field(default_factory=list)
    affected_rows: int | None = None
    duration_ms: float = 0.0
    timings_ms: list[float] = field(default_factory=list)

    @property
    def rows_returned(self) -> int:
        return sum(rs["row_count"] for rs in self.result_sets)


def run_statement(conn: pymysql.Connection, sql: str, params: dict | None, max_rows: int) -> Outcome:
    outcome = Outcome()
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, params if params is not None and uses_params(sql) else None)
        outcome.duration_ms = (time.perf_counter() - started) * 1000
        while True:
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows = cur.fetchall()           # buffered cursor: rows already transferred
                outcome.result_sets.append({
                    "columns": columns,
                    "rows": [[to_json(v) for v in row] for row in rows[:max_rows]],
                    "row_count": len(rows),
                    "truncated": len(rows) > max_rows,
                })
            elif cur.rowcount is not None and cur.rowcount >= 0:
                outcome.affected_rows = (outcome.affected_rows or 0) + cur.rowcount
            if not cur.nextset():
                break
    return outcome


def run_timed(conn: pymysql.Connection, sql: str, params: dict | None, max_rows: int, repeat: int) -> Outcome:
    run_statement(conn, sql, params, max_rows)                 # warm-up, not measured
    timings, last = [], None
    for _ in range(repeat):
        last = run_statement(conn, sql, params, max_rows)
        timings.append(round(last.duration_ms, 3))
    last.timings_ms = timings
    last.duration_ms = statistics.median(timings)
    return last


# --------------------------------------------------------------------------- runner
@dataclass
class RunContext:
    user_role: str
    user_id: int | None
    mode: str                  # EXAMPLE | CLEANUP | FREEFORM
    category: str
    example_id: str | None
    target_db: str


def _step_payload(step: Step, display_sql: str, conn_key: str, account_names: dict) -> dict:
    return {"title": step.title, "role": step.role, "sql": display_sql, "connection": conn_key,
            "account": account_names.get(conn_key.split("#")[0], conn_key), "expect_error": step.expect_error,
            "compare": step.compare, "note": step.note, "repeat": step.repeat}


def execute_steps(steps: tuple[Step, ...] | list[Step], default_conn: str, params: dict,
                  ctx: RunContext, settings: Settings | None = None, *, raw: bool = False) -> dict:
    """raw=True (free-form SQL): text is sent exactly as typed, no placeholder handling."""
    s = settings or get_settings()
    bind = None if raw else {**params, "demo_user": DEMO_DCL_USER, "demo_password": _demo_password,
                             "account_host": s.db_account_host}
    account_names = {"reader": s.db_readonly_user, "lab": s.db_lab_user, "dcl": s.db_dcl_user,
                     "demo": DEMO_DCL_USER}
    sessions = LabSessions(s)
    results, logs = [], []
    aborted = False
    started = time.perf_counter()
    try:
        for step in steps:
            conn_key = step.conn or default_conn
            sql = step.sql if raw else step.sql.replace("{lab_db}", s.lab_db_name).replace("{main_db}", s.db_name)
            display = sql if raw else render(sql, bind)
            payload = _step_payload(step, display, conn_key, account_names)
            if aborted:
                results.append({**payload, "status": "not_run"})
                continue
            step_started = time.perf_counter()
            try:
                conn = sessions.get(conn_key)
                outcome = (run_timed(conn, sql, bind, s.sql_max_rows, step.repeat) if step.repeat > 1
                           else run_statement(conn, sql, bind, s.sql_max_rows))
                status = "unexpected_success" if step.expect_error else "success"
                payload.update(status=status, result_sets=outcome.result_sets,
                               affected_rows=outcome.affected_rows, duration_ms=round(outcome.duration_ms, 3),
                               timings_ms=outcome.timings_ms or None, timing_group=step.timing_group)
                logs.append(_log(ctx, display, "SUCCESS", outcome.rows_returned, outcome.affected_rows or 0,
                                 outcome.duration_ms))
            except pymysql.MySQLError as exc:
                errno, message = _mysql_error(exc)
                elapsed = (time.perf_counter() - step_started) * 1000
                if errno in step.ignore_errors:
                    status = "skipped"
                elif step.expect_error:
                    status = "expected_error"
                else:
                    status, aborted = "error", True
                payload.update(status=status, duration_ms=round(elapsed, 3),
                               error={"code": errno, "message": message})
                logs.append(_log(ctx, display, "ERROR", 0, 0, elapsed, errno, message))
            metrics.record_query(f"lab:{conn_key.split('#')[0]}", display, payload["duration_ms"],
                                 current_request_id(), ok=payload["status"] != "error",
                                 slow_threshold_ms=s.slow_query_ms)
            results.append(payload)
    finally:
        sessions.close()
        sql_log.write(logs)

    return {"status": "error" if aborted else "success", "steps": results,
            "total_duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "timing_comparison": _timing_comparison(results)}


def _mysql_error(exc: pymysql.MySQLError) -> tuple[int | None, str]:
    args = getattr(exc, "args", ())
    if len(args) >= 2 and isinstance(args[0], int):
        return args[0], sanitize_message(args[1])
    return None, sanitize_message(str(exc))


def _log(ctx: RunContext, sql: str, status: str, rows: int, affected: int, duration: float,
         errno: int | None = None, message: str | None = None) -> sql_log.LogEntry:
    return sql_log.LogEntry(category=ctx.category, execution_mode=ctx.mode, target_db=ctx.target_db,
                            statement_text=sql, status=status, user_role=ctx.user_role, user_id=ctx.user_id,
                            example_id=ctx.example_id, rows_returned=rows, rows_affected=affected,
                            duration_ms=duration, error_code=errno, error_message=message)


def _timing_comparison(results: list[dict]) -> dict | None:
    groups = {r.get("timing_group"): r for r in results if r.get("timing_group") and r.get("status") == "success"}
    if "before" not in groups or "after" not in groups:
        return None
    before, after = groups["before"]["duration_ms"], groups["after"]["duration_ms"]
    ratio = before / after if after > 0 else None
    if ratio is None:
        verdict = "not measurable"
    elif ratio >= 1.25:
        verdict = f"faster with the index ({ratio:.1f}x lower median)"
    elif ratio <= 0.8:
        verdict = f"slower with the index ({1 / ratio:.1f}x higher median)"
    else:
        verdict = "no meaningful difference measured"
    return {"before_median_ms": before, "after_median_ms": after,
            "before_runs_ms": groups["before"]["timings_ms"], "after_runs_ms": groups["after"]["timings_ms"],
            "speedup": round(ratio, 2) if ratio else None, "verdict": verdict}


def run_example(example: Example, user_role: str, user_id: int, supplied: dict | None, *,
                cleanup: bool = False, confirm: bool = False) -> dict:
    s = get_settings()
    if ROLE_RANK.get(user_role, 0) < ROLE_RANK[example.min_role]:
        raise ApiError(403, "forbidden", f"This example requires the {example.min_role} role.")
    if cleanup and not example.cleanup:
        raise ApiError(409, "no_cleanup", "This example has no cleanup steps.")
    if example.destructive and not cleanup and not confirm:
        raise ApiError(409, "confirmation_required",
                       "This example changes or removes database objects. Confirm to run it.")
    params = coerce_params(example, supplied)
    target_db = s.db_name if example.target == "main" else s.lab_db_name
    ctx = RunContext(user_role, user_id, "CLEANUP" if cleanup else "EXAMPLE", example.category, example.id, target_db)
    outcome = execute_steps(example.cleanup if cleanup else example.steps, example.account, params, ctx, s)
    return {"example_id": example.id, "title": example.title, "category": example.category,
            "mode": ctx.mode, "database": target_db, "account": {"reader": s.db_readonly_user,
                                                                 "lab": s.db_lab_user,
                                                                 "dcl": s.db_dcl_user}[example.account],
            "explanation": example.explanation, "params": {k: to_json(v) for k, v in params.items()},
            "request_id": current_request_id(), **outcome}


# --------------------------------------------------------------------------- lab reset
_reset_lock = threading.Lock()


def reset_lab(user_role: str, user_id: int) -> dict:
    from app.db.engines import lab_engine
    from app.db.initializer import rebuild_lab

    s = get_settings()
    if not _reset_lock.acquire(blocking=False):
        raise ApiError(409, "reset_in_progress", "A lab reset is already running.")
    started = time.perf_counter()
    try:
        rebuild_lab(s, s.lab_db_name, s.lab_bulk_students)
        lab_engine().dispose()   # pooled sessions pointed at the dropped schema
        status, error = "SUCCESS", None
    except Exception as exc:  # noqa: BLE001
        status, error = "ERROR", sanitize_message(str(exc))
    finally:
        _reset_lock.release()
    duration = (time.perf_counter() - started) * 1000
    sql_log.write([sql_log.LogEntry(category="LAB", execution_mode="RESET", target_db=s.lab_db_name,
                                    statement_text="rebuild lab database from database/*.sql",
                                    status=status, user_role=user_role, user_id=user_id, duration_ms=duration,
                                    error_message=error)])
    if error:
        raise ApiError(500, "reset_failed", f"Lab reset failed: {error}")
    return {"status": "reset", "database": s.lab_db_name, "bulk_students": s.lab_bulk_students,
            "duration_ms": round(duration, 1)}


def run_freeform(sql: str, user_role: str, user_id: int, *, confirm: bool) -> dict:
    from app.services.lab import policy

    s = get_settings()
    if user_role != "ADMIN":
        raise ApiError(403, "forbidden", "Free-form lab SQL is available to administrators only.")
    try:
        checked = policy.check(sql, s)
    except ApiError as exc:
        sql_log.write([sql_log.LogEntry(category="FREEFORM", execution_mode="FREEFORM", target_db=s.lab_db_name,
                                        statement_text=sql, status="REJECTED", user_role=user_role,
                                        user_id=user_id, error_message=exc.message)])
        raise
    if checked.destructive and not confirm:
        raise ApiError(409, "confirmation_required",
                       "These statements modify or remove data/objects in the lab database. Confirm to run them.",
                       {"statements": checked.destructive})
    steps = [Step(f"Statement {i}", text) for i, text in enumerate(checked.statements, start=1)]
    ctx = RunContext(user_role, user_id, "FREEFORM", "FREEFORM", None, s.lab_db_name)
    outcome = execute_steps(steps, "lab", {}, ctx, s, raw=True)
    return {"example_id": None, "title": "Free-form SQL", "category": "FREEFORM", "mode": "FREEFORM",
            "database": s.lab_db_name, "account": s.db_lab_user,
            "explanation": "Executed statement by statement in one lab session. A transaction left open is "
                           "rolled back when the session closes.",
            "params": {}, "request_id": current_request_id(), **outcome}
