-- =============================================================================
-- OEMS — users.sql : DCL reference for the MySQL accounts
--
-- scripts/init_db.py runs exactly these statements (with the passwords from
-- .env). This file documents the security model and lets you set it up by
-- hand. Replace every <...> placeholder before running it as an administrator.
-- Use '%' instead of 'localhost' if your MySQL only matches TCP clients by IP.
-- =============================================================================

-- Application account: data access for the API + read access to object
-- definitions (SHOW VIEW / TRIGGER / SHOW_ROUTINE) for the schema explorer.
CREATE USER IF NOT EXISTS 'oems_app'@'localhost' IDENTIFIED BY '<app password>';
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW, TRIGGER ON oems_db.* TO 'oems_app'@'localhost';
GRANT SHOW_ROUTINE ON *.* TO 'oems_app'@'localhost';

-- Read-only account: reports, DQL / join / subquery demos, table viewer.
-- Any INSERT/UPDATE/DELETE through it is rejected by MySQL (error 1142).
CREATE USER IF NOT EXISTS 'oems_reader'@'localhost' IDENTIFIED BY '<reader password>';
GRANT SELECT ON oems_db.* TO 'oems_reader'@'localhost';
-- read-only routines are SQL SECURITY INVOKER, so EXECUTE adds no new rights
GRANT EXECUTE ON FUNCTION  oems_db.fn_marks_percentage   TO 'oems_reader'@'localhost';
GRANT EXECUTE ON FUNCTION  oems_db.fn_result_status      TO 'oems_reader'@'localhost';
GRANT EXECUTE ON PROCEDURE oems_db.GetExamDetails        TO 'oems_reader'@'localhost';
GRANT EXECUTE ON PROCEDURE oems_db.GetStudentResults     TO 'oems_reader'@'localhost';
GRANT EXECUTE ON PROCEDURE oems_db.sp_exam_attempt_stats TO 'oems_reader'@'localhost';

-- Lab account: everything, but ONLY inside the disposable lab database.
-- DDL, DML, TCL, view/trigger/routine/index demonstrations run here.
CREATE USER IF NOT EXISTS 'oems_lab'@'localhost' IDENTIFIED BY '<lab password>';
GRANT ALL PRIVILEGES ON oems_lab.* TO 'oems_lab'@'localhost';

-- DCL demonstration account: may create users and pass on lab privileges.
-- Used only by the predefined GRANT/REVOKE examples, never for free-form SQL.
CREATE USER IF NOT EXISTS 'oems_lab_dcl'@'localhost' IDENTIFIED BY '<dcl password>';
GRANT CREATE USER ON *.* TO 'oems_lab_dcl'@'localhost';
GRANT ALL PRIVILEGES ON oems_lab.* TO 'oems_lab_dcl'@'localhost' WITH GRANT OPTION;

-- Verify
SHOW GRANTS FOR 'oems_app'@'localhost';
SHOW GRANTS FOR 'oems_reader'@'localhost';
SHOW GRANTS FOR 'oems_lab'@'localhost';
SHOW GRANTS FOR 'oems_lab_dcl'@'localhost';
