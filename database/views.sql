-- =============================================================================
-- OEMS — views.sql : reusable virtual tables
-- A view stores a query, not data: every SELECT against it re-reads the base
-- tables, so it always reflects their current state.
-- =============================================================================

-- One row per exam with its author and live counters.
CREATE OR REPLACE VIEW exam_overview AS
SELECT
    e.exam_id,
    e.title,
    e.subject,
    e.status,
    e.exam_date,
    e.deadline,
    e.duration_minutes,
    e.total_marks,
    e.pass_percentage,
    e.results_released,
    f.faculty_name                                                AS created_by_name,
    (SELECT COUNT(*) FROM exam_question eq WHERE eq.exam_id = e.exam_id)          AS question_count,
    (SELECT COUNT(*) FROM attempt a WHERE a.exam_id = e.exam_id)                  AS attempt_count,
    (SELECT COUNT(*) FROM attempt a WHERE a.exam_id = e.exam_id
                                      AND a.status <> 'IN_PROGRESS')              AS submitted_count
FROM exam e
JOIN faculty_admin f ON f.faculty_admin_id = e.created_by;

-- One row per evaluated attempt: who, which exam, what score.
CREATE OR REPLACE VIEW student_result_view AS
SELECT
    s.student_id,
    s.student_name,
    s.email,
    e.exam_id,
    e.title            AS exam_title,
    e.subject,
    a.attempt_id,
    a.started_at,
    a.submitted_at,
    r.result_id,
    r.marks_obtained,
    e.total_marks,
    r.percentage,
    r.result_status,
    r.evaluated_at,
    e.results_released
FROM result r
JOIN attempt a ON a.attempt_id = r.attempt_id
JOIN student s ON s.student_id = a.student_id
JOIN exam    e ON e.exam_id    = a.exam_id;

-- One row per exam with aggregate performance. LEFT JOINs keep exams that
-- have no attempts/results yet (their counters show 0 / NULL).
CREATE OR REPLACE VIEW exam_performance_view AS
SELECT
    e.exam_id,
    e.title,
    e.subject,
    e.status,
    COUNT(a.attempt_id)                                          AS attempt_count,
    COUNT(r.result_id)                                           AS evaluated_count,
    ROUND(AVG(r.percentage), 2)                                  AS avg_percentage,
    MIN(r.percentage)                                            AS min_percentage,
    MAX(r.percentage)                                            AS max_percentage,
    COALESCE(SUM(r.result_status = 'PASS'), 0)                   AS pass_count,
    ROUND(100 * SUM(r.result_status = 'PASS') / NULLIF(COUNT(r.result_id), 0), 2) AS pass_rate
FROM exam e
LEFT JOIN attempt a ON a.exam_id    = e.exam_id
LEFT JOIN result  r ON r.attempt_id = a.attempt_id
GROUP BY e.exam_id, e.title, e.subject, e.status;
