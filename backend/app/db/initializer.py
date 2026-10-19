"""Database bootstrap: server settings, databases, MySQL accounts, schema and seed data.

Used by scripts/init_db.py, the lab reset endpoint and the test suite.
The administrator account is only ever used here — never by request handlers.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pymysql

from app.core.config import DATABASE_DIR, PROJECT_ROOT, Settings
from app.db.sql_script import load_script

log = logging.getLogger("oems.init")

# Order matters: functions before the triggers/views that use them,
# seed utilities after the triggers they rely on.
OBJECT_FILES = ["schema.sql", "indexes.sql", "views.sql", "procedures.sql", "triggers.sql", "seed_procedures.sql"]
SEED_FILE = "seed.sql"
DEMO_DCL_USER = "oems_demo_ro"
MIN_MYSQL = (8, 0, 16)


class ScriptError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# connections and script execution
# ---------------------------------------------------------------------------
def connect(settings: Settings, user: str, password: str, database: str | None = None,
            autocommit: bool = True) -> pymysql.Connection:
    return pymysql.connect(host=settings.db_host, port=settings.db_port, user=user, password=password,
                           database=database, charset="utf8mb4", autocommit=autocommit,
                           connect_timeout=10, read_timeout=600)


def admin_connect(settings: Settings, database: str | None = None) -> pymysql.Connection:
    return connect(settings, settings.mysql_admin_user, settings.mysql_admin_password.get_secret_value(), database)


def lab_connect(settings: Settings, database: str | None = None) -> pymysql.Connection:
    return connect(settings, settings.db_lab_user, settings.db_lab_password.get_secret_value(), database)


def run_script(conn: pymysql.Connection, path: Path) -> int:
    """Execute every statement in a .sql file (DELIMITER-aware). Returns the statement count."""
    statements = load_script(path)
    with conn.cursor() as cur:
        for stmt in statements:
            try:
                cur.execute(stmt.sql)
                while cur.nextset():  # drain result sets produced by CALL
                    pass
            except pymysql.MySQLError as exc:
                raise ScriptError(f"{path.name} line {stmt.line}: {exc.args[-1]}") from exc
    return len(statements)


def run_object_files(conn: pymysql.Connection, files: list[str] | None = None) -> None:
    for name in files or OBJECT_FILES:
        count = run_script(conn, DATABASE_DIR / name)
        log.info("applied %s (%d statements)", name, count)


def seed(conn: pymysql.Connection, bulk_students: int) -> None:
    run_script(conn, DATABASE_DIR / SEED_FILE)
    if bulk_students > 0:
        started = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute("CALL sp_generate_bulk_data(%s)", (bulk_students,))
        log.info("generated %d bulk students in %.1f s", bulk_students, time.perf_counter() - started)


def _quote_ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"unsafe identifier: {name!r}")
    return f"`{name}`"


# ---------------------------------------------------------------------------
# server, databases and accounts (administrator)
# ---------------------------------------------------------------------------
def check_server(conn: pymysql.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
    numbers = tuple(int("".join(ch for ch in part if ch.isdigit()) or 0) for part in version.split("-")[0].split(".")[:3])
    if numbers < MIN_MYSQL:
        raise ScriptError(f"MySQL {version} found; OEMS needs 8.0.16 or later (CHECK constraints).")
    return version


def allow_routine_creation(conn: pymysql.Connection) -> None:
    """With binary logging on, non-SUPER accounts (the lab account) may only create
    functions/triggers when log_bin_trust_function_creators = 1."""
    with conn.cursor() as cur:
        cur.execute("SELECT @@log_bin, @@log_bin_trust_function_creators")
        log_bin, trusted = cur.fetchone()
        if not log_bin or trusted:
            return
        try:
            cur.execute("SET PERSIST log_bin_trust_function_creators = 1")
        except pymysql.MySQLError:
            cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
        log.info("enabled log_bin_trust_function_creators")


def create_database(conn: pymysql.Connection, name: str, drop_first: bool = False) -> None:
    with conn.cursor() as cur:
        if drop_first:
            cur.execute(f"DROP DATABASE IF EXISTS {_quote_ident(name)}")
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {_quote_ident(name)} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")


def database_has_tables(conn: pymysql.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s", (name,))
        return cur.fetchone()[0] > 0


def create_accounts(conn: pymysql.Connection, settings: Settings,
                    main_dbs: list[str], lab_dbs: list[str]) -> None:
    host = settings.db_account_host
    accounts = {
        settings.db_app_user: settings.db_app_password.get_secret_value(),
        settings.db_readonly_user: settings.db_readonly_password.get_secret_value(),
        settings.db_lab_user: settings.db_lab_password.get_secret_value(),
        settings.db_dcl_user: settings.db_dcl_password.get_secret_value(),
    }
    with conn.cursor() as cur:
        for user, password in accounts.items():
            cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (user, host, password))
            cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (user, host, password))  # keep in sync with .env

        def grant(privileges: str, scope: str, user: str, suffix: str = "") -> None:
            cur.execute(f"GRANT {privileges} ON {scope} TO %s@%s{suffix}", (user, host))

        for db in main_dbs:
            scope = f"{_quote_ident(db)}.*"
            # application: data access + routines + metadata (SHOW VIEW / TRIGGER let it *read* definitions)
            grant("SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW, TRIGGER", scope, settings.db_app_user)
            # reader: SELECT only — any write attempted through it is rejected by MySQL itself
            grant("SELECT", scope, settings.db_readonly_user)
        for db in lab_dbs:
            scope = f"{_quote_ident(db)}.*"
            grant("ALL PRIVILEGES", scope, settings.db_lab_user)
            grant("ALL PRIVILEGES", scope, settings.db_dcl_user, " WITH GRANT OPTION")
        grant("CREATE USER", "*.*", settings.db_dcl_user)
        try:
            # lets the app read stored-program bodies for the schema explorer (MySQL 8.0.20+)
            grant("SHOW_ROUTINE", "*.*", settings.db_app_user)
        except pymysql.MySQLError as exc:
            log.warning("SHOW_ROUTINE not granted (%s); routine bodies will show as hidden", exc.args[-1])


READ_ONLY_ROUTINES = [("FUNCTION", "fn_marks_percentage"), ("FUNCTION", "fn_result_status"),
                      ("PROCEDURE", "GetExamDetails"), ("PROCEDURE", "GetStudentResults"),
                      ("PROCEDURE", "sp_exam_attempt_stats")]


def grant_routine_privileges(conn: pymysql.Connection, settings: Settings, database: str) -> None:
    """Routine-level grants for the read-only account. The routines are SQL SECURITY
    INVOKER, so they run with the reader's own SELECT-only privileges."""
    with conn.cursor() as cur:
        for kind, name in READ_ONLY_ROUTINES:
            cur.execute(f"GRANT EXECUTE ON {kind} {_quote_ident(database)}.{_quote_ident(name)} TO %s@%s",
                        (settings.db_readonly_user, settings.db_account_host))


