/**
 * readoutPolicy — pure decisions about what the end-of-interview readout may show.
 *
 * Deliberately React-free and asset-free so it runs under Node's built-in test runner
 * (`node --test`) with zero deps — same contract as posePolicy / roomPolicy.
 */

/** The evidence floor, mirrored from the server (app/scoring.MIN_SUBSTANTIVE_ANSWERS).
 *  The server decides; this is the client refusing to render a verdict it was not given. */
export const MIN_SUBSTANTIVE_ANSWERS = 3;

/**
 * isEmptyReadout — is there a verdict here at all?
 *
 * A skipped session is not a failed one. When there is nothing to score, the readout must
 * show the "Insufficient evidence" card (plus Presence, if it was measured) and NOTHING
 * that reads as a verdict: no readiness band, no benchmark, no /10 tiles. Rendering
 * "Not Ready · 0/10" for a session nobody answered is exactly the failure this guards
 * against — skipped ≠ failed.
 *
 * Two things make a readout empty, and the order matters:
 *
 *   1. `scored === false` — the SERVER applied the evidence floor (fewer than three
 *      substantive answers). This is authoritative: it is the same count the server
 *      persisted, and it holds even when the model still produced prose.
 *   2. Nothing was actually scored — no strengths, no STAR rows, no sub-scores. The
 *      content-based fallback, kept because it needs no new field and therefore still
 *      protects sessions debriefed before `scored` existed.
 *
 * The signal is never a self-reported band string: the server may still fill in a default
 * band, and a label is not evidence.
 */
export function isEmptyReadout(d) {
  if (!d) return true;
  if (d.scored === false) return true;
  const hasStrengths = Array.isArray(d.strengths) && d.strengths.length > 0;
  const hasStar = Array.isArray(d.star_breakdown) && d.star_breakdown.length > 0;
  const hasScores = d.sub_scores && typeof d.sub_scores === "object"
    && Object.keys(d.sub_scores).length > 0;
  return !(hasStrengths || hasStar || hasScores);
}

/**
 * hasMinimumEvidence — did this attempt clear the floor?
 *
 * Back-compat matters here: a readout from before this sprint has no `substantive_answers`
 * field, and treating "I don't know how many" as "not enough" would retroactively unscore
 * every session in a learner's history. Unknown means we defer to whether it was scored.
 */
export function hasMinimumEvidence(d) {
  if (!d) return false;
  if (typeof d.substantive_answers === "number") {
    return d.substantive_answers >= MIN_SUBSTANTIVE_ANSWERS;
  }
  return d.scored !== false && !isEmptyReadout(d);
}

/**
 * canRenderBand — may this readout print a readiness band anywhere?
 *
 * There is exactly ONE band on a readout and it lives in the Readiness block (item 9).
 * This answers whether that block exists at all — not where it goes.
 */
export function canRenderBand(d) {
  return !isEmptyReadout(d) && Boolean(d && d.overall_band);
}

/**
 * historyStatus — how a session reads in the history list.
 *
 * An attempt that fell below the evidence floor is SHOWN, always: quitting cannot make a
 * run disappear (item 6). It is shown as "Ended early — not scored" — navy and neutral,
 * never red, never a failure. It has no benchmark because none was computed, not because
 * the person did badly, and the copy has to carry that difference.
 */
export function historyStatus(s) {
  if (!s) return { label: "Not scored", tone: "neutral", benchmark: null };
  if (s.status === "active") return { label: "In progress", tone: "neutral", benchmark: null };
  if (s.scored === false) {
    return { label: "Ended early — not scored", tone: "neutral", benchmark: null };
  }
  if (s.benchmark == null) {
    // Scored, but before benchmarks existed (or on a drifted database). Say what is true:
    // there is no benchmark to show. Do NOT fall back to the raw score — a raw 100 from an
    // Easy/10-min run sitting in a benchmark column is the exact lie this sprint removed.
    return { label: "Not scored", tone: "neutral", benchmark: null };
  }
  return { label: s.band || "Scored", tone: "band", benchmark: s.benchmark };
}

/**
 * trendDirection — which way is this learner going?
 *
 * Compares the newest benchmark against the average of the ones before it, inside the
 * window. Trend over trophy (item 7): a best-ever is a story about one good day.
 * `benchmarks` is newest-first. Fewer than two attempts is not a trend, and saying so
 * beats drawing an arrow from a single point.
 */
export function trendDirection(benchmarks) {
  const vals = (benchmarks || []).filter((v) => typeof v === "number");
  if (vals.length < 2) return "none";
  const [latest, ...rest] = vals;
  const prior = rest.reduce((a, b) => a + b, 0) / rest.length;
  if (latest > prior + 2) return "up";
  if (latest < prior - 2) return "down";
  return "flat";
}
