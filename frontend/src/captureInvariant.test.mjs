/**
 * THE CAPTURE INVARIANT — a regression test, in the strict sense of the word.
 *
 *      THE MIC NEVER OPENS WHILE THE INTERVIEWER STILL HAS WORDS SHE HAS NOT SAID.
 *
 * This is not a hypothetical. Three of the six arming sites were violating it: unmuting
 * mid-reply, tapping the mic mid-reply, and accepting the voice-consent modal mid-reply all
 * called the recorder immediately. The recorder happily captured the interviewer's own voice
 * coming out of the laptop speakers, the trailing-silence detector then "heard" her stop, and
 * the whole thing was submitted as the candidate's answer to the question she was still in
 * the middle of asking.
 *
 * It had been enforced by CONVENTION — every arming site remembering to check `audioPlaying`
 * — which is the kind of rule that holds right up until someone adds a seventh arming site.
 * So this file enforces it two ways:
 *
 *   1. POLICY   — canArmCapture is the single decision, and it is tested against the state
 *                 each of the four paths actually passes through (start, next question,
 *                 restart/resume, re-ask).
 *   2. STRUCTURE — App.jsx is read as text, and the test FAILS if anything other than
 *                 armCapture() calls the recorder. A future arming site cannot bypass the
 *                 gate without turning this red.
 *
 * Run with:  npm test   (node --test, no new deps)
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { canArmCapture } from "./roomPolicy.js";

const APP = readFileSync(fileURLToPath(new URL("./App.jsx", import.meta.url)), "utf8");

// A candidate who is fully ready to answer: in the room, unmuted, consented, their turn, and
// the interviewer has finished. Every test below is this, minus one thing.
const READY = {
  inRoom: true, micOn: true, consented: true, answerDue: true,
  connecting: false, speaking: false, speechQueued: false,
  recording: false, transcribing: false, busy: false, typing: false, ended: false,
};

test("the baseline: when it really is their turn, the mic opens", () => {
  assert.equal(canArmCapture(READY), true);
});

// ── THE INVARIANT ITSELF ───────────────────────────────────────────────────
// Three distinct states mean "she has not finished". Any one of them shuts the mic.

test("she is SPEAKING: a clip is in the air -> the mic stays shut", () => {
  assert.equal(canArmCapture({ ...READY, speaking: true }), false);
});

test("her reply is QUEUED but playback has not begun -> the mic stays shut", () => {
  // The window between "the reply arrived" and "the first clip started". It is a few
  // milliseconds wide and it is exactly the one a state update slips through, which is why
  // App.jsx tracks it in a REF and not in React state.
  assert.equal(canArmCapture({ ...READY, speechQueued: true }), false);
});

test("CONNECTING: the room is up but her opening has not arrived -> the mic stays shut", () => {
  // FAST START renders the room on the session row, which ALREADY says it is the candidate's
  // turn. It is not. Nobody has asked them anything yet.
  assert.equal(canArmCapture({ ...READY, connecting: true }), false);
});

test("every combination of the three is still shut — there is no gap between them", () => {
  for (const connecting of [false, true]) {
    for (const speaking of [false, true]) {
      for (const speechQueued of [false, true]) {
        const quiet = !connecting && !speaking && !speechQueued;
        assert.equal(
          canArmCapture({ ...READY, connecting, speaking, speechQueued }),
          quiet,
          `connecting=${connecting} speaking=${speaking} queued=${speechQueued}`,
        );
      }
    }
  }
});

// ── THE FOUR PATHS, walked step by step ───────────────────────────────────
// Each is the real sequence of states that path moves through. The invariant must hold at
// EVERY step, not merely at the end of it.

/** Assert the mic is shut for every step but the last, and open on the last. */
function walk(name, steps) {
  test(name, () => {
    steps.forEach(([label, state], i) => {
      const last = i === steps.length - 1;
      assert.equal(
        canArmCapture({ ...READY, ...state }),
        last,
        `${last ? "should OPEN" : "should stay SHUT"} at: ${label}`,
      );
    });
  });
}

walk("PATH 1 — session start: the room is up long before she has spoken", [
  ["room rendered on the session row; greeting not fetched yet", { connecting: true }],
  ["greeting arrived; playback has not started", { connecting: false, speechQueued: true }],
  ["sentence 1 of 3 in the air", { speaking: true }],
  ["sentence 3 of 3 in the air (the question itself)", { speaking: true }],
  ["she has finished; the floor is theirs", {}],
]);

walk("PATH 2 — the next question: an answer is submitted and she replies", [
  ["the answer is in flight; her reply is being written", { busy: true }],
  ["the reply arrived; playback has not started", { speechQueued: true }],
  ["she is asking the next question", { speaking: true }],
  ["she has finished", {}],
]);

walk("PATH 3 — restart/resume: a refresh mid-interview", [
  // On resume the transcript is rehydrated from the server WITHOUT audio: the last question
  // is not re-spoken. So there is nothing outstanding, and the mic may open at once — but
  // only once the room has actually loaded.
  ["still restoring the session", { connecting: true }],
  ["restored; the last question was already heard before the refresh", {}],
]);

walk("PATH 4 — the re-ask: transcription failed and she says so", [
  ["the re-ask is in flight", { busy: true }],
  ["her 'I didn't catch that' line arrived; not yet playing", { speechQueued: true }],
  ["she is saying it", { speaking: true }],
  ["she has finished; the mic reopens and it costs them no question slot", {}],
]);

