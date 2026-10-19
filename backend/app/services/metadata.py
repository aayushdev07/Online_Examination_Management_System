"""Live database-object inspection through information_schema."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.engines import app_engine, lab_engine, reader_engine


def resolve(database: str) -> tuple[str, Engine, Engine]:
    """Map 'main' / 'lab' to (schema name, metadata engine, data engine)."""
    s = get_settings()
    if database == "main":
        return s.db_name, app_engine(), reader_engine()
    if database == "lab":
        return s.lab_db_name, lab_engine(), lab_engine()
    raise ApiError(422, "validation_error", "database must be 'main' or 'lab'")


def quote_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _rows(conn, sql: str, **params) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def schema(database: str) -> dict:
    db, engine, _ = resolve(database)
    with engine.connect() as conn:
        conn.execute(text("SET SESSION information_schema_stats_expiry = 0"))
        tables = _rows(conn, """
            SELECT TABLE_NAME AS name, TABLE_TYPE AS type, ENGINE AS engine, DATA_LENGTH AS data_bytes,
                   INDEX_LENGTH AS index_bytes, AUTO_INCREMENT AS auto_increment, TABLE_COLLATION AS collation
              FROM information_schema.TABLES WHERE TABLE_SCHEMA = :db ORDER BY TABLE_TYPE, TABLE_NAME""", db=db)
        columns = _rows(conn, """
            SELECT TABLE_NAME AS table_name, COLUMN_NAME AS name, ORDINAL_POSITION AS position,
                   COLUMN_TYPE AS type, IS_NULLABLE = 'YES' AS nullable, COLUMN_DEFAULT AS default_value,
                   COLUMN_KEY AS column_key, EXTRA AS extra
              FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :db
             ORDER BY TABLE_NAME, ORDINAL_POSITION""", db=db)
        constraints = _rows(conn, """
            SELECT tc.TABLE_NAME AS table_name, tc.CONSTRAINT_NAME AS name, tc.CONSTRAINT_TYPE AS type,
                   GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION)             AS columns,
                   MAX(k.REFERENCED_TABLE_NAME)                                         AS ref_table,
                   GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION)  AS ref_columns,
                   MAX(rc.UPDATE_RULE) AS on_update, MAX(rc.DELETE_RULE) AS on_delete,
                   MAX(cc.CHECK_CLAUSE) AS check_clause
              FROM information_schema.TABLE_CONSTRAINTS tc
              LEFT JOIN information_schema.KEY_COLUMN_USAGE k
                     ON k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                    AND k.TABLE_NAME = tc.TABLE_NAME
              LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
                     ON rc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND rc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
              LEFT JOIN information_schema.CHECK_CONSTRAINTS cc
                     ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
             WHERE tc.TABLE_SCHEMA = :db
             GROUP BY tc.TABLE_NAME, tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE
             ORDER BY tc.TABLE_NAME, FIELD(tc.CONSTRAINT_TYPE, 'PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY', 'CHECK'),
                      tc.CONSTRAINT_NAME""", db=db)
        indexes = _rows(conn, """
            SELECT TABLE_NAME AS table_name, INDEX_NAME AS name, NON_UNIQUE = 0 AS is_unique,
                   INDEX_TYPE AS index_type, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns,
                   MAX(CARDINALITY) AS cardinality
              FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = :db
             GROUP BY TABLE_NAME, INDEX_NAME, NON_UNIQUE, INDEX_TYPE
             ORDER BY TABLE_NAME, INDEX_NAME = 'PRIMARY' DESC, INDEX_NAME""", db=db)
        counts = {}
        for t in tables:
            if t["type"] == "BASE TABLE":
                counts[t["name"]] = conn.execute(
                    text(f"SELECT COUNT(*) FROM {quote_ident(db)}.{quote_ident(t['name'])}")).scalar()

    by_table: dict[str, dict[str, list]] = defaultdict(lambda: {"columns": [], "constraints": [], "indexes": []})
    for c in columns:
        c["nullable"] = bool(c["nullable"])
        by_table[c.pop("table_name")]["columns"].append(c)
    for c in constraints:
        by_table[c.pop("table_name")]["constraints"].append(c)
    for i in indexes:
        i["is_unique"] = bool(i["is_unique"])
        by_table[i.pop("table_name")]["indexes"].append(i)

    result = []
    for t in tables:
        result.append({**t, "row_count": counts.get(t["name"]), **by_table[t["name"]]})
    relationships = [{"name": c["name"], "table": t["name"], "columns": c["columns"],
                      "ref_table": c["ref_table"], "ref_columns": c["ref_columns"],
                      "on_update": c["on_update"], "on_delete": c["on_delete"]}
                     for t in result for c in t["constraints"] if c["type"] == "FOREIGN KEY"]
    return {"database": db, "tables": result, "relationships": relationships}


def objects(database: str) -> dict:
    db, engine, _ = resolve(database)
    with engine.connect() as conn:
        views = _rows(conn, """
            SELECT TABLE_NAME AS name, VIEW_DEFINITION AS definition, SECURITY_TYPE AS security_type,
                   IS_UPDATABLE AS is_updatable, DEFINER AS definer
              FROM information_schema.VIEWS WHERE TABLE_SCHEMA = :db ORDER BY TABLE_NAME""", db=db)
        triggers = _rows(conn, """
            SELECT TRIGGER_NAME AS name, ACTION_TIMING AS timing, EVENT_MANIPULATION AS event,
                   EVENT_OBJECT_TABLE AS table_name, ACTION_ORDER AS action_order,
                   ACTION_STATEMENT AS definition, CREATED AS created
              FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = :db
             ORDER BY EVENT_OBJECT_TABLE, ACTION_TIMING, EVENT_MANIPULATION""", db=db)
        routines = _rows(conn, """
            SELECT ROUTINE_NAME AS name, ROUTINE_TYPE AS type, DTD_IDENTIFIER AS returns,
                   SECURITY_TYPE AS security_type, SQL_DATA_ACCESS AS data_access,
                   IS_DETERMINISTIC AS is_deterministic, ROUTINE_COMMENT AS comment,
                   ROUTINE_DEFINITION AS definition, CREATED AS created, LAST_ALTERED AS last_altered
              FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = :db
             ORDER BY ROUTINE_TYPE, ROUTINE_NAME""", db=db)
        params = _rows(conn, """
            SELECT SPECIFIC_NAME AS routine, ORDINAL_POSITION AS position, PARAMETER_MODE AS mode,
                   PARAMETER_NAME AS name, DTD_IDENTIFIER AS type
              FROM information_schema.PARAMETERS
             WHERE SPECIFIC_SCHEMA = :db AND ORDINAL_POSITION > 0
             ORDER BY SPECIFIC_NAME, ORDINAL_POSITION""", db=db)
    by_routine: dict[str, list] = defaultdict(list)
    for p in params:
        by_routine[p.pop("routine")].append(p)
    for r in routines:
        r["parameters"] = by_routine.get(r["name"], [])
        r["definition_visible"] = r["definition"] is not None
    return {"database": db, "views": views, "triggers": triggers, "routines": routines}


def routine_signature(database: str, name: str) -> dict:
    db, engine, _ = resolve(database)
    with engine.connect() as conn:
        routine = conn.execute(text(
            "SELECT ROUTINE_NAME AS name, ROUTINE_TYPE AS type FROM information_schema.ROUTINES "
            "WHERE ROUTINE_SCHEMA = :db AND ROUTINE_NAME = :name"), {"db": db, "name": name}).mappings().first()
        if routine is None:
            raise ApiError(404, "not_found", f"Routine '{name}' does not exist in `{db}`.")
        params = _rows(conn, """
            SELECT ORDINAL_POSITION AS position, PARAMETER_MODE AS mode, PARAMETER_NAME AS name,
                   DTD_IDENTIFIER AS type
              FROM information_schema.PARAMETERS
             WHERE SPECIFIC_SCHEMA = :db AND SPECIFIC_NAME = :name AND ORDINAL_POSITION > 0
             ORDER BY ORDINAL_POSITION""", db=db, name=name)
    return {"name": routine["name"], "type": routine["type"], "parameters": params, "database": db}


def table_columns(database: str, table: str) -> tuple[str, list[str], list[str]]:
    """Validated (schema, columns, primary-key columns) of a table or view."""
    db, engine, _ = resolve(database)
    with engine.connect() as conn:
        cols = conn.execute(text(
            "SELECT COLUMN_NAME, COLUMN_KEY FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"), {"db": db, "t": table}).all()
    if not cols:
        raise ApiError(404, "not_found", f"Table or view '{table}' does not exist in `{db}`.")
    return db, [c[0] for c in cols], [c[0] for c in cols if c[1] == "PRI"]
