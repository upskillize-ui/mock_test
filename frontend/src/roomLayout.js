/**
 * roomLayout — who has the floor, what the room says it is doing, and what the
 * student's tile is showing while they answer.
 *
 * PURE, like roomPolicy: no React, no DOM, no fetch. The room grew a set of floating
 * overlays — a state label under the character that landed on top of her name tag, a muted
 * chip pinned 150px off the bottom edge, a "Heard:" flash in the dead centre of the stage —
 * and each one was individually reasonable and collectively a room where the answer to
 * "what is happening right now?" was in three places at once and sometimes disagreed with
 * itself. So the DECISIONS moved here, where they are one function each and can be tested:
 *
 *   activeSpeaker()   — whose tile is lit
 *   statusStrip()     — the ONE line under the tiles
 *   studentSurface()  — what the student's own tile shows while they speak
 *
 * The rule these exist to keep: THE ROOM NEVER CONTRADICTS ITSELF. The lit tile, the strip,
 * and the interviewer's face are three renderings of one state, so they are derived from
 * one state — see the `orbState` parity test in roomLayout.test.mjs, which is the whole
 * reason statusStrip takes the same inputs App.jsx already computes `orbState` from.
 */

// ── Who is talking ───────────────────────────────────────────────────────────
export const SPEAKER_INTERVIEWER = "interviewer";
export const SPEAKER_STUDENT = "student";

/**
 * activeSpeaker — whose tile gets the ring.
 *
 * Exactly one, or neither. Never both: two lit tiles is the same as none lit, because the
 * ring's whole job is to answer "who has the floor" at a glance.
 *
 * The student wins ties, and the tie is real: during a BARGE-IN the interviewer's clip is
 * still ducking out (~200ms) while the recorder is already open. In that moment the person
 * actually talking is the student — they just took the floor by force — so the ring should
 * be on them. Deferring to `speaking` would light her tile while she is being interrupted.
 *
 * `connecting` counts as hers: FAST START puts the room up before her opening arrives, and
 * she is about to speak into a room that is already listening for her. Nobody else has the
 * floor in that beat.
 */
export function activeSpeaker({
  recording = false,
  speaking = false,
  connecting = false,
} = {}) {
  if (recording) return SPEAKER_STUDENT;
  if (speaking || connecting) return SPEAKER_INTERVIEWER;
  return null;
}

// ── The one status strip ─────────────────────────────────────────────────────
// One line, under both tiles, that says what the room is doing. It replaces the label that
// used to sit under the interviewer's character (and collide with her name tag) and the
// muted chip that used to float over the stage.
//
// `tone` is a NAME, not a colour: the CSS owns the hex. Colour never carries the meaning on
// its own — every state also has words, which is why `label` is never empty.
export const STRIP_SPEAKING = "speaking";
export const STRIP_LISTENING = "listening";
export const STRIP_THINKING = "thinking";
export const STRIP_MUTED = "muted";
export const STRIP_READY = "ready";
export const STRIP_ENDED = "ended";

/**
 * statusStrip — the single answer to "what is happening right now?".
 *
 * The precedence is the point, so read it top to bottom:
 *
 *   ended     — nothing else is true any more.
 *   listening — they are ON THE RECORD. This outranks everything below it, including
 *               `speaking` during a barge-in, for the same reason activeSpeaker does.
 *   thinking  — transcribing / the reply is being written / her opening has not landed.
 *   speaking  — a clip is in the air.
 *   muted     — she has finished, it is their turn, and the mic is off. This is the only
 *               state that is an INSTRUCTION rather than a description, because it is the
 *               only one where the room is waiting on something the student must do. It
 *               pulses (`cue`) so it reads as a prompt and not as a label.
 *   ready     — the honest default: between turns, nothing to report.
 *
 * @returns {{key, label, detail, tone, cue}} — `detail` is the rec counter's slot (the
 *   caller formats the clock; a policy module has no business owning mm:ss), `cue` asks the
 *   strip to pulse.
 */
export function statusStrip({
  ended = false,
  recording = false,
  transcribing = false,
  loading = false,
  connecting = false,
  speaking = false,
  micOn = true,
  answerDue = false,
  recLabel = "",
  textMode = false,
} = {}) {
  if (ended) return strip(STRIP_ENDED, "Interview ended", "", "idle");
  if (recording) return strip(STRIP_LISTENING, "Listening", recLabel, "orange");
  if (connecting) return strip(STRIP_THINKING, "Connecting", "", "navy");
  if (transcribing || loading) return strip(STRIP_THINKING, "Thinking", "", "navy");
  if (speaking) return strip(STRIP_SPEAKING, "Speaking", "", "teal");
  // TEXT: the mic being off is the MODE, not a mistake. "You're muted — tap the mic to
  // answer" told a typing student to fix something that was working as chosen, and pointed
  // them at the one control the mode promises never to need — tapping it would have fired
  // the permission prompt we guarantee a TEXT session never sees. Same job (their turn,
  // here is how to answer), stated in the vocabulary of the mode they picked.
  if (textMode) {
    return answerDue
      ? strip(STRIP_READY, "Your turn", "Type your answer", "orange", true)
      : strip(STRIP_READY, "Ready", "", "idle");
  }
  // Muted with an answer genuinely due: point at the fix, do not merely state the fact.
  if (!micOn && answerDue) {
    return strip(STRIP_MUTED, "You're muted", "Tap the mic to answer", "orange", true);
  }
  return strip(STRIP_READY, "Ready", "", "idle");
}

