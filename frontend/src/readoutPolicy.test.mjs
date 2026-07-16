/**
 * Readout policy tests. Run with:  npm test   (node --test, no new deps)
 *
 * Pins the one rule the embed fixup adds: a session that ended before any substantive
 * answer must be detected as EMPTY, so the readout never renders a band or /10 tiles for
 * it. Skipped ≠ failed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import {
  isEmptyReadout, hasMinimumEvidence, canRenderBand, historyStatus, trendDirection,
  MIN_SUBSTANTIVE_ANSWERS,
} from "./readoutPolicy.js";

test("end-at-question-1: nothing scored -> empty (no band, no tiles)", () => {
  // What /session/end returns when the room wrapped before an answer landed: an opening
  // line and maybe an early-wrap reason, but nothing scored.
  const d = { one_line: "This session ended before any substantive answers.", early_wrap: "no_answer_timeout" };
  assert.equal(isEmptyReadout(d), true);
});

test("a default band string does NOT make an empty session look answered", () => {
  // The server may still fill overall_band; content is what decides, not the label.
  assert.equal(isEmptyReadout({ overall_band: "Not Ready", sub_scores: {} }), true);
  assert.equal(isEmptyReadout({ overall_band: "Not Ready", strengths: [], star_breakdown: [] }), true);
});

test("null / undefined report is treated as empty, never as a verdict", () => {
  assert.equal(isEmptyReadout(null), true);
  assert.equal(isEmptyReadout(undefined), true);
  assert.equal(isEmptyReadout({}), true);
});

test("any one of strengths / STAR / sub-scores makes it a real, scored readout", () => {
  assert.equal(isEmptyReadout({ strengths: [{ strength: "Clear structure" }] }), false);
  assert.equal(isEmptyReadout({ star_breakdown: [{ question: "Q1", situation: 2 }] }), false);
  assert.equal(isEmptyReadout({ sub_scores: { communication: 6 } }), false);
});

test("presence data alone does not count as a substantive answer", () => {
  // Camera cues can exist for a session with zero answers; they must NOT flip it to scored.
  assert.equal(isEmptyReadout({ professional_presence: { measured: true, by_type: { window_blur: 2 } } }), true);
});

test("legacy string strengths still count (back-compat with pre-{strength,evidence} rows)", () => {
  assert.equal(isEmptyReadout({ strengths: ["Answered concisely"] }), false);
});

// ── SCORING_CONTEXT item 4 — the evidence floor ────────────────────────────

test("the server's scored:false is authoritative, even when the model wrote prose", () => {
  // Under three substantive answers there is no verdict. If the server says so, the
  // client does not second-guess it on the strength of some strengths it was sent.
  const d = { scored: false, substantive_answers: 2, strengths: [{ strength: "Clear" }], sub_scores: { clarity: 6 } };
  assert.equal(isEmptyReadout(d), true);
  assert.equal(canRenderBand(d), false);
});

test("three substantive answers is the floor — two is not enough, three is", () => {
  assert.equal(MIN_SUBSTANTIVE_ANSWERS, 3);
  assert.equal(hasMinimumEvidence({ substantive_answers: 2 }), false);
  assert.equal(hasMinimumEvidence({ substantive_answers: 3 }), true);
  assert.equal(hasMinimumEvidence({ substantive_answers: 0 }), false);
  assert.equal(hasMinimumEvidence(null), false);
});

test("a readout from before this sprint is not retroactively unscored", () => {
  // No substantive_answers field. Treating "unknown" as "not enough" would blank every
  // session already in a learner's history.
  assert.equal(hasMinimumEvidence({ sub_scores: { clarity: 6 } }), true);
  assert.equal(hasMinimumEvidence({ strengths: [] }), false);
});

// ── Item 9 — the band appears exactly once, and only when it was earned ────

test("a band renders only for a scored readout that actually has one", () => {
  assert.equal(canRenderBand({ overall_band: "Building", sub_scores: { clarity: 6 } }), true);
  assert.equal(canRenderBand({ overall_band: "", sub_scores: { clarity: 6 } }), false);
  assert.equal(canRenderBand({ overall_band: "Not Ready" }), false, "no content = no verdict");
});

// ── Item 6 — early exits are visible, and never framed as failure ──────────

test("a below-the-floor attempt shows in history as ended early, not as a zero", () => {
  const st = historyStatus({ status: "completed", scored: false, benchmark: null });
  assert.equal(st.label, "Ended early — not scored");
  assert.equal(st.tone, "neutral", "navy and neutral — never red, never a failure");
  assert.equal(st.benchmark, null);
});

test("a scored attempt shows its band and its benchmark", () => {
  const st = historyStatus({ status: "completed", scored: true, benchmark: 42, band: "Building" });
  assert.equal(st.label, "Building");
  assert.equal(st.tone, "band");
  assert.equal(st.benchmark, 42);
});

test("a pre-benchmark row never passes its raw score off as a benchmark", () => {
  // The Easy/10-min raw 100 that started all this must not reappear in a benchmark column.
  const st = historyStatus({ status: "completed", scored: true, benchmark: null, overall: 100 });
  assert.equal(st.benchmark, null);
  assert.equal(st.label, "Not scored");
});

test("an in-progress session is neither scored nor failed", () => {
  assert.equal(historyStatus({ status: "active" }).label, "In progress");
  assert.equal(historyStatus({ status: "active" }).tone, "neutral");
});

// ── Item 7 — trend over trophy ─────────────────────────────────────────────

test("the trend reads the newest against what came before it, not against the best", () => {
  // Newest first. A great day three attempts ago must not make today read as a decline.
  assert.equal(trendDirection([60, 50, 52]), "up");
  assert.equal(trendDirection([40, 60, 62]), "down");
  assert.equal(trendDirection([50, 50, 51]), "flat");
});

test("one attempt is not a trend", () => {
  assert.equal(trendDirection([70]), "none");
  assert.equal(trendDirection([]), "none");
  assert.equal(trendDirection(null), "none");
});
