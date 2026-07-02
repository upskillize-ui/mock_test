-- ==========================================================================
-- InterviewIQ — Migration 003 (Phase 0 completion: INT-07 DPDPA foundation)
-- Adds: consent ledger, session soft-delete column for right-to-erasure.
-- Table names keep the vyom_ prefix by design.
-- Run once against your Aiven MySQL database.
-- ==========================================================================

-- INT-07: consent ledger. One row per grant. copy_version pins exactly which
-- wording the learner agreed to (legal copy finalised outside this sprint).
-- session_id is nullable (voice consent is user-scoped, not always per-session)
-- and ON DELETE SET NULL so a consent record survives a transcript purge — the
-- proof of consent should outlive the session data it covered.
CREATE TABLE IF NOT EXISTS vyom_consents (
  id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id      VARCHAR(64)  NOT NULL,
  session_id   VARCHAR(36)  DEFAULT NULL,
  consent_type VARCHAR(40)  NOT NULL,   -- e.g. voice_recording | data_processing
  copy_version VARCHAR(40)  NOT NULL,   -- e.g. v0-draft
  granted_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_consent_user (user_id),
  INDEX idx_consent_type (user_id, consent_type),
  FOREIGN KEY (session_id) REFERENCES vyom_sessions(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- INT-07: right-to-erasure. Soft-delete now (deleted_at set) hides all of a
-- user's data immediately; the nightly purge hard-deletes after the grace window.
ALTER TABLE vyom_sessions
  ADD COLUMN deleted_at DATETIME DEFAULT NULL AFTER ended_at;

CREATE INDEX idx_sessions_deleted ON vyom_sessions (deleted_at);
