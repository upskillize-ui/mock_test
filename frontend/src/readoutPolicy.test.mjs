/**
 * Readout policy tests. Run with:  npm test   (node --test, no new deps)
 *
 * Pins the one rule the embed fixup adds: a session that ended before any substantive
 * answer must be detected as EMPTY, so the readout never renders a band or /10 tiles for
 * it. Skipped ≠ failed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { isEmptyReadout } from "./readoutPolicy.js";

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
  assert.equal(isEmptyReadout({ professional_presence: { band: "Building", by_type: { window_blur: 2 } } }), true);
});

test("legacy string strengths still count (back-compat with pre-{strength,evidence} rows)", () => {
  assert.equal(isEmptyReadout({ strengths: ["Answered concisely"] }), false);
});
