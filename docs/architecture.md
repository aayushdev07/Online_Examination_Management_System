# OEMS — architecture and data model

## System architecture

```mermaid
flowchart LR
    subgraph Browser
        UI["React + TypeScript (Vite)<br/>pages: dashboards, exams, attempt,<br/>results, SQL Command Center, explorers"]
    end
    subgraph API["FastAPI (Python)"]
        MW["middleware<br/>request id · size limit · metrics · JSON logs"]
        R["routers<br/>auth · users · exams · questions · attempts<br/>results/reports · sql lab · db metadata · system"]
        WF["exam workflow service<br/>row locks, transactions"]
        LAB["SQL lab executor<br/>catalog · policy · private sessions"]
        ORM["SQLAlchemy 2 ORM + Alembic"]
    end
    subgraph MySQL["MySQL 8 (InnoDB)"]
        MAIN[("oems_db<br/>application data")]
        LABDB[("oems_lab<br/>disposable copy")]
    end
    UI -- "HTTPS JSON /api (JWT)" --> MW --> R
    R --> WF --> ORM -- "oems_app" --> MAIN
    R -- "reports, DQL demos: oems_reader (SELECT only)" --> MAIN
    R --> LAB -- "oems_reader" --> MAIN
    LAB -- "oems_lab (ALL on oems_lab only)" --> LABDB
    LAB -- "oems_lab_dcl (GRANT/REVOKE demo)" --> LABDB
```

The browser never talks to MySQL. Each server-side path uses the least-privileged
MySQL account that can do its job, so the database itself enforces the security
boundary:

| Account | Privileges | Used for |
|---|---|---|
| `oems_app` | SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW, TRIGGER on `oems_db`; SHOW_ROUTINE | normal application work, metadata inspection |
| `oems_reader` | SELECT on `oems_db`; EXECUTE on 5 read-only routines | reports, DQL/join/subquery demos, table viewer, EXPLAIN |
| `oems_lab` | ALL on `oems_lab` only | DDL/DML/TCL/view/trigger/procedure/index demos, free-form SQL, lab reset |
| `oems_lab_dcl` | CREATE USER; ALL on `oems_lab` WITH GRANT OPTION | the predefined GRANT/REVOKE demonstration only |
| administrator (root) | everything | `scripts/init_db.py` and tests only — never the running API |

## Entity–relationship diagram

```mermaid
erDiagram
    FACULTY_ADMIN ||--o{ EXAM : creates
    FACULTY_ADMIN ||--o{ QUESTION : authors
    EXAM ||--o{ EXAM_QUESTION : contains
    QUESTION ||--o{ EXAM_QUESTION : "assigned in"
    STUDENT ||--o{ ATTEMPT : makes
    EXAM ||--o{ ATTEMPT : "attempted in"
    ATTEMPT ||--o{ ANSWER : has
    EXAM_QUESTION ||--o{ ANSWER : "answered by"
    ATTEMPT ||--o| RESULT : "evaluated as"
    EXAM ||..o{ EXAM_AUDIT : "audited by trigger"

    STUDENT {
        int student_id PK
        varchar student_name
        varchar email UK
        varchar username UK
        varchar password_hash
        datetime created_at
    }
    FACULTY_ADMIN {
        int faculty_admin_id PK
        varchar faculty_name
        varchar email UK
        varchar username UK
        varchar password_hash
        enum role
        datetime created_at
    }
    EXAM {
        int exam_id PK
        int created_by FK
        varchar title
        varchar subject
        datetime exam_date
        datetime deadline
        int duration_minutes
        decimal total_marks
        decimal pass_percentage
        tinyint results_released
        enum status
    }
    QUESTION {
        int question_id PK
        int created_by FK
        text question_text
        enum question_type
        json options
        decimal marks
        text correct_answer
    }
    EXAM_QUESTION {
        int exam_id PK,FK
        int question_id PK,FK
        int question_order
        decimal marks_assigned
    }
    ATTEMPT {
        int attempt_id PK
        int student_id FK
        int exam_id FK
        datetime started_at
        datetime submitted_at
        enum status
    }
    ANSWER {
        int answer_id PK
        int attempt_id FK
        int exam_id FK
        int question_id FK
        text selected_answer
        decimal marks_obtained
        datetime answered_at
    }
    RESULT {
        int result_id PK
        int attempt_id FK,UK
        decimal marks_obtained
        decimal percentage
        enum result_status
        datetime evaluated_at
    }
    EXAM_AUDIT {
        bigint audit_id PK
        int exam_id
        enum action
        varchar changed_columns
        int old_duration
        int new_duration
        varchar db_user
        datetime changed_at
    }
    SQL_EXECUTION_LOG {
        bigint log_id PK
        varchar request_id
        varchar category
        enum execution_mode
        text statement_text
        enum status
        decimal duration_ms
        datetime executed_at
    }
```

