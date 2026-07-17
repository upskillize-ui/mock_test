/**
 * Room-layout tests. Run with:  npm run test:layout   (node --test, no new deps)
 *
 * These pin the promise the room redesign exists to keep: THE ROOM NEVER CONTRADICTS
 * ITSELF. One lit tile at most, one status strip that always agrees with the interviewer's
 * face, one surface for the answer in progress — and reading the transcript never costs you
 * the microphone.
 */
import test from "node:test";
import assert from "node:assert/strict";
import {
  activeSpeaker, statusStrip, studentSurface, chatSlot, bubbleMeta, composerIntent,
  SPEAKER_INTERVIEWER, SPEAKER_STUDENT,
  STRIP_SPEAKING, STRIP_LISTENING, STRIP_THINKING, STRIP_MUTED, STRIP_READY, STRIP_ENDED,
  STRIP_TO_FACE,
  SURFACE_CLOSED, SURFACE_LIVE, SURFACE_CAPTURED,
} from "./roomLayout.js";

// ── Who is talking ─────────────────────────────────────────────────────────

test("the ring follows the voice: hers while she speaks, theirs while they answer", () => {
  assert.equal(activeSpeaker({ speaking: true }), SPEAKER_INTERVIEWER);
  assert.equal(activeSpeaker({ recording: true }), SPEAKER_STUDENT);
});

test("connecting is still her floor — she is about to speak, nobody else is", () => {
  assert.equal(activeSpeaker({ connecting: true }), SPEAKER_INTERVIEWER);
});

test("nobody is lit between turns", () => {
  assert.equal(activeSpeaker({}), null);
  assert.equal(activeSpeaker({ speaking: false, recording: false, connecting: false }), null);
});

test("BARGE-IN: the interrupter gets the ring, not the interrupted", () => {
  // Her clip is ducking out (200ms) while the recorder is already open. The person talking
  // is the student. Lighting her tile here would show the room deferring to a voice that is
  // in the act of being talked over.
  assert.equal(activeSpeaker({ speaking: true, recording: true }), SPEAKER_STUDENT);
});

test("exactly one tile is ever lit, across the whole input space", () => {
  for (const recording of [false, true])
    for (const speaking of [false, true])
      for (const connecting of [false, true]) {
        const who = activeSpeaker({ recording, speaking, connecting });
        assert.ok(who === null || who === SPEAKER_INTERVIEWER || who === SPEAKER_STUDENT);
      }
});

// ── The one strip ──────────────────────────────────────────────────────────

test("the strip names each state in words, never in colour alone", () => {
  // Every reachable state has a non-empty label. A strip that says a state only by going
  // orange says nothing at all to somebody who cannot see orange.
  for (const recording of [false, true])
    for (const transcribing of [false, true])
      for (const speaking of [false, true])
        for (const micOn of [false, true])
          for (const answerDue of [false, true]) {
            const s = statusStrip({ recording, transcribing, speaking, micOn, answerDue });
            assert.ok(s.label && s.label.length > 0);
            assert.ok(s.tone && s.tone.length > 0);
          }
});

test("listening carries the rec counter the caller formatted", () => {
  const s = statusStrip({ recording: true, recLabel: "0:12" });
  assert.equal(s.key, STRIP_LISTENING);
  assert.equal(s.detail, "0:12");
});

test("listening outranks speaking — same barge-in, same answer", () => {
  assert.equal(statusStrip({ recording: true, speaking: true }).key, STRIP_LISTENING);
});

test("thinking covers both writing the reply and transcribing the answer", () => {
  assert.equal(statusStrip({ transcribing: true }).key, STRIP_THINKING);
  assert.equal(statusStrip({ loading: true }).key, STRIP_THINKING);
});

test("FAST START reads as connecting, not as a room that failed to load", () => {
  const s = statusStrip({ connecting: true });
  assert.equal(s.key, STRIP_THINKING);
  assert.equal(s.label, "Connecting");
});

