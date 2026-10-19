-- =============================================================================
-- OEMS — procedures.sql : stored functions and stored procedures
--
-- FUNCTION  : returns exactly one value, usable inside any SQL expression
--             (SELECT fn_marks_percentage(18, 25);). Cannot return result sets.
-- PROCEDURE : invoked with CALL, may return zero or more result sets, may use
--             IN / OUT / INOUT parameters and may modify data.
--
-- SQL SECURITY INVOKER: a routine runs with the privileges of the account that
-- CALLs it (not its creator), so granting EXECUTE never widens access. The
-- read-only account may therefore run the read-only routines safely.
--
-- Note: when binary logging is enabled, creating functions as a non-SUPER
-- account requires log_bin_trust_function_creators = 1 (set by init_db.py).
-- =============================================================================

DROP FUNCTION  IF EXISTS fn_marks_percentage;
DROP FUNCTION  IF EXISTS fn_result_status;
DROP PROCEDURE IF EXISTS GetExamDetails;
DROP PROCEDURE IF EXISTS GetStudentResults;
DROP PROCEDURE IF EXISTS sp_exam_attempt_stats;
DROP PROCEDURE IF EXISTS sp_finalize_attempt;

DELIMITER $$

-- -----------------------------------------------------------------------------
-- fn_marks_percentage(obtained, total) -> percentage rounded to 2 dp, 0..100
-- -----------------------------------------------------------------------------
CREATE FUNCTION fn_marks_percentage(p_obtained DECIMAL(7,2), p_total DECIMAL(7,2))
RETURNS DECIMAL(5,2)
DETERMINISTIC
NO SQL
SQL SECURITY INVOKER
COMMENT 'Percentage of marks obtained out of total (0-100, 2 dp)'
BEGIN
    IF p_obtained IS NULL OR p_total IS NULL THEN
        RETURN NULL;
    END IF;
    IF p_total <= 0 THEN
        RETURN 0.00;
    END IF;
    RETURN LEAST(100.00, GREATEST(0.00, ROUND(p_obtained * 100 / p_total, 2)));
END$$

-- -----------------------------------------------------------------------------
-- fn_result_status(percentage, pass_percentage) -> 'PASS' | 'FAIL'
-- -----------------------------------------------------------------------------
CREATE FUNCTION fn_result_status(p_percentage DECIMAL(5,2), p_pass_percentage DECIMAL(5,2))
RETURNS VARCHAR(4)
DETERMINISTIC
NO SQL
SQL SECURITY INVOKER
COMMENT 'PASS when percentage reaches the pass mark'
BEGIN
    RETURN IF(p_percentage >= p_pass_percentage, 'PASS', 'FAIL');
END$$

-- -----------------------------------------------------------------------------
-- GetExamDetails(exam_id) -> 2 result sets: exam summary, assigned questions
-- (answer keys are deliberately not returned)
-- -----------------------------------------------------------------------------
CREATE PROCEDURE GetExamDetails(IN p_exam_id INT UNSIGNED)
READS SQL DATA
SQL SECURITY INVOKER
COMMENT 'Exam summary followed by its ordered question list'
BEGIN
    DECLARE v_msg VARCHAR(128);

    IF p_exam_id IS NULL OR NOT EXISTS (SELECT 1 FROM exam WHERE exam_id = p_exam_id) THEN
        SET v_msg = CONCAT('GetExamDetails: exam ', COALESCE(p_exam_id, 'NULL'), ' does not exist');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    SELECT exam_id, title, subject, status, exam_date, deadline, duration_minutes,
           total_marks, pass_percentage, created_by_name,
           question_count, attempt_count, submitted_count
      FROM exam_overview
     WHERE exam_id = p_exam_id;

    SELECT eq.question_order, q.question_id, q.question_type,
           LEFT(q.question_text, 120) AS question_text, eq.marks_assigned
      FROM exam_question eq
      JOIN question q ON q.question_id = eq.question_id
     WHERE eq.exam_id = p_exam_id
     ORDER BY eq.question_order;
END$$

