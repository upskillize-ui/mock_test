-- ==========================================================================
-- InterviewIQ — Migration 007 ROLLBACK (Context-weighted scoring)
--
-- Drops the benchmark columns. `overall` (the RAW rubric score), the bands, the
-- calibration profile and every word of the debrief are untouched — this rollback
-- costs the context weighting, not a single scored answer.
--
-- NOTE: this is LOSSY in one direction. Dropping score_factors/weights_version throws
-- away the record of WHICH weights scored each attempt, and re-applying 007 will leave
-- those rows NULL (there is no backfill — the factors cannot be re-derived once the
-- table has been tuned). Roll back on a schema mistake; don't round-trip it casually.
-- ==========================================================================

DROP INDEX idx_debriefs_benchmark ON vyom_debriefs;

ALTER TABLE vyom_debriefs
  DROP COLUMN scored,
  DROP COLUMN substantive_answers,
  DROP COLUMN gated_band,
  DROP COLUMN weights_version,
  DROP COLUMN score_factors,
  DROP COLUMN benchmark_uncapped,
  DROP COLUMN benchmark;
