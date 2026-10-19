"""Test fixtures.

The suite runs against a REAL MySQL server, in two dedicated databases that are
created and dropped by the suite itself:  oems_test  and  oems_lab_test.
It never touches the development databases. MySQL behaviour (triggers, stored
programs, DDL, privileges) is not emulated with SQLite.

Requirements: the administrator credentials in .env (MYSQL_ADMIN_USER /
MYSQL_ADMIN_PASSWORD). If MySQL is unreachable the whole suite is SKIPPED with
the reason — never reported as passed.
"""

from __future__ import annotations

import os

# --- must happen before any app module reads the settings ---------------------
os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "oems_test")
os.environ["LAB_DB_NAME"] = os.environ.get("TEST_LAB_DB_NAME", "oems_lab_test")
os.environ["BULK_STUDENTS"] = "300"
os.environ["LAB_BULK_STUDENTS"] = "300"
os.environ["SQL_FREEFORM_ENABLED"] = "true"
os.environ["SQL_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["LOG_LEVEL"] = "WARNING"

import pymysql  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import initializer as init  # noqa: E402

PASSWORD = "Password@123"


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def test_databases(settings):
    assert settings.db_name != "oems_db" and settings.lab_db_name != "oems_lab", "refusing to use dev databases"
    try:
        admin = init.admin_connect(settings)
    except pymysql.MySQLError as exc:
        pytest.skip(f"MySQL not reachable with the administrator account: {exc.args[-1]}")
    try:
        init.check_server(admin)
        init.allow_routine_creation(admin)
        init.create_database(admin, settings.db_name, drop_first=True)
        init.create_database(admin, settings.lab_db_name, drop_first=True)
        init.create_accounts(admin, settings, [settings.db_name], [settings.lab_db_name])
    finally:
        admin.close()
    init.migrate_main(settings, settings.db_name)
    admin = init.admin_connect(settings)
    try:
        init.grant_routine_privileges(admin, settings, settings.db_name)
    finally:
        admin.close()
    init.seed_main(settings, settings.db_name, settings.bulk_students)
    init.rebuild_lab(settings, settings.lab_db_name, settings.lab_bulk_students)
    yield
    from app.db.engines import dispose_all

    dispose_all()
    admin = init.admin_connect(settings)
    try:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{settings.db_name}`")
            cur.execute(f"DROP DATABASE IF EXISTS `{settings.lab_db_name}`")
    finally:
        admin.close()


@pytest.fixture(scope="session")
def client(test_databases):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client, username, account_type):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD,
                                             "account_type": account_type})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_h(client):
    return _login(client, "admin", "STAFF")


@pytest.fixture(scope="session")
def faculty_h(client):
    return _login(client, "rdeshpande", "STAFF")


@pytest.fixture(scope="session")
def student_h(client):
    return _login(client, "aarav.shah", "STUDENT")


@pytest.fixture()
def admin_db(settings):
    """Administrator connection to the test database (autocommit)."""
    conn = init.admin_connect(settings, settings.db_name)
    yield conn
    conn.close()


def connect_as(settings, account: str, database: str | None = None, autocommit: bool = True):
    users = {"app": (settings.db_app_user, settings.db_app_password),
             "reader": (settings.db_readonly_user, settings.db_readonly_password),
             "lab": (settings.db_lab_user, settings.db_lab_password)}
    user, password = users[account]
    return init.connect(settings, user, password.get_secret_value(), database or settings.db_name, autocommit)


def scalar(conn, sql, args=None):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def mysql_errno(excinfo) -> int:
    return excinfo.value.args[0]