-- -----------------------------------------------------------------------------
-- GetStudentResults(student_id) -> every evaluated result of the student
-- -----------------------------------------------------------------------------
CREATE PROCEDURE GetStudentResults(IN p_student_id INT UNSIGNED)
READS SQL DATA
SQL SECURITY INVOKER
COMMENT 'All evaluated results of one student, newest first'
BEGIN
    DECLARE v_msg VARCHAR(128);

    IF p_student_id IS NULL OR NOT EXISTS (SELECT 1 FROM student WHERE student_id = p_student_id) THEN
        SET v_msg = CONCAT('GetStudentResults: student ', COALESCE(p_student_id, 'NULL'), ' does not exist');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    SELECT student_name, exam_title, subject, marks_obtained, total_marks,
           percentage, result_status, results_released, evaluated_at
      FROM student_result_view
     WHERE student_id = p_student_id
     ORDER BY evaluated_at DESC;
END$$

-- -----------------------------------------------------------------------------
-- sp_exam_attempt_stats(exam_id, OUT total, OUT evaluated, OUT avg_pct)
-- Demonstrates OUT parameters:
--   CALL sp_exam_attempt_stats(1, @t, @e, @a); SELECT @t, @e, @a;
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_exam_attempt_stats(
    IN  p_exam_id   INT UNSIGNED,
    OUT p_total     INT,
    OUT p_evaluated INT,
    OUT p_avg_pct   DECIMAL(5,2))
READS SQL DATA
SQL SECURITY INVOKER
COMMENT 'Attempt counters of one exam returned through OUT parameters'
BEGIN
    DECLARE v_msg VARCHAR(128);

    IF p_exam_id IS NULL OR NOT EXISTS (SELECT 1 FROM exam WHERE exam_id = p_exam_id) THEN
        SET v_msg = CONCAT('sp_exam_attempt_stats: exam ', COALESCE(p_exam_id, 'NULL'), ' does not exist');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    SELECT COUNT(*), COUNT(r.result_id), ROUND(AVG(r.percentage), 2)
      INTO p_total, p_evaluated, p_avg_pct
      FROM attempt a
      LEFT JOIN result r ON r.attempt_id = a.attempt_id
     WHERE a.exam_id = p_exam_id;
END$$

-- -----------------------------------------------------------------------------
-- sp_finalize_attempt(attempt_id)
-- Converts a SUBMITTED, fully graded attempt into a result row and marks the
-- attempt EVALUATED. It does NOT commit: the caller owns the transaction, so
-- the result insert and the status change succeed or fail together.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_finalize_attempt(IN p_attempt_id INT UNSIGNED)
MODIFIES SQL DATA
SQL SECURITY INVOKER
COMMENT 'Create the result for a submitted, fully graded attempt'
BEGIN
    DECLARE v_status    VARCHAR(20);
    DECLARE v_exam_id   INT UNSIGNED;
    DECLARE v_ungraded  INT;
    DECLARE v_obtained  DECIMAL(7,2);
    DECLARE v_total     DECIMAL(7,2);
    DECLARE v_pass      DECIMAL(5,2);
    DECLARE v_pct       DECIMAL(5,2);

    -- lock the attempt row so two concurrent finalizations serialize here
    SELECT status, exam_id INTO v_status, v_exam_id
      FROM attempt WHERE attempt_id = p_attempt_id
       FOR UPDATE;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_finalize_attempt: attempt does not exist';
    ELSEIF v_status = 'IN_PROGRESS' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_finalize_attempt: attempt has not been submitted';
    ELSEIF v_status = 'EVALUATED' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_finalize_attempt: attempt is already evaluated';
    END IF;

    SELECT COUNT(*) INTO v_ungraded
      FROM answer WHERE attempt_id = p_attempt_id AND marks_obtained IS NULL;
    IF v_ungraded > 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_finalize_attempt: some answers are not graded yet';
    END IF;

    SELECT COALESCE(SUM(marks_obtained), 0) INTO v_obtained
      FROM answer WHERE attempt_id = p_attempt_id;

    SELECT total_marks, pass_percentage INTO v_total, v_pass
      FROM exam WHERE exam_id = v_exam_id;

    SET v_pct = fn_marks_percentage(v_obtained, v_total);

    INSERT INTO result (attempt_id, marks_obtained, percentage, result_status)
    VALUES (p_attempt_id, v_obtained, v_pct, fn_result_status(v_pct, v_pass));

    UPDATE attempt SET status = 'EVALUATED' WHERE attempt_id = p_attempt_id;
END$$

DELIMITER ;
