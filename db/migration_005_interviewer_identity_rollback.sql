-- ==========================================================================
-- InterviewIQ — Migration 005 ROLLBACK (Conversation Realism v2)
-- Drops the additive interviewer_identity column. Safe: it holds only the
-- improvised tone/continuity line, never transcript, rating, or debrief data.
-- Sessions simply lose cross-turn identity continuity.
-- ==========================================================================

ALTER TABLE vyom_sessions
  DROP COLUMN interviewer_identity;
