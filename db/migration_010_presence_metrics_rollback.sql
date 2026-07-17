-- ==========================================================================
-- ROLLBACK for migration 010 (Phase D: presence metrics m1–m8)
--
-- Drops the session-level presence_metrics store. This discards any m1–m8 that were
-- recorded — but presence is REPORT-ONLY and never entered a benchmark or a band, so no
-- score is affected by losing them: a rolled-back session simply shows the "No presence
-- data" line, exactly as a camera-off join always does. Nothing is re-scored.
--
-- The 006 per-message vyom_messages.presence_metrics column is NOT touched here — 010
-- never created it and never wrote it.
--
-- Run only if 010 must be undone. Prefer leaving the column in place — it is additive,
-- nullable, and inert to any code that does not read it.
-- ==========================================================================

ALTER TABLE vyom_sessions DROP COLUMN presence_metrics;
