-- =============================================================================
-- OEMS — indexes.sql : secondary indexes for the common query paths
--
-- Already provided by schema.sql (no extra index needed):
--   * student lookup by email      -> uq_student_email      (UNIQUE index)
--   * attempts by student AND exam -> uq_attempt_student_exam (student_id, exam_id)
--   * result by attempt            -> uq_result_attempt     (UNIQUE index)
--   * questions of an exam         -> pk_exam_question      (exam_id, question_id)
--                                     uq_exam_question_order (exam_id, question_order)
--   * one answer per question      -> uq_answer_attempt_question (attempt_id, question_id)
-- InnoDB also creates an index for every foreign key that has none.
-- =============================================================================

-- Faculty dashboards: "attempts of exam X that are SUBMITTED / EVALUATED"
CREATE INDEX idx_attempt_exam_status    ON attempt (exam_id, status);

-- Student dashboard: "exams that are ACTIVE, ordered by date"
CREATE INDEX idx_exam_status_date       ON exam (status, exam_date);

-- Faculty: "my exams"
CREATE INDEX idx_exam_created_by_date   ON exam (created_by, exam_date);

-- Reports: toppers / score bands
CREATE INDEX idx_result_percentage      ON result (percentage);

-- Admin search by name
CREATE INDEX idx_student_name           ON student (student_name);

-- Question bank filters
CREATE INDEX idx_question_type          ON question (question_type);

-- Grading queue: ungraded answers of an exam
CREATE INDEX idx_answer_exam_marks      ON answer (exam_id, marks_obtained);

-- Audit timeline per exam
CREATE INDEX idx_exam_audit_exam_time   ON exam_audit (exam_id, changed_at);

-- Execution history page (newest first) and status filters
CREATE INDEX idx_sql_log_executed_at    ON sql_execution_log (executed_at);
CREATE INDEX idx_sql_log_status_time    ON sql_execution_log (status, executed_at);
