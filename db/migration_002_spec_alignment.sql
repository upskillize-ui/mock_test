-- ==========================================================================
-- InterviewIQ — Migration 002 (Spec Alignment sprint: INT-04/01/03/02)
-- Adds: server-side stage tracking, per-answer confidence ratings,
--       readiness bands + calibration storage.
-- Table names keep the vyom_ prefix by design (audit: safe-to-leave).
-- Run once against your Aiven MySQL database.
-- ==========================================================================

-- INT-04: server-side stage machine state on the session row
ALTER TABLE vyom_sessions
  ADD COLUMN current_stage   VARCHAR(20)  NOT NULL DEFAULT 'SETUP' AFTER status,
  ADD COLUMN round_index     INT          NOT NULL DEFAULT 0        AFTER current_stage,
  ADD COLUMN awaiting_rating TINYINT(1)   NOT NULL DEFAULT 0        AFTER round_index,
  ADD COLUMN last_answer_id  BIGINT       DEFAULT NULL              AFTER awaiting_rating,
  ADD COLUMN answer_count    INT          NOT NULL DEFAULT 0        AFTER last_answer_id;

-- INT-01: one confidence rating per answered question.
-- answer_id is the vyom_messages.id of the learner's answer; PK blocks double-submit.
-- rating is NULL when the learner chose "prefer not to say".
CREATE TABLE IF NOT EXISTS vyom_answer_ratings (
  answer_id   BIGINT       NOT NULL PRIMARY KEY,
  session_id  VARCHAR(36)  NOT NULL,
  rating      TINYINT      DEFAULT NULL,
  stage       VARCHAR(20)  DEFAULT NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ratings_session (session_id),
  FOREIGN KEY (session_id) REFERENCES vyom_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- INT-03 + INT-02: band + calibration outputs on the debrief.
-- The raw 0-100 `overall` column stays for internal analysis; bands are what the
-- readout surfaces. `calibration` holds the full calibration profile JSON.
ALTER TABLE vyom_debriefs
  ADD COLUMN overall_band  VARCHAR(20)  DEFAULT NULL AFTER overall,
  ADD COLUMN round_bands   JSON         DEFAULT NULL AFTER overall_band,
  ADD COLUMN calibration   JSON         DEFAULT NULL AFTER round_bands;

-- Existing active sessions predate the stage machine; park them at WARMUP so
-- they don't get wedged in 'SETUP'.
UPDATE vyom_sessions
SET current_stage = 'WARMUP'
WHERE status = 'active' AND current_stage = 'SETUP';
