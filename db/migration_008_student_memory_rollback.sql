-- ==========================================================================
-- InterviewIQ — Migration 008 ROLLBACK (Student memory)
--
-- Drops the variety engine's memory table. The app degrades cleanly without it: every
-- read and write is wrapped defensively (db.recent_lines / db.remember_line), a missing
-- table means the do-not-repeat list is simply empty, and the interviewer improvises as
-- it did before — it just cannot remember what it already said to this student.
--
-- DATA LOSS: this discards every student's heard-lines history. It cannot be recovered
-- by re-running migration 008; the table comes back empty and repetition-avoidance
-- restarts from nothing. That is survivable (the engine refills as students interview
-- again) but it is real, so this is not a no-op rollback.
-- ==========================================================================

DROP TABLE IF EXISTS vyom_student_memory;

-- Also discards every student's answer to "how was that session for you?". Same caveat:
-- real data loss, not recoverable by re-running migration 008.
ALTER TABLE vyom_sessions DROP COLUMN experience_feedback;
