"""Database-level tests: constraints, views, triggers, routines, transactions, privileges, plans.

These run directly against MySQL (no API) to prove the rules live in the database.
"""

import pymysql
import pytest

from tests.conftest import connect_as, mysql_errno, scalar


# --------------------------------------------------------------------------- constraints
def test_duplicate_email_rejected(admin_db):
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:
        cur.execute("INSERT INTO student (student_name, email, username, password_hash) "
                    "VALUES ('Dup', 'aarav.shah@students.oems.edu', 'dup_user_1', 'x')")
    assert mysql_errno(exc) == 1062 and "uq_student_email" in exc.value.args[1]


def test_foreign_key_violations(admin_db):
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:
        cur.execute("INSERT INTO attempt (student_id, exam_id) VALUES (99999999, 1)")
    assert mysql_errno(exc) == 1452
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:
        cur.execute("DELETE FROM exam WHERE exam_id = 1")
    assert mysql_errno(exc) == 1451


def test_answer_must_belong_to_attempt_exam(admin_db):
    """Composite FK: the answered question must be assigned to the attempt's exam."""
    attempt_id = scalar(admin_db, "SELECT attempt_id FROM attempt WHERE exam_id = 5 AND status = 'IN_PROGRESS' LIMIT 1")
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:
        cur.execute("INSERT INTO answer (attempt_id, exam_id, question_id) VALUES (%s, 5, 1)", (attempt_id,))
    assert mysql_errno(exc) == 1452 and "fk_answer_exam_question" in exc.value.args[1]
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:  # lie about the exam
        cur.execute("INSERT INTO answer (attempt_id, exam_id, question_id) VALUES (%s, 1, 1)", (attempt_id,))
    assert mysql_errno(exc) == 1452


@pytest.mark.parametrize("sql", [
    "UPDATE exam SET duration_minutes = 0 WHERE exam_id = 7",
    "UPDATE exam SET duration_minutes = 601 WHERE exam_id = 7",
    "UPDATE exam SET duration_minutes = 500 WHERE exam_id = 9",          # longer than the 2 h window
    "UPDATE exam SET deadline = exam_date WHERE exam_id = 9",
    "UPDATE question SET marks = 0 WHERE question_id = 1",
    "UPDATE exam_question SET marks_assigned = -1 WHERE exam_id = 1 AND question_id = 1",
    "UPDATE result SET percentage = 100.01 WHERE result_id = 1",
    "UPDATE answer SET marks_obtained = -1 WHERE answer_id = 1",
    "INSERT INTO question (created_by, question_text, question_type, options, marks, correct_answer) "
    "VALUES (2, 'q', 'MCQ', JSON_ARRAY('one'), 1, 'one')",
    "INSERT INTO question (created_by, question_text, question_type, marks, correct_answer) "
    "VALUES (2, 'q', 'TRUE_FALSE', 1, 'MAYBE')",
    "INSERT INTO student (student_name, email, username, password_hash) VALUES ('X', 'not-an-email', 'abc_x', 'h')",
])
def test_check_constraints(admin_db, sql):
    with pytest.raises(pymysql.MySQLError) as exc, admin_db.cursor() as cur:
        cur.execute(sql)
    assert mysql_errno(exc) == 3819


def test_not_null_and_defaults(admin_db):
    with pytest.raises(pymysql.MySQLError) as exc, admin_db.cursor() as cur:
        cur.execute("INSERT INTO exam (created_by, title, subject, exam_date, deadline, duration_minutes) "
                    "VALUES (2, NULL, 'S', NOW(), NOW() + INTERVAL 1 DAY, 30)")
    assert mysql_errno(exc) == 1048
    admin_db.begin()
    with admin_db.cursor() as cur:
        cur.execute("INSERT INTO exam (created_by, title, subject, exam_date, deadline, duration_minutes) "
                    "VALUES (2, 'Defaults', 'S', NOW(), NOW() + INTERVAL 1 DAY, 30)")
        cur.execute("SELECT status, total_marks, pass_percentage, results_released FROM exam WHERE exam_id = %s",
                    (cur.lastrowid,))
        assert cur.fetchone() == ("SCHEDULED", 0, 40, 0)
    admin_db.rollback()


def test_duplicate_attempt_and_result_rejected(admin_db):
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:
        cur.execute("INSERT INTO attempt (student_id, exam_id) VALUES (1, 1)")
    assert mysql_errno(exc) == 1062
    with pytest.raises(pymysql.IntegrityError) as exc, admin_db.cursor() as cur:
        cur.execute("INSERT INTO result (attempt_id, marks_obtained, percentage, result_status) "
                    "SELECT attempt_id, 1, 1, 'FAIL' FROM result LIMIT 1")
    assert mysql_errno(exc) == 1062


