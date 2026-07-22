/**
 * Room-clock tests. Run with:  npm run test:room   (node --test, no new deps)
 *
 * These pin the promise the E7.7 fix exists to keep: an expired clock never strands the
 * candidate. Whatever they managed to get out is submitted; if they got nothing out, the
 * interview moves on anyway; and only a genuinely dead room wraps the session.
 */
import test from "node:test";
import assert from "node:assert/strict";
import {
  questionSeconds, expiryAction, shouldArmAbandon,
  shouldBackchannel, shouldBargeIn, textIdleAction,
  TEXT_IDLE_NUDGE_MS, TEXT_IDLE_EXPIRY_MS,
  QUESTION_SECONDS, DEFAULT_QUESTION_SECONDS, CHECKIN_SECONDS,
  CAMERA_GRACE_MS, SILENT_ABANDON_MS,
  BACKCHANNEL_MIN_ANSWER_MS, BACKCHANNEL_MIN_PAUSE_MS,
  BACKCHANNEL_NEVER_BEFORE_MS, BACKCHANNEL_MAX_PER_ANSWER,
  BARGE_IN_RMS, BARGE_IN_SUSTAIN_MS,
  expiryEscalation, EXPIRY_GRACE_SECONDS, HEARING_FAILURE_LINES,
} from "./roomPolicy.js";

// ── The per-question budget ────────────────────────────────────────────────

test("each round gets its own budget; an unknown round falls back, never to zero", () => {
  assert.equal(questionSeconds("CASE"), QUESTION_SECONDS.CASE);
  assert.equal(questionSeconds("warmup"), QUESTION_SECONDS.WARMUP);   // case-insensitive
  assert.equal(questionSeconds("READOUT"), DEFAULT_QUESTION_SECONDS);
  assert.equal(questionSeconds(""), DEFAULT_QUESTION_SECONDS);
  assert.equal(questionSeconds(undefined), DEFAULT_QUESTION_SECONDS);
  // A zero budget would expire every question the instant it was asked.
  for (const v of Object.values(QUESTION_SECONDS)) assert.ok(v > 0);
});

// ── Expiry with something captured -> submit it ────────────────────────────

test("a partial transcript is submitted as the answer, not thrown away", () => {
  const a = expiryAction({ partial: "We'd cap exposure per borrower and re-price the" });
  assert.equal(a.timeout, "partial");
  assert.equal(a.text, "We'd cap exposure per borrower and re-price the");
});

test("a typed draft counts just as much as speech", () => {
  const a = expiryAction({ draft: "  I'd start by segmenting the book  " });
  assert.equal(a.timeout, "partial");
  assert.equal(a.text, "I'd start by segmenting the book");     // trimmed
});

test("speech wins over a stale draft — it is the more recent act", () => {
  const a = expiryAction({ partial: "spoken words", draft: "abandoned draft" });
  assert.equal(a.text, "spoken words");
});

test("a long partial is clamped to the field limit", () => {
  const a = expiryAction({ partial: "x".repeat(5000) });
  assert.equal(a.text.length, 4000);
});

// ── Expiry with nothing captured -> a skip, and the interview moves on ─────

test("nothing captured is a skip, and a skip sends no text", () => {
  for (const input of [{}, { partial: "", draft: "" }, { partial: "   ", draft: "\n" }, undefined]) {
    const a = expiryAction(input);
    assert.equal(a.timeout, "skip", `for ${JSON.stringify(input)}`);
    assert.equal(a.text, "");
  }
});

test("the two outcomes are the only two outcomes", () => {
  // There is no third branch where nothing is posted and the mic sits in "Waiting…".
  // That state was the dead end; it does not exist here.
  for (const a of [expiryAction({ partial: "something" }), expiryAction({})]) {
    assert.ok(["partial", "skip"].includes(a.timeout));
  }
});

// ── Abandonment: only a genuinely dead room wraps ──────────────────────────

const DEAD = { inRoom: true, answerDue: true, micOn: false, typedChars: 0 };

test("mic muted, nothing typed, answer due — that is abandonment", () => {
  assert.equal(shouldArmAbandon(DEAD), true);
});

test("an unmuted mic is never abandonment — silence there is thinking", () => {
  assert.equal(shouldArmAbandon({ ...DEAD, micOn: true }), false);
});

test("typing keeps the interview alive — typed answers are first-class", () => {
  assert.equal(shouldArmAbandon({ ...DEAD, typedChars: 1 }), false);
});

