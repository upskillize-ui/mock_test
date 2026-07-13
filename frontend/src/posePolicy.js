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
