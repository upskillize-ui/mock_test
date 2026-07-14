/**
 * Pose policy tests. Run with:  npm run test:poses   (node --test, no new deps)
 *
 * Pins the three things the spec calls out: the fallback map, the tone->pose mapping,
 * and the rule that an escalated focus ladder forces "intense" while speaking.
 */
import test from "node:test";
import assert from "node:assert/strict";
import {
  choosePose, hasPoseSet, resolvePose, nextEmphasis, weightedPool, POSES,
  EMPHASIS_ON, EMPHASIS_OFF, EMPHASIS_MIN_HOLD_MS, POSED_WEIGHT,
} from "./posePolicy.js";

const FULL_SET = {
  priya_listening: "L.png",
  priya_smile: "S.png",
  priya_intense: "I.png",
  priya_thinking: "T.png",
};

// The roster as it actually stands: Riya is the one character with a pose grid on disk.
const RIYA_SET = {
  riya_listening: "L.png",
  riya_smile: "S.png",
  riya_intense: "I.png",
  riya_thinking: "T.png",
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

// ── Emphasis: her hands move with her voice ───────────────────────────────
// The whole point of the hysteresis is that a single loud syllable must NOT flip the
// face, and a brief dip mid-sentence must NOT drop the gesture.

test("a sustained loud passage raises the emphatic frame; a settled voice drops it", () => {
  const long = EMPHASIS_MIN_HOLD_MS + 1;
  assert.equal(nextEmphasis(false, 0.9, long), true);    // loud -> gesture up
  assert.equal(nextEmphasis(true, 0.2, long), false);    // settled -> gesture down
});

test("between the thresholds nothing changes — no strobing on ordinary speech", () => {
  const long = EMPHASIS_MIN_HOLD_MS + 1;
  const mid = (EMPHASIS_ON + EMPHASIS_OFF) / 2;          // 0.525: above OFF, below ON
  assert.equal(nextEmphasis(false, mid, long), false);   // not loud enough to raise
  assert.equal(nextEmphasis(true, mid, long), true);     // not quiet enough to drop
  // Exactly ON/OFF are not crossings — the amplitude must pass them.
  assert.equal(nextEmphasis(false, EMPHASIS_ON, long), false);
  assert.equal(nextEmphasis(true, EMPHASIS_OFF, long), true);
});

test("a switch is held for at least 1.5s, however the amplitude swings", () => {
  assert.equal(nextEmphasis(false, 1.0, 0), false);                       // just switched
  assert.equal(nextEmphasis(false, 1.0, EMPHASIS_MIN_HOLD_MS - 1), false);
  assert.equal(nextEmphasis(true, 0.0, EMPHASIS_MIN_HOLD_MS - 1), true);
  // First frame of a reply: nothing has switched yet, so the gesture may fire at once.
  assert.equal(nextEmphasis(false, 0.9, Infinity), true);
});

// ── ROSTER WEIGHTING: the founder must actually SEE the pose system ────────
// Half the value of this build is in the faces, and it is invisible in any session that
// happens to draw a character whose pose grid has not been made yet. Until the whole cast
// has one, the posed characters are weighted up. This is scaffolding with a delete-by
// date: when the grids land, POSED_WEIGHT goes to 1 and these two tests go with it.

const FEMALE_REALISTIC = [{ id: "priya" }, { id: "riya" }, { id: "meera" }];

test("a posed character is three times as likely to be drawn as an un-posed one", () => {
  const pool = weightedPool(FEMALE_REALISTIC, RIYA_SET);
  const riya = pool.filter(c => c.id === "riya").length;
  const priya = pool.filter(c => c.id === "priya").length;
  assert.equal(riya, POSED_WEIGHT);
  assert.equal(priya, 1);
  assert.equal(pool.length, 5);           // 3 + 1 + 1
  // ...which is a MAJORITY. "A Female/Realistic session should usually be Riya."
  assert.ok(riya / pool.length > 0.5, "the posed character must win more often than not");
});

test("the un-posed characters stay in the pool — weighting is not exclusion", () => {
  const ids = new Set(weightedPool(FEMALE_REALISTIC, RIYA_SET).map(c => c.id));
  assert.deepEqual([...ids].sort(), ["meera", "priya", "riya"]);
  // With no pose grids at all (the pre-poses world), the pool is exactly uniform again —
  // which is also what happens the day we set POSED_WEIGHT to 1.
  const flat = weightedPool(FEMALE_REALISTIC, {});
  assert.equal(flat.length, FEMALE_REALISTIC.length);
});

// ── CRITICAL: the pressure panel never smiles ──────────────────────────────

test("critical tone puts the face in `intense`, warm-up or not", () => {
  assert.equal(choosePose({ state: "speaking", tone: "critical" }), "intense");
  // ...and it outranks the warm-up smile, which every other difficulty gets.
  assert.equal(choosePose({ state: "speaking", tone: "critical", stage: "WARMUP" }), "intense");
  assert.equal(choosePose({ state: "speaking", tone: "warm", stage: "WARMUP" }), "smile");
});

test("with no server tone, Critical still leans in from the first question", () => {
  assert.equal(
    choosePose({ state: "speaking", tone: "", stage: "WARMUP", difficulty: "Critical" }),
    "intense",
  );
  // She still LISTENS like a person — the pressure is in how she speaks, not a stare.
  assert.equal(choosePose({ state: "listening", tone: "critical" }), "listening");
  assert.equal(choosePose({ state: "thinking", tone: "critical" }), "thinking");
});
