-- ==========================================================================
-- InterviewIQ — Migration 004 ROLLBACK (Voice Phase 3: delivery metrics)
-- Reverses migration_004_delivery_metrics.sql by dropping the additive column.
-- Safe: delivery_metrics holds only derived metrics for spoken answers; dropping
-- it loses those numbers but no transcript, rating, or debrief data.
-- ==========================================================================

ALTER TABLE vyom_messages
  DROP COLUMN delivery_metrics;
