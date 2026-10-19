"""Server-side policy for free-form SQL in the lab ("lab mode").

Defence in depth — none of these checks is the security boundary on its own:
  1. free-form mode must be enabled in .env and is ADMIN-only;
  2. statements are tokenized (quotes and comments respected), so the policy
     sees every statement, not just the first keyword of the text;
  3. account-management, server-administration, file and session-escape
     statements are refused, as are references to system or other schemas;
  4. destructive statements need explicit confirmation;
  5. everything runs as the lab account, whose MySQL privileges are limited
     to the disposable lab database — the real boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.sql_script import split_statements

MAX_SQL_CHARS = 10_000
MAX_STATEMENTS = 20

ALLOWED_FIRST = {
    "SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "RENAME", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "START", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT",
    "RELEASE", "CALL", "SET", "ANALYZE", "TABLE", "VALUES",
}
DESTRUCTIVE_FIRST = {"DROP", "TRUNCATE", "DELETE", "UPDATE", "ALTER", "RENAME", "REPLACE"}
STORED_PROGRAM = re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION|TRIGGER)\b", re.IGNORECASE)

# (pattern, reason) checked against each statement with string literals removed
FORBIDDEN = [
    (r"\b(GRANT|REVOKE)\b", "privilege changes are only available through the DCL examples"),
    (r"\b(CREATE|DROP|ALTER|RENAME)\s+(USER|ROLE)\b", "account management is not allowed"),
    (r"\bSET\s+(PASSWORD|ROLE|DEFAULT\s+ROLE)\b", "account management is not allowed"),
    (r"\b(CREATE|DROP|ALTER)\s+(DATABASE|SCHEMA|SERVER|TABLESPACE|EVENT|SPATIAL)\b",
     "only objects inside the lab database may be managed"),
    (r"\bDEFINER\s*=", "DEFINER clauses are not allowed"),
    (r"\bSET\s+(@@|GLOBAL\b|PERSIST\b|PERSIST_ONLY\b|SESSION\b|LOCAL\b)", "server/session variables cannot be changed"),
    (r"\bINTO\s+(OUT|DUMP)FILE\b", "writing files is not allowed"),
    (r"\b(LOAD_FILE|SLEEP|BENCHMARK|GET_LOCK|RELEASE_ALL_LOCKS|SYS_EVAL|SYS_EXEC)\s*\(",
     "this function is not allowed"),
    (r"\bLOAD\s+(DATA|XML)\b", "file import is not allowed"),
    (r"\b(LOCK|UNLOCK)\s+(TABLES?|INSTANCE)\b", "table locks are not allowed"),
]


@dataclass
class PolicyResult:
    statements: list[str]
    destructive: list[str]


def _strip_literals(sql: str) -> str:
    # remove '...' and "..." literals so their content cannot trigger (or hide) keywords
    return re.sub(r"'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\"", "''", sql)


def _schema_refs(sql: str) -> set[str]:
    refs = set()
    for match in re.finditer(r"(`?)([A-Za-z0-9_$]+)\1\s*\.\s*`?[A-Za-z0-9_$*]", sql):
        refs.add(match.group(2).lower())
    return refs


def check(sql: str, settings: Settings) -> PolicyResult:
    if not settings.sql_freeform_enabled:
        raise ApiError(403, "freeform_disabled",
                       "Free-form SQL is disabled. Set SQL_FREEFORM_ENABLED=true in .env to enable lab mode.")
    if len(sql) > MAX_SQL_CHARS:
        raise ApiError(413, "sql_too_long", f"SQL text is limited to {MAX_SQL_CHARS} characters.")

    if STORED_PROGRAM.match(sql):
        # a stored program body contains ';' — accept it as exactly one statement
        statements = [sql.strip().rstrip(";").strip()]
    else:
        try:
            statements = [s.sql for s in split_statements(sql, allow_delimiter_command=False)]
        except ValueError as exc:
            raise ApiError(422, "sql_parse_error", str(exc)) from None
    if not statements:
        raise ApiError(422, "empty_sql", "Enter at least one SQL statement.")
    if len(statements) > MAX_STATEMENTS:
        raise ApiError(422, "too_many_statements", f"At most {MAX_STATEMENTS} statements per run.")

    forbidden_schemas = {"mysql", "information_schema", "performance_schema", "sys", settings.db_name.lower()}
    destructive = []
    for statement in statements:
        bare = _strip_literals(statement)
        words = re.findall(r"[A-Za-z_]+", bare[:100])
        first = words[0].upper() if words else ""
        if first not in ALLOWED_FIRST:
            raise ApiError(422, "statement_not_allowed", f"'{first or statement[:20]}' statements are not allowed in lab mode.")
        if first == "SET" and not re.match(r"^\s*SET\s+@[A-Za-z0-9_]", bare, re.IGNORECASE):
            raise ApiError(422, "statement_not_allowed", "Only user variables (SET @name = ...) may be set.")
        for pattern, reason in FORBIDDEN:
            if re.search(pattern, bare, re.IGNORECASE | re.DOTALL):
                raise ApiError(422, "statement_not_allowed", f"Rejected: {reason}.")
        blocked = _schema_refs(bare) & forbidden_schemas
        if blocked:
            raise ApiError(422, "schema_not_allowed",
                           f"Lab mode may only use the lab database (`{settings.lab_db_name}`); "
                           f"references to {', '.join(sorted(blocked))} are refused.")
        if first in DESTRUCTIVE_FIRST:
            destructive.append(statement[:80])
    return PolicyResult(statements, destructive)