# --------------------------------------------------------------------------- views
def test_views_match_base_tables(admin_db):
    assert scalar(admin_db, "SELECT COUNT(*) FROM student_result_view") == scalar(admin_db, "SELECT COUNT(*) FROM result")
    with admin_db.cursor() as cur:
        cur.execute("""SELECT v.exam_id, v.evaluated_count, v.avg_percentage,
                              (SELECT COUNT(*) FROM result r JOIN attempt a ON a.attempt_id = r.attempt_id
                                WHERE a.exam_id = v.exam_id),
                              (SELECT ROUND(AVG(r.percentage), 2) FROM result r
                                 JOIN attempt a ON a.attempt_id = r.attempt_id WHERE a.exam_id = v.exam_id)
                         FROM exam_performance_view v""")
        for exam_id, evaluated, avg, expected_count, expected_avg in cur.fetchall():
            assert evaluated == expected_count and avg == expected_avg, exam_id
        cur.execute("SELECT exam_id, question_count FROM exam_overview")
        for exam_id, count in cur.fetchall():
            assert count == scalar(admin_db, "SELECT COUNT(*) FROM exam_question WHERE exam_id = %s", (exam_id,))


# --------------------------------------------------------------------------- triggers
def test_audit_trigger_records_old_and_new(admin_db):
    before = scalar(admin_db, "SELECT COUNT(*) FROM exam_audit WHERE exam_id = 7")
    old = scalar(admin_db, "SELECT duration_minutes FROM exam WHERE exam_id = 7")
    with admin_db.cursor() as cur:
        cur.execute("UPDATE exam SET duration_minutes = %s WHERE exam_id = 7", (old + 1,))
        cur.execute("SELECT action, changed_columns, old_duration, new_duration FROM exam_audit "
                    "WHERE exam_id = 7 ORDER BY audit_id DESC LIMIT 1")
        assert cur.fetchone() == ("UPDATE", "duration_minutes", old, old + 1)
        cur.execute("UPDATE exam SET duration_minutes = %s WHERE exam_id = 7", (old + 1,))   # no change
    assert scalar(admin_db, "SELECT COUNT(*) FROM exam_audit WHERE exam_id = 7") == before + 1
    with admin_db.cursor() as cur:
        cur.execute("UPDATE exam SET duration_minutes = %s WHERE exam_id = 7", (old,))


def test_trigger_write_rolls_back_with_transaction(settings):
    conn = connect_as(settings, "app", autocommit=False)
    try:
        before = scalar(conn, "SELECT COUNT(*) FROM exam_audit")
        with conn.cursor() as cur:
            cur.execute("UPDATE exam SET duration_minutes = duration_minutes + 1 WHERE exam_id = 9")
        assert scalar(conn, "SELECT COUNT(*) FROM exam_audit") == before + 1
        conn.rollback()
        assert scalar(conn, "SELECT COUNT(*) FROM exam_audit") == before
    finally:
        conn.close()


def test_total_marks_maintained_by_triggers(admin_db):
    with admin_db.cursor() as cur:
        cur.execute("""SELECT e.exam_id FROM exam e
                        WHERE e.total_marks <> (SELECT COALESCE(SUM(marks_assigned), 0)
                                                  FROM exam_question eq WHERE eq.exam_id = e.exam_id)""")
        assert cur.fetchall() == ()
        cur.execute("INSERT INTO exam_question VALUES (9, 56, 1, 2.5)")
        assert scalar(admin_db, "SELECT total_marks FROM exam WHERE exam_id = 9") == 2.5
        cur.execute("DELETE FROM exam_question WHERE exam_id = 9 AND question_id = 56")
        assert scalar(admin_db, "SELECT total_marks FROM exam WHERE exam_id = 9") == 0


def test_answer_trigger_rules(admin_db):
    with pytest.raises(pymysql.MySQLError) as exc, admin_db.cursor() as cur:
        cur.execute("UPDATE answer SET selected_answer = 'changed' WHERE attempt_id = 1 AND question_id = 1")
    assert mysql_errno(exc) == 1644
    with pytest.raises(pymysql.MySQLError) as exc, admin_db.cursor() as cur:
        cur.execute("UPDATE answer SET marks_obtained = 99 WHERE attempt_id = 1 AND question_id = 1")
    assert mysql_errno(exc) == 1644


# --------------------------------------------------------------------------- routines
def test_get_exam_details_returns_two_result_sets(admin_db):
    with admin_db.cursor() as cur:
        cur.execute("CALL GetExamDetails(1)")
        summary = cur.fetchall()
        assert cur.nextset()
        questions = cur.fetchall()
        while cur.nextset():
            pass
    assert summary[0][0] == 1 and len(questions) == 10


def test_routine_errors_and_function(admin_db):
    with pytest.raises(pymysql.MySQLError) as exc, admin_db.cursor() as cur:
        cur.execute("CALL GetExamDetails(424242)")
    assert mysql_errno(exc) == 1644 and "does not exist" in exc.value.args[1]
    assert float(scalar(admin_db, "SELECT fn_marks_percentage(13.5, 17)")) == pytest.approx(79.41)
    assert scalar(admin_db, "SELECT fn_marks_percentage(5, 0)") == 0
    assert scalar(admin_db, "SELECT fn_marks_percentage(20, 10)") == 100
    assert scalar(admin_db, "SELECT fn_marks_percentage(NULL, 10)") is None
    assert scalar(admin_db, "SELECT fn_result_status(39.99, 40)") == "FAIL"


