-- ==========================================================================
-- InterviewIQ — Migration 005 (Conversation Realism v2: dynamic interviewer)
-- Adds: vyom_sessions.interviewer_identity — the ONE-LINE identity the model
-- improvises at session start (tone/pacing/warmth/phrasing habits). It is replayed
-- into the system prompt on every later turn so the interviewer stays in character.
-- Never shown to the candidate; it is continuity state, not content.
-- ADDITIVE ONLY: one nullable column, no data rewrite, no drops. Existing sessions
-- keep interviewer_identity = NULL and simply behave as before.
-- Run once. Rollback: migration_005_interviewer_identity_rollback.sql
-- ==========================================================================

ALTER TABLE vyom_sessions
  ADD COLUMN interviewer_identity VARCHAR(400) DEFAULT NULL AFTER intro;
