# PRESENCE_PHASE_PROMPT.md — make it feel like a person, start to finish
# From founder UAT (six-question silent session). Five items. Fresh session,
# one report, suites green, no hf push.

## 1. FAST START — the loading spinner is too long
Session start currently blocks on kickoff LLM + full greeting TTS before
the room renders. Restructure: the ROOM renders immediately after
/session/start returns the session row (interviewer tile, "connecting"
shimmer on the caption band), and the greeting begins the moment its
FIRST sentence clip is ready — later sentences synthesize while the first
plays (they already exist as separate clips; stop awaiting the full set).
Measure and report: time from "Start interview" click → first audible
word, before vs after. Target under 4s on a warm backend.

## 2. ENGAGEMENT FLOOR — a real panel never asks six questions into silence
Founder-reported and readout-confirmed. New server-side rule:
- After 2 CONSECUTIVE timeout-skips with zero substantive answers so far
  in the session: the interviewer breaks the question march and checks in,
  in persona: "I want to make sure you're still with me — we can continue,
  or wrap up here and try again fresh. Shall we keep going?" This is a
  direct question with its own short clock (45s).
- Any response (voice or typed — even "yes") → continue normally, counter
  resets.
- A third consecutive silence → courteous EARLY_WRAP ("Let's wrap here —
  the readout will help you prepare, and the next attempt is a clean
  slate."), scored honestly as today.
- If the candidate HAS given substantive answers earlier, the threshold
  is 3 consecutive skips before the check-in (a good candidate freezing
  on hard questions deserves more rope than a blank session).
This also stops burning LLM+TTS on questions nobody hears. Tests: the
2-skip check-in, the reset-on-any-response, the 3rd-silence wrap, the
looser threshold after substantive answers.

## 3. REALISM PACK — kill the "scripted next-next" feel
(a) ACKNOWLEDGMENT CLIPS: pre-cache ~8 short Bulbul clips per voice at
    build/first-run ("Hmm.", "Okay.", "Right.", "Accha.", "Got it.",
    "Interesting.", "Let me think about that.", "Mm-hmm."). The instant
    an answer is submitted, play one (seeded rotation) while the real
    reply generates — the thinking gap becomes a person considering, not
    a machine loading.
(b) LISTENING BACKCHANNELS: during answers longer than ~20s, at a natural
    pause (silence > 1.2s but below the end-of-answer threshold), softly
    play one "mm-hmm" clip, max twice per answer, never in the first 10s.
(c) BARGE-IN: if the candidate starts speaking while the interviewer is
    mid-reply (mic is open in hands-free flow), duck the audio 200ms then
    stop the remaining clips; captions show the spoken portion only; do
    not re-speak. Their turn begins.
(d) QUESTION CADENCE: before each new QUESTION sentence, the existing
    700ms beat rises to 1000–1200ms when the previous answer was
    substantive — a person absorbs an answer before firing the next
    question. Keep 700ms after skips.

## 4. NEW DIFFICULTY: "Critical" — the pressure panel
Add a fourth difficulty after Stretch. Positioning: a stress-interview
simulator for candidates who want to be challenged hard — a real genre in
Indian hiring (bank PO panels, consulting partners, some PSU boards).
- Selector card: "Critical — Pressure panel. Your answers will be
  challenged and criticised. Not a gentle experience." Requires one extra
  confirmation tap ("I want the pressure panel") — nobody lands here by
  accident.
- tone_hint: new value "critical". Persona addendum for this mode ONLY:
  challenge every substantive answer at least once; express open
  scepticism of weak reasoning ("That number doesn't hold up — walk me
  through it again."); interrupt rambling after ~90s with a redirect;
  be blunt in reactions ("That's not an answer to what I asked.").
- HARD GUARDRAILS UNCHANGED AND TESTED: criticism targets the ANSWER and
  the REASONING, never the person. The banned-vocabulary and attribution-
  pattern tests apply in full — no emotion attributions, no insults, no
  mockery of background/English/accent, and the readout keeps its mentor
  voice (the debrief explicitly acknowledges the mode: "You chose the
  pressure panel — here is what held up under it and what cracked.").
- Poses: critical sessions default the face to `intense` while speaking.
- Curveball rule: two curveballs, not one.

## 5. ROSTER WEIGHTING — posed characters first
Until every character has a pose set, pickInterviewer prefers characters
with full pose sets (currently Riya) at 3x weight within the eligible
pool, falling back to stills for variety. Remove the weighting (one
constant) when the cast's pose grids land. The founder must SEE the pose
system: after this sprint, a Female/Realistic session should usually be
Riya.

Report: PRESENCE_PHASE_REPORT.md — measured start latency before/after,
the engagement-floor test matrix, clip cache contents + size, Critical-
mode sample exchange (one Q/A/challenge transcript), and anything
deliberately not done.
