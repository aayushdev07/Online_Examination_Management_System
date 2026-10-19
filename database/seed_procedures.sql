-- =============================================================================
-- OEMS — seed_procedures.sql : deterministic synthetic-data generators
--
-- Used by seed.sql (core data) and by init_db.py (bulk data for joins,
-- aggregates and index/performance demonstrations).
--
-- Determinism: instead of RAND(), "random" choices come from CRC32 hashes of
-- ids, so every fresh database gets exactly the same data.
-- =============================================================================

DROP PROCEDURE IF EXISTS sp_seed_exam_attempts;
DROP PROCEDURE IF EXISTS sp_generate_bulk_data;

DELIMITER $$

-- -----------------------------------------------------------------------------
-- sp_seed_exam_attempts
--   Creates attempts for students [p_student_min, p_student_max] on one exam,
--   answers every assigned question, submits, grades and (optionally) creates
--   results — following the same lifecycle the application enforces:
--   IN_PROGRESS -> answers saved -> SUBMITTED -> graded -> EVALUATED.
--
--   p_participation : % of students in the range that attempt the exam
--   p_grade_long    : FALSE leaves answered LONG_ANSWER questions ungraded
--   p_finalize      : TRUE creates result rows (needs everything graded)
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_seed_exam_attempts(
    IN p_exam_id       INT UNSIGNED,
    IN p_student_min   INT UNSIGNED,
    IN p_student_max   INT UNSIGNED,
    IN p_participation INT,
    IN p_grade_long    BOOLEAN,
    IN p_finalize      BOOLEAN)
MODIFIES SQL DATA
SQL SECURITY INVOKER
COMMENT 'Seed utility: deterministic attempts/answers/results for one exam'
BEGIN
    DECLARE v_last_attempt INT UNSIGNED;

    SET v_last_attempt = (SELECT COALESCE(MAX(attempt_id), 0) FROM attempt);

    -- 1. attempts start inside the exam window, and never in the future
    --    (the window is cut at NOW() for exams that are still open)
    INSERT INTO attempt (student_id, exam_id, started_at, status)
    SELECT s.student_id, e.exam_id,
           e.exam_date + INTERVAL (CRC32(CONCAT(s.student_id, ':', e.exam_id))
                 % GREATEST(1, TIMESTAMPDIFF(MINUTE, e.exam_date, LEAST(e.deadline, NOW())) - e.duration_minutes)) MINUTE,
           'IN_PROGRESS'
      FROM student s
      JOIN exam e ON e.exam_id = p_exam_id
     WHERE s.student_id BETWEEN p_student_min AND p_student_max
       AND CRC32(CONCAT('p', s.student_id, ':', e.exam_id)) % 100 < p_participation
       AND NOT EXISTS (SELECT 1 FROM attempt x
                        WHERE x.student_id = s.student_id AND x.exam_id = e.exam_id)
     ORDER BY s.student_id;

    -- 2. answers: each student has a "skill" between 30% and 89%;
    --    ~6% of questions are left unanswered (NULL)
    INSERT INTO answer (attempt_id, exam_id, question_id, selected_answer, answered_at)
    SELECT a.attempt_id, a.exam_id, q.question_id,
           CASE
             WHEN CRC32(CONCAT(a.student_id, '-', q.question_id)) % 100 >= 94 THEN NULL
             WHEN CRC32(CONCAT(a.student_id, '-', q.question_id)) % 100 < 30 + (a.student_id * 7) % 60 THEN
                  CASE q.question_type
                    WHEN 'LONG_ANSWER' THEN CONCAT('Detailed answer to Q', q.question_id,
                                                   ': covers the key definitions, steps and an example.')
                    ELSE q.correct_answer
                  END
             ELSE
                  CASE q.question_type
                    WHEN 'MCQ' THEN IF(JSON_UNQUOTE(JSON_EXTRACT(q.options, '$[0]')) = q.correct_answer,
                                       JSON_UNQUOTE(JSON_EXTRACT(q.options, '$[1]')),
                                       JSON_UNQUOTE(JSON_EXTRACT(q.options, '$[0]')))
                    WHEN 'TRUE_FALSE'   THEN IF(q.correct_answer = 'TRUE', 'FALSE', 'TRUE')
                    WHEN 'SHORT_ANSWER' THEN 'not sure'
                    ELSE CONCAT('Brief answer to Q', q.question_id, ': mentions the idea without much detail.')
                  END
           END,
           a.started_at + INTERVAL eq.question_order MINUTE
      FROM attempt a
      JOIN exam_question eq ON eq.exam_id = a.exam_id
      JOIN question q       ON q.question_id = eq.question_id
     WHERE a.attempt_id > v_last_attempt;

    -- 3. submit (within the allowed duration)
    UPDATE attempt a
      JOIN exam e ON e.exam_id = a.exam_id
       SET a.status       = 'SUBMITTED',
           a.submitted_at = a.started_at + INTERVAL (5 + a.attempt_id * 13 % GREATEST(1, e.duration_minutes - 5)) MINUTE
     WHERE a.attempt_id > v_last_attempt;

    -- 4. grade: unanswered = 0, objective types compared with the key,
    --    long answers get 40-100% of their marks (or stay NULL = pending)
    UPDATE answer an
      JOIN question q       ON q.question_id = an.question_id
      JOIN exam_question eq ON eq.exam_id = an.exam_id AND eq.question_id = an.question_id
       SET an.marks_obtained =
           CASE
             WHEN an.selected_answer IS NULL THEN 0
             WHEN q.question_type <> 'LONG_ANSWER' THEN
                  IF(LOWER(TRIM(an.selected_answer)) = LOWER(TRIM(q.correct_answer)), eq.marks_assigned, 0)
             WHEN p_grade_long THEN
                  ROUND(eq.marks_assigned * (40 + CRC32(CONCAT('g', an.answer_id)) % 61) / 100, 0)
             ELSE NULL
           END
     WHERE an.attempt_id > v_last_attempt;

    -- 5. results for fully graded attempts
    IF p_finalize THEN
        INSERT INTO result (attempt_id, marks_obtained, percentage, result_status, evaluated_at)
        SELECT a.attempt_id,
               SUM(an.marks_obtained),
               fn_marks_percentage(SUM(an.marks_obtained), e.total_marks),
               fn_result_status(fn_marks_percentage(SUM(an.marks_obtained), e.total_marks), e.pass_percentage),
               LEAST(NOW(), a.submitted_at + INTERVAL 2 DAY)
          FROM attempt a
          JOIN exam e    ON e.exam_id = a.exam_id
          JOIN answer an ON an.attempt_id = a.attempt_id
         WHERE a.attempt_id > v_last_attempt
         GROUP BY a.attempt_id, e.total_marks, e.pass_percentage, a.submitted_at
        HAVING COUNT(an.marks_obtained) = COUNT(*);

        UPDATE attempt a
          JOIN result r ON r.attempt_id = a.attempt_id
           SET a.status = 'EVALUATED'
         WHERE a.attempt_id > v_last_attempt;
    END IF;
