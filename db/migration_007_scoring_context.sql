-- ==========================================================================
-- InterviewIQ — Migration 007 (Context-weighted scoring: the benchmark)
--
-- WHY THESE COLUMNS EXIST AT ALL:
--   The benchmark is raw × difficulty × evidence × feedback × coverage. Every one
--   of those weights is TUNABLE (app/scoring.py, WEIGHTS). If we stored only `raw`
--   and recomputed the benchmark on read, then the day ops retunes "Easy" from .60
--   to .90, every attempt ever taken would silently change score — a student's July
--   readout would say something different in September, and nobody would know why.
--
--   So: PERSIST, NEVER RECOMPUTE. We store the benchmark, the exact factor values it
--   was computed from, and the weights_version that produced them. An old attempt can
--   then explain itself with the weights it was actually scored on, and two attempts
--   from different versions can be compared honestly — or knowingly not compared.
--
--   `overall` (already on this table) stays the RAW rubric score, untouched. It is the
--   level-anchored verdict on the answers, and no factor here is ever applied to it —
--   that is what keeps "skipped ≠ failed" true.
--
-- ADDITIVE ONLY: nullable columns on an existing table. No drops, no rewrites, no
-- backfill. Rows written before this migration have benchmark = NULL, which reads as
-- "scored before the benchmark existed" — see main._debrief_row_to_response.
-- Run once. Rollback: migration_007_scoring_context_rollback.sql
-- ==========================================================================

ALTER TABLE vyom_debriefs
  -- The context-weighted score the learner sees, 0-100 (display-capped).
  ADD COLUMN benchmark          INT           DEFAULT NULL AFTER overall,
  -- The same maths WITHOUT the 100 cap. A 101 and a 140 both display as 100; only this
  -- column can tell them apart when the weights are next tuned.
  ADD COLUMN benchmark_uncapped DECIMAL(6,1)  DEFAULT NULL AFTER benchmark,
  -- {difficulty, evidence, feedback, coverage, mode} — the exact multipliers used, plus
  -- the inputs they were derived from. This is what "How this score is calculated"
  -- reads, so the explanation is always the one that produced the number.
  ADD COLUMN score_factors      JSON          DEFAULT NULL AFTER benchmark_uncapped,
  -- Which release of scoring.WEIGHTS scored this attempt. The audit trail.
  ADD COLUMN weights_version    VARCHAR(20)   DEFAULT NULL AFTER score_factors,
  -- The band AFTER the context gates (Easy caps at Building, etc.) — this is the band
  -- that is shown. `overall_band` remains what the raw answers EARNED, so the gap
  -- between the two is inspectable rather than lost.
  ADD COLUMN gated_band         VARCHAR(20)   DEFAULT NULL AFTER weights_version,
  -- How many substantive answers this attempt actually had. The evidence floor (< 3 =
  -- no band, no benchmark) is a stored FACT about the attempt, not something re-derived
  -- from a transcript that retention may since have purged.
  ADD COLUMN substantive_answers INT          DEFAULT NULL AFTER gated_band,
  -- FALSE when the attempt fell below the evidence floor. History renders these as
  -- "Ended early — not scored": neutral, visible, never framed as a failure. Quitting
  -- cannot hide a run.
  ADD COLUMN scored             TINYINT(1)    NOT NULL DEFAULT 1 AFTER substantive_answers;

-- History's trend view sorts a user's attempts by date and reads the newest few
-- benchmarks. Without this the placement view table-scans every debrief a user owns.
CREATE INDEX idx_debriefs_benchmark ON vyom_debriefs (benchmark);
