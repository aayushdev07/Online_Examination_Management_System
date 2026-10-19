-- =============================================================================
-- OEMS — Online Examination Management System
-- schema.sql : database structure (tables, keys, constraints)
--
-- Target : MySQL 8.0.16+ (CHECK constraints are enforced from 8.0.16)
-- Engine : InnoDB (transactions, row-level locking, foreign keys)
--
-- Run against an EMPTY database that is already selected, e.g.
--   mysql -u root -p oems_db < database/schema.sql
--
-- The ten tables follow the DrawDB design (student, faculty_admin, exam,
-- question, exam_question, attempt, answer, result) plus the two tables the
-- project workflow requires (exam_audit, sql_execution_log). Columns added to
-- the DrawDB design are marked  [added]  with the reason.
-- =============================================================================

SET NAMES utf8mb4;

-- -----------------------------------------------------------------------------
-- 1. student
-- -----------------------------------------------------------------------------
CREATE TABLE student (
    student_id     INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    student_name   VARCHAR(100)  NOT NULL,
    email          VARCHAR(255)  NOT NULL,
    username       VARCHAR(50)   NOT NULL,
    password_hash  VARCHAR(255)  NOT NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_student          PRIMARY KEY (student_id),
    CONSTRAINT uq_student_email    UNIQUE (email),
    CONSTRAINT uq_student_username UNIQUE (username),
    CONSTRAINT chk_student_name    CHECK (CHAR_LENGTH(TRIM(student_name)) > 0),
    CONSTRAINT chk_student_email   CHECK (email LIKE '%_@_%._%'),
    CONSTRAINT chk_student_username CHECK (REGEXP_LIKE(username, '^[A-Za-z0-9_.]{3,50}$'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 2. faculty_admin  (one table for both staff roles, distinguished by `role`)
-- -----------------------------------------------------------------------------
CREATE TABLE faculty_admin (
    faculty_admin_id INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    faculty_name     VARCHAR(100)  NOT NULL,
    email            VARCHAR(255)  NOT NULL,
    username         VARCHAR(50)   NOT NULL,
    password_hash    VARCHAR(255)  NOT NULL,
    role             ENUM('FACULTY','ADMIN') NOT NULL DEFAULT 'FACULTY',
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- [added] account audit trail

    CONSTRAINT pk_faculty_admin          PRIMARY KEY (faculty_admin_id),
    CONSTRAINT uq_faculty_admin_email    UNIQUE (email),
    CONSTRAINT uq_faculty_admin_username UNIQUE (username),
    CONSTRAINT chk_faculty_name          CHECK (CHAR_LENGTH(TRIM(faculty_name)) > 0),
    CONSTRAINT chk_faculty_email         CHECK (email LIKE '%_@_%._%'),
    CONSTRAINT chk_faculty_username      CHECK (REGEXP_LIKE(username, '^[A-Za-z0-9_.]{3,50}$'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 3. exam
--    exam_date = window opens; deadline = window closes.
--    total_marks is maintained automatically by the exam_question triggers.
-- -----------------------------------------------------------------------------
CREATE TABLE exam (
    exam_id          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    created_by       INT UNSIGNED  NOT NULL,
    title            VARCHAR(150)  NOT NULL,
    subject          VARCHAR(100)  NOT NULL,
    exam_date        DATETIME      NOT NULL,
    deadline         DATETIME      NOT NULL,                 -- [added] PDF: "set deadlines"
    duration_minutes INT UNSIGNED  NOT NULL,
    total_marks      DECIMAL(7,2)  NOT NULL DEFAULT 0.00,
    pass_percentage  DECIMAL(5,2)  NOT NULL DEFAULT 40.00,   -- [added] PASS/FAIL rule
    results_released TINYINT(1)    NOT NULL DEFAULT 0,       -- [added] PDF: "result-release rules"
    status           ENUM('SCHEDULED','ACTIVE','COMPLETED','CANCELLED') NOT NULL DEFAULT 'SCHEDULED',
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- [added]

    CONSTRAINT pk_exam                 PRIMARY KEY (exam_id),
    CONSTRAINT fk_exam_created_by      FOREIGN KEY (created_by)
        REFERENCES faculty_admin (faculty_admin_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT chk_exam_title          CHECK (CHAR_LENGTH(TRIM(title)) > 0),
    CONSTRAINT chk_exam_duration       CHECK (duration_minutes > 0 AND duration_minutes <= 600),
    CONSTRAINT chk_exam_total_marks    CHECK (total_marks >= 0),
    CONSTRAINT chk_exam_pass_pct       CHECK (pass_percentage >= 0 AND pass_percentage <= 100),
    CONSTRAINT chk_exam_released       CHECK (results_released IN (0, 1)),
    CONSTRAINT chk_exam_window         CHECK (deadline > exam_date),
    CONSTRAINT chk_exam_window_fits    CHECK (TIMESTAMPDIFF(MINUTE, exam_date, deadline) >= duration_minutes)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 4. question  (question bank; reusable across exams)
-- -----------------------------------------------------------------------------
CREATE TABLE question (
    question_id    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    created_by     INT UNSIGNED  NOT NULL,                   -- [added] question ownership
    question_text  TEXT          NOT NULL,
    question_type  ENUM('MCQ','TRUE_FALSE','SHORT_ANSWER','LONG_ANSWER') NOT NULL,
    options        JSON          NULL,                       -- [added] MCQ choices, JSON array of strings
    marks          DECIMAL(6,2)  NOT NULL,
    correct_answer TEXT          NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- [added]

    CONSTRAINT pk_question             PRIMARY KEY (question_id),
    CONSTRAINT fk_question_created_by  FOREIGN KEY (created_by)
        REFERENCES faculty_admin (faculty_admin_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT chk_question_marks      CHECK (marks > 0),
    CONSTRAINT chk_question_text       CHECK (CHAR_LENGTH(TRIM(question_text)) > 0),
    -- auto-graded types must carry an answer key
    CONSTRAINT chk_question_answer_key CHECK (question_type = 'LONG_ANSWER' OR correct_answer IS NOT NULL),
    -- MCQs need at least two options; other types must not carry options
    CONSTRAINT chk_question_mcq_options CHECK (
        (question_type = 'MCQ' AND JSON_TYPE(options) = 'ARRAY' AND JSON_LENGTH(options) >= 2)
        OR (question_type <> 'MCQ' AND options IS NULL)
    ),
    CONSTRAINT chk_question_true_false CHECK (question_type <> 'TRUE_FALSE' OR correct_answer IN ('TRUE', 'FALSE'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 5. exam_question  (M:N between exam and question)
--    Composite PK prevents assigning the same question twice to one exam.
-- -----------------------------------------------------------------------------
CREATE TABLE exam_question (
    exam_id        INT UNSIGNED  NOT NULL,
    question_id    INT UNSIGNED  NOT NULL,
    question_order INT UNSIGNED  NOT NULL,
    marks_assigned DECIMAL(6,2)  NOT NULL,

    CONSTRAINT pk_exam_question          PRIMARY KEY (exam_id, question_id),
    CONSTRAINT uq_exam_question_order    UNIQUE (exam_id, question_order),
    CONSTRAINT fk_exam_question_exam     FOREIGN KEY (exam_id)
        REFERENCES exam (exam_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT fk_exam_question_question FOREIGN KEY (question_id)
        REFERENCES question (question_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT chk_exam_question_order   CHECK (question_order > 0),
    CONSTRAINT chk_exam_question_marks   CHECK (marks_assigned > 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 6. attempt
--    One attempt per (student, exam) — this is what makes "submit exactly
--    once" a database guarantee rather than an application promise.
-- -----------------------------------------------------------------------------
CREATE TABLE attempt (
    attempt_id   INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    student_id   INT UNSIGNED  NOT NULL,
    exam_id      INT UNSIGNED  NOT NULL,
    started_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    submitted_at DATETIME      NULL,
    status       ENUM('IN_PROGRESS','SUBMITTED','EVALUATED') NOT NULL DEFAULT 'IN_PROGRESS',

    CONSTRAINT pk_attempt               PRIMARY KEY (attempt_id),
    CONSTRAINT uq_attempt_student_exam  UNIQUE (student_id, exam_id),
    -- target of the composite FK from answer: (attempt, exam) must belong together
    CONSTRAINT uq_attempt_id_exam       UNIQUE (attempt_id, exam_id),
    CONSTRAINT fk_attempt_student       FOREIGN KEY (student_id)
        REFERENCES student (student_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT fk_attempt_exam          FOREIGN KEY (exam_id)
        REFERENCES exam (exam_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT chk_attempt_submit_time  CHECK (submitted_at IS NULL OR submitted_at >= started_at),
    -- an attempt is IN_PROGRESS exactly when it has not been submitted
    CONSTRAINT chk_attempt_status_time  CHECK ((status = 'IN_PROGRESS') = (submitted_at IS NULL))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 7. answer
--    exam_id [added] lets two composite foreign keys prove that the answered
--    question is assigned to the SAME exam the attempt belongs to.
-- -----------------------------------------------------------------------------
CREATE TABLE answer (
    answer_id       INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    attempt_id      INT UNSIGNED  NOT NULL,
    exam_id         INT UNSIGNED  NOT NULL,                  -- [added] integrity anchor
    question_id     INT UNSIGNED  NOT NULL,
    selected_answer TEXT          NULL,                      -- NULL = left unanswered
    marks_obtained  DECIMAL(6,2)  NULL,                      -- NULL = not graded yet
    answered_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- [added] last time the student saved it

    CONSTRAINT pk_answer                 PRIMARY KEY (answer_id),
    CONSTRAINT uq_answer_attempt_question UNIQUE (attempt_id, question_id),
    CONSTRAINT fk_answer_attempt         FOREIGN KEY (attempt_id)
        REFERENCES attempt (attempt_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT fk_answer_question        FOREIGN KEY (question_id)
        REFERENCES question (question_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT fk_answer_attempt_exam    FOREIGN KEY (attempt_id, exam_id)
        REFERENCES attempt (attempt_id, exam_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT fk_answer_exam_question   FOREIGN KEY (exam_id, question_id)
        REFERENCES exam_question (exam_id, question_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT chk_answer_marks          CHECK (marks_obtained IS NULL OR marks_obtained >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 8. result  (1:1 with attempt — UNIQUE(attempt_id) prevents duplicate results)
-- -----------------------------------------------------------------------------
CREATE TABLE result (
    result_id      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    attempt_id     INT UNSIGNED  NOT NULL,
    marks_obtained DECIMAL(7,2)  NOT NULL,
    percentage     DECIMAL(5,2)  NOT NULL,
    result_status  ENUM('PASS','FAIL') NOT NULL,
    evaluated_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_result            PRIMARY KEY (result_id),
    CONSTRAINT uq_result_attempt    UNIQUE (attempt_id),
    CONSTRAINT fk_result_attempt    FOREIGN KEY (attempt_id)
        REFERENCES attempt (attempt_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
    CONSTRAINT chk_result_marks     CHECK (marks_obtained >= 0),
    CONSTRAINT chk_result_percentage CHECK (percentage >= 0 AND percentage <= 100)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 9. exam_audit  (written ONLY by the exam triggers — see triggers.sql)
--    No FK to exam on purpose: the audit trail must survive an exam deletion.
-- -----------------------------------------------------------------------------
CREATE TABLE exam_audit (
    audit_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    exam_id         INT UNSIGNED    NOT NULL,
    action          ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    changed_columns VARCHAR(200)    NULL,
    old_title       VARCHAR(150)    NULL,
    new_title       VARCHAR(150)    NULL,
    old_exam_date   DATETIME        NULL,
    new_exam_date   DATETIME        NULL,
    old_duration    INT UNSIGNED    NULL,
    new_duration    INT UNSIGNED    NULL,
    old_status      VARCHAR(20)     NULL,
    new_status      VARCHAR(20)     NULL,
    db_user         VARCHAR(288)    NOT NULL,
    changed_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    CONSTRAINT pk_exam_audit PRIMARY KEY (audit_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------------
-- 10. sql_execution_log  (every DBMS-Lab execution; no passwords/tokens stored)
-- -----------------------------------------------------------------------------
CREATE TABLE sql_execution_log (
    log_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_id     VARCHAR(64)     NOT NULL,
    user_role      VARCHAR(20)     NOT NULL,
    user_id        INT UNSIGNED    NULL,
    example_id     VARCHAR(80)     NULL,
    category       VARCHAR(40)     NOT NULL,
    execution_mode ENUM('EXAMPLE','CLEANUP','FREEFORM','EXPLAIN','PROCEDURE','REPORT','RESET') NOT NULL,
    target_db      VARCHAR(64)     NOT NULL,
    statement_text TEXT            NOT NULL,
    status         ENUM('SUCCESS','ERROR','REJECTED') NOT NULL,
    rows_returned  INT UNSIGNED    NOT NULL DEFAULT 0,
    rows_affected  BIGINT          NOT NULL DEFAULT 0,
    duration_ms    DECIMAL(10,3)   NOT NULL DEFAULT 0,
    error_code     INT             NULL,
    error_message  VARCHAR(500)    NULL,
    executed_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    CONSTRAINT pk_sql_execution_log PRIMARY KEY (log_id),
    CONSTRAINT chk_sql_log_duration CHECK (duration_ms >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
