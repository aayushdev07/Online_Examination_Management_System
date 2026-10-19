"""Database engines — one per MySQL account, each with least privilege.

    app     : oems_app    -> normal application work (ORM) + metadata inspection
    reader  : oems_reader -> SELECT-only on the main database (reports, DQL demos, data viewer)
    lab     : oems_lab    -> full rights, but only on the disposable lab database

The frontend never connects to MySQL; only these server-side engines do.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from functools import lru_cache

import pymysql
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.context import current_request_id
from app.core.metrics import metrics


def mysql_url(user: str, password: str, database: str | None, settings: Settings) -> URL:
    return URL.create("mysql+pymysql", username=user, password=password,
                      host=settings.db_host, port=settings.db_port, database=database,
                      query={"charset": "utf8mb4"})


def _instrument(engine: Engine, source: str, slow_ms: float) -> None:
    """Measure every statement executed through this engine."""

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        started = conn.info["_query_start"].pop()
        metrics.record_query(source, statement, (time.perf_counter() - started) * 1000,
                             current_request_id(), slow_threshold_ms=slow_ms)

    @event.listens_for(engine, "handle_error")
    def _error(ctx):
        stack = ctx.connection.info.get("_query_start") if ctx.connection is not None else None
        started = stack.pop() if stack else None
        duration = (time.perf_counter() - started) * 1000 if started else 0.0
        metrics.record_query(source, ctx.statement or "", duration, current_request_id(), ok=False,
                             error=str(getattr(ctx.original_exception, "args", [""])[-1])[:200],
                             slow_threshold_ms=slow_ms)


def _build(user: str, password: str, database: str, settings: Settings, source: str,
           pool_size: int, max_overflow: int) -> Engine:
    engine = create_engine(
        mysql_url(user, password, database, settings),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=10,
        connect_args={"connect_timeout": 5, "read_timeout": settings.sql_timeout_seconds + 20,
                      "write_timeout": 30},
    )
    _instrument(engine, source, settings.slow_query_ms)
    return engine


@lru_cache
def app_engine() -> Engine:
    s = get_settings()
    return _build(s.db_app_user, s.db_app_password.get_secret_value(), s.db_name, s, "app", 10, 10)


@lru_cache
def reader_engine() -> Engine:
    s = get_settings()
    return _build(s.db_readonly_user, s.db_readonly_password.get_secret_value(), s.db_name, s, "reader", 5, 5)


@lru_cache
def lab_engine() -> Engine:
    s = get_settings()
    return _build(s.db_lab_user, s.db_lab_password.get_secret_value(), s.lab_db_name, s, "lab", 3, 3)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=app_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


def dispose_all() -> None:
    for factory in (app_engine, reader_engine, lab_engine):
        if factory.cache_info().currsize:
            factory().dispose()


def raw_connection(role: str, *, autocommit: bool = True, database: str | None = None) -> pymysql.Connection:
    """A fresh, un-pooled PyMySQL connection for the SQL lab executor.

    Lab demonstrations change session state (transactions, variables), so they
    get a private connection that is closed afterwards instead of a pooled one.
    """
    s = get_settings()
    accounts = {
        "reader": (s.db_readonly_user, s.db_readonly_password.get_secret_value(), s.db_name),
        "lab": (s.db_lab_user, s.db_lab_password.get_secret_value(), s.lab_db_name),
        "dcl": (s.db_dcl_user, s.db_dcl_password.get_secret_value(), s.lab_db_name),
    }
    user, password, default_db = accounts[role]
    return pymysql.connect(
        host=s.db_host, port=s.db_port, user=user, password=password,
        database=database if database is not None else default_db,
        charset="utf8mb4", autocommit=autocommit,
        connect_timeout=5, read_timeout=s.sql_timeout_seconds + 5, write_timeout=s.sql_timeout_seconds + 5,
        client_flag=0,  # no CLIENT.MULTI_STATEMENTS: one statement per execute()
    )
