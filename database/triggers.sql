-- =============================================================================
-- OEMS — triggers.sql : automatic actions on table events
--
-- Uses DELIMITER so the file runs unchanged in the mysql command-line client:
--   mysql -u root -p oems_db < database/triggers.sql
-- (The backend's SQL loader understands DELIMITER as well.)
--
-- A trigger runs inside the same InnoDB transaction as the statement that fired
-- it, so if that transaction rolls back, the trigger's writes roll back too.
-- =============================================================================

DROP TRIGGER IF EXISTS trg_exam_after_insert;
DROP TRIGGER IF EXISTS trg_exam_after_update;
DROP TRIGGER IF EXISTS trg_exam_after_delete;
DROP TRIGGER IF EXISTS trg_exam_question_after_insert;
DROP TRIGGER IF EXISTS trg_exam_question_after_update;
DROP TRIGGER IF EXISTS trg_exam_question_after_delete;
DROP TRIGGER IF EXISTS trg_answer_before_insert;
DROP TRIGGER IF EXISTS trg_answer_before_update;

DELIMITER $$

-- -----------------------------------------------------------------------------
-- Exam audit trail (exam -> exam_audit)
-- USER() records the client account that issued the statement.
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_exam_after_insert
AFTER INSERT ON exam
FOR EACH ROW
BEGIN
    INSERT INTO exam_audit (exam_id, action, changed_columns,
                            new_title, new_exam_date, new_duration, new_status, db_user)
    VALUES (NEW.exam_id, 'INSERT', NULL,
            NEW.title, NEW.exam_date, NEW.duration_minutes, NEW.status, USER());
END$$

CREATE TRIGGER trg_exam_after_update
AFTER UPDATE ON exam
FOR EACH ROW
BEGIN
    DECLARE v_cols VARCHAR(200) DEFAULT NULL;

    -- <=> is NULL-safe equality; total_marks is system-maintained and not audited
    IF NOT (OLD.title            <=> NEW.title)            THEN SET v_cols = CONCAT_WS(',', v_cols, 'title');            END IF;
    IF NOT (OLD.subject          <=> NEW.subject)          THEN SET v_cols = CONCAT_WS(',', v_cols, 'subject');          END IF;
    IF NOT (OLD.exam_date        <=> NEW.exam_date)        THEN SET v_cols = CONCAT_WS(',', v_cols, 'exam_date');        END IF;
    IF NOT (OLD.deadline         <=> NEW.deadline)         THEN SET v_cols = CONCAT_WS(',', v_cols, 'deadline');         END IF;
    IF NOT (OLD.duration_minutes <=> NEW.duration_minutes) THEN SET v_cols = CONCAT_WS(',', v_cols, 'duration_minutes'); END IF;
    IF NOT (OLD.pass_percentage  <=> NEW.pass_percentage)  THEN SET v_cols = CONCAT_WS(',', v_cols, 'pass_percentage');  END IF;
    IF NOT (OLD.results_released <=> NEW.results_released) THEN SET v_cols = CONCAT_WS(',', v_cols, 'results_released'); END IF;
    IF NOT (OLD.status           <=> NEW.status)           THEN SET v_cols = CONCAT_WS(',', v_cols, 'status');           END IF;

    IF v_cols IS NOT NULL THEN
        INSERT INTO exam_audit (exam_id, action, changed_columns,
                                old_title, new_title, old_exam_date, new_exam_date,
                                old_duration, new_duration, old_status, new_status, db_user)
        VALUES (NEW.exam_id, 'UPDATE', v_cols,
                OLD.title, NEW.title, OLD.exam_date, NEW.exam_date,
                OLD.duration_minutes, NEW.duration_minutes, OLD.status, NEW.status, USER());
    END IF;
END$$

CREATE TRIGGER trg_exam_after_delete
AFTER DELETE ON exam
FOR EACH ROW
BEGIN
    INSERT INTO exam_audit (exam_id, action, changed_columns,
                            old_title, old_exam_date, old_duration, old_status, db_user)
    VALUES (OLD.exam_id, 'DELETE', NULL,
            OLD.title, OLD.exam_date, OLD.duration_minutes, OLD.status, USER());
END$$

-- -----------------------------------------------------------------------------
-- Keep exam.total_marks = SUM(exam_question.marks_assigned)
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_exam_question_after_insert
AFTER INSERT ON exam_question
FOR EACH ROW
BEGIN
    UPDATE exam
       SET total_marks = (SELECT COALESCE(SUM(marks_assigned), 0)
                            FROM exam_question WHERE exam_id = NEW.exam_id)
     WHERE exam_id = NEW.exam_id;
END$$

CREATE TRIGGER trg_exam_question_after_update
AFTER UPDATE ON exam_question
FOR EACH ROW
BEGIN
    UPDATE exam
       SET total_marks = (SELECT COALESCE(SUM(marks_assigned), 0)
                            FROM exam_question WHERE exam_id = NEW.exam_id)
     WHERE exam_id = NEW.exam_id;
    IF OLD.exam_id <> NEW.exam_id THEN
        UPDATE exam
           SET total_marks = (SELECT COALESCE(SUM(marks_assigned), 0)
                                FROM exam_question WHERE exam_id = OLD.exam_id)
         WHERE exam_id = OLD.exam_id;
    END IF;
END$$

CREATE TRIGGER trg_exam_question_after_delete
AFTER DELETE ON exam_question
FOR EACH ROW
BEGIN
    UPDATE exam
       SET total_marks = (SELECT COALESCE(SUM(marks_assigned), 0)
                            FROM exam_question WHERE exam_id = OLD.exam_id)
     WHERE exam_id = OLD.exam_id;
END$$

-- -----------------------------------------------------------------------------
-- Answer integrity rules that a CHECK constraint cannot express because they
-- need data from other tables:
--   1. answers can only be added/changed while the attempt is IN_PROGRESS
--      (grading — changing marks_obtained — stays allowed after submission)
--   2. marks_obtained can never exceed the marks assigned to that question
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_answer_before_insert
BEFORE INSERT ON answer
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    DECLARE v_max    DECIMAL(6,2);

    SET v_status = (SELECT status FROM attempt WHERE attempt_id = NEW.attempt_id);
    IF v_status IS NOT NULL AND v_status <> 'IN_PROGRESS' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Answers cannot be added after the attempt has been submitted';
    END IF;

    IF NEW.marks_obtained IS NOT NULL THEN
        SET v_max = (SELECT marks_assigned FROM exam_question
                      WHERE exam_id = NEW.exam_id AND question_id = NEW.question_id);
        IF v_max IS NOT NULL AND NEW.marks_obtained > v_max THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'marks_obtained cannot exceed the marks assigned to the question';
        END IF;
    END IF;
END$$

CREATE TRIGGER trg_answer_before_update
BEFORE UPDATE ON answer
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    DECLARE v_max    DECIMAL(6,2);

    IF NOT (NEW.selected_answer <=> OLD.selected_answer)
       OR NEW.attempt_id  <> OLD.attempt_id
       OR NEW.exam_id     <> OLD.exam_id
       OR NEW.question_id <> OLD.question_id THEN
        SET v_status = (SELECT status FROM attempt WHERE attempt_id = OLD.attempt_id);
        IF v_status <> 'IN_PROGRESS' THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Answer is locked: the attempt has already been submitted';
        END IF;
    END IF;

    IF NEW.marks_obtained IS NOT NULL THEN
        SET v_max = (SELECT marks_assigned FROM exam_question
                      WHERE exam_id = NEW.exam_id AND question_id = NEW.question_id);
        IF v_max IS NOT NULL AND NEW.marks_obtained > v_max THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'marks_obtained cannot exceed the marks assigned to the question';
        END IF;
    END IF;
END$$

DELIMITER ;
