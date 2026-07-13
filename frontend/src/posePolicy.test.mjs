/**
 * Pose policy tests. Run with:  npm run test:poses   (node --test, no new deps)
 *
 * Pins the three things the spec calls out: the fallback map, the tone->pose mapping,
 * and the rule that an escalated focus ladder forces "intense" while speaking.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { choosePose, hasPoseSet, resolvePose, POSES } from "./posePolicy.js";

const FULL_SET = {
  priya_listening: "L.png",
  priya_smile: "S.png",
  priya_intense: "I.png",
  priya_thinking: "T.png",
};

// ── Pose map + fallback (a character with no poses must never crash) ────────

test("hasPoseSet is true only when all four poses exist", () => {
  assert.equal(hasPoseSet(FULL_SET, "priya"), true);
  assert.equal(hasPoseSet({ priya_smile: "S.png" }, "priya"), false);   // partial set
  assert.equal(hasPoseSet({}, "robo1"), false);                          // robots
  assert.equal(hasPoseSet(null, "priya"), false);
});

test("resolvePose falls back: exact pose -> listening -> the single base image", () => {
  assert.equal(resolvePose(FULL_SET, "priya", "intense", "base.png"), "I.png");
  // Pose missing -> that character's listening still holds the frame.
  assert.equal(resolvePose({ priya_listening: "L.png" }, "priya", "smile", "base.png"), "L.png");
  // No poses at all (robot / art not generated) -> the original portrait. No crash.
  assert.equal(resolvePose({}, "vikram", "smile", "base.png"), "base.png");
  assert.equal(resolvePose(null, "vikram", "smile", "base.png"), "base.png");
});

test("every pose name resolves for a full set", () => {
  for (const p of POSES) {
    assert.ok(resolvePose(FULL_SET, "priya", p, "base.png"));
  }
});

// ── State drives the pose ──────────────────────────────────────────────────

test("thinking and listening states map straight through; idle rests on listening", () => {
  assert.equal(choosePose({ state: "thinking" }), "thinking");
  assert.equal(choosePose({ state: "listening" }), "listening");
  assert.equal(choosePose({ state: "idle" }), "listening");
  assert.equal(choosePose({ state: "ready" }), "listening");
});

// ── tone -> pose (the server hint) ─────────────────────────────────────────

test("tone maps to pose while speaking", () => {
  assert.equal(choosePose({ state: "speaking", tone: "warm" }), "smile");
  assert.equal(choosePose({ state: "speaking", tone: "probing" }), "intense");
  // neutral alternates so the face never freezes for a whole round
  assert.equal(choosePose({ state: "speaking", tone: "neutral", group: 0 }), "listening");
  assert.equal(choosePose({ state: "speaking", tone: "neutral", group: 1 }), "smile");
});

test("tone only applies while speaking — it never overrides listening/thinking", () => {
  assert.equal(choosePose({ state: "listening", tone: "probing" }), "listening");
  assert.equal(choosePose({ state: "thinking", tone: "warm" }), "thinking");
});

// ── Escalation >= 2 forces intense during speaking ────────────────────────

test("escalation >= 2 forces intense while speaking, outranking a warm tone", () => {
  assert.equal(choosePose({ state: "speaking", tone: "warm", escalationLevel: 2 }), "intense");
  assert.equal(choosePose({ state: "speaking", tone: "warm", escalationLevel: 3 }), "intense");
  // Below the threshold the tone still wins — one drift shouldn't harden the face.
  assert.equal(choosePose({ state: "speaking", tone: "warm", escalationLevel: 1 }), "smile");
});

test("escalation does not harden the face while merely listening", () => {
  assert.equal(choosePose({ state: "listening", escalationLevel: 3 }), "listening");
});

// ── Fallback heuristics when the server sends no tone ──────────────────────

test("without a tone hint: greeting/warm-up smiles, Stretch leans in", () => {
  assert.equal(choosePose({ state: "speaking", stage: "" }), "smile");          // greeting
  assert.equal(choosePose({ state: "speaking", stage: "WARMUP" }), "smile");
  assert.equal(choosePose({ state: "speaking", stage: "CASE", difficulty: "Stretch" }), "intense");
  // Ordinary round, no hint -> alternate rather than freeze.
  assert.equal(choosePose({ state: "speaking", stage: "DOMAIN", difficulty: "Realistic", group: 0 }), "listening");
});
