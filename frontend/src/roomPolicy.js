/**
 * roomPolicy — the room's clocks, and what each one does when it runs out.
 *
 * Deliberately PURE: no React, no DOM, no fetch. The client owns the wall clock (it is
 * the thing with a screen), but every DECISION a clock makes lives here, where it can be
 * tested with `node --test` and read in one sitting. The server owns the CONSEQUENCE:
 * an expiry becomes /session/turn with a timeout kind, or /session/wrap — both persisted,
 * so a refresh cannot dodge either.
 *
 * The one rule all of this exists to keep: a clock running out must never strand the
 * candidate. Something always happens next.
 */

// ── The per-question clock (E7.7) ────────────────────────────────────────────
// Long enough that nobody sane feels rushed; short enough that a stalled question can't
// eat a 20-minute session. The case gets the most room because it is meant to be
// reasoned through out loud.
export const QUESTION_SECONDS = {
  WARMUP: 90,
  DOMAIN: 180,
  BEHAVIOURAL: 180,
  CASE: 240,
  REVERSE: 120,
};
export const DEFAULT_QUESTION_SECONDS = 180;
// When the chip starts warning. Shown from the first second either way — a clock the
// candidate cannot see is a trap, and we do not lay traps.
export const QUESTION_WARN_SECONDS = 30;

// The engagement floor's check-in ("Shall we keep going?") is a direct question, and it
// gets its own short clock — a yes/no does not need three minutes, and giving it three
// minutes would just be another three minutes of the silence we are trying to break.
// Mirrors stages.CHECKIN_SECONDS; the server sends the number, this is the fallback.
export const CHECKIN_SECONDS = 45;

export function questionSeconds(stage, kind = "question", checkinSeconds = CHECKIN_SECONDS) {
  if (kind === "checkin") return Number(checkinSeconds) || CHECKIN_SECONDS;
  return QUESTION_SECONDS[String(stage || "").toUpperCase()] || DEFAULT_QUESTION_SECONDS;
}

// ── QA-03: in TEXT the per-question clock measures IDLE, not elapsed ─────────
// The clocks above are voice clocks. In a spoken interview, elapsed time and thinking
// time are the same thing — silence is the signal. In a typed one they are not: reading
// the question, thinking, and typing the answer all cost wall-clock, and none of them is
// disengagement. Running the voice clock in TEXT meant a student who read a case prompt
// carefully for ninety seconds had the question taken away mid-thought, auto-submitted as
// "(No answer — the time on this question ran out.)" — the deliberate thinker punished
// hardest, which is exactly backwards for a product that scores thinking.
//
// So in TEXT the deadline counts CONTINUOUS INACTIVITY. Every keystroke pushes it out, so
// nobody is ever cut off mid-draft and nobody loses a question for thinking. What remains
// bounded is the thing that was always the real limit: the session clock.
//
// The nudge comes first and only once, and it is not a device fork — nothing here mentions
// a microphone, because this mode does not have one.
export const TEXT_IDLE_NUDGE_MS = 75_000;
export const TEXT_IDLE_EXPIRY_MS = 180_000;
export const TEXT_IDLE_NUDGE_LINE = "Take your time — type when you're ready.";

/**
 * textIdleAction — how long has the composer been untouched, and what does that earn?
 *
 * Pure so the ladder is testable without a browser: nudge at 75s of true idle, expire at
 * 180s. Anything under the nudge is just a student thinking, which is the point.
 */
export function textIdleAction(idleMs = 0) {
  if (idleMs >= TEXT_IDLE_EXPIRY_MS) return "expire";
  if (idleMs >= TEXT_IDLE_NUDGE_MS) return "nudge";
  return "none";
}

// What the SERVER stores for a skipped question. Kept here only so the transcript drawer
// can show the same words the server wrote; the server's copy is the authoritative one
// (see stages.TIMEOUT_SKIP_TEXT) and the client never sends this text.
export const SKIP_MARKER = "(No answer — the time on this question ran out.)";

/**
 * expiryAction — the per-question clock just hit zero. What do we submit?
 *
 * Anything they got out — a partial transcript from a recording we cut off, or a draft
 * sitting in the composer — IS their answer: submitting it is strictly kinder than
 * throwing it away, and the interviewer engages with what is there. With nothing at all
 * captured, it becomes a skip: no slot spent, no rating, and the interview moves on.
 *
 * The spoken partial wins over a stale typed draft — it is the more recent act.
 */