# ---------------------------------------------------------------------------
# main database (Alembic) and lab database (disposable)
# ---------------------------------------------------------------------------
def migrate_main(settings: Settings, database: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.db.engines import mysql_url

    cfg = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "backend" / "alembic"))
    cfg.attributes["url"] = mysql_url(settings.mysql_admin_user,
                                      settings.mysql_admin_password.get_secret_value(), database, settings)
    command.upgrade(cfg, "head")


def seed_main(settings: Settings, database: str, bulk_students: int) -> None:
    conn = admin_connect(settings, database)
    try:
        seed(conn, bulk_students)
    finally:
        conn.close()


def rebuild_lab(settings: Settings, database: str, bulk_students: int) -> None:
    """Drop and rebuild the lab database using ONLY the lab account's own privileges."""
    conn = lab_connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {_quote_ident(database)}")
            cur.execute(f"CREATE DATABASE {_quote_ident(database)} "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            cur.execute(f"USE {_quote_ident(database)}")
        run_object_files(conn)
        seed(conn, bulk_students)
    finally:
        conn.close()
    drop_demo_dcl_user(settings)


def drop_demo_dcl_user(settings: Settings) -> None:
    conn = connect(settings, settings.db_dcl_user, settings.db_dcl_password.get_secret_value())
    try:
        with conn.cursor() as cur:
            cur.execute("DROP USER IF EXISTS %s@%s", (DEMO_DCL_USER, settings.db_account_host))
    finally:
        conn.close()


def verify_accounts(settings: Settings) -> dict[str, str]:
    """Connect with every API account; returns {account: 'ok' | error}."""
    checks = {
        settings.db_app_user: (settings.db_app_password, settings.db_name),
        settings.db_readonly_user: (settings.db_readonly_password, settings.db_name),
        settings.db_lab_user: (settings.db_lab_password, settings.lab_db_name),
        settings.db_dcl_user: (settings.db_dcl_password, settings.lab_db_name),
    }
    status = {}
    for user, (password, db) in checks.items():
        try:
            connect(settings, user, password.get_secret_value(), db).close()
            status[user] = "ok"
        except pymysql.MySQLError as exc:
            status[user] = str(exc.args[-1])
    return status
