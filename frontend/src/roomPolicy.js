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

export function questionSeconds(stage) {
  return QUESTION_SECONDS[String(stage || "").toUpperCase()] || DEFAULT_QUESTION_SECONDS;
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
