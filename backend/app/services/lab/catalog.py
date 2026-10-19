"""The DBMS-Lab example catalog.

Every example is real SQL executed against MySQL:
  * target "main" examples run on the application database through the
    SELECT-only account (reads only; writes are rejected by MySQL itself);
  * target "lab" examples run on the disposable lab database, a full copy of
    the schema with synthetic data that an administrator can reset at any time.

Placeholders: {lab_db} and {main_db} are replaced with the configured database
names; %(name)s are bound parameters (so a literal percent sign is written %%
in steps that use parameters).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import DATABASE_DIR
from app.db.sql_script import load_script
from app.services.lab.model import Example, Param, Step

CATEGORIES = [
    ("DDL", "Data Definition", "CREATE, ALTER, RENAME, TRUNCATE and DROP on disposable demo objects"),
    ("DML", "Data Manipulation", "INSERT, UPDATE and DELETE with before/after state"),
    ("DQL", "Data Query", "SELECT, WHERE, ORDER BY, LIMIT, DISTINCT, aggregates, GROUP BY, HAVING"),
    ("JOINS", "Joins", "INNER, LEFT, RIGHT, CROSS and SELF joins — plus common mistakes"),
    ("SUBQUERIES", "Subqueries", "Scalar, multi-row, correlated, IN, EXISTS and NOT EXISTS"),
    ("CONSTRAINTS", "Constraints & Integrity", "Watch MySQL reject invalid data"),
    ("VIEWS", "Views", "View definitions, live results, drop and recreate"),
    ("TRIGGERS", "Triggers", "Audit trail, derived totals and integrity rules fired automatically"),
    ("PROCEDURES", "Stored Procedures & Functions", "CALL with IN/OUT parameters, functions in queries"),
    ("TCL", "Transactions", "START TRANSACTION, COMMIT, ROLLBACK, SAVEPOINT, implicit commit"),
    ("DCL", "Permissions", "GRANT, REVOKE and a read-only account denied write access"),
    ("INDEXES", "Indexes & Query Plans", "EXPLAIN, EXPLAIN ANALYZE, CREATE/DROP INDEX with measured timings"),
]


@lru_cache
def _definition(file: str, prefix: str) -> str:
    """Return the statement in database/<file> that starts with `prefix`."""
    for statement in load_script(DATABASE_DIR / file):
        if statement.sql.upper().startswith(prefix.upper()):
            return statement.sql
    raise LookupError(f"{prefix!r} not found in {file}")


DEMO_COURSE_DDL = """CREATE TABLE demo_course (
    course_id   INT UNSIGNED     NOT NULL AUTO_INCREMENT,
    course_code VARCHAR(10)      NOT NULL,
    course_name VARCHAR(100)     NOT NULL,
    credits     TINYINT UNSIGNED NOT NULL DEFAULT 3,
    created_at  DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_demo_course      PRIMARY KEY (course_id),
    CONSTRAINT uq_demo_course_code UNIQUE (course_code),
    CONSTRAINT chk_demo_credits    CHECK (credits BETWEEN 1 AND 6)
) ENGINE = InnoDB"""

LIST_DEMO_TABLES = """SELECT TABLE_NAME, TABLE_ROWS, CREATE_TIME
  FROM information_schema.TABLES
 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'demo\\_%'
 ORDER BY TABLE_NAME"""

DESCRIBE_COURSE = "DESCRIBE demo_course"
RESET_COURSE = (
    Step("Reset: drop any previous copy", "DROP TABLE IF EXISTS demo_course", role="setup"),
    Step("Reset: create the demo table", DEMO_COURSE_DDL, role="setup"),
)
DROP_COURSE = (Step("Drop the demo table", "DROP TABLE IF EXISTS demo_course, demo_subject"),)


def _examples() -> list[Example]:
    ex: list[Example] = []

    # ================================================================== DDL
    ex += [
        Example(
            "ddl_create_table", "DDL", "CREATE TABLE",
            "Create a new table with a primary key, a UNIQUE column, a DEFAULT and a CHECK constraint.",
            "CREATE TABLE defines a new relation and its constraints in the data dictionary. The table list "
            "before and after shows the new object; DESCRIBE shows the columns MySQL actually created.",
            (
                Step("Reset: remove an earlier copy", "DROP TABLE IF EXISTS demo_course, demo_subject", role="setup"),
                Step("Demo tables before", LIST_DEMO_TABLES, role="before", compare="tables"),
                Step("CREATE TABLE demo_course", DEMO_COURSE_DDL),
                Step("Demo tables after", LIST_DEMO_TABLES, role="after", compare="tables"),
                Step("Structure of the new table", DESCRIBE_COURSE, role="after"),
            ),
            cleanup=DROP_COURSE, min_role="ADMIN", tags=("CREATE",)),
        Example(
            "ddl_alter_table", "DDL", "ALTER TABLE",
            "Add a column, widen another and add a constraint to an existing table.",
            "ALTER TABLE changes the definition of an existing table. In InnoDB most of these changes are "
            "online operations; existing rows receive NULL/DEFAULT values for the new column.",
            (
                *RESET_COURSE,
                Step("Structure before", DESCRIBE_COURSE, role="before", compare="structure"),
                Step("ALTER TABLE demo_course",
                     "ALTER TABLE demo_course\n"
                     "    ADD COLUMN department VARCHAR(60) NULL AFTER course_name,\n"
                     "    MODIFY COLUMN course_name VARCHAR(150) NOT NULL,\n"
                     "    ADD CONSTRAINT chk_demo_code_upper CHECK (course_code = UPPER(course_code))"),
                Step("Structure after", DESCRIBE_COURSE, role="after", compare="structure"),
            ),
            cleanup=DROP_COURSE, min_role="ADMIN", tags=("ALTER",)),
        Example(
            "ddl_rename", "DDL", "RENAME TABLE / RENAME COLUMN",
            "Rename a table, then rename one of its columns.",
            "RENAME TABLE changes only the name in the data dictionary — rows, indexes and constraints move "
            "with it. ALTER TABLE ... RENAME COLUMN renames a column without touching its data.",
            (
                *RESET_COURSE,
                Step("Reset: drop the target name", "DROP TABLE IF EXISTS demo_subject", role="setup"),
                Step("Demo tables before", LIST_DEMO_TABLES, role="before", compare="tables"),
                Step("RENAME TABLE", "RENAME TABLE demo_course TO demo_subject"),
                Step("Demo tables after", LIST_DEMO_TABLES, role="after", compare="tables"),
                Step("RENAME COLUMN", "ALTER TABLE demo_subject RENAME COLUMN course_name TO subject_name"),
                Step("Columns after the rename", "DESCRIBE demo_subject", role="after"),
            ),
            cleanup=DROP_COURSE, min_role="ADMIN", tags=("RENAME",)),
        Example(
            "ddl_truncate", "DDL", "TRUNCATE TABLE",
            "Empty a table instantly while keeping its structure.",
            "TRUNCATE drops and recreates the table internally: it removes every row, resets AUTO_INCREMENT "
            "and causes an implicit COMMIT — unlike DELETE it cannot be rolled back. The next insert gets "
            "course_id = 1 again.",
            (
                *RESET_COURSE,
                Step("Insert sample rows", "INSERT INTO demo_course (course_code, course_name, credits) VALUES\n"
                     "  ('CS201', 'Database Management Systems', 4),\n"
                     "  ('CS202', 'Operating Systems', 4),\n"
                     "  ('CS203', 'Computer Networks', 3)", role="setup"),
                Step("Rows before", "SELECT * FROM demo_course", role="before", compare="rows"),
                Step("TRUNCATE TABLE", "TRUNCATE TABLE demo_course"),
                Step("Rows after", "SELECT * FROM demo_course", role="after", compare="rows"),
                Step("Insert again: AUTO_INCREMENT was reset",
                     "INSERT INTO demo_course (course_code, course_name) VALUES ('CS204', 'Software Engineering')",
                     role="after"),
                Step("New row id", "SELECT course_id, course_code, credits AS default_credits FROM demo_course",
                     role="after"),
            ),
            cleanup=DROP_COURSE, destructive=True, min_role="ADMIN", tags=("TRUNCATE",)),
        Example(
            "ddl_drop", "DDL", "DROP TABLE",
            "Remove a table — its structure, data and indexes.",
            "DROP TABLE deletes the object from the data dictionary. Any later query on it fails with "
            "error 1146 (table doesn't exist). DROP also commits implicitly.",
            (
                *RESET_COURSE,
                Step("Demo tables before", LIST_DEMO_TABLES, role="before", compare="tables"),
                Step("DROP TABLE", "DROP TABLE demo_course"),
                Step("Demo tables after", LIST_DEMO_TABLES, role="after", compare="tables"),
                Step("Querying the dropped table fails", "SELECT * FROM demo_course", role="after",
                     expect_error=True),
            ),
            destructive=True, min_role="ADMIN", tags=("DROP",)),
    ]

    # ================================================================== DML
    find_lab_students = ("SELECT student_id, student_name, email, username, created_at\n"
                         "  FROM student WHERE username LIKE 'lab.%' ORDER BY student_id")
    ex += [
        Example(
            "dml_insert", "DML", "INSERT a row",
            "Register a new student with your own name and e-mail. Try a duplicate or malformed e-mail.",
            "INSERT adds a row. MySQL fills student_id (AUTO_INCREMENT) and created_at (DEFAULT "
            "CURRENT_TIMESTAMP). Invalid values are rejected by constraints: a used e-mail violates "
            "uq_student_email, a malformed one violates chk_student_email.",
            (
                Step("Lab students before", find_lab_students, role="before", compare="rows"),
                Step("INSERT INTO student",
                     "INSERT INTO student (student_name, email, username, password_hash)\n"
                     "VALUES (%(student_name)s, %(email)s, CONCAT('lab.', FLOOR(UNIX_TIMESTAMP(NOW(6)) * 1000)),\n"
                     "        '$2b$12$labdemo.not.a.usable.password.hash.value.xxxxxxxxxxxxxx')"),
                Step("Lab students after", find_lab_students, role="after", compare="rows"),
            ),
            params=(Param("student_name", "Student name", "text", "Riya Desai", max_length=100),
                    Param("email", "E-mail", "text", "riya.desai@students.oems.edu", max_length=255)),
            cleanup=(Step("Delete lab-created students", "DELETE FROM student WHERE username LIKE 'lab.%'"),),
            tags=("INSERT",)),
        Example(
            "dml_insert_multi", "DML", "INSERT multiple rows",
            "Add two questions to the question bank with one multi-row INSERT.",
            "A single INSERT can carry many rows; it is atomic — if one row violates a constraint, none are "
            "inserted. JSON_ARRAY builds the MCQ options stored in the JSON column.",
            (
                Step("Demo questions before",
                     "SELECT question_id, question_type, question_text, options, marks, correct_answer\n"
                     "  FROM question WHERE question_text LIKE 'Lab demo:%' ORDER BY question_id",
                     role="before", compare="rows"),
                Step("Multi-row INSERT",
                     "INSERT INTO question (created_by, question_text, question_type, options, marks, correct_answer)\n"
                     "VALUES (2, 'Lab demo: InnoDB supports row-level locking.', 'TRUE_FALSE', NULL, 1, 'TRUE'),\n"
                     "       (2, 'Lab demo: Which isolation level is the InnoDB default?', 'MCQ',\n"
                     "        JSON_ARRAY('READ UNCOMMITTED','READ COMMITTED','REPEATABLE READ','SERIALIZABLE'),\n"
                     "        2, 'REPEATABLE READ')"),
                Step("Demo questions after",
                     "SELECT question_id, question_type, question_text, options, marks, correct_answer\n"
                     "  FROM question WHERE question_text LIKE 'Lab demo:%' ORDER BY question_id",
                     role="after", compare="rows"),
            ),
            cleanup=(Step("Delete demo questions",
                          "DELETE FROM question WHERE question_text LIKE 'Lab demo:%'\n"
                          "   AND question_id NOT IN (SELECT question_id FROM exam_question)"),),
            tags=("INSERT",)),
        Example(
            "dml_update", "DML", "UPDATE a row",
            "Change the duration of an exam. Try 0 or a value longer than the exam window.",
            "UPDATE modifies rows matched by WHERE. The affected-row count tells how many changed. "
            "CHECK constraints validate the new value (chk_exam_duration, chk_exam_window_fits), and the "
            "AFTER UPDATE trigger writes an audit row automatically.",
            (
                Step("Exam before",
                     "SELECT exam_id, title, exam_date, deadline, duration_minutes,\n"
                     "       TIMESTAMPDIFF(MINUTE, exam_date, deadline) AS window_minutes\n"
                     "  FROM exam WHERE exam_id = %(exam_id)s", role="before", compare="exam"),
                Step("UPDATE exam",
                     "UPDATE exam SET duration_minutes = %(new_duration)s WHERE exam_id = %(exam_id)s"),
                Step("Exam after",
                     "SELECT exam_id, title, exam_date, deadline, duration_minutes,\n"
                     "       TIMESTAMPDIFF(MINUTE, exam_date, deadline) AS window_minutes\n"
                     "  FROM exam WHERE exam_id = %(exam_id)s", role="after", compare="exam"),
                Step("Audit rows written by the trigger",
                     "SELECT audit_id, action, changed_columns, old_duration, new_duration, db_user, changed_at\n"
                     "  FROM exam_audit WHERE exam_id = %(exam_id)s ORDER BY audit_id DESC LIMIT 3", role="after"),
            ),
            params=(Param("exam_id", "Exam id", "int", 7, 1, 1_000_000),
                    Param("new_duration", "New duration (minutes)", "int", 50, 0, 1000)),
            tags=("UPDATE",)),
        Example(
            "dml_delete", "DML", "DELETE a row",
            "Insert a temporary student, then delete it.",
            "DELETE removes the rows matched by WHERE (always check the WHERE clause!). Unlike TRUNCATE it is "
            "transactional and fires DELETE triggers. Deleting a student who has attempts is blocked by the "
            "foreign key — see the Constraints category.",
            (
                Step("Setup: create a temporary student",
                     "INSERT IGNORE INTO student (student_name, email, username, password_hash)\n"
                     "VALUES ('Temp Student', 'temp.student@students.oems.edu', 'lab.temp',\n"
                     "        '$2b$12$labdemo.not.a.usable.password.hash.value.xxxxxxxxxxxxxx')", role="setup"),
                Step("Before", "SELECT student_id, student_name, email FROM student WHERE username = 'lab.temp'",
                     role="before", compare="rows"),
                Step("DELETE FROM student", "DELETE FROM student WHERE username = 'lab.temp'"),
                Step("After", "SELECT student_id, student_name, email FROM student WHERE username = 'lab.temp'",
                     role="after", compare="rows"),
            ),
            destructive=True, tags=("DELETE",)),
    ]

    # ================================================================== DQL (main DB, read-only account)
    def dql(id_, title, description, explanation, steps, params=(), tags=()):
        return Example(id_, "DQL", title, description, explanation, steps, target="main", account="reader",
                       params=params, tags=tags)

    ex += [
        dql("dql_select", "SELECT", "Read columns from a table.",
            "SELECT projects the listed columns. LIMIT keeps the demo small; without ORDER BY the row order "
            "is not guaranteed.",
            (Step("SELECT", "SELECT student_id, student_name, email, created_at\n  FROM student\n LIMIT 10"),),
            tags=("SELECT",)),
        dql("dql_where", "WHERE", "Filter rows with conditions — try another subject.",
            "WHERE keeps only rows whose condition is TRUE. Comparisons with NULL are never TRUE, which is "
            "why IS NULL exists. The subject is passed as a bound parameter, never concatenated into SQL.",
            (Step("SELECT ... WHERE",
                  "SELECT exam_id, title, status, exam_date, duration_minutes\n  FROM exam\n"
                  " WHERE subject = %(subject)s AND status <> 'CANCELLED'\n ORDER BY exam_date"),),
            params=(Param("subject", "Subject", "text", "Database Management Systems"),),
            tags=("WHERE",)),
        dql("dql_like", "WHERE ... LIKE", "Pattern matching on names (% = any characters, _ = one character).",
            "LIKE 'Aar%' matches names starting with 'Aar'. A leading wildcard ('%sha') prevents index use "
            "because the B+ tree is ordered by the beginning of the value.",
            (Step("SELECT ... LIKE",
                  "SELECT student_id, student_name, email\n  FROM student\n"
                  " WHERE student_name LIKE %(pattern)s\n ORDER BY student_name\n LIMIT 25"),),
            params=(Param("pattern", "Pattern", "text", "Aar%", max_length=50),),
            tags=("WHERE", "LIKE")),
        dql("dql_order_limit", "ORDER BY + LIMIT", "Top-N students by percentage.",
            "ORDER BY sorts the result (DESC = largest first; the second key breaks ties). LIMIT returns only "
            "the first N rows of the sorted result.",
            (Step("ORDER BY ... LIMIT",
                  "SELECT student_name, exam_title, percentage, submitted_at\n  FROM student_result_view\n"
                  " ORDER BY percentage DESC, submitted_at ASC\n LIMIT %(n)s"),),
            params=(Param("n", "How many rows (N)", "int", 10, 1, 100),),
            tags=("ORDER BY", "LIMIT")),
        dql("dql_distinct", "DISTINCT", "List each subject once.",
            "DISTINCT removes duplicate rows from the result. COUNT(subject) counts values; "
            "COUNT(DISTINCT subject) counts different values.",
            (Step("SELECT DISTINCT", "SELECT DISTINCT subject FROM exam ORDER BY subject"),
             Step("COUNT vs COUNT(DISTINCT)",
                  "SELECT COUNT(subject) AS subject_values, COUNT(DISTINCT subject) AS distinct_subjects FROM exam")),
            tags=("DISTINCT",)),
        dql("dql_aggregates", "COUNT, SUM, AVG, MIN, MAX", "Summarise every result in one row.",
            "Aggregate functions collapse many rows into one value. They ignore NULLs (COUNT(*) counts rows, "
            "COUNT(column) counts non-NULL values).",
            (Step("Aggregates over result",
                  "SELECT COUNT(*)                     AS results,\n"
                  "       SUM(marks_obtained)          AS total_marks_awarded,\n"
                  "       ROUND(AVG(percentage), 2)    AS avg_percentage,\n"
                  "       MIN(percentage)              AS lowest,\n"
                  "       MAX(percentage)              AS highest,\n"
                  "       SUM(result_status = 'PASS')  AS passed\n  FROM result"),),
            tags=("COUNT", "SUM", "AVG", "MIN", "MAX")),
        dql("dql_group_by", "GROUP BY", "Average score per subject.",
            "GROUP BY forms one group per subject; aggregates are computed per group. Every selected "
            "non-aggregated column must be in GROUP BY (ONLY_FULL_GROUP_BY).",
            (Step("GROUP BY subject",
                  "SELECT e.subject,\n       COUNT(*)                   AS results,\n"
                  "       ROUND(AVG(r.percentage), 2) AS avg_percentage\n"
                  "  FROM result r\n  JOIN attempt a ON a.attempt_id = r.attempt_id\n"
                  "  JOIN exam e    ON e.exam_id    = a.exam_id\n GROUP BY e.subject\n ORDER BY avg_percentage DESC"),),
            tags=("GROUP BY",)),
        dql("dql_having", "HAVING", "Exams whose average is at least a threshold — change the threshold.",
            "WHERE filters rows before grouping; HAVING filters groups after aggregation, so it can use "
            "AVG(), COUNT() and other aggregates.",
            (Step("GROUP BY ... HAVING",
                  "SELECT a.exam_id, e.title,\n       COUNT(*) AS results,\n"
                  "       ROUND(AVG(r.percentage), 2) AS avg_percentage\n"
                  "  FROM result r\n  JOIN attempt a ON a.attempt_id = r.attempt_id\n"
                  "  JOIN exam e    ON e.exam_id    = a.exam_id\n GROUP BY a.exam_id, e.title\n"
                  "HAVING AVG(r.percentage) >= %(min_avg)s\n ORDER BY avg_percentage DESC"),),
            params=(Param("min_avg", "Minimum average %", "decimal", 60, 0, 100),),
            tags=("HAVING",)),
    ]

    # ================================================================== JOINS
    def join(id_, title, description, explanation, steps, params=(), tags=()):
        return Example(id_, "JOINS", title, description, explanation, steps, target="main", account="reader",
                       params=params, tags=tags)

    ex += [
        join("join_inner", "INNER JOIN", "Students together with their exam attempts.",
             "INNER JOIN returns only pairs that satisfy the ON condition. Students 11 and 12 have no "
             "attempts, so they do not appear.",
             (Step("INNER JOIN student, attempt, exam",
                   "SELECT s.student_name, e.title AS exam, a.status, a.started_at\n"
                   "  FROM attempt a\n INNER JOIN student s ON s.student_id = a.student_id\n"
                   " INNER JOIN exam e    ON e.exam_id    = a.exam_id\n WHERE s.student_id <= 12\n"
                   " ORDER BY s.student_id, e.exam_id"),),
             tags=("INNER JOIN",)),
        join("join_left", "LEFT JOIN", "Every named student with their number of attempts — including zero.",
             "LEFT JOIN preserves every row of the left table. When there is no match, the right-side columns "
             "are NULL, so COUNT(a.attempt_id) is 0 for Kabir and Aditi.",
             (Step("LEFT JOIN student -> attempt",
                   "SELECT s.student_id, s.student_name, COUNT(a.attempt_id) AS attempts\n"
                   "  FROM student s\n  LEFT JOIN attempt a ON a.student_id = s.student_id\n"
                   " WHERE s.student_id <= 12\n GROUP BY s.student_id, s.student_name\n ORDER BY s.student_id"),
              Step("LEFT JOIN exam -> attempt (exams without attempts show NULL)",
                   "SELECT e.exam_id, e.title, e.status, a.attempt_id\n  FROM exam e\n"
                   "  LEFT JOIN attempt a ON a.exam_id = e.exam_id AND a.student_id = 1\n ORDER BY e.exam_id")),
             tags=("LEFT JOIN",)),
        join("join_right", "RIGHT JOIN", "Questions in the bank that are not assigned to any exam.",
             "RIGHT JOIN preserves every row of the right table (question). Unassigned questions get NULL "
             "exam_id, which the WHERE clause then selects. Any RIGHT JOIN can be rewritten as a LEFT JOIN "
             "by swapping the tables.",
             (Step("RIGHT JOIN exam_question -> question",
                   "SELECT q.question_id, q.question_type, LEFT(q.question_text, 60) AS question, eq.exam_id\n"
                   "  FROM exam_question eq\n RIGHT JOIN question q ON q.question_id = eq.question_id\n"
                   " WHERE eq.exam_id IS NULL\n ORDER BY q.question_id"),),
             tags=("RIGHT JOIN",)),
        join("join_cross", "CROSS JOIN", "Every staff member paired with every subject.",
             "CROSS JOIN is the Cartesian product: rows(A) x rows(B), with no join condition. Useful for "
             "building grids or calendars; dangerous on large tables.",
             (Step("CROSS JOIN",
                   "SELECT f.faculty_name, d.subject\n  FROM faculty_admin f\n"
                   " CROSS JOIN (SELECT DISTINCT subject FROM exam) AS d\n ORDER BY f.faculty_name, d.subject"),
              Step("Row counts prove the product",
                   "SELECT (SELECT COUNT(*) FROM faculty_admin)              AS staff,\n"
                   "       (SELECT COUNT(DISTINCT subject) FROM exam)        AS subjects,\n"
                   "       (SELECT COUNT(*) FROM faculty_admin) *\n"
                   "       (SELECT COUNT(DISTINCT subject) FROM exam)        AS cross_join_rows")),
             tags=("CROSS JOIN",)),
        join("join_self", "SELF JOIN", "Pairs of exams on the same subject; students who share a name.",
             "A self join joins a table to itself using two aliases. The condition e1.exam_id < e2.exam_id "
             "avoids pairing a row with itself and listing each pair twice.",
             (Step("Exams on the same subject",
                   "SELECT e1.subject, e1.title AS first_exam, e2.title AS second_exam\n"
                   "  FROM exam e1\n  JOIN exam e2 ON e1.subject = e2.subject AND e1.exam_id < e2.exam_id"),
              Step("Different students with the same name",
                   "SELECT s1.student_name, s1.student_id AS id_1, s2.student_id AS id_2\n"
                   "  FROM student s1\n  JOIN student s2 ON s1.student_name = s2.student_name\n"
                   "                  AND s1.student_id < s2.student_id\n ORDER BY s1.student_name\n LIMIT 15")),
             tags=("SELF JOIN",)),
        join("join_mistake_cartesian", "Mistake: missing join condition",
             "Forgetting the ON/WHERE condition silently multiplies rows.",
             "The comma join without a condition is a CROSS JOIN: 9 exams x 3 staff = 27 rows instead of 9. "
             "Always state the join condition explicitly with JOIN ... ON.",
             (Step("Wrong: no join condition", "SELECT COUNT(*) AS rows_returned FROM exam, faculty_admin",
                   compare="result"),
              Step("Right: JOIN ... ON",
                   "SELECT COUNT(*) AS rows_returned\n  FROM exam e\n"
                   "  JOIN faculty_admin f ON f.faculty_admin_id = e.created_by", compare="result")),
             tags=("mistake",)),
        join("join_mistake_where_outer", "Mistake: filtering an outer join in WHERE",
             "A WHERE condition on the right table turns a LEFT JOIN back into an INNER JOIN.",
             "Unmatched rows have NULL in a.exam_id, and NULL = 5 is not TRUE, so WHERE removes them. Put "
             "conditions on the optional side into the ON clause to keep every student.",
             (Step("Wrong: condition in WHERE",
                   "SELECT s.student_id, s.student_name, a.status\n  FROM student s\n"
                   "  LEFT JOIN attempt a ON a.student_id = s.student_id\n"
                   " WHERE s.student_id <= 12 AND a.exam_id = 5", compare="result"),
              Step("Right: condition in ON",
                   "SELECT s.student_id, s.student_name, a.status\n  FROM student s\n"
                   "  LEFT JOIN attempt a ON a.student_id = s.student_id AND a.exam_id = 5\n"
                   " WHERE s.student_id <= 12", compare="result")),
             tags=("mistake",)),
        join("join_mistake_fanout", "Mistake: aggregating after a fan-out join",
             "Joining two one-to-many tables multiplies rows before SUM().",
             "Each exam_question row is repeated once per attempt, so SUM(marks_assigned) is multiplied by "
             "the number of attempts. Aggregate in a subquery first (or use the stored total_marks).",
             (Step("Wrong: SUM after joining attempts",
                   "SELECT e.exam_id, SUM(eq.marks_assigned) AS total_marks\n  FROM exam e\n"
                   "  JOIN exam_question eq ON eq.exam_id = e.exam_id\n"
                   "  JOIN attempt a        ON a.exam_id  = e.exam_id\n WHERE e.exam_id <= 4\n GROUP BY e.exam_id",
                   compare="result"),
              Step("Right: aggregate before joining",
                   "SELECT e.exam_id, m.total_marks, COUNT(a.attempt_id) AS attempts\n  FROM exam e\n"
                   "  JOIN (SELECT exam_id, SUM(marks_assigned) AS total_marks\n"
                   "          FROM exam_question GROUP BY exam_id) m ON m.exam_id = e.exam_id\n"
                   "  LEFT JOIN attempt a ON a.exam_id = e.exam_id\n WHERE e.exam_id <= 4\n"
                   " GROUP BY e.exam_id, m.total_marks", compare="result")),
             tags=("mistake",)),
    ]

    # ================================================================== SUBQUERIES
    def sub(id_, title, description, explanation, steps, params=(), tags=()):
        return Example(id_, "SUBQUERIES", title, description, explanation, steps, target="main",
                       account="reader", params=params, tags=tags)

    ex += [
        sub("sub_scalar", "Scalar subquery", "Show each named student's score next to the overall average.",
            "A scalar subquery returns exactly one value (one row, one column) and can be used like a "
            "constant anywhere an expression is allowed.",
            (Step("Scalar subquery in SELECT",
                  "SELECT student_name, exam_title, percentage,\n"
                  "       (SELECT ROUND(AVG(percentage), 2) FROM result) AS overall_average\n"
                  "  FROM student_result_view\n WHERE student_id <= 12\n ORDER BY student_id, exam_id"),),
            tags=("scalar",)),
        sub("sub_above_average", "Students scoring above the average", "Compare each result with AVG().",
            "The subquery computes the average once; the outer query keeps results above it.",
            (Step("WHERE percentage > (subquery)",
                  "SELECT student_name, exam_title, percentage\n  FROM student_result_view\n"
                  " WHERE percentage > (SELECT AVG(percentage) FROM result)\n   AND student_id <= 12\n"
                  " ORDER BY percentage DESC"),),
            tags=("scalar", "AVG")),
        sub("sub_in", "Multi-row subquery with IN", "Named students who attempted a given subject.",
            "IN compares a value with every row returned by the subquery. The subquery returns many rows "
            "(one column).",
            (Step("WHERE student_id IN (subquery)",
                  "SELECT student_id, student_name\n  FROM student\n WHERE student_id <= 12\n"
                  "   AND student_id IN (SELECT a.student_id\n"
                  "                        FROM attempt a JOIN exam e ON e.exam_id = a.exam_id\n"
                  "                       WHERE e.subject = %(subject)s)\n ORDER BY student_id"),),
            params=(Param("subject", "Subject", "text", "Data Structures"),),
            tags=("IN", "multi-row")),
        sub("sub_correlated", "Correlated subquery", "Each named student's best percentage.",
            "A correlated subquery refers to the outer row (s.student_id) and is evaluated per outer row. "
            "Students without results get NULL.",
            (Step("Correlated subquery",
                  "SELECT s.student_id, s.student_name,\n"
                  "       (SELECT MAX(r.percentage)\n          FROM result r\n"
                  "          JOIN attempt a ON a.attempt_id = r.attempt_id\n"
                  "         WHERE a.student_id = s.student_id) AS best_percentage\n"
                  "  FROM student s\n WHERE s.student_id <= 12\n ORDER BY best_percentage DESC"),),
            tags=("correlated",)),
        sub("sub_exists", "EXISTS", "Exams that have at least one attempt.",
            "EXISTS is TRUE as soon as the subquery returns one row; the selected columns do not matter "
            "(SELECT 1). MySQL can stop at the first match.",
            (Step("WHERE EXISTS",
                  "SELECT e.exam_id, e.title, e.status\n  FROM exam e\n"
                  " WHERE EXISTS (SELECT 1 FROM attempt a WHERE a.exam_id = e.exam_id)\n ORDER BY e.exam_id"),),
            tags=("EXISTS",)),
        sub("sub_not_exists_exams", "NOT EXISTS: exams with no attempts", "Anti-join on attempt.",
            "NOT EXISTS keeps exams for which no attempt row exists — scheduled, cancelled and empty exams.",
            (Step("WHERE NOT EXISTS",
                  "SELECT e.exam_id, e.title, e.status\n  FROM exam e\n"
                  " WHERE NOT EXISTS (SELECT 1 FROM attempt a WHERE a.exam_id = e.exam_id)\n ORDER BY e.exam_id"),),
            tags=("NOT EXISTS",)),
        sub("sub_not_exists_students", "NOT EXISTS: students with no submitted answers",
            "Students who have never submitted an answer.",
            "The correlated NOT EXISTS checks answers of submitted attempts per student. NOT IN would "
            "behave unexpectedly if the subquery returned a NULL — NOT EXISTS is NULL-safe.",
            (Step("WHERE NOT EXISTS (answer of a submitted attempt)",
                  "SELECT s.student_id, s.student_name, s.created_at\n  FROM student s\n"
                  " WHERE NOT EXISTS (SELECT 1\n                     FROM attempt a\n"
                  "                     JOIN answer an ON an.attempt_id = a.attempt_id\n"
                  "                    WHERE a.student_id = s.student_id\n"
                  "                      AND a.status <> 'IN_PROGRESS')\n ORDER BY s.student_id\n LIMIT 25"),),
            tags=("NOT EXISTS",)),
    ]

    # ================================================================== CONSTRAINTS (lab)
    def con(id_, title, description, explanation, steps, cleanup=(), tags=()):
        return Example(id_, "CONSTRAINTS", title, description, explanation, steps, cleanup=cleanup, tags=tags)

    ex += [
        con("con_primary_key", "PRIMARY KEY", "Insert a student with an id that already exists.",
            "A primary key is UNIQUE + NOT NULL. MySQL rejects the duplicate with error 1062 for key "
            "'PRIMARY' and nothing is written.",
            (Step("Existing row", "SELECT student_id, student_name FROM student WHERE student_id = 1",
                  role="before"),
             Step("Duplicate primary key",
                  "INSERT INTO student (student_id, student_name, email, username, password_hash)\n"
                  "VALUES (1, 'Duplicate Id', 'dup.id@students.oems.edu', 'dup.id', 'x')", expect_error=True)),
            tags=("PRIMARY KEY",)),
        con("con_foreign_key", "FOREIGN KEY", "Reference a missing student; delete a referenced exam.",
            "Foreign keys protect references in both directions: a child row cannot point to a missing parent "
            "(error 1452), and a parent row still referenced by children cannot be deleted (error 1451).",
            (Step("Child row with a missing parent",
                  "INSERT INTO attempt (student_id, exam_id) VALUES (999999, 1)", expect_error=True),
             Step("Deleting a parent that is referenced", "DELETE FROM exam WHERE exam_id = 1", expect_error=True),
             Step("Composite FK: answer for a question not in the attempt's exam",
                  "INSERT INTO answer (attempt_id, exam_id, question_id, selected_answer)\n"
                  "SELECT attempt_id, exam_id, 1, 'Primary key'\n  FROM attempt\n"
                  " WHERE exam_id = 5 AND status = 'IN_PROGRESS'\n LIMIT 1", expect_error=True,
                  note="fk_answer_exam_question: question 1 belongs to exam 1, not exam 5")),
            tags=("FOREIGN KEY",)),
        con("con_unique", "UNIQUE", "Register a second account with an e-mail that is already used.",
            "UNIQUE constraints are backed by unique indexes. uq_student_email rejects the duplicate.",
            (Step("Existing e-mail", "SELECT student_id, email FROM student WHERE student_id = 1", role="before"),
             Step("Duplicate e-mail",
                  "INSERT INTO student (student_name, email, username, password_hash)\n"
                  "VALUES ('Copy Cat', 'aarav.shah@students.oems.edu', 'copy.cat', 'x')", expect_error=True)),
            tags=("UNIQUE",)),
        con("con_not_null", "NOT NULL", "Create an exam without a title.",
            "NOT NULL columns must receive a value. In strict SQL mode MySQL rejects NULL with error 1048 "
            "instead of silently converting it.",
            (Step("NULL into a NOT NULL column",
                  "INSERT INTO exam (created_by, title, subject, exam_date, deadline, duration_minutes)\n"
                  "VALUES (2, NULL, 'Demo', NOW() + INTERVAL 1 DAY, NOW() + INTERVAL 2 DAY, 30)",
                  expect_error=True),),
            tags=("NOT NULL",)),
        con("con_check", "CHECK", "Violate several CHECK constraints.",
            "CHECK constraints (enforced since MySQL 8.0.16) validate a row's own values: a positive "
            "duration, a percentage within 0-100, an MCQ with at least two options.",
            (Step("Duration must be > 0", "UPDATE exam SET duration_minutes = 0 WHERE exam_id = 7",
                  expect_error=True),
             Step("Percentage must be 0..100", "UPDATE result SET percentage = 150 WHERE result_id = 1",
                  expect_error=True),
             Step("MCQ needs at least two options",
                  "INSERT INTO question (created_by, question_text, question_type, options, marks, correct_answer)\n"
                  "VALUES (2, 'Lab demo: bad MCQ', 'MCQ', JSON_ARRAY('only one'), 2, 'only one')",
                  expect_error=True),
             Step("Exam window must fit the duration",
                  "UPDATE exam SET duration_minutes = 500 WHERE exam_id = 9", expect_error=True)),
            tags=("CHECK",)),
        con("con_default", "DEFAULT", "Insert an exam that omits most columns.",
            "Omitted columns take their DEFAULT: status SCHEDULED, total_marks 0, pass_percentage 40, "
            "results_released 0, created_at = now.",
            (Step("INSERT with defaults",
                  "INSERT INTO exam (created_by, title, subject, exam_date, deadline, duration_minutes)\n"
                  "VALUES (2, 'Lab demo: defaults', 'Demo', NOW() + INTERVAL 1 DAY, NOW() + INTERVAL 2 DAY, 30)"),
             Step("Values filled in by DEFAULT",
                  "SELECT exam_id, title, status, total_marks, pass_percentage, results_released, created_at\n"
                  "  FROM exam WHERE title = 'Lab demo: defaults' ORDER BY exam_id DESC LIMIT 1", role="after")),
            cleanup=(Step("Delete demo exams", "DELETE FROM exam WHERE title = 'Lab demo: defaults'"),),
            tags=("DEFAULT",)),
        Example("con_duplicate_submission", "CONSTRAINTS", "Duplicate attempts and results",
                "Try to start the same exam twice and to create a second result for one attempt.",
                "UNIQUE(student_id, exam_id) on attempt and UNIQUE(attempt_id) on result make 'submit exactly "
                "once' a database guarantee: even two simultaneous requests cannot both succeed.",
                (Step("Second attempt for the same student and exam",
                      "INSERT INTO attempt (student_id, exam_id) VALUES (1, 1)", expect_error=True),
                 Step("Second result for the same attempt",
                      "INSERT INTO result (attempt_id, marks_obtained, percentage, result_status)\n"
                      "VALUES (1, 10, 58.82, 'PASS')", expect_error=True)),
                tags=("UNIQUE",)),
    ]

    # ================================================================== VIEWS
    overview_ddl = _definition("views.sql", "CREATE OR REPLACE VIEW exam_overview")
    ex += [
        Example("view_exam_overview", "VIEWS", "SELECT from exam_overview",
                "One row per exam with author and live counters.",
                "exam_overview joins exam with faculty_admin and computes question/attempt counts with "
                "scalar subqueries. Querying a view looks exactly like querying a table.",
                (Step("SELECT * FROM exam_overview", "SELECT * FROM exam_overview ORDER BY exam_id"),),
                target="main", account="reader", tags=("view",)),
        Example("view_student_result", "VIEWS", "SELECT from student_result_view",
                "Results of one student, with names instead of ids.",
                "student_result_view hides a four-table join (result, attempt, student, exam). Filtering a "
                "view with WHERE works like filtering a table.",
                (Step("Results of a student",
                      "SELECT exam_title, marks_obtained, total_marks, percentage, result_status, evaluated_at\n"
                      "  FROM student_result_view\n WHERE student_id = %(student_id)s\n ORDER BY evaluated_at"),),
                target="main", account="reader", params=(Param("student_id", "Student id", "int", 1, 1, 10**7),),
                tags=("view",)),
        Example("view_exam_performance", "VIEWS", "SELECT from exam_performance_view",
                "Aggregated performance for every exam.",
                "The view groups attempts and results per exam. LEFT JOINs keep exams with no attempts "
                "(their averages are NULL and counts 0).",
                (Step("SELECT * FROM exam_performance_view", "SELECT * FROM exam_performance_view ORDER BY exam_id"),),
                target="main", account="reader", tags=("view",)),
        Example("view_definition", "VIEWS", "Inspect view definitions",
                "Read the stored definitions from the data dictionary.",
                "A view stores only its SELECT. information_schema.VIEWS and SHOW CREATE VIEW reveal it.",
                (Step("information_schema.VIEWS",
                      "SELECT TABLE_NAME, SECURITY_TYPE, LEFT(VIEW_DEFINITION, 200) AS definition_start\n"
                      "  FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE()"),
                 Step("SHOW CREATE VIEW", "SHOW CREATE VIEW exam_performance_view")),
                tags=("view",)),
        Example("view_reflects_changes", "VIEWS", "A view always reflects its base tables",
                "Assign a question to an exam and watch the view change, then undo it.",
                "Views are not snapshots. After the INSERT into exam_question, exam_overview immediately shows "
                "the new question_count and the total_marks maintained by the trigger.",
                (Step("Reset: make sure question 56 is not assigned",
                      "DELETE FROM exam_question WHERE exam_id = 9 AND question_id = 56", role="setup"),
                 Step("View before", "SELECT exam_id, title, question_count, total_marks FROM exam_overview "
                      "WHERE exam_id = 9", role="before", compare="view"),
                 Step("Change a base table",
                      "INSERT INTO exam_question (exam_id, question_id, question_order, marks_assigned)\n"
                      "VALUES (9, 56, 1, 2)"),
                 Step("View after", "SELECT exam_id, title, question_count, total_marks FROM exam_overview "
                      "WHERE exam_id = 9", role="after", compare="view"),
                 Step("Restore the base table", "DELETE FROM exam_question WHERE exam_id = 9 AND question_id = 56",
                      role="restore")),
                tags=("view",)),
        Example("view_create_drop", "VIEWS", "CREATE VIEW, query it, DROP it",
                "Create a toppers view, list it, query it, drop it and show the error afterwards.",
                "CREATE VIEW adds a named query to the schema. After DROP VIEW, selecting from it fails with "
                "error 1146.",
                (Step("Reset", "DROP VIEW IF EXISTS demo_toppers_view", role="setup"),
                 Step("CREATE VIEW",
                      "CREATE VIEW demo_toppers_view AS\n"
                      "SELECT student_name, exam_title, percentage\n  FROM student_result_view\n"
                      " WHERE percentage >= 90"),
                 Step("Views in the schema",
                      "SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE() "
                      "ORDER BY TABLE_NAME", role="after"),
                 Step("SELECT from the new view",
                      "SELECT * FROM demo_toppers_view ORDER BY percentage DESC, student_name LIMIT 10"),
                 Step("DROP VIEW", "DROP VIEW demo_toppers_view"),
                 Step("Querying the dropped view fails", "SELECT * FROM demo_toppers_view", expect_error=True)),
                cleanup=(Step("Drop the demo view", "DROP VIEW IF EXISTS demo_toppers_view"),),
                min_role="ADMIN", tags=("CREATE VIEW", "DROP VIEW")),
        Example("view_recreate", "VIEWS", "DROP and recreate exam_overview",
                "Remove a real view of the lab database and restore it from views.sql.",
                "Dropping a view never touches table data. Recreating it with the same definition restores "
                "it completely — the data was always in the base tables.",
                (Step("DROP VIEW exam_overview", "DROP VIEW exam_overview"),
                 Step("It is gone", "SELECT COUNT(*) FROM exam_overview", expect_error=True),
                 Step("Recreate from views.sql", overview_ddl),
                 Step("Works again", "SELECT exam_id, title, question_count FROM exam_overview ORDER BY exam_id",
                      role="after")),
                cleanup=(Step("Ensure the view exists", overview_ddl),),
                destructive=True, min_role="ADMIN", tags=("DROP VIEW",)),
    ]

    # ================================================================== TRIGGERS
    audit_update_trigger = _definition("triggers.sql", "CREATE TRIGGER trg_exam_after_update")
    audit_rows = ("SELECT audit_id, action, changed_columns, old_duration, new_duration, db_user, changed_at\n"
                  "  FROM exam_audit WHERE exam_id = %(exam_id)s ORDER BY audit_id DESC LIMIT 5")
    ex += [
        Example("trg_audit_duration", "TRIGGERS", "AFTER UPDATE audit trigger",
                "Change an exam's duration; the trigger records OLD and NEW values automatically.",
                "trg_exam_after_update runs for every updated exam row. It compares OLD and NEW and inserts "
                "an exam_audit row only when an audited column really changed — setting the same value "
                "again writes nothing.",
                (Step("Exam before", "SELECT exam_id, title, duration_minutes FROM exam WHERE exam_id = %(exam_id)s",
                      role="before", compare="exam"),
                 Step("Audit rows before", audit_rows, role="before", compare="audit"),
                 Step("UPDATE (no INSERT into exam_audit is written by us)",
                      "UPDATE exam SET duration_minutes = %(new_duration)s WHERE exam_id = %(exam_id)s"),
                 Step("Exam after", "SELECT exam_id, title, duration_minutes FROM exam WHERE exam_id = %(exam_id)s",
                      role="after", compare="exam"),
                 Step("Audit rows after", audit_rows, role="after", compare="audit")),
                params=(Param("exam_id", "Exam id", "int", 7, 1, 10**6),
                        Param("new_duration", "New duration (minutes)", "int", 55, 1, 600)),
                tags=("AFTER UPDATE",)),
        Example("trg_audit_rollback", "TRIGGERS", "Trigger writes roll back with the transaction",
                "Update an exam inside a transaction, then ROLLBACK: the audit row disappears too.",
                "A trigger is part of the statement that fired it, so its INSERT belongs to the same InnoDB "
                "transaction. A second session cannot see the uncommitted audit row, and ROLLBACK removes it.",
                (Step("Audit count before",
                      "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 7", role="before",
                      compare="count"),
                 Step("START TRANSACTION", "START TRANSACTION"),
                 Step("UPDATE fires the trigger",
                      "UPDATE exam SET duration_minutes = duration_minutes + 1 WHERE exam_id = 7"),
                 Step("Inside the transaction: one more audit row",
                      "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 7"),
                 Step("Second session: uncommitted row is invisible",
                      "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 7", conn="lab#2"),
                 Step("ROLLBACK", "ROLLBACK"),
                 Step("Audit count after ROLLBACK",
                      "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 7", role="after",
                      compare="count")),
                tags=("transaction",)),
        Example("trg_total_marks", "TRIGGERS", "Derived column maintained by triggers",
                "Assign and remove a question; exam.total_marks follows automatically.",
                "AFTER INSERT/DELETE triggers on exam_question recompute exam.total_marks = "
                "SUM(marks_assigned), so the stored total can never drift from the assignments.",
                (Step("Reset", "DELETE FROM exam_question WHERE exam_id = 9 AND question_id = 57", role="setup"),
                 Step("Total before", "SELECT exam_id, title, total_marks FROM exam WHERE exam_id = 9",
                      role="before", compare="total"),
                 Step("Assign a 1-mark question",
                      "INSERT INTO exam_question (exam_id, question_id, question_order, marks_assigned)\n"
                      "VALUES (9, 57, 1, 1)"),
                 Step("Total after INSERT", "SELECT exam_id, title, total_marks FROM exam WHERE exam_id = 9",
                      role="after", compare="total"),
                 Step("Remove it again", "DELETE FROM exam_question WHERE exam_id = 9 AND question_id = 57",
                      role="restore"),
                 Step("Total after DELETE", "SELECT exam_id, title, total_marks FROM exam WHERE exam_id = 9",
                      role="after")),
                tags=("AFTER INSERT", "AFTER DELETE")),
        Example("trg_answer_lock", "TRIGGERS", "BEFORE UPDATE trigger enforcing a business rule",
                "Try to change a submitted answer and to award more marks than a question is worth.",
                "trg_answer_before_update SIGNALs an error (SQLSTATE 45000, error 1644) — rules that need data "
                "from other tables cannot be CHECK constraints, so a BEFORE trigger enforces them.",
                (Step("Answer of an evaluated attempt",
                      "SELECT an.answer_id, an.question_id, an.selected_answer, an.marks_obtained, a.status\n"
                      "  FROM answer an JOIN attempt a ON a.attempt_id = an.attempt_id\n"
                      " WHERE an.attempt_id = 1 ORDER BY an.question_id LIMIT 3", role="before"),
                 Step("Edit an answer after submission",
                      "UPDATE answer SET selected_answer = 'changed later' WHERE attempt_id = 1 AND question_id = 1",
                      expect_error=True),
                 Step("Marks above the question's maximum",
                      "UPDATE answer SET marks_obtained = 99 WHERE attempt_id = 1 AND question_id = 1",
                      expect_error=True)),
                tags=("BEFORE UPDATE", "SIGNAL")),
        Example("trg_definitions", "TRIGGERS", "List trigger definitions",
                "Every trigger of the schema with its timing, event and table.",
                "information_schema.TRIGGERS describes each trigger: BEFORE/AFTER, INSERT/UPDATE/DELETE and "
                "the table it is attached to.",
                (Step("information_schema.TRIGGERS",
                      "SELECT TRIGGER_NAME, ACTION_TIMING, EVENT_MANIPULATION, EVENT_OBJECT_TABLE,\n"
                      "       LEFT(ACTION_STATEMENT, 120) AS body_start\n"
                      "  FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()\n"
                      " ORDER BY EVENT_OBJECT_TABLE, ACTION_TIMING, EVENT_MANIPULATION"),),
                tags=("metadata",)),
        Example("trg_drop_recreate", "TRIGGERS", "DROP TRIGGER and CREATE TRIGGER",
                "Drop the audit trigger, prove updates are no longer audited, recreate it, prove it works.",
                "Without the trigger the UPDATE succeeds but leaves no audit row. After CREATE TRIGGER (body "
                "taken from triggers.sql) the next UPDATE is audited again.",
                (Step("DROP TRIGGER", "DROP TRIGGER IF EXISTS trg_exam_after_update"),
                 Step("Audit count", "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 9",
                      compare="a"),
                 Step("UPDATE without the trigger",
                      "UPDATE exam SET duration_minutes = IF(duration_minutes = 30, 35, 30) WHERE exam_id = 9"),
                 Step("Audit count unchanged", "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 9",
                      compare="a"),
                 Step("CREATE TRIGGER", audit_update_trigger),
                 Step("UPDATE with the trigger",
                      "UPDATE exam SET duration_minutes = IF(duration_minutes = 30, 35, 30) WHERE exam_id = 9"),
                 Step("Audit count increased", "SELECT COUNT(*) AS audit_rows FROM exam_audit WHERE exam_id = 9",
                      role="after", compare="a")),
                cleanup=(Step("Ensure the trigger exists", "DROP TRIGGER IF EXISTS trg_exam_after_update"),
                         Step("Recreate it", audit_update_trigger)),
                destructive=True, min_role="ADMIN", tags=("DROP TRIGGER", "CREATE TRIGGER")),
    ]

    # ================================================================== PROCEDURES & FUNCTIONS
    ex += [
        Example("proc_get_exam_details", "PROCEDURES", "CALL GetExamDetails(exam_id)",
                "A procedure returning two result sets. Try an id that does not exist.",
                "IN parameter p_exam_id selects the exam. The procedure returns the summary and the ordered "
                "question list; for an unknown id it raises an error with SIGNAL.",
                (Step("CALL", "CALL GetExamDetails(%(exam_id)s)"),),
                target="main", account="reader", params=(Param("exam_id", "Exam id", "int", 1, 0, 10**7),),
                tags=("CALL", "IN")),
        Example("proc_get_student_results", "PROCEDURES", "CALL GetStudentResults(student_id)",
                "All evaluated results of one student.",
                "Procedures package a query behind a name and parameters, so clients do not need to know the "
                "joins.",
                (Step("CALL", "CALL GetStudentResults(%(student_id)s)"),),
                target="main", account="reader", params=(Param("student_id", "Student id", "int", 1, 0, 10**7),),
                tags=("CALL",)),
        Example("proc_out_params", "PROCEDURES", "OUT parameters",
                "sp_exam_attempt_stats returns three values through OUT parameters.",
                "OUT parameters are written by the procedure into session variables (@total, ...), which the "
                "same session then reads with SELECT.",
                (Step("CALL with OUT variables", "CALL sp_exam_attempt_stats(%(exam_id)s, @total, @evaluated, @avg)"),
                 Step("Read the OUT values", "SELECT @total AS attempts, @evaluated AS evaluated, @avg AS avg_percentage")),
                target="main", account="reader", params=(Param("exam_id", "Exam id", "int", 2, 0, 10**7),),
                tags=("OUT",)),
        Example("func_percentage", "PROCEDURES", "Stored function in an expression",
                "fn_marks_percentage(obtained, total) — try total 0 or obtained > total.",
                "A function returns one value and can be used inside SELECT. fn_marks_percentage returns 0 "
                "when total <= 0 and clamps to 0..100, so it never violates the result CHECK constraint.",
                (Step("Call the function",
                      "SELECT fn_marks_percentage(%(obtained)s, %(total)s) AS percentage,\n"
                      "       fn_result_status(fn_marks_percentage(%(obtained)s, %(total)s), 40) AS status_at_40"),
                 Step("Use it inside a query",
                      "SELECT attempt_id, marks_obtained, total_marks,\n"
                      "       fn_marks_percentage(marks_obtained, total_marks) AS recomputed, percentage AS stored_percentage\n"
                      "  FROM student_result_view\n WHERE student_id = 1")),
                target="main", account="reader",
                params=(Param("obtained", "Marks obtained", "decimal", 13.5, -1000, 100000),
                        Param("total", "Total marks", "decimal", 17, -1000, 100000)),
                tags=("FUNCTION",)),
        Example("proc_definitions", "PROCEDURES", "List routines",
                "Stored procedures and functions in the schema, with their parameters.",
                "information_schema.ROUTINES and PARAMETERS describe every stored program.",
                (Step("Routines",
                      "SELECT ROUTINE_NAME, ROUTINE_TYPE, DATA_TYPE AS returns, SECURITY_TYPE, ROUTINE_COMMENT\n"
                      "  FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() ORDER BY ROUTINE_TYPE, ROUTINE_NAME"),
                 Step("Parameters",
                      "SELECT SPECIFIC_NAME, ORDINAL_POSITION, PARAMETER_MODE, PARAMETER_NAME, DTD_IDENTIFIER\n"
                      "  FROM information_schema.PARAMETERS WHERE SPECIFIC_SCHEMA = DATABASE()\n"
                      " ORDER BY SPECIFIC_NAME, ORDINAL_POSITION")),
                tags=("metadata",)),
        Example("proc_create_call_drop", "PROCEDURES", "CREATE, CALL and DROP a procedure and a function",
                "Define new stored programs, run them, then remove them.",
                "Through an API (no mysql client) a CREATE PROCEDURE is sent as one statement, so no DELIMITER "
                "is needed. DROP removes the routine from the data dictionary.",
                (Step("Reset", "DROP PROCEDURE IF EXISTS demo_exams_by_subject", role="setup"),
                 Step("Reset", "DROP FUNCTION IF EXISTS demo_grade_letter", role="setup"),
                 Step("CREATE PROCEDURE",
                      "CREATE PROCEDURE demo_exams_by_subject(IN p_subject VARCHAR(100))\n"
                      "READS SQL DATA\nBEGIN\n"
                      "    SELECT exam_id, title, status FROM exam WHERE subject = p_subject ORDER BY exam_date;\nEND"),
                 Step("CALL it", "CALL demo_exams_by_subject('Database Management Systems')"),
                 Step("CREATE FUNCTION",
                      "CREATE FUNCTION demo_grade_letter(p_percentage DECIMAL(5,2)) RETURNS CHAR(1)\n"
                      "DETERMINISTIC NO SQL\n"
                      "RETURN CASE WHEN p_percentage >= 85 THEN 'A' WHEN p_percentage >= 70 THEN 'B'\n"
                      "            WHEN p_percentage >= 55 THEN 'C' WHEN p_percentage >= 40 THEN 'D' ELSE 'F' END"),
                 Step("Use the function",
                      "SELECT demo_grade_letter(percentage) AS grade, COUNT(*) AS results\n"
                      "  FROM result GROUP BY grade ORDER BY grade"),
                 Step("DROP both", "DROP PROCEDURE demo_exams_by_subject"),
                 Step("DROP both", "DROP FUNCTION demo_grade_letter")),
                cleanup=(Step("Drop", "DROP PROCEDURE IF EXISTS demo_exams_by_subject"),
                         Step("Drop", "DROP FUNCTION IF EXISTS demo_grade_letter")),
                min_role="ADMIN", tags=("CREATE PROCEDURE", "CREATE FUNCTION")),
        Example("proc_finalize_attempt", "PROCEDURES", "sp_finalize_attempt: validation inside a procedure",
                "Finalize a submitted attempt that still has ungraded answers, grade them, finalize again.",
                "The procedure locks the attempt (SELECT ... FOR UPDATE), refuses to finalize while answers "
                "are ungraded, then inserts the result and marks the attempt EVALUATED. If no SUBMITTED "
                "attempt is left, reset the lab database.",
                (Step("Pick a submitted attempt",
                      "SET @demo_attempt = (SELECT MIN(attempt_id) FROM attempt WHERE status = 'SUBMITTED')"),
                 Step("Its ungraded answers",
                      "SELECT @demo_attempt AS attempt_id, question_id, LEFT(selected_answer, 50) AS answer, marks_obtained\n"
                      "  FROM answer WHERE attempt_id = @demo_attempt AND marks_obtained IS NULL", role="before"),
                 Step("Finalize too early", "CALL sp_finalize_attempt(@demo_attempt)", expect_error=True),
                 Step("Grade the remaining answers",
                      "UPDATE answer SET marks_obtained = 4\n WHERE attempt_id = @demo_attempt AND marks_obtained IS NULL"),
                 Step("Finalize", "CALL sp_finalize_attempt(@demo_attempt)"),
                 Step("Result created",
                      "SELECT r.*, a.status FROM result r JOIN attempt a ON a.attempt_id = r.attempt_id\n"
                      " WHERE r.attempt_id = @demo_attempt", role="after")),
                tags=("CALL", "SIGNAL")),
    ]

    # ================================================================== TCL
    duration_q = "SELECT exam_id, duration_minutes FROM exam WHERE exam_id = 9"
    toggle = "UPDATE exam SET duration_minutes = IF(duration_minutes = 30, 35, 30) WHERE exam_id = 9"
    ex += [
        Example("tcl_commit", "TCL", "START TRANSACTION ... COMMIT",
                "Change data inside a transaction, observe it from a second session, then COMMIT.",
                "Inside the transaction your session sees its own change; another session still sees the "
                "committed value (InnoDB REPEATABLE READ / consistent reads). After COMMIT the change is "
                "durable and visible to everyone.",
                (Step("Committed state", duration_q, role="before", compare="state"),
                 Step("START TRANSACTION", "START TRANSACTION"),
                 Step("UPDATE", toggle),
                 Step("Same session: change visible", duration_q),
                 Step("Second session: still the old value", duration_q, conn="lab#2"),
                 Step("COMMIT", "COMMIT"),
                 Step("Second session after COMMIT", duration_q, conn="lab#2"),
                 Step("Persisted state", duration_q, role="after", compare="state")),
                tags=("COMMIT",)),
        Example("tcl_rollback", "TCL", "START TRANSACTION ... ROLLBACK",
                "Make a change and undo it with ROLLBACK.",
                "ROLLBACK discards every change since START TRANSACTION. The persisted state equals the "
                "initial state.",
                (Step("Initial state", duration_q, role="before", compare="state"),
                 Step("START TRANSACTION", "START TRANSACTION"),
                 Step("UPDATE", toggle),
                 Step("Temporary state (inside the transaction)", duration_q),
                 Step("ROLLBACK", "ROLLBACK"),
                 Step("Persisted state", duration_q, role="after", compare="state")),
                tags=("ROLLBACK",)),
        Example("tcl_savepoint", "TCL", "SAVEPOINT and ROLLBACK TO SAVEPOINT",
                "Keep the first insert, undo the second, commit.",
                "ROLLBACK TO SAVEPOINT undoes only the work done after the savepoint; the transaction stays "
                "open and the earlier work can still be committed.",
                (Step("Reset", "DELETE FROM question WHERE question_text LIKE 'Lab demo: savepoint%'", role="setup"),
                 Step("START TRANSACTION", "START TRANSACTION"),
                 Step("First INSERT",
                      "INSERT INTO question (created_by, question_text, question_type, marks, correct_answer)\n"
                      "VALUES (2, 'Lab demo: savepoint keep', 'TRUE_FALSE', 1, 'TRUE')"),
                 Step("SAVEPOINT", "SAVEPOINT after_first"),
                 Step("Second INSERT",
                      "INSERT INTO question (created_by, question_text, question_type, marks, correct_answer)\n"
                      "VALUES (2, 'Lab demo: savepoint discard', 'TRUE_FALSE', 1, 'FALSE')"),
                 Step("Both rows (temporary)",
                      "SELECT question_id, question_text FROM question WHERE question_text LIKE 'Lab demo: savepoint%'",
                      compare="rows"),
                 Step("ROLLBACK TO SAVEPOINT", "ROLLBACK TO SAVEPOINT after_first"),
                 Step("After partial rollback",
                      "SELECT question_id, question_text FROM question WHERE question_text LIKE 'Lab demo: savepoint%'",
                      compare="rows"),
                 Step("COMMIT", "COMMIT"),
                 Step("Persisted",
                      "SELECT question_id, question_text FROM question WHERE question_text LIKE 'Lab demo: savepoint%'",
                      role="after")),
                cleanup=(Step("Delete demo rows",
                              "DELETE FROM question WHERE question_text LIKE 'Lab demo: savepoint%'"),),
                tags=("SAVEPOINT",)),
        Example("tcl_error_rollback", "TCL", "An error does not end the transaction",
                "One statement fails mid-transaction; the earlier change is still pending until ROLLBACK.",
                "In MySQL a failed statement is rolled back on its own, but the transaction stays open with "
                "the earlier statements still pending. The application must issue ROLLBACK (OEMS does this "
                "for exam submission) so the whole unit of work is all-or-nothing.",
                (Step("Initial state", "SELECT exam_id, title FROM exam WHERE exam_id = 9", role="before",
                      compare="state"),
                 Step("START TRANSACTION", "START TRANSACTION"),
                 Step("First change succeeds",
                      "UPDATE exam SET title = CONCAT(title, ' [draft]') WHERE exam_id = 9"),
                 Step("Second change violates a CHECK",
                      "UPDATE exam SET duration_minutes = 0 WHERE exam_id = 9", expect_error=True),
                 Step("First change is still pending", "SELECT exam_id, title FROM exam WHERE exam_id = 9"),
                 Step("ROLLBACK the unit of work", "ROLLBACK"),
                 Step("Persisted state", "SELECT exam_id, title FROM exam WHERE exam_id = 9", role="after",
                      compare="state")),
                tags=("ROLLBACK", "atomicity")),
        Example("tcl_implicit_commit", "TCL", "DDL causes an implicit COMMIT",
                "ROLLBACK cannot undo work that a DDL statement already committed.",
                "CREATE TABLE (like most DDL) commits the open transaction before it runs. The UPDATE issued "
                "earlier becomes permanent, and the later ROLLBACK has nothing to undo.",
                (Step("Reset", "DROP TABLE IF EXISTS demo_implicit", role="setup"),
                 Step("Initial state", duration_q, role="before", compare="state"),
                 Step("START TRANSACTION", "START TRANSACTION"),
                 Step("UPDATE", toggle),
                 Step("DDL: CREATE TABLE (implicit COMMIT)", "CREATE TABLE demo_implicit (id INT PRIMARY KEY)"),
                 Step("ROLLBACK", "ROLLBACK"),
                 Step("State after ROLLBACK: the UPDATE survived", duration_q, role="after", compare="state")),
                cleanup=(Step("Drop demo table", "DROP TABLE IF EXISTS demo_implicit"),),
                min_role="ADMIN", tags=("implicit commit",)),
    ]

    # ================================================================== DCL
    demo = "%(demo_user)s@%(account_host)s"
    ex += [
        Example("dcl_grant_revoke", "DCL", "GRANT and REVOKE",
                "Create a demo account, grant SELECT on one table, use it, revoke it, verify.",
                "Privileges are checked by MySQL on every statement. The demo account can read lab.exam only "
                "after GRANT; UPDATE and other tables are denied (error 1142). After REVOKE even SELECT is "
                "denied — table-privilege changes apply to the very next statement of an open session.",
                (Step("Reset: remove an old demo account", f"DROP USER IF EXISTS {demo}", role="setup"),
                 Step("CREATE USER", f"CREATE USER {demo} IDENTIFIED BY %(demo_password)s"),
                 Step("GRANT SELECT on one table", f"GRANT SELECT ON `{{lab_db}}`.`exam` TO {demo}"),
                 Step("Demo account: its own privileges", "SHOW GRANTS", conn="demo", compare="grants"),
                 Step("Demo account: SELECT works",
                      "SELECT exam_id, title, status FROM `{lab_db}`.exam ORDER BY exam_id LIMIT 5", conn="demo"),
                 Step("Demo account: UPDATE is denied",
                      "UPDATE `{lab_db}`.exam SET title = 'hacked' WHERE exam_id = 1", conn="demo",
                      expect_error=True),
                 Step("Demo account: other tables are denied",
                      "SELECT student_id, email FROM `{lab_db}`.student LIMIT 1", conn="demo", expect_error=True),
                 Step("REVOKE", f"REVOKE SELECT ON `{{lab_db}}`.`exam` FROM {demo}"),
                 Step("Demo account: privileges after REVOKE", "SHOW GRANTS", conn="demo", compare="grants"),
                 Step("Demo account: SELECT now denied",
                      "SELECT exam_id, title FROM `{lab_db}`.exam LIMIT 1", conn="demo", expect_error=True),
                 Step("Remove the demo account", f"DROP USER {demo}", role="restore")),
                account="dcl",
                cleanup=(Step("Drop the demo account", f"DROP USER IF EXISTS {demo}"),),
                min_role="ADMIN", tags=("GRANT", "REVOKE")),
        Example("dcl_readonly_denied", "DCL", "Read-only account denied write access",
                "The API's SELECT-only account reads the main database but cannot change it.",
                "oems_reader has only SELECT on the application database. MySQL itself rejects every write "
                "with error 1142 — the security boundary does not depend on application code.",
                (Step("Privileges of this account", "SHOW GRANTS FOR CURRENT_USER()"),
                 Step("SELECT succeeds", "SELECT COUNT(*) AS students FROM student"),
                 Step("UPDATE is rejected", "UPDATE student SET student_name = 'changed' WHERE student_id = 1",
                      expect_error=True),
                 Step("DELETE is rejected", "DELETE FROM result WHERE result_id = 1", expect_error=True),
                 Step("DDL is rejected", "CREATE TABLE not_allowed (id INT)", expect_error=True)),
                target="main", account="reader", tags=("least privilege",)),
        Example("dcl_account_privileges", "DCL", "Privileges of every OEMS account",
                "Least privilege in practice: what each account used by the API may do.",
                "Each account is limited to the job it does: the reader can only SELECT the main database, "
                "the lab account has full rights but only inside the lab database.",
                (Step("Read-only account", "SHOW GRANTS FOR CURRENT_USER()", conn="reader"),
                 Step("Lab account", "SHOW GRANTS FOR CURRENT_USER()", conn="lab"),
                 Step("DCL demo account", "SHOW GRANTS FOR CURRENT_USER()", conn="dcl")),
                account="reader", target="main", min_role="ADMIN", tags=("SHOW GRANTS",)),
    ]

    # ================================================================== INDEXES
    window = ("FROM answer\n WHERE answered_at >= TIMESTAMP(CURDATE() - INTERVAL 40 DAY, '12:00:00')\n"
              "   AND answered_at <  TIMESTAMP(CURDATE() - INTERVAL 40 DAY, '13:00:00')")
    timed_query = f"SELECT COUNT(*) AS answers, ROUND(AVG(marks_obtained), 2) AS avg_marks\n  {window}"
    ex += [
        Example("idx_list", "INDEXES", "Indexes of a table",
                "Every index of attempt with its columns and uniqueness.",
                "PRIMARY is the clustered index (the table itself is stored in primary-key order). Secondary "
                "indexes store the indexed columns plus the primary key.",
                (Step("SHOW INDEX", "SHOW INDEX FROM attempt"),
                 Step("All indexes of the schema",
                      "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE,\n"
                      "       GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns_in_index\n"
                      "  FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()\n"
                      " GROUP BY TABLE_NAME, INDEX_NAME, NON_UNIQUE ORDER BY TABLE_NAME, INDEX_NAME")),
                target="main", account="reader", tags=("SHOW INDEX",)),
        Example("idx_explain_email", "INDEXES", "EXPLAIN: student lookup by email",
                "Compare an indexed lookup with the same lookup wrapped in a function.",
                "With email = ?, MySQL uses the unique index uq_student_email (type const, 1 row). Wrapping the "
                "column in LOWER() hides it from the index, forcing a full scan (type ALL).",
                (Step("Indexed lookup", "EXPLAIN SELECT * FROM student WHERE email = %(email)s", compare="plan"),
                 Step("Function on the column", "EXPLAIN SELECT * FROM student WHERE LOWER(email) = %(email)s",
                      compare="plan")),
                target="main", account="reader",
                params=(Param("email", "E-mail", "text", "aarav.shah@students.oems.edu", max_length=255),),
                tags=("EXPLAIN",)),
        Example("idx_explain_attempt", "INDEXES", "EXPLAIN: attempts by student and exam",
                "The composite unique index answers both filters; a filter on only the 2nd column cannot use it.",
                "uq_attempt_student_exam is (student_id, exam_id). A B+ tree is sorted by the leftmost column "
                "first, so it serves student_id (+ exam_id) lookups. The exam_id-only query uses another index "
                "that starts with exam_id.",
                (Step("Both columns", "EXPLAIN SELECT * FROM attempt WHERE student_id = 1 AND exam_id = 1",
                      compare="plan"),
                 Step("Second column only", "EXPLAIN SELECT * FROM attempt WHERE exam_id = 1", compare="plan")),
                target="main", account="reader", tags=("EXPLAIN", "composite index")),
        Example("idx_explain_analyze", "INDEXES", "EXPLAIN ANALYZE",
                "Execute a join + aggregation and show the real plan with measured times.",
                "EXPLAIN ANALYZE (MySQL 8.0.18+) runs the query and reports, per plan node, the estimated "
                "cost and the actual time and row counts.",
                (Step("EXPLAIN ANALYZE",
                      "EXPLAIN ANALYZE\nSELECT e.subject, COUNT(*) AS results, ROUND(AVG(r.percentage), 2) AS avg_pct\n"
                      "  FROM result r\n  JOIN attempt a ON a.attempt_id = r.attempt_id\n"
                      "  JOIN exam e    ON e.exam_id    = a.exam_id\n GROUP BY e.subject"),),
                target="main", account="reader", tags=("EXPLAIN ANALYZE",)),
        Example("idx_create_compare", "INDEXES", "CREATE INDEX: measured before/after",
                "Time a range query on answer.answered_at without and with an index.",
                "Each timed step runs the query once to warm caches, then 7 measured times; the median is "
                "compared. The verdict is computed from these measurements only — on small tables or warm "
                "caches the difference can be small.",
                (Step("Reset: drop the demo index if present", "DROP INDEX idx_demo_answer_answered_at ON answer",
                      role="setup", ignore_errors=(1091,)),
                 Step("Row count", "SELECT COUNT(*) AS answer_rows FROM answer", role="info"),
                 Step("Plan without index", f"EXPLAIN {timed_query}", role="before", compare="plan"),
                 Step("Timed without index", timed_query, role="before", repeat=7, timing_group="before"),
                 Step("CREATE INDEX", "CREATE INDEX idx_demo_answer_answered_at ON answer (answered_at)"),
                 Step("Plan with index", f"EXPLAIN {timed_query}", role="after", compare="plan"),
                 Step("Timed with index", timed_query, role="after", repeat=7, timing_group="after"),
                 Step("EXPLAIN ANALYZE with index", f"EXPLAIN ANALYZE {timed_query}", role="after")),
                cleanup=(Step("DROP INDEX", "DROP INDEX idx_demo_answer_answered_at ON answer",
                              ignore_errors=(1091,)),),
                min_role="ADMIN", tags=("CREATE INDEX",)),
        Example("idx_drop", "INDEXES", "DROP INDEX",
                "Remove the demo index and see the plan fall back to a full scan.",
                "DROP INDEX removes the B+ tree; queries keep working but must scan the table again.",
                (Step("Setup: make sure the demo index exists",
                      "CREATE INDEX idx_demo_answer_answered_at ON answer (answered_at)", role="setup",
                      ignore_errors=(1061,)),
                 Step("Plan before", f"EXPLAIN {timed_query}", role="before", compare="plan"),
                 Step("DROP INDEX", "DROP INDEX idx_demo_answer_answered_at ON answer"),
                 Step("Plan after", f"EXPLAIN {timed_query}", role="after", compare="plan")),
                destructive=True, min_role="ADMIN", tags=("DROP INDEX",)),
    ]
    return ex


@lru_cache
def catalog() -> dict[str, Example]:
    examples = _examples()
    ids = [e.id for e in examples]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate example id in the SQL lab catalog")
    return {e.id: e for e in examples}