function strip(key, label, detail, tone, cue = false) {
  return { key, label, detail, tone, cue };
}

/**
 * stripMatchesFace — the parity rule, stated as code so the test can hold us to it.
 *
 * App.jsx already derives `orbState` (the interviewer's expression) from these same
 * signals. If the strip could ever say "Speaking" while her face said "listening", the room
 * would be lying to somebody, so: every strip key maps onto exactly one face state, and the
 * test walks the whole input space checking the two agree.
 *
 * `muted`, `ready` and `ended` all map to `idle` — the face has nothing to do in any of
 * them; it is the STRIP that carries what is different about them.
 */
export const STRIP_TO_FACE = {
  [STRIP_SPEAKING]: "speaking",
  [STRIP_LISTENING]: "listening",
  [STRIP_THINKING]: "thinking",
  [STRIP_MUTED]: "idle",
  [STRIP_READY]: "idle",
  [STRIP_ENDED]: "idle",
};

// ── The student's own tile, while they answer ────────────────────────────────
// "Type your answer" was always available, but SPEAKING one had no surface of its own: the
// waveform floated over the stage 16px off the bottom and the running transcript borrowed
// the interviewer's caption band. So an answer in progress looked like a thing happening TO
// the room rather than a thing the student was doing, and the moment it was safely captured
// was a 3-second flash in the middle of the screen that was easy to miss entirely.
//
// Now it opens inside their own tile and closes when the interviewer takes the floor back.
export const SURFACE_CLOSED = "closed";
export const SURFACE_LIVE = "live";
export const SURFACE_CAPTURED = "captured";

/**
 * studentSurface — what the student's tile shows while they have (or just had) the floor.
 *
 *   live     — the mic is open. Waveform + their own running "You:" transcript.
 *   captured — they have stopped and the answer is safely ours: the tick. This spans BOTH
 *              `transcribing` (in flight — the tick is a promise we are about to keep) and
 *              the `heard` flash that follows (the transcript, quoted back). Collapsing the
 *              two means the surface does not blink out and back between them.
 *   closed   — nothing of theirs is in flight.
 *
 * `caption` is only ever their OWN words, verbatim, and it is empty rather than invented:
 * a caption the student did not say is worse than no caption at all.
 */
export function studentSurface({
  recording = false,
  transcribing = false,
  heard = "",
  selfCaption = "",
  selfCaptionsOn = false,
} = {}) {
  if (recording) {
    return {
      phase: SURFACE_LIVE,
      open: true,
      wave: true,
      // Self-captions are opt-in (they cost STT calls). Off, the surface is the waveform and
      // the counter — which still says "we can hear you", which is the part that matters.
      caption: selfCaptionsOn ? String(selfCaption || "") : "",
      showCaption: selfCaptionsOn,
    };
  }
  if (transcribing || String(heard || "").trim()) {
    return {
      phase: SURFACE_CAPTURED,
      open: true,
      wave: false,
      caption: String(heard || "").trim(),
      showCaption: true,
    };
  }
  return { phase: SURFACE_CLOSED, open: false, wave: false, caption: "", showCaption: false };
}

// ── The chat panel ───────────────────────────────────────────────────────────
// The panel is the full session transcript AND a composer, and it is deliberately
// MODE-AGNOSTIC: in voice mode it is a third column you can collapse, and in text mode it
// takes the student tile's place and becomes the primary surface. Same component, same
// bubbles, same send path — the only thing that changes is which slot it is rendered into.

/**
 * chatSlot — where the panel goes.
 *
 * The layout is TWO TILES in both modes. Text mode does not get a different room; it gets
 * the same room with the panel sitting where the camera would have been (there is no camera
 * tile to show, because there is no camera turn to take).
 */
export function chatSlot({ textMode = false, chatOpen = false } = {}) {
  if (textMode) return "student-tile";      // it IS the second tile
  return chatOpen ? "side" : "hidden";
}

/**
 * bubbleMeta — the little line under a student's bubble.
 *
 * "Heard you" is the tick on a captured VOICE answer, and it is doing a specific job: a
 * spoken answer is the one the student has no receipt for. They typed nothing; they just
 * talked at a laptop. The tick is the receipt. A typed answer needs no such reassurance —
 * they can see their own words — and a skip is not a receipt for anything.
 */
export function bubbleMeta(meta) {
  switch (meta) {
    case "SPOKEN": return { label: "Heard you", tick: true };
    case "SKIPPED": return { label: "Time ran out", tick: false };
    case "TYPED": return { label: "Typed", tick: false };
    default: return null;
  }
}

/**
 * composerIntent — has the student CHOSEN to type?
 *
 * This one is load-bearing, and it used to be wrong in a way that only the chat panel
 * exposed. `canArmCapture({typing})` suppresses the mic when the student has picked the
 * composer — right rule, because opening the mic on somebody who is mid-sentence in a text
 * box is rude and races their own answer. But `typing` was wired to "the typing drawer is
 * open", and that was only ever a decent proxy because the drawer did nothing else.
 *
 * The panel does something else: it is where you RE-READ an earlier question. Keeping the
 * old proxy would mean opening the transcript to check what was asked silently disarmed the
 * microphone, and hands-free would die from an act of reading.
 *
 * So the signal is now the composer itself — focused, or holding a draft — and never the
 * panel's visibility. Reading is not typing.
 */
export function composerIntent({ focused = false, draft = "" } = {}) {
  return !!focused || String(draft || "").trim().length > 0;
}
