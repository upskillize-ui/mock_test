-- ==========================================================================
-- InterviewIQ — Migration 006 (Interview Room: focus events, presence, early wrap)
--
-- PRIVACY (non-negotiable, enforced by this schema):
--   Camera frames NEVER leave the browser. Nothing here stores media, images,
--   video, or facial landmarks — and there is deliberately no column that could.
--   We persist ONLY:
--     * focus EVENTS  — an enum string + a timestamp
--     * presence METRICS — a few derived numbers per answer (compute-and-discard,
--       exactly like the existing delivery_metrics)
--   If a future change wants to store anything richer than a number or an enum
--   here, that is a red flag: stop and re-read the privacy constraint.
--
-- ADDITIVE ONLY: one new table + nullable columns. No drops, no rewrites.
-- Run once. Rollback: migration_006_interview_room_rollback.sql
-- ==========================================================================

-- ── Focus events (Phase C) ────────────────────────────────────────────────
-- One row per debounced attention signal. Strings + timestamps ONLY.
-- event_type is a closed set enforced in the app layer:
--   no_face | multiple_faces | looking_away | tab_hidden | window_blur
-- NOTE: the word "cheating" appears nowhere in this system, by design. These are
-- attention/presence heuristics used to COACH, never to accuse.
CREATE TABLE IF NOT EXISTS vyom_focus_events (
  id          BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
  session_id  VARCHAR(36) NOT NULL,
  event_type  VARCHAR(24) NOT NULL,
  created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_focus_session (session_id),
  INDEX idx_focus_session_type (session_id, event_type),
  FOREIGN KEY (session_id) REFERENCES vyom_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Per-answer presence aggregates (Phase D — schema landed now so the
-- detector sprint needs no further migration). Derived NUMBERS only:
-- {eye_contact_pct, posture_stability, composure_index, presence_pct,
--  engagement_note}. Never landmarks, never an emotion label.
ALTER TABLE vyom_messages
  ADD COLUMN presence_metrics JSON DEFAULT NULL AFTER delivery_metrics;

-- ── Device commitment / early wrap (Phase E) ──────────────────────────────
-- A wrap decision is SERVER-side and persisted, so a refresh cannot dodge it.
ALTER TABLE vyom_sessions
  ADD COLUMN early_wrap_reason VARCHAR(40) DEFAULT NULL AFTER completion_type,
  ADD COLUMN early_wrap_stage  VARCHAR(20) DEFAULT NULL AFTER early_wrap_reason,
  -- Did the learner JOIN with the camera on? If not, the camera-based signals
  -- (no_face / multiple_faces / looking_away) are disabled for the whole session
  -- and the readout omits camera-based presence lines. A camera-off join is an
  -- accessibility path and must never be penalised.
  ADD COLUMN camera_at_join   TINYINT(1) NOT NULL DEFAULT 0 AFTER early_wrap_stage;
