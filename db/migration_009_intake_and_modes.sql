-- ==========================================================================
-- InterviewIQ — Migration 009 (Intake & Modes: how the student answers)
--
-- WHY A NEW COLUMN AND NOT THE OBVIOUS ONE:
--   `vyom_sessions.mode` is ALREADY TAKEN, and it does not mean what its name suggests.
--   It holds the FEEDBACK style — interview | coach — i.e. WHEN the student hears how
--   they did (at the end, or after every answer). The lobby relabelled that heading to
--   FEEDBACK months ago; the column kept its name, and scoring.feedback_factor() is where
--   the two meet.
--
--   This migration adds a genuinely different axis: HOW they answer. Typed, spoken, or on
--   camera. Overloading `mode` to carry both would silently re-weight every historical
--   session the first time someone read the wrong one — the two axes even have colliding
--   weights (feedback: interview 1.00 / coach 0.90; mode: TEXT 0.90 / AUDIO 1.00 /
--   VIDEO 1.00). So it gets its own column and an unambiguous name.
--
--   If you are here to "clean up the duplicate mode columns": they are not duplicates.
--   Read scoring.WEIGHTS — there are two independent factors, and both are multiplied.
--
-- ADDITIVE ONLY: two new columns, both with safe defaults, no backfill, no rewrites.
-- Existing rows are AUDIO by default, which is exactly what they were: every session that
-- ever ran, ran with the mic and TTS on. That is not a guess — it is the only mode that
-- existed before this migration.
--
-- Run once. Rollback: migration_009_intake_and_modes_rollback.sql
-- ==========================================================================

-- ── 1. The session's MODE ────────────────────────────────────────────────────
-- TEXT | AUDIO | VIDEO.
--   TEXT  — typed. No mic permission is ever requested, no TTS is ever synthesised
--           (zero Sarvam spend), and Delivery metrics are NOT computed: there is no voice
--           to measure, and inventing a pace score for a typed answer would be a lie with
--           a number on it.
--   AUDIO — spoken. The behaviour every session had before this column existed.
--   VIDEO — camera on, and the student may speak OR type per question, switching freely.
--           Delivery is measured over the spoken answers only, and the readout says so.
--
-- NOT an ENUM, deliberately — same reasoning as vyom_student_memory.kind (008): the closed
-- set is enforced in the app layer (intake.MODES), where extending it is a code change and
-- a test, not a schema change and a deploy window.
--
-- DEFAULT 'AUDIO' matters for more than tidiness: an older client that does not know this
-- field exists still starts a normal spoken session, and a row written during a partial
-- deploy is never NULL-mode. There is no such thing as a session with no mode.
ALTER TABLE vyom_sessions
  ADD COLUMN session_mode VARCHAR(10) NOT NULL DEFAULT 'AUDIO' AFTER mode;


-- ── 2. How each individual answer arrived ────────────────────────────────────
-- VIDEO lets a student speak question 1, type question 2 and speak question 3. Delivery
-- (pace, fillers, pauses) is only meaningful over the spoken ones, so each answer has to
-- carry its own channel — the SESSION's mode cannot answer "was THIS answer spoken?".
--
-- 'voice' | 'text'. NULL means "not an answer, or written before this column existed":
--   * interviewer turns have no input channel at all;
--   * every historical row predates the question.
-- NULL is therefore honest and load-bearing — do NOT backfill it to 'voice'. A readout
-- that says "Delivery measured on your 4 spoken answers" must count answers we actually
-- know were spoken, not answers we assumed were.
ALTER TABLE vyom_messages
  ADD COLUMN input_channel VARCHAR(10) DEFAULT NULL;