test("no clock runs when no answer is due, or outside the room", () => {
  assert.equal(shouldArmAbandon({ ...DEAD, answerDue: false }), false);   // e.g. rating due
  assert.equal(shouldArmAbandon({ ...DEAD, inRoom: false }), false);      // typed-only mode
  assert.equal(shouldArmAbandon(), false);
});

// ── The numbers the spec fixed ────────────────────────────────────────────

test("the device-policy clocks are the ones the policy promised", () => {
  assert.equal(CAMERA_GRACE_MS, 60_000);      // 60s camera grace
  assert.equal(SILENT_ABANDON_MS, 90_000);    // 90s both-channels-silent
});

// ── The engagement floor's check-in clock ──────────────────────────────────
// The check-in ("Shall we keep going?") is a direct question, and it is the ONE question
// in the interview that must not be given three minutes: three minutes is exactly the
// silence it exists to break.

test("a check-in gets its own short clock, not the round's full budget", () => {
  assert.equal(questionSeconds("DOMAIN", "checkin"), CHECKIN_SECONDS);
  assert.equal(CHECKIN_SECONDS, 45);
  // ...and it is much shorter than the question it interrupted.
  assert.ok(CHECKIN_SECONDS < QUESTION_SECONDS.DOMAIN);
  // The server sends the number; we honour it rather than hard-coding our own.
  assert.equal(questionSeconds("DOMAIN", "checkin", 30), 30);
});

test("an ordinary question is completely unaffected by the check-in clock", () => {
  assert.equal(questionSeconds("DOMAIN"), QUESTION_SECONDS.DOMAIN);
  assert.equal(questionSeconds("DOMAIN", "question"), QUESTION_SECONDS.DOMAIN);
  assert.equal(questionSeconds("CASE", "question", 30), QUESTION_SECONDS.CASE);
});

// ── Listening backchannels ────────────────────────────────────────────────
// Every one of these conditions exists to stop the "mm-hmm" becoming an INTERRUPTION,
// which is worse than saying nothing at all.

const bc = (over = {}) => shouldBackchannel({
  elapsedMs: 30_000, pauseMs: 1_500, playedCount: 0, endOfAnswerMs: 2_500, ...over,
});

test("a long answer with a real pause earns a soft mm-hmm", () => {
  assert.equal(bc(), true);
});

test("never in a short answer, and never in the opening seconds", () => {
  assert.equal(bc({ elapsedMs: BACKCHANNEL_MIN_ANSWER_MS - 1 }), false);
  assert.equal(bc({ elapsedMs: BACKCHANNEL_NEVER_BEFORE_MS - 1 }), false);
  assert.equal(bc({ elapsedMs: 5_000 }), false);
  // Exactly at the 20s mark it is allowed — the bar is "longer than ~20s".
  assert.equal(bc({ elapsedMs: BACKCHANNEL_MIN_ANSWER_MS }), true);
});

test("a breath is not a pause, and a pause is not the end of an answer", () => {
  // Too short: they are mid-sentence. Stepping on this is talking over them.
  assert.equal(bc({ pauseMs: BACKCHANNEL_MIN_PAUSE_MS - 1 }), false);
  assert.equal(bc({ pauseMs: BACKCHANNEL_MIN_PAUSE_MS }), true);
  // Too long: they have FINISHED. That silence belongs to the end-of-answer detector, and
  // an "mm-hmm" landing on top of it would cut off the answer we asked for.
  assert.equal(bc({ pauseMs: 2_500 }), false);
  assert.equal(bc({ pauseMs: 4_000 }), false);
});

test("at most twice in one answer — three is a tic, not a person", () => {
  assert.equal(bc({ playedCount: BACKCHANNEL_MAX_PER_ANSWER - 1 }), true);
  assert.equal(bc({ playedCount: BACKCHANNEL_MAX_PER_ANSWER }), false);
  assert.equal(BACKCHANNEL_MAX_PER_ANSWER, 2);
});

// ── Barge-in ──────────────────────────────────────────────────────────────
// The mic is open while the interviewer's own voice is coming out of the same laptop. A
// low or instant trigger would have her hear herself, conclude she was interrupted, and
// stop talking — to herself. Hence: a HIGH threshold, and it must be SUSTAINED.

test("sustained speech over the interviewer is a barge-in", () => {
  assert.equal(shouldBargeIn({ rms: 0.2, aboveSinceMs: BARGE_IN_SUSTAIN_MS }), true);
});

