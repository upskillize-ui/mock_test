-- ==========================================================================
-- ROLLBACK for migration 011 (Capacity/Cost phase: per-session cost ledger)
--
-- Drops the per-session cost_ledger store. This discards every stored ledger — the LLM $
-- and Sarvam credit breakdown recorded at each session close. Nothing else depends on it:
-- the ledger is REPORT-ONLY telemetry (a cost dashboard / finance input), it never enters
-- a benchmark, a band, or the interview flow, so a rolled-back session runs and scores
-- exactly as it did — it simply stops carrying its cost record. The in-process meters
-- (tts.py / stt.py / ledger.py) are untouched; they never lived in the database.
--
-- Run only if 011 must be undone. Prefer leaving the column in place — it is additive,
-- nullable, and inert to any code that does not read it.
-- ==========================================================================

ALTER TABLE vyom_sessions DROP COLUMN cost_ledger;