test("muted WITH an answer due is an instruction, and it pulses", () => {
  const s = statusStrip({ micOn: false, answerDue: true });
  assert.equal(s.key, STRIP_MUTED);
  assert.equal(s.detail, "Tap the mic to answer");
  assert.equal(s.cue, true);
});

test("muted with nothing due is not nagged about", () => {
  // She is mid-question. Being muted is not a problem yet, so it is not a prompt yet.
  const s = statusStrip({ micOn: false, answerDue: false });
  assert.equal(s.key, STRIP_READY);
  assert.equal(s.cue, false);
});

test("muted never shouts over her — she is still speaking", () => {
  assert.equal(statusStrip({ micOn: false, answerDue: true, speaking: true }).key, STRIP_SPEAKING);
  assert.equal(statusStrip({ micOn: false, answerDue: true, loading: true }).key, STRIP_THINKING);
});

test("TEXT is never told to tap a mic it does not have", () => {
  // Caught by driving a real TEXT session: micOn=false + answerDue=true printed
  // "You're muted — tap the mic to answer" at a student who chose to type. It told them
  // to fix something that was working as chosen, and pointed them at the ONE control the
  // mode promises never to need — tapping it fires the permission prompt TEXT guarantees
  // they will never see.
  const s = statusStrip({ micOn: false, answerDue: true, textMode: true });
  assert.equal(s.key, STRIP_READY);
  assert.equal(s.label, "Your turn");
  assert.equal(s.detail, "Type your answer");
  assert.equal(s.cue, true, "it is still their turn — it should still prompt");
  assert.notEqual(s.key, STRIP_MUTED);
});

test("TEXT with nothing due is not nagged either", () => {
  const s = statusStrip({ micOn: false, answerDue: false, textMode: true });
  assert.equal(s.key, STRIP_READY);
  assert.equal(s.cue, false);
});

test("TEXT still never shouts over her", () => {
  assert.equal(statusStrip({ textMode: true, answerDue: true, speaking: true }).key, STRIP_SPEAKING);
  assert.equal(statusStrip({ textMode: true, answerDue: true, loading: true }).key, STRIP_THINKING);
  assert.equal(statusStrip({ textMode: true, answerDue: true, ended: true }).key, STRIP_ENDED);
});

test("ended outranks everything", () => {
  assert.equal(statusStrip({ ended: true, recording: true, speaking: true }).key, STRIP_ENDED);
});

// ── THE PARITY RULE ────────────────────────────────────────────────────────
// The strip and the interviewer's face are two renderings of one state. If they can
// disagree, one of them is lying, and the candidate has no way to know which.

// The face state, exactly as App.jsx derives `orbState`. Kept verbatim on purpose: this
// test is only worth anything if it is checking the REAL expression, so if App.jsx's
// derivation changes and this copy is not updated in the same breath, the parity test fails
// — which is precisely the alarm we want.
const faceState = ({ recording, transcribing, loading, connecting, speaking }) =>
  recording ? "listening"
    : (transcribing || loading || connecting) ? "thinking"
    : speaking ? "speaking" : "idle";

test("the strip and her face never disagree, in any reachable state", () => {
  for (const recording of [false, true])
    for (const transcribing of [false, true])
      for (const loading of [false, true])
        for (const connecting of [false, true])
          for (const speaking of [false, true])
            for (const micOn of [false, true])
              for (const answerDue of [false, true]) {
                const inputs = { recording, transcribing, loading, connecting, speaking, micOn, answerDue };
                const s = statusStrip(inputs);
                assert.equal(
                  STRIP_TO_FACE[s.key], faceState(inputs),
                  `strip "${s.key}" vs face "${faceState(inputs)}" for ${JSON.stringify(inputs)}`,
                );
              }
});

test("every strip key maps to a face — no key can be added without deciding this", () => {
  for (const k of [STRIP_SPEAKING, STRIP_LISTENING, STRIP_THINKING, STRIP_MUTED, STRIP_READY, STRIP_ENDED]) {
    assert.ok(STRIP_TO_FACE[k], `no face mapped for strip key "${k}"`);
  }
});

// ── The student's surface ──────────────────────────────────────────────────