test("a cough, a chair, a single loud syllable: not a barge-in", () => {
  // Loud, but not held.
  assert.equal(shouldBargeIn({ rms: 0.9, aboveSinceMs: BARGE_IN_SUSTAIN_MS - 1 }), false);
  assert.equal(shouldBargeIn({ rms: 0.9, aboveSinceMs: 0 }), false);
  // Held, but not loud — room tone and breathing must never take the floor from her.
  assert.equal(shouldBargeIn({ rms: BARGE_IN_RMS, aboveSinceMs: 5_000 }), false);
  assert.equal(shouldBargeIn({ rms: 0.01, aboveSinceMs: 5_000 }), false);
  assert.equal(shouldBargeIn({}), false);
});

test("the barge-in bar sits well clear of ordinary silence", () => {
  // SILENCE_RMS in App.jsx is 0.018. The barge-in bar has to be far above it, or she
  // would interrupt herself on background noise.
  assert.ok(BARGE_IN_RMS > 0.018 * 2);
  assert.ok(BARGE_IN_SUSTAIN_MS >= 250);   // long enough to be words, not a knock
});


// ── QA-03: in TEXT the per-question clock counts idle, not elapsed ───────────
// The sweep watched a TEXT student read a question for 90 seconds and have it taken
// away, auto-submitted as "(No answer — the time on this question ran out.)". Reading
// is not disengagement, and a clock that cannot tell them apart punishes the deliberate
// thinker hardest — backwards for a product that scores thinking.

test("thinking is free: a long read earns nothing at all", () => {
  assert.equal(textIdleAction(0), "none");
  assert.equal(textIdleAction(30_000), "none");
  // 90s of reading is exactly what used to cost a WARMUP question.
  assert.equal(textIdleAction(QUESTION_SECONDS.WARMUP * 1000), "nudge");
  assert.notEqual(textIdleAction(QUESTION_SECONDS.WARMUP * 1000), "expire");
});

test("the nudge comes before the expiry, and both come late", () => {
  assert.ok(TEXT_IDLE_NUDGE_MS < TEXT_IDLE_EXPIRY_MS, "nudge must precede expiry");
  // Both must outlast the voice clock that used to apply here, or the fix changes
  // nothing for the student it exists to protect.
  assert.ok(TEXT_IDLE_EXPIRY_MS > QUESTION_SECONDS.WARMUP * 1000);
  assert.equal(textIdleAction(TEXT_IDLE_NUDGE_MS), "nudge");
  assert.equal(textIdleAction(TEXT_IDLE_EXPIRY_MS), "expire");
  assert.equal(textIdleAction(TEXT_IDLE_EXPIRY_MS + 60_000), "expire");
});

test("expiry still never strands the student", () => {
  // Unchanged contract: three minutes of true silence WITH a draft submits the draft;
  // with nothing typed it is a skip and the interview moves on. Nobody is cut off
  // mid-draft, because typing resets the idle clock long before it reaches here.
  assert.deepEqual(expiryAction({ draft: "half an answer" }),
    { timeout: "partial", text: "half an answer" });
  assert.deepEqual(expiryAction({ draft: "" }), { timeout: "skip", text: "" });
});

// ── Soft expiry: the first zero nudges, only the second expires ────────────

test("the first zero of a voice question clock is a nudge with a real extension", () => {
  const first = expiryEscalation({ nudged: false, capturing: false });
  assert.equal(first.action, "nudge");
  assert.ok(first.extendSeconds > 0, "a nudge must buy real time");
  assert.equal(first.extendSeconds, EXPIRY_GRACE_SECONDS);
  assert.equal(first.silent, false, "an idle candidate must SEE that she is waiting");
});

test("mid-capture the nudge is silent — they are already answering", () => {
  const mid = expiryEscalation({ nudged: false, capturing: true });
  assert.equal(mid.action, "nudge");
  assert.equal(mid.silent, true);
});

test("the second zero expires for real — the backstop still backstops", () => {
  assert.deepEqual(expiryEscalation({ nudged: true, capturing: false }), { action: "expire" });
  assert.deepEqual(expiryEscalation({ nudged: true, capturing: true }), { action: "expire" });
});

test("every hearing failure has a visible line that says what to do next", () => {
  for (const kind of ["reask", "quiet", "noise"]) {
    const line = HEARING_FAILURE_LINES[kind];
    assert.ok(line && line.length > 20, `${kind} needs a real, actionable banner`);
  }
});