The Schema explorer page draws the same diagram live from `information_schema`.

### Additions to the DrawDB design (and why)

| Table | Column / rule | Reason |
|---|---|---|
| exam | `deadline`, `pass_percentage`, `results_released`, `created_at` | workflow requires deadlines, PASS/FAIL rule and result release |
| question | `created_by`, `options` (JSON), `created_at` | ownership; MCQ options must be stored somewhere |
| answer | `exam_id`, `answered_at` | `exam_id` lets two composite FKs prove the question belongs to the attempt's exam |
| attempt | `UNIQUE(student_id, exam_id)` | one attempt per student per exam ⇒ "submit exactly once" is a database guarantee |
| exam_question | `UNIQUE(exam_id, question_order)` | no two questions share a position |
| answer | `UNIQUE(attempt_id, question_id)` | one answer per question per attempt |
| faculty_admin | `created_at` | account audit trail |

## Integrity rules and where they live

| Rule | Enforced by |
|---|---|
| unique e-mail / username | `uq_student_email`, `uq_student_username`, … |
| no duplicate question in an exam | composite PK `pk_exam_question` |
| answer belongs to a valid attempt and to a question of that attempt's exam | `fk_answer_attempt_exam`, `fk_answer_exam_question` |
| valid durations / marks / percentages / exam window | CHECK constraints (`chk_exam_duration`, `chk_exam_window_fits`, `chk_result_percentage`, …) |
| one result per attempt | `uq_result_attempt` |
| no duplicate / concurrent submission | `uq_attempt_student_exam` + `SELECT … FOR UPDATE` in one transaction |
| answers locked after submission; marks ≤ question marks | triggers `trg_answer_before_insert/update` (SIGNAL 45000) |
| total marks always equal to assigned marks | triggers on `exam_question` |
| audit of exam changes | triggers `trg_exam_after_insert/update/delete` |
| result creation only for fully graded, submitted attempts | procedure `sp_finalize_attempt` |

## Submission transaction

```mermaid
sequenceDiagram
    participant S as Student (browser)
    participant A as FastAPI
    participant M as MySQL
    S->>A: POST /api/attempts/{id}/submit
    A->>M: START TRANSACTION
    A->>M: SELECT … FROM attempt WHERE attempt_id=? FOR UPDATE
    Note over A,M: a concurrent submit waits here, then sees SUBMITTED → 409
    A->>M: INSERT missing answers (NULL) — trigger checks IN_PROGRESS
    A->>M: UPDATE attempt SET status='SUBMITTED', submitted_at=NOW()
    A->>M: UPDATE answer SET marks_obtained=… (auto grading)
    alt nothing left for manual grading
        A->>M: CALL sp_finalize_attempt(id) → INSERT result, status EVALUATED
    end
    A->>M: COMMIT (any error → ROLLBACK of everything)
    A-->>S: 200 {status, pending_manual_grading}
```
