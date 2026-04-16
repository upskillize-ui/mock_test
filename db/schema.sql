-- ==========================================================================
-- Vyom — MySQL schema for Aiven
-- Run this once against your existing Upskillize database.
-- Tables are prefixed `vyom_` so they don't collide with your LMS tables.
-- ==========================================================================

-- 1. Sessions: one row per mock interview attempt
CREATE TABLE IF NOT EXISTS vyom_sessions (
  id               VARCHAR(36)   NOT NULL PRIMARY KEY,
  user_id          VARCHAR(64)   NOT NULL,
  name             VARCHAR(120),
  role             VARCHAR(120)  NOT NULL,
  level            VARCHAR(40)   NOT NULL,
  company          VARCHAR(80),
  duration_min     INT           NOT NULL,
  difficulty       VARCHAR(20)   NOT NULL,
  mode             VARCHAR(20)   NOT NULL,
  focus            VARCHAR(500),
  intro            TEXT,
  status           VARCHAR(20)   NOT NULL DEFAULT 'active', -- active|completed|abandoned
  started_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at         DATETIME,
  INDEX idx_user   (user_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Messages: full conversation history per session
CREATE TABLE IF NOT EXISTS vyom_messages (
  id          BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  session_id  VARCHAR(36)   NOT NULL,
  role        VARCHAR(12)   NOT NULL, -- user | assistant
  content     MEDIUMTEXT    NOT NULL,
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_session (session_id),
  FOREIGN KEY (session_id) REFERENCES vyom_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Debriefs: final structured report per session
CREATE TABLE IF NOT EXISTS vyom_debriefs (
  session_id    VARCHAR(36)   NOT NULL PRIMARY KEY,
  overall       INT,
  sub_scores    JSON,
  strengths     JSON,
  gaps          JSON,
  star          JSON,
  plan          JSON,
  next_focus    TEXT,
  one_line      VARCHAR(500),
  raw_json      JSON,
  created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (session_id) REFERENCES vyom_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Rate limiting — simple per-user daily counter
CREATE TABLE IF NOT EXISTS vyom_rate_limits (
  user_id      VARCHAR(64)   NOT NULL,
  day          DATE          NOT NULL,
  session_count INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Alumni Question Bank — the Golden Point foundation
-- Start populating this from Day 1 via the /alumni/submit endpoint.
CREATE TABLE IF NOT EXISTS vyom_alumni_questions (
  id              BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  submitted_by    VARCHAR(64)   NOT NULL,
  company         VARCHAR(120)  NOT NULL,
  role            VARCHAR(120)  NOT NULL,
  city            VARCHAR(80),
  round_type      VARCHAR(40),  -- HR | Technical | Managerial | System Design | Behavioral
  question        TEXT          NOT NULL,
  interview_date  DATE,
  verified        TINYINT(1)    NOT NULL DEFAULT 0,
  credits_paid    TINYINT(1)    NOT NULL DEFAULT 0,
  created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_company_role (company, role),
  INDEX idx_verified     (verified),
  INDEX idx_date         (interview_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Progress tracking — for the "you scored better than X%" feature and readiness verdict
CREATE OR REPLACE VIEW vyom_user_progress AS
SELECT
  s.user_id,
  s.role,
  COUNT(*) AS total_sessions,
  AVG(d.overall) AS avg_score,
  MAX(d.overall) AS best_score,
  MAX(s.started_at) AS last_session_at
FROM vyom_sessions s
JOIN vyom_debriefs d ON d.session_id = s.id
WHERE s.status = 'completed'
GROUP BY s.user_id, s.role;
