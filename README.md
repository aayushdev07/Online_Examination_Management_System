# OEMS — Online Examination Management System + Interactive DBMS Lab

A database-driven web application in which students take online examinations, faculty
create and grade them, and administrators manage the system — plus a **DBMS lab** where
every SQL concept (DDL, DML, DQL, joins, subqueries, constraints, views, triggers,
procedures, transactions, permissions, indexes) is executed against a real MySQL server
and the genuine results, errors and timings are shown on screen.

| Layer | Technology |
|---|---|
| Frontend | React 19 + TypeScript, Vite, Tailwind CSS, React Router |
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyMySQL, bcrypt, JWT |
| Database | MySQL 8.0.16+ (InnoDB) |
| Tests | Pytest (real MySQL), Vitest + Testing Library |

Architecture, ER diagram and integrity rules: **[docs/architecture.md](docs/architecture.md)**.

---

## 1. Project structure

```
oems/
├── .env.example                 configuration template (copy to .env)
├── database/                    the single source of truth for the schema
│   ├── schema.sql               10 tables, keys, UNIQUE / NOT NULL / CHECK / DEFAULT
│   ├── indexes.sql              secondary indexes
│   ├── views.sql                exam_overview, student_result_view, exam_performance_view
│   ├── procedures.sql           GetExamDetails, GetStudentResults, sp_exam_attempt_stats,
│   │                            sp_finalize_attempt, fn_marks_percentage, fn_result_status
│   ├── triggers.sql             exam audit, total-marks maintenance, answer integrity
│   ├── seed_procedures.sql      deterministic synthetic-data generators
│   ├── seed.sql                 core data (staff, students, exams, 60 questions, attempts)
│   ├── reports.sql              10 analytical queries (window functions, CTEs, anti-joins…)
│   └── users.sql                DCL reference for the MySQL accounts
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, middleware (request id, size limit, metrics)
│   │   ├── core/                settings, security, errors, logging, metrics, rate limits
│   │   ├── db/                  engines per MySQL account, ORM models, SQL loader, initializer
│   │   ├── schemas/             Pydantic request validation
│   │   ├── services/            exam workflow, SQL-lab catalog/executor/policy, metadata, log
│   │   └── api/routers/         auth, users, exams, questions, attempts, results,
│   │                            sql_lab, db_meta, system
│   ├── alembic/                 migration 0001 applies database/*.sql
│   ├── scripts/init_db.py       one-command database setup
│   ├── scripts/load_test.py     dependency-free load test (scripts/locustfile.py for Locust)
│   └── tests/                   49 pytest tests against MySQL
├── frontend/
│   ├── src/pages/               18 pages (see section 7)
│   ├── src/components/          UI kit, result grid, ER diagram, layout
│   ├── src/lib/                 API client, auth context, hooks, types
│   └── src/test/                Vitest tests
└── docs/architecture.md         architecture, ER diagram, transaction flow
```

## 2. Prerequisites

* **MySQL Server 8.0.16 or newer** (8.0.18+ for `EXPLAIN ANALYZE`, 8.0.20+ for `SHOW_ROUTINE`), running, with an administrator account (usually `root`).
* **Python 3.11+** (tested with 3.13).
* **Node.js 20+** (tested with 22).

## 3. Setup

### 3.1 Configure

```bash
cp .env.example .env            # Windows: copy .env.example .env
```

Edit `.env`: set `MYSQL_ADMIN_PASSWORD` to your MySQL root password, choose passwords for
the four OEMS accounts and set a long random `JWT_SECRET`. Nothing else needs to change.

### 3.2 Backend + database

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/init_db.py
```

`init_db.py` performs, and prints, seven steps:

1. checks the MySQL version and sets `log_bin_trust_function_creators = 1` (needed so the non-SUPER lab account can create functions/triggers when binary logging is on);
2. creates the databases `oems_db` and `oems_lab`;
3. creates the accounts `oems_app`, `oems_reader`, `oems_lab`, `oems_lab_dcl` and grants their privileges;
4. runs `alembic upgrade head` (schema, indexes, views, routines, triggers) and routine-level grants;
5. seeds core data + 3,000 synthetic students (≈ 8,400 attempts, ≈ 67,000 answers, ≈ 8,400 results);
6. builds the lab database **with the lab account itself**;
7. connects with every API account to verify the setup.

Rebuild everything from scratch at any time with `python scripts/init_db.py --reset`.

Manual alternative (MySQL client): run the files in `database/` in this order —
`schema, indexes, views, procedures, triggers, seed_procedures, seed` — then
`CALL sp_generate_bulk_data(3000);` and the statements in `users.sql`.

### 3.3 Start

Two terminals:

```bash
# terminal 1 — API on http://127.0.0.1:8000   (Swagger UI: http://127.0.0.1:8000/docs)
cd backend
uvicorn app.main:app --reload --port 8000

