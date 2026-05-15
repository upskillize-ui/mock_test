-- ==========================================================================
-- InterviewIQ — Migration 001
-- Adds: round columns, history-tracking columns, indexes.
-- Run once against your Aiven MySQL database.
-- ==========================================================================

ALTER TABLE vyom_sessions
  ADD COLUMN round VARCHAR(20) NOT NULL DEFAULT 'full' AFTER mode,
  ADD COLUMN round_label VARCHAR(80) DEFAULT '' AFTER round,
  ADD COLUMN round_detail TEXT AFTER round_label;

ALTER TABLE vyom_sessions
  ADD COLUMN actual_duration_seconds INT DEFAULT NULL AFTER ended_at,
  ADD COLUMN user_message_count INT NOT NULL DEFAULT 0 AFTER actual_duration_seconds,
  ADD COLUMN assistant_message_count INT NOT NULL DEFAULT 0 AFTER user_message_count,
  ADD COLUMN completion_type VARCHAR(20) DEFAULT NULL AFTER assistant_message_count;

CREATE INDEX idx_user_started ON vyom_sessions (user_id, started_at);
CREATE INDEX idx_session_msg_order ON vyom_messages (session_id, id);

UPDATE vyom_sessions s
LEFT JOIN (
    SELECT session_id,
           SUM(role = 'user') AS u_cnt,
           SUM(role = 'assistant') AS a_cnt
    FROM vyom_messages
    GROUP BY session_id
) m ON m.session_id = s.id
SET s.user_message_count = COALESCE(m.u_cnt, 0),
    s.assistant_message_count = COALESCE(m.a_cnt, 0)
WHERE s.id IS NOT NULL;

UPDATE vyom_sessions
SET actual_duration_seconds = TIMESTAMPDIFF(SECOND, started_at, ended_at)
WHERE ended_at IS NOT NULL AND actual_duration_seconds IS NULL;