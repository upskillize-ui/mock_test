-- ==========================================================================
-- InterviewIQ — Migration 008 (Student memory: the variety engine's first slice)
--
-- WHAT THIS IS FOR, TODAY:
--   The interviewer improvises every opening, closing, check-in, re-ask and
--   encouragement. Improvisation alone does not stop repetition ACROSS SESSIONS — the
--   model has no recollection of what it said to this student last month, so "invent
--   something fresh" is an instruction it cannot actually follow. It reliably drifts
--   back to its modal phrasing, and the second-time student hears the same warm hello
--   they heard the first time. That is the moment the person becomes a program.
--
--   So we remember what each student HEARD, and we hand it back to the persona as a
--   do-not-repeat list. This table is that memory.
--
-- WHAT THIS IS FOR, LATER — READ BEFORE CHANGING THE SHAPE:
--   This is deliberately NOT a `vyom_openings` table. It is the first slice of the
--   Flagship longitudinal memory, and it is shaped so that memory can GROW here rather
--   than be thrown away and re-migrated:
--     * `kind` is an open vocabulary, not an ENUM. Today: opening | closing | checkin |
--       reask | encouragement. Tomorrow: recurring_gap, stated_goal, strength, whatever
--       Flagship needs. Adding a kind must never need a migration — an ENUM would make
--       every new memory type a schema change, which is exactly the tax we are avoiding.
--       The closed set is enforced in the app layer (db.MEMORY_KINDS), where it is cheap
--       to extend and cheap to test.
--     * `session_id` is NULLABLE on purpose. Every row today belongs to an attempt, but
--       durable cross-session memory ("they keep under-explaining trade-offs") belongs to
--       the STUDENT and to no single attempt. That row must have a home here.
--     * `meta` is the extension point for structure we cannot predict. Anything that
--       earns an index later gets promoted to a real column then; JSON now means the
--       next memory type does not block on a migration.
--   `user_id` + `created_at` is the spine. Everything else is allowed to grow.
--
-- PRIVACY / DPDPA (this table holds personal data — it is keyed by user_id):
--   * Content here is what the INTERVIEWER said, never the learner's answers. It is a
--     record of our own output, attributed to a student so we can avoid repeating it.
--   * It is NOT covered by the transcript retention window, and that is deliberate: the
--     transcript is purged at TRANSCRIPT_RETENTION_DAYS but this must outlive it, or the
--     variety engine forgets exactly the old sessions it exists to remember. It gets its
--     OWN, longer window (MEMORY_RETENTION_DAYS) enforced by /admin/purge.
--   * Right-to-erasure: the session FK cascades, and /admin/purge additionally deletes
--     user-scoped rows explicitly (the same belt-and-braces the user-scoped
--     vyom_consents table gets), so a NULL-session row can never survive an erasure.
--
-- ADDITIVE ONLY: one new table. No drops, no rewrites, no backfill.
-- Run once. Rollback: migration_008_student_memory_rollback.sql
-- ==========================================================================

CREATE TABLE IF NOT EXISTS vyom_student_memory (
  id              BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  -- The spine. Memory belongs to a STUDENT and outlives any one attempt.
  user_id         VARCHAR(36)  NOT NULL,
  -- The attempt this was heard in. NULLABLE: see the note above — durable cross-session
  -- memory has no single attempt. ON DELETE CASCADE gives us erasure for free on every
  -- row that does have one.
  session_id      VARCHAR(36)  DEFAULT NULL,
  -- Open vocabulary, app-enforced (db.MEMORY_KINDS). NOT an ENUM — see above.
  kind            VARCHAR(32)  NOT NULL,
  -- Verbatim, as the student heard it. Interviewer output only, never a learner answer.
  content         TEXT         NOT NULL,
  -- sha256 of the NORMALISED content (casefolded, punctuation and whitespace collapsed).
  -- Cheap exact-repeat detection that a TEXT column cannot index: MySQL cannot put a
  -- unique/lookup index on TEXT without a prefix length, and a prefix index on prose
  -- collides on every line that shares an opening clause — which, for greetings, is most
  -- of them. A fixed-width digest makes "has this student heard this exact line?" a
  -- point lookup. Near-duplicates are the persona's job; this catches the literal ones.
  content_digest  CHAR(64)     NOT NULL,
  -- Extension point. Promote to a real column if it ever earns an index.
  meta            JSON         DEFAULT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- The read path, and the only one that runs during a live interview: "the last N
  -- things this student heard of this kind." Ordered by created_at so the index serves
  -- the ORDER BY too, rather than filesorting a student's whole history at kickoff.
  INDEX idx_memory_user_kind_recent (user_id, kind, created_at),
  -- The exact-repeat lookup.
  INDEX idx_memory_user_digest (user_id, content_digest),
  -- Retention sweeps scan by age.
  INDEX idx_memory_created (created_at),

  CONSTRAINT fk_memory_session FOREIGN KEY (session_id)
    REFERENCES vyom_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ── The closing ritual's feedback beat (item 4) ───────────────────────────
-- Before the readout, the interviewer asks the student ONE question about how the
-- session was FOR THEM. This is where that answer lands.
--
-- It is stored on the SESSION and not in vyom_student_memory on purpose: memory is what
-- the student HEARD (our output). This is what they SAID about us — a different thing,
-- with a different owner and a different reader. It is product feedback, it belongs to
-- the attempt it is about, and it is read by us, not by the interviewer.
--
-- It is NOT scored, NOT rated, and NOT shown to the model that writes the readout. What
-- they think of us must never touch what we think of them, in either direction.
-- The answer also lives in vyom_messages like any other turn; this column is the
-- queryable copy that survives the transcript retention purge, because "what did students
-- say about the product in Q3" must not be answerable only for the last 90 days.
ALTER TABLE vyom_sessions
  ADD COLUMN experience_feedback TEXT DEFAULT NULL AFTER early_wrap_stage;
