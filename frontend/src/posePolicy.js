/**
 * posePolicy — which face the interviewer wears, and when.
 *
 * Deliberately PURE: no React, no asset imports, no DOM. That keeps it testable with
 * Node's built-in test runner (`node --test`) and adds zero dependencies — the asset
 * imports are Vite-only and would make this module un-importable outside a bundler.
 *
 * Poses are stills of the same person (sliced from one 2x2 generation, so identity is
 * consistent). We crossfade between them; we never animate a mouth on a photograph.
 * Lip motion stays the job of the amplitude glow/badge — the POSE carries the register.
 */

export const POSES = ["listening", "smile", "intense", "thinking"];

/**
 * choosePose — state first, then the server's tone hint, then heuristics.
 *
 * @param state            "speaking" | "listening" | "thinking" | "idle"/"ready"
 * @param tone             "warm" | "neutral" | "probing" from the server (may be absent)
 * @param escalationLevel  focus ladder, 0..3
 * @param stage            WARMUP | DOMAIN | ... (fallback heuristic when tone is absent)
 * @param difficulty       "Easy" | "Realistic" | "Stretch" (fallback heuristic)
 * @param group            increments per reply, so "neutral" can alternate and stay alive
 */
export function choosePose({
  state,
  tone = "",
  escalationLevel = 0,
  stage = "",
  difficulty = "",
  group = 0,
} = {}) {
  if (state === "thinking") return "thinking";
  if (state !== "speaking") return "listening";   // listening AND idle/ready rest here

  // The panel has leaned in. This outranks tone: if the focus ladder has escalated, the
  // face must not be smiling while the words are firm.
  if (escalationLevel >= 2) return "intense";

  if (tone === "probing") return "intense";
  if (tone === "warm") return "smile";

  if (!tone) {
    // No server hint -> heuristics.
    const s = String(stage || "").toUpperCase();
    if (s === "" || s === "WARMUP") return "smile";        // greeting / warm-up
    if (String(difficulty) === "Stretch") return "intense"; // deep-dives lean in
  }

  // "neutral": alternate so the face doesn't freeze into one expression for a whole round.
  return group % 2 === 0 ? "listening" : "smile";
}

// ── Emphasis (amplitude-driven) ──────────────────────────────────────────────
// While the interviewer speaks warmly/neutrally, a loud, emphatic passage swaps in the
// `intense` frame — the one where her hands are up mid-gesture — and it drops back when
// her voice settles. The effect is that her hands move with her voice. Hysteresis (a
// high ON threshold, a lower OFF threshold) plus a minimum hold stops the face
// strobing on every syllable: the amplitude has to STAY up, not merely spike.
export const EMPHASIS_ON = 0.65;
export const EMPHASIS_OFF = 0.4;
export const EMPHASIS_MIN_HOLD_MS = 1500;

/**
 * nextEmphasis — should the emphatic frame be showing on the next tick?
 *
 * @param emphatic      is it showing right now?
 * @param amp           current TTS amplitude, 0..1
 * @param msSinceSwitch ms since the last switch (Infinity if we've never switched)
 */
export function nextEmphasis(emphatic, amp, msSinceSwitch) {
  if (!(msSinceSwitch >= EMPHASIS_MIN_HOLD_MS)) return emphatic;   // too soon; also guards NaN
  if (!emphatic && amp > EMPHASIS_ON) return true;
  if (emphatic && amp < EMPHASIS_OFF) return false;
  return emphatic;
}

/** True only when EVERY pose exists for this character (robots / un-regenerated humans false). */
export function hasPoseSet(poseMap, characterId) {
  if (!poseMap || !characterId) return false;
  return POSES.every((p) => Boolean(poseMap[`${characterId}_${p}`]));
}

/**
 * resolvePose — the image to actually show.
 * Falls back gracefully: exact pose -> that character's "listening" -> their single base
 * image. A character with no pose set (robots, art not yet generated) simply keeps its
 * original portrait. Never returns undefined, never crashes.
 */
export function resolvePose(poseMap, characterId, pose, baseImg) {
  if (!poseMap || !characterId) return baseImg;
  return (
    poseMap[`${characterId}_${pose}`] ||
    poseMap[`${characterId}_listening`] ||
    baseImg
  );
}