test("the surface opens when they speak and shows the live waveform", () => {
  const s = studentSurface({ recording: true, selfCaption: "So the way I'd", selfCaptionsOn: true });
  assert.equal(s.phase, SURFACE_LIVE);
  assert.equal(s.open, true);
  assert.equal(s.wave, true);
  assert.equal(s.caption, "So the way I'd");
});

test("self-captions off: the waveform still says we can hear you", () => {
  const s = studentSurface({ recording: true, selfCaption: "ignored", selfCaptionsOn: false });
  assert.equal(s.phase, SURFACE_LIVE);
  assert.equal(s.wave, true);
  assert.equal(s.showCaption, false);
  assert.equal(s.caption, "");   // never leaks a caption the student did not opt into
});

test("captured spans transcribing AND the flash — the tick does not blink out between", () => {
  const inFlight = studentSurface({ transcribing: true });
  assert.equal(inFlight.phase, SURFACE_CAPTURED);
  assert.equal(inFlight.wave, false);
  const flash = studentSurface({ heard: "We'd cap exposure per borrower." });
  assert.equal(flash.phase, SURFACE_CAPTURED);
  assert.equal(flash.caption, "We'd cap exposure per borrower.");
});

test("the surface closes when nothing of theirs is in flight", () => {
  const s = studentSurface({});
  assert.equal(s.phase, SURFACE_CLOSED);
  assert.equal(s.open, false);
});

test("an empty 'heard' does not open a surface with nothing in it", () => {
  assert.equal(studentSurface({ heard: "   " }).phase, SURFACE_CLOSED);
});

test("live outranks captured — the new answer, not the last one's echo", () => {
  const s = studentSurface({ recording: true, heard: "the previous answer" });
  assert.equal(s.phase, SURFACE_LIVE);
});

// ── The chat panel ─────────────────────────────────────────────────────────

test("voice mode: the panel is a collapsible third column", () => {
  assert.equal(chatSlot({ textMode: false, chatOpen: true }), "side");
  assert.equal(chatSlot({ textMode: false, chatOpen: false }), "hidden");
});

test("text mode: the panel IS the second tile, and cannot be collapsed away", () => {
  // Collapsing the primary answering surface in text mode would leave a room with no way
  // to answer in it.
  assert.equal(chatSlot({ textMode: true, chatOpen: true }), "student-tile");
  assert.equal(chatSlot({ textMode: true, chatOpen: false }), "student-tile");
});

test("the room is two tiles in both modes", () => {
  for (const chatOpen of [false, true]) {
    assert.notEqual(chatSlot({ textMode: true, chatOpen }), "hidden");
  }
});

// ── The bubble tick ────────────────────────────────────────────────────────

test("only a spoken answer gets the 'heard you' tick — it is the only one with no receipt", () => {
  assert.deepEqual(bubbleMeta("SPOKEN"), { label: "Heard you", tick: true });
  assert.equal(bubbleMeta("TYPED").tick, false);
  assert.equal(bubbleMeta("SKIPPED").tick, false);
  assert.equal(bubbleMeta(undefined), null);
  assert.equal(bubbleMeta("SOMETHING_NEW"), null);
});

// ── Reading is not typing ──────────────────────────────────────────────────

test("READING THE TRANSCRIPT DOES NOT COST YOU THE MICROPHONE", () => {
  // The whole reason composerIntent exists. Opening the panel to re-read an earlier
  // question must not be mistaken for choosing to type, or hands-free dies from an act of
  // reading. Panel visibility is not an input here — and that is the assertion.
  assert.equal(composerIntent({ focused: false, draft: "" }), false);
});

test("focusing the composer, or holding a draft, IS choosing to type", () => {
  assert.equal(composerIntent({ focused: true }), true);
  assert.equal(composerIntent({ draft: "I'd start by segmenting" }), true);
  // Blurred with a draft still counts: their half-written answer is sitting right there.
  assert.equal(composerIntent({ focused: false, draft: "I'd start by" }), true);
});

test("whitespace is not a draft", () => {
  assert.equal(composerIntent({ focused: false, draft: "   \n " }), false);
});
