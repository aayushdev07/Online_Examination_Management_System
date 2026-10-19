"""Alembic environment.

Migrations are written as SQL (the schema uses CHECK constraints, triggers and
stored programs that autogenerate cannot express), so no target metadata is
compared. The URL comes from `config.attributes["url"]` (set by init_db.py) or
from the administrator settings in .env when running `alembic upgrade head`.
"""

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.engines import mysql_url  # noqa: E402

config = context.config
target_metadata = None


def _url():
    url = config.attributes.get("url")
    if url is not None:
        return url
    s = get_settings()
    return mysql_url(s.mysql_admin_user, s.mysql_admin_password.get_secret_value(), s.db_name, s)


def run_migrations_offline() -> None:
    context.configure(url=_url().render_as_string(hide_password=True), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