export function expiryAction({ partial = "", draft = "" } = {}) {
  const text = (partial || "").trim() || (draft || "").trim();
  return text
    ? { timeout: "partial", text: text.slice(0, 4000) }
    : { timeout: "skip", text: "" };
}

// ── The "is this a real spoken answer?" gate (item 7) ────────────────────────
// The trailing-silence auto-stop is LOUDNESS-only: any sustained background noise above the
// amplitude gate arms "they spoke", and once armed the recording stops and whatever the STT
// hallucinated from the noise ("you", "um", ".") was submitted as an answer — the "ANSWER
// CAPTURED before I said anything" complaint. So before a voice answer is auto-captured and
// submitted, it must clear a CONTENT gate: a couple of real words, a few characters, and a
// recording that actually ran long enough to be speech. A transcript that fails this is
// treated exactly like an empty one — she says "I didn't quite catch that" and the mic
// reopens; nothing is captured, nothing is submitted.
export const ANSWER_MIN_WORDS = 2;     // a lone token is noise, not an answer
export const ANSWER_MIN_CHARS = 6;     // "." / "um" / "you" don't clear this
export const ANSWER_MIN_MS = 1200;     // and it must have run long enough to be speech

export function isSubstantiveAnswer(transcript, durationMs = Infinity) {
  const s = (transcript || "").trim();
  if (s.length < ANSWER_MIN_CHARS) return false;
  // Count only tokens that carry a letter or digit — punctuation and stray symbols the STT
  // emits from noise ("...", "-") must not count toward the word floor.
  const words = s.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w));
  if (words.length < ANSWER_MIN_WORDS) return false;
  if (Number(durationMs) < ANSWER_MIN_MS) return false;
  return true;
}

// ── The device-policy clocks (Phase E) ───────────────────────────────────────
// These mirror app/presence.py — same numbers, same rules, tested on both sides.
export const CAMERA_GRACE_MS = 60_000;
export const SILENT_ABANDON_MS = 90_000;

export const WRAP_CAMERA_OFF = "camera_off";
export const WRAP_NO_ANSWER = "no_answer_timeout";
export const WRAP_SESSION_TIME_UP = "session_time_up";

/**
 * shouldArmAbandon — is this the total dead end that counts as abandonment?
 *
 * Only in the room (the stage is where the mic is the primary channel), only while an
 * answer is actually due, only with the mic MUTED, and only with nothing typed. An
 * unmuted candidate sitting quiet is thinking, not leaving — the per-question clock
 * already handles that, and it ends in a skip, not in ending their session.
 */
export function shouldArmAbandon({ inRoom = false, answerDue = false, micOn = true, typedChars = 0 } = {}) {
  if (!inRoom || !answerDue) return false;
  if (micOn) return false;
  return !(Number(typedChars) > 0);
}

// ── THE CAPTURE INVARIANT ────────────────────────────────────────────────────
// THE MIC NEVER OPENS WHILE THE INTERVIEWER STILL HAS WORDS SHE HAS NOT SAID.
//
// This is one rule with several names. "Don't record over her." "Don't start the answer
// before the question finished." "Don't submit half a question's worth of her own voice as
// their answer." They are all the same invariant, and it had been enforced by CONVENTION —
// every arming site remembering to check — which is exactly the kind of rule that holds
// until someone adds a seventh arming site. Three of the six already got it wrong: unmuting,
// tapping the mic, and accepting the consent modal all began capture mid-reply.
//
// So it is a function now, and it is the ONLY door to the microphone. `armCapture()` in
// App.jsx is the single call site of the recorder; everything else asks this.
//
// The three states that mean "she is not finished":
//   connecting   — FAST START: the room is up but her opening has not arrived yet. The
//                  session row already says it is the candidate's turn. It is not.
//   speaking     — a clip is in the air right now.
//   speechQueued — her reply has ARRIVED but playback has not begun. A tiny window, and
//                  exactly the one a state update can slip through.
//
// Barge-in is NOT an exception to this. When the candidate talks over her, she is STOPPED
// first — the remaining clips are abandoned, not merely postponed — and only then does the
// mic open. By the time capture is armed she genuinely has nothing left to say, so barge-in
// passes this gate honestly rather than going around it.
export function canArmCapture({
  inRoom = false,        // the voice stage (the mic is the primary channel here)
  micOn = false,         // the mute toggle. Muted means muted — no capture, ever.
  consented = false,     // explicit, always
  answerDue = false,     // it is their turn to answer...
  ratingDue = false,     // ...or to speak their confidence rating
  connecting = false,    // ─┐
  speaking = false,      //  ├─ THE INVARIANT
  speechQueued = false,  // ─┘
  recording = false,     // already capturing
  transcribing = false,  // the last answer is still in flight
  busy = false,          // a re-ask / nudge is in flight
  typing = false,        // they chose the composer; do not also open the mic on them
  ended = false,
} = {}) {
  if (!inRoom || !micOn || !consented) return false;
  if (!(answerDue || ratingDue)) return false;
  if (ended || typing) return false;
  if (recording || transcribing || busy) return false;
  // THE INVARIANT. Everything above is "is it their turn?"; this is "has she finished?".
  if (connecting || speaking || speechQueued) return false;
  return true;
}

