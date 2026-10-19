"""Initialise MySQL for OEMS.

    python scripts/init_db.py            # create everything that is missing
    python scripts/init_db.py --reset    # drop and rebuild both databases (asks first)

Steps
  1. check the server version (8.0.16+) and allow routine creation by non-SUPER accounts
  2. create the databases  <DB_NAME> (application) and <LAB_DB_NAME> (disposable lab)
  3. create the least-privilege MySQL accounts and grant their privileges
  4. migrate the main database with Alembic (schema, indexes, views, routines, triggers)
  5. seed core data + synthetic bulk data
  6. build the lab database with the lab account itself
  7. verify that every API account can connect

Uses the administrator credentials (MYSQL_ADMIN_USER / MYSQL_ADMIN_PASSWORD)
from .env. They are needed only here, never by the running API.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import initializer as init  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialise the OEMS MySQL databases.")
    parser.add_argument("--reset", action="store_true", help="drop and recreate both databases")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation with --reset")
    parser.add_argument("--bulk", type=int, default=None, help="synthetic students for the main database")
    parser.add_argument("--lab-bulk", type=int, default=None, help="synthetic students for the lab database")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    bulk = s.bulk_students if args.bulk is None else args.bulk
    lab_bulk = s.lab_bulk_students if args.lab_bulk is None else args.lab_bulk

    if args.reset and not args.yes:
        answer = input(f"This DROPS `{s.db_name}` and `{s.lab_db_name}` and all their data. Type 'yes': ")
        if answer.strip().lower() != "yes":
            print("Aborted.")
            return 1

    try:
        admin = init.admin_connect(s)
    except pymysql.MySQLError as exc:
        print(f"[x] Cannot connect as administrator '{s.mysql_admin_user}' at {s.db_host}:{s.db_port}: "
              f"{exc.args[-1]}\n    Check MYSQL_ADMIN_USER / MYSQL_ADMIN_PASSWORD / DB_HOST in .env "
              "and that the MySQL service is running.")
        return 2

    try:
        version = init.check_server(admin)
        print(f"[1/7] MySQL {version}")
        init.allow_routine_creation(admin)

        main_exists = init.database_has_tables(admin, s.db_name)
        init.create_database(admin, s.db_name, drop_first=args.reset)
        init.create_database(admin, s.lab_db_name, drop_first=args.reset)
        print(f"[2/7] databases `{s.db_name}` and `{s.lab_db_name}` ready")

        init.create_accounts(admin, s, [s.db_name], [s.lab_db_name])
        print(f"[3/7] accounts {s.db_app_user}, {s.db_readonly_user}, {s.db_lab_user}, {s.db_dcl_user} "
              f"@'{s.db_account_host}' granted")
    finally:
        admin.close()

    init.migrate_main(s, s.db_name)
    admin = init.admin_connect(s)
    try:
        init.grant_routine_privileges(admin, s, s.db_name)
    finally:
        admin.close()
    print("[4/7] Alembic migration applied (alembic upgrade head); routine grants added")

    if main_exists and not args.reset:
        print("[5/7] main database already has data — seed skipped (use --reset to rebuild)")
    else:
        init.seed_main(s, s.db_name, bulk)
        print(f"[5/7] seeded core data + {bulk} synthetic students")

    init.rebuild_lab(s, s.lab_db_name, lab_bulk)
    print(f"[6/7] lab database rebuilt by '{s.db_lab_user}' with {lab_bulk} synthetic students")

    status = init.verify_accounts(s)
    failures = {user: err for user, err in status.items() if err != "ok"}
    if failures:
        print("[x] some accounts cannot connect:")
        for user, err in failures.items():
            print(f"    {user}: {err}")
        print("    If the error says 'Access denied' for a TCP connection, set DB_ACCOUNT_HOST=% in .env "
              "and run this script again.")
        return 3
    print("[7/7] all API accounts connect successfully — OEMS database is ready.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except init.ScriptError as exc:
        print(f"[x] SQL error: {exc}")
        sys.exit(4)