# terminal 2 — web app on http://localhost:5173
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to the API, so the browser talks to one origin.
Production build: `npm run build && npm run preview` (also proxies `/api`).

### 3.4 Demo accounts (password `Password@123` for all)

| Role | Username | Notes |
|---|---|---|
| Administrator | `admin` | everything, incl. users, free-form SQL, lab reset |
| Faculty | `rdeshpande` | authored DBMS and Networks exams (Networks has 7 attempts waiting for grading) |
| Faculty | `aiyer` | authored OS, Data Structures, Discrete Maths, Python exams |
| Student | `aarav.shah` | has released results; two ACTIVE exams are open to attempt |
| Student | `kabir.malhotra`, `aditi.verma` | no attempts yet (fresh accounts for a live demo) |

Students can also self-register on the sign-in page.

## 4. Tests

```bash
cd backend && pytest            # 49 tests, ~15 s
cd frontend && npm test         # 11 tests
cd frontend && npm run typecheck
```

The backend suite creates **its own databases** `oems_test` and `oems_lab_test`
(administrator credentials from `.env`), runs against real MySQL and drops them at the
end; it never touches `oems_db`. If MySQL is unreachable the suite is reported as
*skipped*, never as passed.

**Results of the last run (MySQL 8.0.46, Python 3.13, Node 22):** backend 49 passed,
0 failed; frontend 11 passed, 0 failed; TypeScript build clean.

What the backend tests cover: duplicate-email rejection; foreign-key violations in both
directions and the composite answer→exam FK; 11 CHECK-constraint violations; NOT NULL
and DEFAULT; duplicate attempt/result rejection; view correctness against base tables;
audit trigger OLD/NEW values (and no row for a no-op update); trigger writes rolled back
with their transaction; total-marks triggers; answer-lock triggers; procedures with two
result sets, SIGNAL errors, OUT parameters and finalization; COMMIT / ROLLBACK /
SAVEPOINT with a second session; read-only account denied writes (1142) and denied
`sp_finalize_attempt` (1370); lab account denied the main database; EXPLAIN index usage;
health check with a broken database (503); register/login/authorization; payload size
limit; exam CRUD with audit; question validation; full student flow (start, resume,
save, invalid option, submit, double submit, locked answers, release, revealed key);
manual grading; **8 concurrent submits → exactly one 200 and one result**;
**6 concurrent starts → one attempt**; every one of the 73 lab examples + cleanup;
free-form SQL restrictions; EXPLAIN and routine endpoints; schema explorer; reports;
metrics; lab reset.

## 5. Load test

With the API running:

```bash
cd backend
python scripts/load_test.py --users 10 --duration 20      # no extra dependencies
# or: locust -f scripts/locustfile.py --host http://127.0.0.1:8000
```

The script prints client-side throughput and p50/p95/p99; the **Performance** page shows
the server-side measurements of the same traffic. A local run (8 users, 10 s) measured
87 req/s, 0 errors, p50 46 ms, p95 232 ms — your numbers will differ with hardware.

## 6. API

Interactive documentation: `http://127.0.0.1:8000/docs`. Errors always have the shape
`{"error": {"code", "message", "details", "request_id"}}`; every response carries
`X-Request-ID`, which also appears in the JSON logs and in `sql_execution_log`.

