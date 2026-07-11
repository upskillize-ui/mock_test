-- ==========================================================================
-- InterviewIQ — Migration 004 (Voice Phase 3: delivery metrics)
-- Adds: vyom_messages.delivery_metrics — a small JSON blob of DERIVED delivery
-- metrics (wpm, filler counts, pause count) for SPOKEN answers only.
-- ADDITIVE ONLY: one nullable column, no data rewrite, no drops. Existing rows
-- and typed answers keep delivery_metrics = NULL.
-- Privacy: this is NOT audio and NOT a recording — audio is transcribed and
-- discarded upstream. Only the derived numbers land here.
-- Table names keep the vyom_ prefix by design. Run once. Rollback:
-- migration_004_delivery_metrics_rollback.sql
-- ==========================================================================

ALTER TABLE vyom_messages
  ADD COLUMN delivery_metrics JSON DEFAULT NULL AFTER content;
