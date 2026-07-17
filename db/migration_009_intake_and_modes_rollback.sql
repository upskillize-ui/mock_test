-- ==========================================================================
-- ROLLBACK for migration 009 (Intake & Modes)
--
-- LOSSY, and specifically about the thing this phase exists to record: which sessions
-- were TEXT. A TEXT session is benchmarked ×0.90 (scoring.WEIGHTS["mode"]), so dropping
-- session_mode discards the reason a stored benchmark has the value it has. Re-applying
-- 009 afterwards defaults every one of those rows back to 'AUDIO', which will quietly
-- claim a typed session was spoken.
--
-- The stored `score_factors` JSON on vyom_debriefs keeps its own copy of the mode factor
-- per attempt, so past benchmarks remain explicable after a rollback — but the session
-- row itself will no longer know how it was answered.
--
-- input_channel is likewise unrecoverable: which individual answers were spoken in a
-- VIDEO session exists nowhere else.
--
-- Run only if 009 must be undone. Prefer leaving the columns in place — they are additive
-- and inert to any code that does not read them.
-- ==========================================================================

ALTER TABLE vyom_messages DROP COLUMN input_channel;
ALTER TABLE vyom_sessions DROP COLUMN session_mode;
