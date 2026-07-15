# POSES_PHASE_PROMPT.md — InterviewIQ expressive interviewer poses
# Paste to Claude Code AFTER the polish pass lands. Assets arrive from the
# maintainer as frontend/src/interviewers/poses/{characterId}_{pose}.png

## What ships
Each human interviewer gains FOUR pose stills of the same person:
  listening (attentive neutral) · smile (warm, encouraging)
  intense (leaning in, probing) · thinking (hand on chin)
Sliced from single-generation 2x2 grids, so identity is consistent.
Robots keep their existing single image + LED/eye overlays.

## Component behaviour (extend the interviewer tile)
1. Preload all four poses on mount (hidden <img> or Image()) — pose swaps
   must never flash-load.
2. Crossfade between poses: two stacked absolutely-positioned imgs, opacity
   transition 350–450ms ease. Never hard-swap.
3. Pose selection — driven by state + conversational context:
   - listening state → "listening"
   - thinking state  → "thinking"
   - speaking state  → context-dependent:
       greeting / warm-up rounds / positive acknowledgements → "smile"
       probing follow-ups, Stretch difficulty deep-dives,
       escalation level >= 2 (focus ladder) → "intense"
       otherwise alternate smile/listening per sentence group for life
   - idle → "listening" with the existing Ken Burns micro-motion
4. Micro-motion from the polish pass applies to the ACTIVE pose layer
   (glow/scale pulse on amplitude while speaking, sway while listening).
5. Server hint: the turn payload should carry tone: "warm" | "neutral" |
   "probing" derived from the persona directive (the server already knows
   escalation level and round type) — frontend maps tone → pose. Fallback
   to the heuristics in (3) when tone is absent.
6. Reduced motion: crossfades allowed (opacity only), motion effects off.
7. Asset contract: poses live at
   frontend/src/interviewers/poses/{id}_listening.png etc. Characters
   WITHOUT a pose set (robots, any human not yet regenerated) fall back to
   their single image — feature-detect by import map, no crashes.
8. Tests: pose map fallback; tone→pose mapping; escalation>=2 forces
   intense during speaking.

## Notes for the implementer
- Poses are cropped quadrants: framing may shift slightly between poses of
  the same character. Apply object-fit:cover with a shared object-position
  per character (config value) so the face stays anchored across fades.
- Do NOT attempt mouth animation on photos. Lip motion stays the job of
  the amplitude glow/badge; pose changes carry the emotion.

## NONVERBAL ADDENDUM (fold into the Phase D detector sprint)

### Interviewer audio
There is NO interviewer-mute control — the interviewer is always heard,
like a real panel. Captions remain available via the CC toggle.

### Expressiveness metrics (extend Phase D, same compute-and-discard rules)
  m6 expressiveness_index — variance of facial-landmark motion over the
     answer (animated vs flat delivery), 0–100, banded like m1–m4
  m7 smile_moments — count of detected smiles (mouth-curvature landmark
     heuristic), noted especially during greeting and closing
  m8 nod_count — vertical head oscillation events while LISTENING to the
     interviewer (engagement-while-listening proxy)
Readout Presence Profile gains "Expressiveness" and "Warmth signals" lines
with ONE coaching sentence each. Persona may reference at most one
non-verbal observation per session mid-interview ("Good — you lit up when
you talked about that project."), positive-only in-session; corrective
non-verbal coaching lives in the readout, not mid-interview.

### Hard language rules (extends the existing vocabulary-ban test)
Feedback describes OBSERVABLE BEHAVIOUR only: expressions, smiles, nods,
posture, gaze. BANNED in any engine/persona/readout string: emotion and
state attributions — bored, nervous, disinterested, anxious, sad, scared,
unconfident, low-energy-as-personality — and the words feeling/felt/seemed
followed by an emotion. Pattern: "your expressions/posture/gaze did X;
try Y" — never "you were/seemed X". Extend the banned-vocabulary test.