END$$

-- -----------------------------------------------------------------------------
-- sp_generate_bulk_data(n)
--   Adds n synthetic students and runs them through every COMPLETED exam
--   (70 % participation). Uses a recursive CTE for set-based inserts and a
--   cursor to walk the exams.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_generate_bulk_data(IN p_students INT)
MODIFIES SQL DATA
SQL SECURITY INVOKER
COMMENT 'Seed utility: n synthetic students with attempts on completed exams'
BEGIN
    DECLARE v_first   INT UNSIGNED;
    DECLARE v_last    INT UNSIGNED;
    DECLARE v_offset  INT UNSIGNED;
    DECLARE v_hash    VARCHAR(255);
    DECLARE v_exam_id INT UNSIGNED;
    DECLARE v_done    BOOLEAN DEFAULT FALSE;
    DECLARE cur_exams CURSOR FOR
        SELECT exam_id FROM exam WHERE status = 'COMPLETED' ORDER BY exam_id;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = TRUE;

    IF p_students IS NULL OR p_students < 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_generate_bulk_data: count must be >= 1';
    END IF;

    SET v_offset = (SELECT COALESCE(MAX(student_id), 0) FROM student);
    -- every synthetic account shares the demo password of the first student
    SET v_hash   = (SELECT password_hash FROM student ORDER BY student_id LIMIT 1);
    IF v_hash IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_generate_bulk_data: run seed.sql first';
    END IF;

    SET SESSION cte_max_recursion_depth = GREATEST(1000, p_students + 1);

    INSERT INTO student (student_name, email, username, password_hash, created_at)
    WITH RECURSIVE seq (n) AS (
        SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < p_students
    ),
    named AS (
        SELECT v_offset + n AS k,
               ELT(1 + (v_offset + n) % 30,
                   'Aarav','Vivaan','Aditya','Vihaan','Arjun','Sai','Reyansh','Ayaan','Krishna','Ishaan',
                   'Shaurya','Atharv','Advik','Pranav','Rohan','Diya','Saanvi','Ananya','Aadhya','Pari',
                   'Anika','Navya','Myra','Sara','Ira','Kiara','Riya','Aditi','Meera','Tanvi') AS first_name,
               ELT(1 + ((v_offset + n) DIV 30) % 30,
                   'Sharma','Verma','Patel','Shah','Mehta','Joshi','Kulkarni','Deshpande','Iyer','Nair',
                   'Reddy','Rao','Gupta','Singh','Kapoor','Malhotra','Chopra','Bose','Das','Banerjee',
                   'Pillai','Menon','Jain','Agarwal','Pandey','Mishra','Naik','Pawar','Gaikwad','Kamath') AS last_name
          FROM seq
    )
    SELECT CONCAT(first_name, ' ', last_name),
           CONCAT(LOWER(first_name), '.', LOWER(last_name), '.', k, '@students.oems.edu'),
           CONCAT('stu', LPAD(k, 6, '0')),
           v_hash,
           NOW() - INTERVAL (k * 7919 % 730) DAY - INTERVAL (k * 31 % 1440) MINUTE
      FROM named;

    SET v_first = v_offset + 1;
    SET v_last  = v_offset + p_students;

    OPEN cur_exams;
    exam_loop: LOOP
        FETCH cur_exams INTO v_exam_id;
        IF v_done THEN
            LEAVE exam_loop;
        END IF;
        CALL sp_seed_exam_attempts(v_exam_id, v_first, v_last, 70, TRUE, TRUE);
    END LOOP;
    CLOSE cur_exams;
END$$

DELIMITER ;
