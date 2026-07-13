-- ==========================================================================
-- InterviewIQ — Migration 006 ROLLBACK (Interview Room)
-- Drops the focus-event table and the additive columns. Safe: none of it holds
-- transcript, rating, or debrief data — only attention events, derived presence
-- numbers, and the early-wrap markers.
-- ==========================================================================

ALTER TABLE vyom_sessions
  DROP COLUMN camera_at_join,
  DROP COLUMN early_wrap_stage,
  DROP COLUMN early_wrap_reason,
  DROP COLUMN interviewer_name;

ALTER TABLE vyom_messages
  DROP COLUMN presence_metrics;

DROP TABLE IF EXISTS vyom_focus_events;
