"""Initial OEMS schema: tables, indexes, views, routines, triggers, seed utilities.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-20

The SQL files in /database are the single source of truth; this migration
applies them in dependency order. MySQL DDL causes implicit commits, so a
failed upgrade must be cleaned up by dropping and recreating the database
(`python scripts/init_db.py --reset`).
"""

from alembic import op

from app.core.config import DATABASE_DIR
from app.db.sql_script import load_script

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

FILES = ["schema.sql", "indexes.sql", "views.sql", "procedures.sql", "triggers.sql", "seed_procedures.sql"]

DROP_ORDER = [
    "DROP PROCEDURE IF EXISTS sp_generate_bulk_data",
    "DROP PROCEDURE IF EXISTS sp_seed_exam_attempts",
    "DROP PROCEDURE IF EXISTS sp_finalize_attempt",
    "DROP PROCEDURE IF EXISTS sp_exam_attempt_stats",
    "DROP PROCEDURE IF EXISTS GetStudentResults",
    "DROP PROCEDURE IF EXISTS GetExamDetails",
    "DROP FUNCTION IF EXISTS fn_result_status",
    "DROP FUNCTION IF EXISTS fn_marks_percentage",
    "DROP VIEW IF EXISTS exam_performance_view",
    "DROP VIEW IF EXISTS student_result_view",
    "DROP VIEW IF EXISTS exam_overview",
    "DROP TABLE IF EXISTS sql_execution_log",
    "DROP TABLE IF EXISTS exam_audit",
    "DROP TABLE IF EXISTS result",
    "DROP TABLE IF EXISTS answer",
    "DROP TABLE IF EXISTS attempt",
    "DROP TABLE IF EXISTS exam_question",
    "DROP TABLE IF EXISTS question",
    "DROP TABLE IF EXISTS exam",
    "DROP TABLE IF EXISTS faculty_admin",
    "DROP TABLE IF EXISTS student",
]


def _execute_raw(sql: str) -> None:
    # go through the DBAPI cursor so '%' and ':' in SQL bodies are not treated as parameters
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def upgrade() -> None:
    for name in FILES:
        for statement in load_script(DATABASE_DIR / name):
            _execute_raw(statement.sql)


def downgrade() -> None:
    for sql in DROP_ORDER:  # triggers are dropped together with their tables
        _execute_raw(sql)