| Method & path | Role | Purpose |
|---|---|---|
| GET `/api/health` | public | real round trip to MySQL; 503 when unreachable |
| POST `/api/auth/register`, `/api/auth/login`; GET `/api/auth/me` | public / any | accounts, JWT |
| GET/PUT/DELETE `/api/students[/{id}]` | staff / admin / self | student management |
| GET/POST/PUT/DELETE `/api/staff[/{id}]` | admin | staff management |
| GET/POST `/api/exams`; GET/PUT/DELETE `/api/exams/{id}` | staff (students: list) | exams |
| POST `/api/exams/{id}/release` | staff | result-release rule |
| GET/POST `/api/exams/{id}/questions`; PUT/DELETE `…/questions/{qid}` | staff | assignment |
| POST `/api/exams/{id}/attempts` | student | start or resume |
| GET `/api/exams/{id}/attempts`, `/api/exams/{id}/audit` | staff | attempts, trigger audit trail |
| GET/POST/PUT/DELETE `/api/questions[/{id}]` | staff | question bank |
| GET `/api/attempts`, `/api/attempts/{id}` | owner / staff | attempt and answers |
| PUT `/api/attempts/{id}/answers` | student | save answers |
| POST `/api/attempts/{id}/submit` | student | transactional submission |
| GET `/api/attempts/{id}/result` | owner (released) / staff | result |
| POST `/api/attempts/{id}/grade` | staff | manual grading → `sp_finalize_attempt` |
| GET `/api/results`, `/api/results/performance` | any / staff | results, `exam_performance_view` |
| GET `/api/reports`, `/api/reports/{id}` | staff | reports from `reports.sql` (read-only account) |
| GET `/api/sql/config`, `/api/sql/examples` | staff | lab configuration and catalog |
| POST `/api/sql/execute` | staff (some admin) | run an example / cleanup / free-form SQL |
| GET `/api/sql/history` | staff | `sql_execution_log` |
| POST `/api/sql/lab/reset` | admin | rebuild the lab database |
| GET `/api/db/schema`, `/api/db/objects` | staff | live metadata (tables, keys, views, triggers, routines) |
| GET `/api/db/tables/{table}/rows` | staff | paginated table viewer |
| POST `/api/db/explain` | staff | EXPLAIN / FORMAT=TREE / ANALYZE for one SELECT |
| POST `/api/db/routines/{name}/call` | staff | execute a stored procedure / function |
| GET `/api/metrics`, `/api/db/metrics` | staff | measured API/DB metrics, pools, server status |

Testing with Postman: `POST /api/auth/login` with
`{"username":"admin","password":"Password@123","account_type":"STAFF"}`, copy
`access_token` and send it as `Authorization: Bearer <token>`. Postman can also import
the OpenAPI document from `http://127.0.0.1:8000/openapi.json`.

## 7. The web application

| Page | Who | What it shows |
|---|---|---|
| Sign in / register | all | role choice, validation, demo accounts |
| Student dashboard | student | open, upcoming and submitted exams, released scores |
| Exam attempt | student | countdown from server time, answer-sheet bubbles, autosave, submit, auto-submit on timeout; review with answer key after release |
| Faculty dashboard | faculty | exams, grading queue, `exam_performance_view` |
| Admin dashboard | admin | health of each DB account, accounts, lab reset |
| Examinations / exam detail | staff | create/edit, assign questions, release results, attempts, trigger audit trail, delete |
| Question bank | staff | CRUD with type-specific validation |
| Results & reports | all / staff | results from `student_result_view`; 10 SQL reports with their SQL |
| Users | admin | students and staff, roles |
| **SQL Command Center** | staff | categories + live object list · statements + parameters · results, affected rows, errors, durations, before/after comparisons, measured index timings |
| Schema explorer | staff | live ER diagram, columns, constraints (incl. CHECK clauses), indexes |
| Table data | staff | any table or view, sortable, paginated (password hashes hidden) |
| Views & triggers | staff | definitions, live view results, interactive audit-trigger demo |
| Procedures | staff | routine definitions, run with your arguments |
| Indexes & plans | staff | EXPLAIN / tree / EXPLAIN ANALYZE viewer, measured index experiment |
| Execution history | staff | every lab execution from `sql_execution_log` |
| Performance | staff | request count, success rate, P50/P95/P99, query latency, pools, slow & failed queries |

## 8. SQL concepts implemented (73 lab examples)