walk("PATH 5 — the spoken confidence rating (a rating, not an answer)", [
  // answerDue is FALSE here: it is not their turn to answer. It is their turn to say a number.
  ["she is asking 'how confident were you?'", { answerDue: false, ratingDue: true, speaking: true }],
  ["she has finished asking", { answerDue: false, ratingDue: true }],
]);

// ── Barge-in is not an exception; it satisfies the invariant by force ──────

test("barge-in does not go AROUND the gate — it stops her, then passes it", () => {
  // While she is speaking, the gate is shut. That is the state barge-in starts from.
  assert.equal(canArmCapture({ ...READY, speaking: true }), false);
  // Barge-in ABANDONS the rest of her reply (it is cancelled, not postponed) and marks her
  // stopped — synchronously, in refs — and only then arms. By that point she genuinely has
  // nothing left to say, so the same gate lets it through honestly.
  assert.equal(canArmCapture({ ...READY, speaking: false, speechQueued: false }), true);
});

// ── The gate still enforces everything it enforced before ──────────────────

test("muted means muted, whatever else is true", () => {
  assert.equal(canArmCapture({ ...READY, micOn: false }), false);
});

test("consent stays explicit — it is never implied by anything", () => {
  assert.equal(canArmCapture({ ...READY, consented: false }), false);
});

test("no capture when it is nobody's turn, when they are typing, or when it is over", () => {
  assert.equal(canArmCapture({ ...READY, answerDue: false }), false);   // e.g. a rating is due
  assert.equal(canArmCapture({ ...READY, typing: true }), false);       // they chose the composer
  assert.equal(canArmCapture({ ...READY, ended: true }), false);
  assert.equal(canArmCapture({ ...READY, inRoom: false }), false);      // classic typed mode
  assert.equal(canArmCapture({ ...READY, recording: true }), false);    // already capturing
  assert.equal(canArmCapture({ ...READY, transcribing: true }), false);
  assert.equal(canArmCapture({ ...READY, busy: true }), false);         // a turn/nudge in flight
  assert.equal(canArmCapture(), false);                                  // and it fails CLOSED
});

// ══ STRUCTURE: nothing may reach the recorder except through the gate ══════
// The policy above is worthless if a seventh arming site simply calls the recorder directly.
// This is what stops that happening, and it is the half that will still be doing its job in
// six months when nobody remembers this bug.

const RECORDER = "openMicUnsafe";

test("the recorder has exactly ONE caller, and it is the gate", () => {
  const lines = APP.split("\n");
  const callers = lines
    .map((line, i) => [i + 1, line])
    .filter(([, line]) => line.includes(`${RECORDER}(`) && !line.trim().startsWith("//"))
    .filter(([, line]) => !line.includes(`const ${RECORDER} =`));   // the definition itself

  assert.equal(
    callers.length, 1,
    "The microphone must have exactly one door.\n" +
    `Found ${callers.length} call(s) to ${RECORDER}():\n` +
    callers.map(([n, l]) => `  App.jsx:${n}  ${l.trim()}`).join("\n") +
    "\n\nIf you are adding a new way to start capture, call armCapture() — it asks " +
    "canArmCapture() first, which is what stops the mic opening while the interviewer is " +
    "still talking. Do not call the recorder directly.",
  );

  // ...and that one caller is inside armCapture, immediately after the gate says yes.
  const gate = APP.slice(APP.indexOf("const armCapture ="), APP.indexOf(`const ${RECORDER} =`));
  assert.ok(gate.includes("canArmCapture(captureState("), "armCapture must consult the policy");
  assert.ok(gate.includes(`${RECORDER}(`), "armCapture must be the caller");
});

test("the recorder is defined, and named so nobody calls it by accident", () => {
  assert.ok(APP.includes(`const ${RECORDER} = async (existing)`));
  // The old name is gone. If it comes back, so does the bug it used to carry.
  assert.ok(!APP.includes("beginRecording"),
    "beginRecording() was the ungated door. It must not return.");
});

test("the three invariant refs are written synchronously, not left to React state", () => {
  // Every one of these is read by a callback or an rAF loop that would otherwise see the
  // PREVIOUS render's value — and one stale read is a recording over the top of a question.
  for (const ref of ["audioPlayingRef", "speechQueuedRef", "connectingRef"]) {
    assert.ok(APP.includes(`${ref}.current`), `${ref} must exist and be read`);
  }
  // The sequencer flips "speaking" through one helper that writes the ref as well as state.
  assert.ok(APP.includes("const setSpeaking = (on) => { audioPlayingRef.current = on; setAudioPlaying(on); };"));
  // Every interviewer line is announced through one helper that marks it queued BEFORE the
  // re-render — closing the gap between "her reply arrived" and "playback began".
  assert.ok(APP.includes("const sayNext = (msg) => {"));
  assert.ok(APP.includes("speechQueuedRef.current = !!(msg.audio_segments?.length || msg.audio_url);"));
});

test("the interviewer's lines are all announced through sayNext", () => {
  // A raw setMessages(...assistant...) would append a line WITHOUT marking it queued, which
  // reopens the exact gap this invariant exists to close.
  const raw = APP.split("\n").filter(l =>
    l.includes("setMessages(m => [...m, { role: \"assistant\""));
  assert.deepEqual(raw, [], "append interviewer lines with sayNext(), not setMessages()");
});
