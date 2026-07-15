/**
 * readoutPolicy — pure decisions about what the end-of-interview readout may show.
 *
 * Deliberately React-free and asset-free so it runs under Node's built-in test runner
 * (`node --test`) with zero deps — same contract as posePolicy / roomPolicy.
 */

/**
 * isEmptyReadout — did the session end before ANY substantive answer?
 *
 * A skipped session is not a failed one. When the server scored nothing — no strengths,
 * no STAR rows, no sub-scores — the readout must show the "ended before any substantive
 * answers" card (plus Presence, if it was measured) and NOTHING that reads as a verdict:
 * no readiness band, no /10 tiles. Rendering "Not Ready · 0/10" for a session nobody
 * answered is exactly the failure this guards against — skipped ≠ failed.
 *
 * The signal is content-based (what the server actually scored), not a self-reported flag,
 * so it holds even when the server still fills in a default band string.
 */
export function isEmptyReadout(d) {
  if (!d) return true;
  const hasStrengths = Array.isArray(d.strengths) && d.strengths.length > 0;
  const hasStar = Array.isArray(d.star_breakdown) && d.star_breakdown.length > 0;
  const hasScores = d.sub_scores && typeof d.sub_scores === "object"
    && Object.keys(d.sub_scores).length > 0;
  return !(hasStrengths || hasStar || hasScores);
}