| Category | Examples | Database / account |
|---|---|---|
| DDL | CREATE, ALTER, RENAME (table + column), TRUNCATE, DROP on `demo_*` tables | lab / `oems_lab` |
| DML | INSERT (your values), multi-row INSERT, UPDATE (CHECK + trigger), DELETE | lab |
| DQL | SELECT, WHERE, LIKE, ORDER BY + LIMIT, DISTINCT, COUNT/SUM/AVG/MIN/MAX, GROUP BY, HAVING | main / `oems_reader` |
| Joins | INNER, LEFT, RIGHT, CROSS, SELF, and three common mistakes (missing condition, WHERE on outer side, fan-out aggregation) | main |
| Subqueries | scalar, above-average, IN, correlated, EXISTS, NOT EXISTS (exams, students) | main |
| Constraints | PK, FK (both directions + composite), UNIQUE, NOT NULL, CHECK ×4, DEFAULT, duplicate attempt/result | lab |
| Views | SELECT from the 3 views, definitions, base-table change reflected, CREATE/DROP, drop & recreate | main + lab |
| Triggers | audit OLD/NEW, rollback with transaction, derived total marks, BEFORE-UPDATE rules, DROP/CREATE TRIGGER | lab |
| Procedures | GetExamDetails (2 result sets), GetStudentResults, OUT parameters, function in a query, CREATE/CALL/DROP, sp_finalize_attempt | main + lab |
| TCL | COMMIT (second session view), ROLLBACK, SAVEPOINT, error inside a transaction, DDL implicit commit | lab |
| DCL | CREATE USER, GRANT, use, denied UPDATE, REVOKE, denied SELECT, DROP USER; read-only account denied writes; SHOW GRANTS of all accounts | lab / `oems_lab_dcl`, main / `oems_reader` |
| Indexes | SHOW INDEX, EXPLAIN by email (and function on column), composite index, EXPLAIN ANALYZE, measured CREATE INDEX before/after, DROP INDEX | main + lab |

Destructive examples ask for confirmation; examples with leftovers have a *Clean up*
button; the whole lab database can be rebuilt from the admin dashboard.

## 9. Security model

* Passwords are bcrypt hashes; authentication uses signed JWTs (HS256) with expiry; every endpoint checks the role.
* MySQL privileges are the primary boundary (table in docs/architecture.md). The API never uses the administrator account; DB credentials live only in `.env` and never appear in responses or logs (error messages are sanitised; the DCL demo password is masked as `********`).
* Application queries use the ORM or bound parameters; lab parameters are bound too.
* The SQL executor uses private sessions with `max_execution_time`, socket timeouts, a row cap, one statement per call (multi-statements disabled in the driver), per-user rate limits and a request-size limit.
* Free-form SQL (admin only, `SQL_FREEFORM_ENABLED`) runs only as `oems_lab`; statements are tokenized (quotes and comments respected) and account management, server variables, file access, system/other schemas and `SLEEP`/`BENCHMARK` are refused; destructive statements need confirmation.
* Correct answers are never sent to students before results are released.

## 10. Known limitations

* Free-form SQL rejects references to `information_schema`/`mysql`; use the explorer pages for metadata instead. A stored program must be sent as a single run of its own.
* Metrics are kept in memory per API process and reset on restart (the SQL log is persistent).
* Rate limiting and the lab-reset lock are in-process (single-worker deployment assumed).
* `oems_lab_dcl` holds the global `CREATE USER` privilege required for the GRANT/REVOKE demonstration; it is used only by predefined statements.
* `init_db.py` sets `log_bin_trust_function_creators = 1` globally on the server (a common local-development setting).
* Dates are MySQL `DATETIME` values in the server's local time; run browser, API and MySQL on the same machine/time zone (as in local development).
* Google Fonts are loaded from the internet; offline, the UI falls back to system fonts.

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `init_db.py`: cannot connect as administrator | check `MYSQL_ADMIN_USER/PASSWORD`, `DB_HOST`, that MySQL is running (`services.msc` → MySQL80 on Windows) |
| `[7/7]` reports `Access denied` for an account | set `DB_ACCOUNT_HOST=%` in `.env` and rerun `python scripts/init_db.py` |
| `Authentication plugin 'caching_sha2_password' requires cryptography` | `pip install -r requirements.txt` inside the venv |
| Frontend shows "The API server is not reachable" | start uvicorn on port 8000 (or set `VITE_API_TARGET`) |
| An exam cannot be started | it must be ACTIVE, inside its window and have questions; each student gets one attempt |
| A lab example fails because an earlier demo changed data | press *Clean up*, or *Reset lab database* on the admin dashboard |
| Port already in use | `uvicorn … --port 8001` and `VITE_API_TARGET=http://127.0.0.1:8001 npm run dev` |