// ── Listening backchannels (the REALISM pack) ────────────────────────────────
// A person who is listening to you makes noise. Not much — an "mm-hmm" at the moment you
// pause for breath — but its ABSENCE is loud, and a panel that sits in perfect silence for
// a three-minute answer is the single most machine-like thing in the room.
//
// The constraints are all about not INTERRUPTING, because a backchannel in the wrong place
// is worse than none at all:
//   - only in a long answer (a short one has no room for it);
//   - only at a real pause, and never one long enough to be them FINISHING (that pause
//     belongs to the end-of-answer detector, and stepping on it would cut them off);
//   - never in the opening seconds, when they are still finding their footing;
//   - at most twice, ever, in one answer. Three is a tic.
export const BACKCHANNEL_MIN_ANSWER_MS = 20_000;   // "answers longer than ~20s"
export const BACKCHANNEL_NEVER_BEFORE_MS = 10_000; // never in the first 10s
export const BACKCHANNEL_MIN_PAUSE_MS = 1_200;     // a real breath, not a syllable gap
export const BACKCHANNEL_MAX_PER_ANSWER = 2;

/**
 * shouldBackchannel — should a soft "mm-hmm" land right now?
 *
 * @param elapsedMs     how long they have been speaking, this answer
 * @param pauseMs       how long the current silence has run
 * @param playedCount   backchannels already played in THIS answer
 * @param endOfAnswerMs the trailing silence that ENDS an answer. The pause must stay
 *                      strictly under it: at that point they are not pausing, they are done.
 */
export function shouldBackchannel({
  elapsedMs = 0, pauseMs = 0, playedCount = 0, endOfAnswerMs = 2_500,
} = {}) {
  if (playedCount >= BACKCHANNEL_MAX_PER_ANSWER) return false;
  if (elapsedMs < BACKCHANNEL_MIN_ANSWER_MS) return false;
  if (elapsedMs < BACKCHANNEL_NEVER_BEFORE_MS) return false;
  if (pauseMs < BACKCHANNEL_MIN_PAUSE_MS) return false;
  return pauseMs < endOfAnswerMs;
}

// ── Barge-in (the REALISM pack) ──────────────────────────────────────────────
// You can interrupt a person. That is most of what makes them a person. If the candidate
// starts talking while the interviewer is mid-reply, the interviewer stops — ducks out over
// 200ms rather than cutting dead, because a hard cut sounds like a bug — and the floor is
// theirs. She does not then re-say the sentences she was interrupted out of: nobody does
// that, and a candidate who interrupts has already decided they do not need the rest.
export const BARGE_IN_RMS = 0.06;        // well above SILENCE_RMS: a voice, not a cough
export const BARGE_IN_SUSTAIN_MS = 300;  // ...held for long enough to be words
export const BARGE_IN_DUCK_MS = 200;     // fade out, don't cut

/**
 * shouldBargeIn — is that the candidate talking over the interviewer?
 *
 * The threshold is deliberately high and requires SUSTAIN. The mic is open while audio is
 * playing out of the same laptop, so echo cancellation is doing real work underneath this;
 * a low bar would have the interviewer interrupting herself with her own voice.
 *
 * @param rms          current mic level, 0..1
 * @param aboveSinceMs how long the level has been continuously above the threshold
 */
export function shouldBargeIn({ rms = 0, aboveSinceMs = 0 } = {}) {
  return Number(rms) > BARGE_IN_RMS && Number(aboveSinceMs) >= BARGE_IN_SUSTAIN_MS;
}
