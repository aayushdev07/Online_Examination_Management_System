"""API integration tests (FastAPI TestClient -> real MySQL)."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine

from tests.conftest import PASSWORD, scalar


# --------------------------------------------------------------------------- helpers
def new_student(client) -> dict:
    tag = uuid.uuid4().hex[:8]
    r = client.post("/api/auth/register", json={"student_name": f"Test {tag}", "email": f"t{tag}@example.com",
                                               "username": f"t_{tag}", "password": PASSWORD})
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "h": {"Authorization": f"Bearer {body['access_token']}"}}


def db_now(admin_db):
    return scalar(admin_db, "SELECT NOW()")


def make_exam(client, faculty_h, admin_db, questions: list[dict], status="ACTIVE") -> int:
    now = db_now(admin_db)
    r = client.post("/api/exams", headers=faculty_h, json={
        "title": f"API test exam {uuid.uuid4().hex[:6]}", "subject": "Testing",
        "exam_date": (now - timedelta(hours=1)).isoformat(), "deadline": (now + timedelta(days=1)).isoformat(),
        "duration_minutes": 30, "pass_percentage": 50, "status": status})
    assert r.status_code == 201, r.text
    exam_id = r.json()["exam_id"]
    for q in questions:
        rq = client.post("/api/questions", headers=faculty_h, json=q)
        assert rq.status_code == 201, rq.text
        ra = client.post(f"/api/exams/{exam_id}/questions", headers=faculty_h,
                         json={"question_id": rq.json()["question_id"]})
        assert ra.status_code == 201, ra.text
    return exam_id


OBJECTIVE = [
    {"question_text": "2 + 2 = ?", "question_type": "MCQ", "options": ["3", "4", "5"], "marks": 2,
     "correct_answer": "4"},
    {"question_text": "MySQL is a DBMS.", "question_type": "TRUE_FALSE", "marks": 1, "correct_answer": "true"},
    {"question_text": "Keyword that removes duplicates?", "question_type": "SHORT_ANSWER", "marks": 2,
     "correct_answer": "DISTINCT"},
]


# --------------------------------------------------------------------------- health & auth
def test_health_checks_database(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"]["status"] == "up"
    assert r.headers["X-Request-ID"]


def test_health_reports_database_failure(client, monkeypatch, settings):
    from app.api.routers import system
    from app.db.engines import mysql_url

    broken = create_engine(mysql_url("nobody", "x", settings.db_name, settings).set(port=1),
                           connect_args={"connect_timeout": 2})
    monkeypatch.setattr(system, "app_engine", lambda: broken)
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["database"]["status"] == "down"


def test_register_and_validation(client):
    s = new_student(client)
    me = client.get("/api/auth/me", headers=s["h"])
    assert me.status_code == 200 and me.json()["role"] == "STUDENT"
    dup = client.post("/api/auth/register", json={"student_name": "X", "email": "aarav.shah@students.oems.edu",
                                                  "username": "brand_new_1", "password": PASSWORD})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_value"
    weak = client.post("/api/auth/register", json={"student_name": "X", "email": "w@example.com",
                                                   "username": "weak_pw", "password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "validation_error"


def test_login_failures_and_authorization(client, student_h):
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass1", "account_type": "STAFF"})
    assert bad.status_code == 401
    assert client.get("/api/students").status_code == 401
    assert client.get("/api/students", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/api/students", headers=student_h).status_code == 403
    assert client.get("/api/sql/examples", headers=student_h).status_code == 403
    assert client.post("/api/staff", headers=student_h, json={}).status_code in (403, 422)


def test_payload_size_limit(client, admin_h):
    r = client.post("/api/sql/execute", headers={**admin_h, "content-type": "application/json"},
                    content=b'{"sql": "' + b"x" * 300_000 + b'"}')
    assert r.status_code == 413


# --------------------------------------------------------------------------- CRUD
def test_exam_crud_and_audit(client, faculty_h, admin_h, admin_db):
    exam_id = make_exam(client, faculty_h, admin_db, OBJECTIVE[:1], status="SCHEDULED")
    exam = client.get(f"/api/exams/{exam_id}", headers=faculty_h).json()
    assert exam["question_count"] == 1 and exam["total_marks"] == 2
    r = client.put(f"/api/exams/{exam_id}", headers=faculty_h, json={"duration_minutes": 45})
    assert r.status_code == 200 and r.json()["duration_minutes"] == 45
    audit = client.get(f"/api/exams/{exam_id}/audit", headers=faculty_h).json()
    assert [a["action"] for a in audit][:2] == ["UPDATE", "INSERT"]
    assert audit[0]["old_duration"] == 30 and audit[0]["new_duration"] == 45
    # window too short for the duration
    r = client.put(f"/api/exams/{exam_id}", headers=faculty_h, json={"duration_minutes": 600,
                   "deadline": exam["exam_date"]})
    assert r.status_code == 422
    # duplicate assignment -> PK violation -> 409
    qid = client.get(f"/api/exams/{exam_id}/questions", headers=faculty_h).json()["questions"][0]["question_id"]
    assert client.post(f"/api/exams/{exam_id}/questions", headers=faculty_h,
                       json={"question_id": qid}).status_code == 409
    # another faculty member cannot edit; admin can
    other = client.post("/api/auth/login", json={"username": "aiyer", "password": PASSWORD, "account_type": "STAFF"})
    other_h = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.put(f"/api/exams/{exam_id}", headers=other_h, json={"title": "x"}).status_code == 403
    assert client.delete(f"/api/exams/{exam_id}", headers=admin_h).status_code == 204
    assert client.get(f"/api/exams/{exam_id}", headers=faculty_h).status_code == 404


def test_question_validation_and_fk_protection(client, faculty_h):
    bad = client.post("/api/questions", headers=faculty_h, json={
        "question_text": "q", "question_type": "MCQ", "options": ["a", "b"], "marks": 1, "correct_answer": "c"})
    assert bad.status_code == 422
    # question 1 is assigned to exam 1 -> FK blocks the delete
    assert client.delete("/api/questions/1", headers={**faculty_h}).status_code == 409


def test_cannot_delete_student_with_history(client, admin_h):
    r = client.delete("/api/students/1", headers=admin_h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "row_referenced"


# --------------------------------------------------------------------------- exam workflow
def test_student_attempt_flow(client, faculty_h, admin_db):
    exam_id = make_exam(client, faculty_h, admin_db, OBJECTIVE)
    s = new_student(client)
    listed = {e["exam_id"]: e for e in client.get("/api/exams", headers=s["h"]).json()}
    assert listed[exam_id]["can_start"] is True

    r = client.post(f"/api/exams/{exam_id}/attempts", headers=s["h"])
    assert r.status_code == 201
    attempt_id = r.json()["attempt_id"]
    assert client.post(f"/api/exams/{exam_id}/attempts", headers=s["h"]).json()["resumed"] is True

    detail = client.get(f"/api/attempts/{attempt_id}", headers=s["h"]).json()
    assert "correct_answer" not in detail["questions"][0]          # answer key hidden
    q = {x["question_type"]: x["question_id"] for x in detail["questions"]}
    bad = client.put(f"/api/attempts/{attempt_id}/answers", headers=s["h"],
                     json={"answers": [{"question_id": q["MCQ"], "selected_answer": "7"}]})
    assert bad.status_code == 422
    ok = client.put(f"/api/attempts/{attempt_id}/answers", headers=s["h"], json={"answers": [
        {"question_id": q["MCQ"], "selected_answer": "4"},
        {"question_id": q["TRUE_FALSE"], "selected_answer": "TRUE"},
        {"question_id": q["SHORT_ANSWER"], "selected_answer": "  distinct "}]})
    assert ok.status_code == 200 and ok.json()["saved"] == 3

    sub = client.post(f"/api/attempts/{attempt_id}/submit", headers=s["h"])
    assert sub.status_code == 200 and sub.json()["status"] == "EVALUATED"
    assert client.post(f"/api/attempts/{attempt_id}/submit", headers=s["h"]).status_code == 409
    assert client.put(f"/api/attempts/{attempt_id}/answers", headers=s["h"], json={"answers": [
        {"question_id": q["MCQ"], "selected_answer": "3"}]}).status_code == 409

    assert client.get(f"/api/attempts/{attempt_id}/result", headers=s["h"]).status_code == 403   # not released
    assert client.post(f"/api/exams/{exam_id}/release", headers=faculty_h, json={"released": True}).status_code == 200
    result = client.get(f"/api/attempts/{attempt_id}/result", headers=s["h"]).json()
    assert result["marks_obtained"] == 5 and result["percentage"] == 100 and result["result_status"] == "PASS"
    revealed = client.get(f"/api/attempts/{attempt_id}", headers=s["h"]).json()
    assert revealed["answers_revealed"] and revealed["questions"][0]["correct_answer"]


def test_manual_grading_flow(client, faculty_h, admin_db):
    long_q = {"question_text": "Explain ACID.", "question_type": "LONG_ANSWER", "marks": 5}
    exam_id = make_exam(client, faculty_h, admin_db, [OBJECTIVE[0], long_q])
    s = new_student(client)
    attempt_id = client.post(f"/api/exams/{exam_id}/attempts", headers=s["h"]).json()["attempt_id"]
    qs = client.get(f"/api/attempts/{attempt_id}", headers=s["h"]).json()["questions"]
    long_id = next(x["question_id"] for x in qs if x["question_type"] == "LONG_ANSWER")
    client.put(f"/api/attempts/{attempt_id}/answers", headers=s["h"],
               json={"answers": [{"question_id": long_id, "selected_answer": "Atomicity, consistency..."}]})
    sub = client.post(f"/api/attempts/{attempt_id}/submit", headers=s["h"]).json()
    assert sub["status"] == "SUBMITTED" and sub["pending_manual_grading"] == 1
    too_high = client.post(f"/api/attempts/{attempt_id}/grade", headers=faculty_h,
                           json={"grades": [{"question_id": long_id, "marks_obtained": 6}]})
    assert too_high.status_code == 422
    graded = client.post(f"/api/attempts/{attempt_id}/grade", headers=faculty_h,
                         json={"grades": [{"question_id": long_id, "marks_obtained": 3.5}]}).json()
    assert graded["status"] == "EVALUATED"
    result = client.get(f"/api/attempts/{attempt_id}/result", headers=faculty_h).json()
    assert result["marks_obtained"] == 3.5 and result["percentage"] == 50 and result["result_status"] == "PASS"


def test_concurrent_submissions_only_one_wins(client, faculty_h, admin_db):
    exam_id = make_exam(client, faculty_h, admin_db, OBJECTIVE[:2])
    s = new_student(client)
    attempt_id = client.post(f"/api/exams/{exam_id}/attempts", headers=s["h"]).json()["attempt_id"]
    codes, barrier = [], threading.Barrier(8)

    def submit():
        barrier.wait()
        codes.append(client.post(f"/api/attempts/{attempt_id}/submit", headers=s["h"]).status_code)

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200] + [409] * 7
    assert scalar(admin_db, "SELECT COUNT(*) FROM result WHERE attempt_id = %s", (attempt_id,)) == 1


def test_concurrent_starts_create_one_attempt(client, faculty_h, admin_db):
    exam_id = make_exam(client, faculty_h, admin_db, OBJECTIVE[:1])
    s = new_student(client)
    ids, barrier = [], threading.Barrier(6)

    def start():
        barrier.wait()
        r = client.post(f"/api/exams/{exam_id}/attempts", headers=s["h"])
        ids.append((r.status_code, r.json().get("attempt_id")))

    threads = [threading.Thread(target=start) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({i for _, i in ids}) == 1 and [c for c, _ in ids].count(201) == 1
    assert scalar(admin_db, "SELECT COUNT(*) FROM attempt WHERE exam_id = %s", (exam_id,)) == 1


def test_closed_exam_cannot_be_started(client, student_h):
    exams = client.get("/api/exams", headers=student_h).json()
    scheduled = next(e for e in exams if e["status"] == "SCHEDULED")
    r = client.post(f"/api/exams/{scheduled['exam_id']}/attempts", headers=student_h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "exam_not_open"


# --------------------------------------------------------------------------- SQL lab
def test_every_catalog_example_runs(client, admin_h):
    examples = client.get("/api/sql/examples", headers=admin_h).json()["examples"]
    failures = []
    for e in examples:
        r = client.post("/api/sql/execute", headers=admin_h, json={"example_id": e["id"], "confirm": True})
        if r.status_code != 200 or r.json()["status"] != "success":
            failures.append((e["id"], r.status_code, r.text[:300]))
            continue
        if any(s["status"] == "unexpected_success" for s in r.json()["steps"]):
            failures.append((e["id"], "a step expected to fail succeeded"))
        if e["has_cleanup"]:
            c = client.post("/api/sql/execute", headers=admin_h, json={"example_id": e["id"], "action": "cleanup"})
            if c.status_code != 200 or c.json()["status"] != "success":
                failures.append((e["id"], "cleanup", c.text[:300]))
    assert not failures, failures


def test_sql_execution_restrictions(client, admin_h, faculty_h):
    assert client.post("/api/sql/execute", headers=faculty_h, json={"sql": "SELECT 1"}).status_code == 403
    assert client.post("/api/sql/execute", headers=faculty_h,
                       json={"example_id": "ddl_drop", "confirm": True}).status_code == 403   # ADMIN example
    assert client.post("/api/sql/execute", headers=admin_h,
                       json={"example_id": "ddl_drop"}).status_code == 409                  # needs confirm
    for sql in ("SELECT * FROM mysql.user", "GRANT ALL ON *.* TO x", "SELECT 1; DROP DATABASE x",
                "SET GLOBAL max_connections = 1", "SELECT SLEEP(2)", "USE oems_test",
                "SELECT * INTO OUTFILE '/tmp/x' FROM exam", "LOAD DATA INFILE 'x' INTO TABLE exam"):
        r = client.post("/api/sql/execute", headers=admin_h, json={"sql": sql, "confirm": True})
        assert r.status_code in (403, 422), (sql, r.status_code, r.text)
    r = client.post("/api/sql/execute", headers=admin_h, json={"sql": "DELETE FROM exam_audit WHERE 1 = 0"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirmation_required"
    r = client.post("/api/sql/execute", headers=admin_h,
                    json={"sql": "START TRANSACTION; UPDATE exam SET title = 'x' WHERE exam_id = 9; ROLLBACK; "
                                 "SELECT title FROM exam WHERE exam_id = 9", "confirm": True}).json()
    assert r["status"] == "success" and r["steps"][-1]["result_sets"][0]["rows"][0][0] != "x"
    history = client.get("/api/sql/history?status=REJECTED", headers=admin_h).json()
    assert history["total"] >= 1


def test_read_only_account_rejects_writes_through_example(client, faculty_h):
    r = client.post("/api/sql/execute", headers=faculty_h, json={"example_id": "dcl_readonly_denied"}).json()
    denied = [s for s in r["steps"] if s["status"] == "expected_error"]
    assert len(denied) == 3 and all(s["error"]["code"] == 1142 for s in denied)


def test_explain_and_routines(client, faculty_h):
    r = client.post("/api/db/explain", headers=faculty_h,
                    json={"sql": "SELECT * FROM student WHERE email = 'x@y.z'", "analyze": True})
    assert r.status_code == 200 and {"table", "tree", "analyze"} <= set(r.json()["plans"])
    assert client.post("/api/db/explain", headers=faculty_h, json={"sql": "DELETE FROM student"}).status_code == 422
    call = client.post("/api/db/routines/GetExamDetails/call", headers=faculty_h, json={"args": [1]}).json()
    assert call["status"] == "success" and len(call["result_sets"]) == 2
    out = client.post("/api/db/routines/sp_exam_attempt_stats/call", headers=faculty_h, json={"args": [1]}).json()
    assert out["status"] == "success" and out["result_sets"][-1]["columns"] == ["p_total", "p_evaluated", "p_avg_pct"]
    blocked = client.post("/api/db/routines/sp_finalize_attempt/call", headers=faculty_h, json={"args": [1]})
    assert blocked.status_code == 403


# --------------------------------------------------------------------------- metadata, reports, metrics
def test_schema_explorer_and_table_viewer(client, faculty_h):
    schema = client.get("/api/db/schema?database=main", headers=faculty_h).json()
    names = {t["name"] for t in schema["tables"]}
    assert {"student", "faculty_admin", "exam", "question", "exam_question", "attempt", "answer", "result",
            "exam_audit", "sql_execution_log", "exam_overview", "student_result_view",
            "exam_performance_view"} <= names
    assert any(r["name"] == "fk_answer_exam_question" for r in schema["relationships"])
    objects = client.get("/api/db/objects?database=main", headers=faculty_h).json()
    assert len(objects["triggers"]) == 8 and all(r["definition_visible"] for r in objects["routines"])
    rows = client.get("/api/db/tables/student/rows?database=main&page_size=5", headers=faculty_h).json()
    assert rows["total"] > 300 and all(r[rows["columns"].index("password_hash")] == "(hidden)" for r in rows["rows"])
    assert client.get("/api/db/tables/nope/rows", headers=faculty_h).status_code == 404


def test_reports_and_metrics(client, faculty_h):
    for report in client.get("/api/reports", headers=faculty_h).json():
        r = client.get(f"/api/reports/{report['id']}", headers=faculty_h)
        assert r.status_code == 200, report["id"]
    metrics = client.get("/api/metrics", headers=faculty_h).json()
    assert metrics["api"]["total_requests"] > 0 and metrics["db"]["total_queries"] > 0
    db = client.get("/api/db/metrics", headers=faculty_h).json()
    assert all(p["status"] == "up" for p in db["connectivity"].values())


@pytest.mark.slow
def test_lab_reset(client, admin_h, faculty_h):
    assert client.post("/api/sql/lab/reset", headers=faculty_h).status_code == 403
    r = client.post("/api/sql/lab/reset", headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "reset"
    after = client.post("/api/sql/execute", headers=faculty_h, json={"example_id": "trg_definitions"}).json()
    assert after["status"] == "success" and after["steps"][0]["result_sets"][0]["row_count"] == 8
