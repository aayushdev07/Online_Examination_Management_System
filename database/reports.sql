-- =============================================================================
-- OEMS — reports.sql : analytical queries
--
-- Each report starts with a header line:
--   -- @report <id> | <title> | <one-line description>
-- The backend reads this file and exposes every report on the Reports page,
-- executing it through the READ-ONLY database account.
-- =============================================================================

-- @report toppers_per_exam | Top 3 students per exam | ROW_NUMBER() per exam; ties broken by earlier submission
WITH ranked AS (
    SELECT e.exam_id, e.title AS exam_title, s.student_name, r.percentage, a.submitted_at,
           ROW_NUMBER() OVER (PARTITION BY e.exam_id
                              ORDER BY r.percentage DESC, a.submitted_at, a.attempt_id) AS exam_rank
      FROM result r
      JOIN attempt a ON a.attempt_id = r.attempt_id
      JOIN student s ON s.student_id = a.student_id
      JOIN exam e    ON e.exam_id    = a.exam_id
)
SELECT exam_id, exam_title, exam_rank, student_name, percentage, submitted_at
  FROM ranked
 WHERE exam_rank <= 3
 ORDER BY exam_id, exam_rank;

-- @report subject_performance | Performance by subject | GROUP BY subject with averages and pass rate
SELECT e.subject,
       COUNT(DISTINCT e.exam_id)                                   AS exams,
       COUNT(r.result_id)                                          AS results,
       ROUND(AVG(r.percentage), 2)                                 AS avg_percentage,
       ROUND(100 * AVG(r.result_status = 'PASS'), 2)               AS pass_rate
  FROM exam e
  JOIN attempt a ON a.exam_id    = e.exam_id
  JOIN result r  ON r.attempt_id = a.attempt_id
 GROUP BY e.subject
 ORDER BY avg_percentage DESC;

-- @report question_difficulty | Question difficulty | Share of answers that earned full marks, hardest first
SELECT q.question_id, eq.exam_id, q.question_type,
       LEFT(q.question_text, 70)                                   AS question,
       COUNT(an.answer_id)                                         AS answers,
       ROUND(100 * AVG(an.marks_obtained = eq.marks_assigned), 2)  AS full_marks_pct
  FROM answer an
  JOIN exam_question eq ON eq.exam_id = an.exam_id AND eq.question_id = an.question_id
  JOIN question q       ON q.question_id = an.question_id
 WHERE an.marks_obtained IS NOT NULL
 GROUP BY q.question_id, eq.exam_id, q.question_type, q.question_text
 ORDER BY full_marks_pct ASC
 LIMIT 25;

-- @report score_distribution | Score distribution | Results bucketed into 10-point percentage bands
SELECT e.title AS exam_title,
       CONCAT(LEAST(FLOOR(r.percentage / 10) * 10, 90), '-',
              LEAST(FLOOR(r.percentage / 10) * 10, 90) + 10, '%')  AS band,
       COUNT(*)                                                    AS students
  FROM result r
  JOIN attempt a ON a.attempt_id = r.attempt_id
  JOIN exam e    ON e.exam_id    = a.exam_id
 GROUP BY e.exam_id, e.title, band
 ORDER BY e.exam_id, band;

-- @report pending_grading | Grading queue | Answers still waiting for manual marks, per exam
SELECT e.exam_id, e.title AS exam_title,
       COUNT(DISTINCT an.attempt_id) AS attempts_waiting,
       COUNT(*)                      AS ungraded_answers
  FROM answer an
  JOIN exam e ON e.exam_id = an.exam_id
 WHERE an.marks_obtained IS NULL
 GROUP BY e.exam_id, e.title
 ORDER BY ungraded_answers DESC;

-- @report inactive_students | Students who never attempted an exam | NOT EXISTS anti-join
SELECT s.student_id, s.student_name, s.email, s.created_at
  FROM student s
 WHERE NOT EXISTS (SELECT 1 FROM attempt a WHERE a.student_id = s.student_id)
 ORDER BY s.created_at DESC
 LIMIT 50;

-- @report above_exam_average | Students above their exam's average | Correlated subquery per exam
SELECT e.title AS exam_title, s.student_name, r.percentage,
       (SELECT ROUND(AVG(r2.percentage), 2)
          FROM result r2 JOIN attempt a2 ON a2.attempt_id = r2.attempt_id
         WHERE a2.exam_id = a.exam_id)                             AS exam_average
  FROM result r
  JOIN attempt a ON a.attempt_id = r.attempt_id
  JOIN student s ON s.student_id = a.student_id
  JOIN exam e    ON e.exam_id    = a.exam_id
 WHERE s.student_id <= 12
   AND r.percentage > (SELECT AVG(r2.percentage)
                         FROM result r2 JOIN attempt a2 ON a2.attempt_id = r2.attempt_id
                        WHERE a2.exam_id = a.exam_id)
 ORDER BY e.exam_id, r.percentage DESC;

-- @report monthly_registrations | Monthly student registrations | Last 12 months, GROUP BY month
SELECT DATE_FORMAT(created_at, '%Y-%m') AS month,
       COUNT(*)                         AS new_students
  FROM student
 WHERE created_at >= DATE_FORMAT(CURDATE() - INTERVAL 11 MONTH, '%Y-%m-01')
 GROUP BY month
 ORDER BY month;

-- @report faculty_workload | Faculty workload | Exams and questions authored per staff member (LEFT JOIN keeps admins)
SELECT f.faculty_admin_id, f.faculty_name, f.role,
       (SELECT COUNT(*) FROM exam e     WHERE e.created_by = f.faculty_admin_id) AS exams_created,
       (SELECT COUNT(*) FROM question q WHERE q.created_by = f.faculty_admin_id) AS questions_authored
  FROM faculty_admin f
 ORDER BY exams_created DESC, f.faculty_name;

-- @report exam_audit_timeline | Exam audit timeline | Latest changes captured by the exam triggers
SELECT ea.audit_id, ea.exam_id, ea.action, ea.changed_columns,
       ea.old_duration, ea.new_duration, ea.old_status, ea.new_status,
       ea.db_user, ea.changed_at
  FROM exam_audit ea
 ORDER BY ea.changed_at DESC, ea.audit_id DESC
 LIMIT 50;
