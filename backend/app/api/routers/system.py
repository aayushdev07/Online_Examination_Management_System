"""Health check and monitoring endpoints (all values are measured, none simulated)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import CurrentUser, require_staff
from app.core.config import get_settings
from app.core.errors import mysql_error_parts
from app.core.metrics import metrics
from app.db.engines import app_engine, lab_engine, reader_engine

router = APIRouter(prefix="/api", tags=["system"])

STATUS_VARIABLES = ("Uptime", "Threads_connected", "Threads_running", "Questions", "Slow_queries",
                    "Com_select", "Com_insert", "Com_update", "Com_delete", "Com_commit", "Com_rollback",
                    "Innodb_row_lock_waits", "Innodb_buffer_pool_read_requests", "Innodb_buffer_pool_reads",
                    "Aborted_connects", "Max_used_connections")


def _probe(engine) -> dict:
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
        return {"status": "up", "latency_ms": round((time.perf_counter() - started) * 1000, 3), "version": version}
    except DBAPIError as exc:
        errno, message = mysql_error_parts(exc)
        return {"status": "down", "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": {"code": errno, "message": message}}


@router.get("/health")
def health():
    """Liveness + a real round trip to MySQL. 503 when the database is unreachable."""
    db = _probe(app_engine())
    body = {"status": "ok" if db["status"] == "up" else "degraded", "api": "up", "database": db,
            "environment": get_settings().app_env}
    return JSONResponse(body, status_code=200 if db["status"] == "up" else 503)


def _pool(engine) -> dict:
    pool = engine.pool
    return {"size": pool.size(), "checked_out": pool.checkedout(), "checked_in": pool.checkedin(),
            "overflow": max(0, pool.overflow()), "max_overflow": getattr(pool, "_max_overflow", None),
            "status": pool.status()}


@router.get("/metrics")
def api_metrics(_: CurrentUser = Depends(require_staff)):
    snapshot = metrics.snapshot()
    snapshot["pools"] = {"app": _pool(app_engine()), "reader": _pool(reader_engine()), "lab": _pool(lab_engine())}
    try:
        with app_engine().connect() as conn:
            attempts = conn.execute(text("SELECT status, COUNT(*) AS n FROM attempt GROUP BY status")).all()
            lab_log = conn.execute(text(
                "SELECT COUNT(*) AS executions, SUM(status = 'ERROR') AS errors, SUM(status = 'REJECTED') AS rejected, "
                "ROUND(AVG(duration_ms), 3) AS avg_ms, MAX(duration_ms) AS max_ms FROM sql_execution_log")).mappings().one()
            slow = conn.execute(text(
                "SELECT log_id, execution_mode, category, LEFT(statement_text, 200) AS statement, duration_ms, "
                "status, executed_at FROM sql_execution_log ORDER BY duration_ms DESC LIMIT 10")).mappings().all()
        snapshot["exam_activity"] = {row[0]: row[1] for row in attempts}
        snapshot["sql_lab"] = {**lab_log, "slowest": slow}
    except DBAPIError as exc:
        snapshot["exam_activity"] = None
        snapshot["sql_lab"] = {"error": mysql_error_parts(exc)[1]}
    return snapshot


@router.get("/db/metrics")
def db_metrics(_: CurrentUser = Depends(require_staff)):
    s = get_settings()
    probes = {"app": _probe(app_engine()), "reader": _probe(reader_engine()), "lab": _probe(lab_engine())}
    server, tables = {}, []
    try:
        with app_engine().connect() as conn:
            placeholders = ", ".join(f":v{i}" for i in range(len(STATUS_VARIABLES)))
            rows = conn.execute(text(f"SHOW GLOBAL STATUS WHERE Variable_name IN ({placeholders})"),
                                {f"v{i}": v for i, v in enumerate(STATUS_VARIABLES)}).all()
            server = {name: value for name, value in rows}
            conn.execute(text("SET SESSION information_schema_stats_expiry = 0"))
            tables = conn.execute(text(
                "SELECT TABLE_NAME AS name, TABLE_ROWS AS approx_rows, DATA_LENGTH AS data_bytes, "
                "INDEX_LENGTH AS index_bytes FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :db AND TABLE_TYPE = 'BASE TABLE' ORDER BY DATA_LENGTH DESC"),
                {"db": s.db_name}).mappings().all()
    except DBAPIError as exc:
        server = {"error": mysql_error_parts(exc)[1]}
    reads, requests = int(server.get("Innodb_buffer_pool_reads", 0) or 0), \
        int(server.get("Innodb_buffer_pool_read_requests", 0) or 0)
    return {"connectivity": probes,
            "pools": {"app": _pool(app_engine()), "reader": _pool(reader_engine()), "lab": _pool(lab_engine())},
            "server_status": server,
            "buffer_pool_hit_rate": round(100 * (1 - reads / requests), 3) if requests else None,
            "tables": tables}