def test_out_parameters(admin_db):
    with admin_db.cursor() as cur:
        cur.execute("CALL sp_exam_attempt_stats(1, @t, @e, @a)")
        cur.execute("SELECT @t, @e")
        total, evaluated = cur.fetchone()
    assert total == scalar(admin_db, "SELECT COUNT(*) FROM attempt WHERE exam_id = 1") and evaluated <= total


def test_finalize_procedure_requires_grading(admin_db):
    attempt_id = scalar(admin_db, "SELECT MIN(attempt_id) FROM attempt WHERE status = 'SUBMITTED'")
    admin_db.begin()
    try:
        with pytest.raises(pymysql.MySQLError) as exc, admin_db.cursor() as cur:
            cur.execute("CALL sp_finalize_attempt(%s)", (attempt_id,))
        assert "not graded" in exc.value.args[1]
        with admin_db.cursor() as cur:
            cur.execute("UPDATE answer SET marks_obtained = 1 WHERE attempt_id = %s AND marks_obtained IS NULL",
                        (attempt_id,))
            cur.execute("CALL sp_finalize_attempt(%s)", (attempt_id,))
        assert scalar(admin_db, "SELECT status FROM attempt WHERE attempt_id = %s", (attempt_id,)) == "EVALUATED"
        assert scalar(admin_db, "SELECT COUNT(*) FROM result WHERE attempt_id = %s", (attempt_id,)) == 1
    finally:
        admin_db.rollback()
    assert scalar(admin_db, "SELECT status FROM attempt WHERE attempt_id = %s", (attempt_id,)) == "SUBMITTED"


# --------------------------------------------------------------------------- transactions
def test_commit_rollback_savepoint(settings):
    conn = connect_as(settings, "app", autocommit=False)
    observer = connect_as(settings, "app")
    try:
        original = scalar(conn, "SELECT title FROM exam WHERE exam_id = 9")
        with conn.cursor() as cur:
            cur.execute("UPDATE exam SET title = 'T1' WHERE exam_id = 9")
            cur.execute("SAVEPOINT s1")
            cur.execute("UPDATE exam SET title = 'T2' WHERE exam_id = 9")
            assert scalar(conn, "SELECT title FROM exam WHERE exam_id = 9") == "T2"
            assert scalar(observer, "SELECT title FROM exam WHERE exam_id = 9") == original  # isolation
            cur.execute("ROLLBACK TO SAVEPOINT s1")
            assert scalar(conn, "SELECT title FROM exam WHERE exam_id = 9") == "T1"
        conn.rollback()
        assert scalar(observer, "SELECT title FROM exam WHERE exam_id = 9") == original
        with conn.cursor() as cur:
            cur.execute("UPDATE exam SET title = 'Committed title' WHERE exam_id = 9")
        conn.commit()
        assert scalar(observer, "SELECT title FROM exam WHERE exam_id = 9") == "Committed title"
        with conn.cursor() as cur:
            cur.execute("UPDATE exam SET title = %s WHERE exam_id = 9", (original,))
        conn.commit()
    finally:
        conn.close()
        observer.close()


# --------------------------------------------------------------------------- privileges
def test_reader_is_read_only(settings):
    conn = connect_as(settings, "reader")
    try:
        assert scalar(conn, "SELECT COUNT(*) FROM student") > 0
        for sql in ("UPDATE student SET student_name = 'x' WHERE student_id = 1",
                    "DELETE FROM result WHERE result_id = 1", "CREATE TABLE nope (id INT)"):
            with pytest.raises(pymysql.MySQLError) as exc, conn.cursor() as cur:
                cur.execute(sql)
            assert mysql_errno(exc) == 1142
        with conn.cursor() as cur:  # read-only routine allowed
            cur.execute("CALL GetStudentResults(1)")
            assert cur.fetchall()
            while cur.nextset():
                pass
        with pytest.raises(pymysql.MySQLError) as exc, conn.cursor() as cur:
            cur.execute("CALL sp_finalize_attempt(1)")
        assert mysql_errno(exc) == 1370   # execute command denied
    finally:
        conn.close()


def test_lab_account_cannot_touch_main_database(settings):
    conn = connect_as(settings, "lab", database=settings.lab_db_name)
    try:
        with pytest.raises(pymysql.MySQLError) as exc, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM `{settings.db_name}`.student")
        assert mysql_errno(exc) == 1142
    finally:
        conn.close()


# --------------------------------------------------------------------------- indexes / plans
def test_email_lookup_uses_unique_index(settings):
    conn = connect_as(settings, "reader")
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("EXPLAIN SELECT * FROM student WHERE email = 'aarav.shah@students.oems.edu'")
            plan = cur.fetchone()
            assert plan["key"] == "uq_student_email" and plan["type"] == "const"
            cur.execute("EXPLAIN SELECT * FROM student WHERE LOWER(email) = 'aarav.shah@students.oems.edu'")
            assert cur.fetchone()["type"] == "ALL"
    finally:
        conn.close()
