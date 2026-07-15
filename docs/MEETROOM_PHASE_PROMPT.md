# MEETROOM_PHASE_PROMPT.md — InterviewIQ "Interview Room" Sprint
# Paste this whole file as the task prompt for Claude Code in the VYOM_BUILD repo.

## Goal
Rebuild the voice stage as a Google-Meet-style interview room: one pre-join
lobby that asks for mic + camera together, a meeting-room layout, live
interviewer captions, typing always available, and Phase 2 on-device focus
monitoring with graded interviewer responses.

## Non-negotiable constraints (read first)
1. PRIVACY: camera frames NEVER leave the browser. No MediaRecorder, no
   canvas upload, no frame transmission. Proctoring produces EVENTS only
   (strings + timestamps). Mark all new user-facing consent/notice copy
   with `[PENDING LEGAL REVIEW]`.
2. VOICE PIPELINE UNTOUCHED: STT (Saarika, transcribe-and-discard), TTS
   (Bulbul + analyser lip-sync via wireTtsAnalyser/resumeTtsAnalyser),
   silence detection, spoken confidence ratings, Hinglish parsing — all
   must keep working exactly as-is. Reuse, don't rewrite.
3. BRAND: navy #0B1628/#1a2744, gold #C8992A/#F5B800, teal #00C4A0, orange
   #E8521A. Plus Jakarta Sans / Playfair Display / DM Mono. Lucide-style
   inline SVG icons 1.6px stroke. No emojis on the interview surface.
   Interviewer tone: exam-room serious in session, coaching in readout,
   never punitive.
4. InterviewerCharacter.jsx (v4.1 roster) and SelfView.jsx exist — reuse
   InterviewerCharacter unchanged; SelfView's stream logic can be absorbed
   into the room's camera tile, keeping its privacy comments.

## PHASE A — Pre-join lobby ("green room")
Route: shown after session config (role/difficulty/mode/voice), before the
first question. Like Meet's join screen:
- Left: camera preview tile (mirrored). If camera off/denied: initial-letter
  avatar tile. Camera toggle + mic toggle buttons under the tile.
- Mic check: live input level meter using a temporary getUserMedia audio
  stream (released before Join). Label: "Say something — the bar should move."
- ONE permission moment: on lobby mount, request audio+video together with
  a single getUserMedia({audio:true, video:true}) call, wrapped in our own
  pre-prompt card explaining both (draft copy below). If the user denies
  video but allows audio, proceed audio-only. If both denied, allow
  join in TYPE-ONLY mode — never hard-block the interview.
- Consent card copy (draft, [PENDING LEGAL REVIEW]):
  "Your mic converts answers to text — audio is never stored. Your camera
   stays on your device — never recorded or uploaded. You can type instead
   at any time."
  Buttons: "Allow mic & camera" / "Mic only" / "Type instead".
  Record consent rows (voice_recording and/or camera_selfview) via the
  existing recordConsent(); reuse CONSENT_COPY_VERSION.
- "Join interview" button (disabled until a choice is made). Joining tears
  down the lobby streams and hands the chosen devices to the room.
- Remove the old mid-session VoiceConsentModal trigger path — consent now
  happens once in the lobby. Keep the modal component for the classic
  (non-voice-stage) mode only.

## PHASE B — The room
Layout (dark navy stage, like a 2-person Meet call):
- Main tile: InterviewerCharacter (existing component, size ~min(60vh, 420px)
  wide, responsive). Interviewer name chip bottom-left of the tile
  (e.g. "Priya · InterviewIQ") — get the name from pickInterviewer.
- Corner tile: student self-view bottom-right (absorb SelfView), with mic
  status dot. Draggable optional; skip if it adds risk.
- Bottom control bar, centered, Meet-style pill buttons:
  [Mic toggle] [Camera toggle] [CC captions toggle] [Keyboard: type answer]
  [End — existing end flow]
  Mic button doubles as the push-to-talk trigger in auto-listen gaps;
  preserve the existing tap-to-speak semantics.
- "Type instead" becomes the keyboard button: opens a bottom text input
  drawer; submitting routes through the same answer path as typed mode.
  Always available, every question.
- CC captions (default ON): while TTS plays, show the interviewer's current
  sentence in a Meet-style caption bar above the control bar — dark pill,
  white text, 'Plus Jakarta Sans','Noto Sans Devanagari' stack, max 2 lines,
  sentence-by-sentence sync is fine (split the TTS text on sentence
  boundaries and advance on audio timeupdate proportionally; exact word
  timing not required). Student's own "Heard:" caption stays as-is.

## PHASE C — Focus monitoring (proctoring done responsibly)
Purpose: TRAIN interview presence, not punish. Frame everything as the
interviewer noticing attention, exactly like a real panel would.
- Engine: on-device only. Use MediaPipe Face Detection (or
  @tensorflow-models/face-detection, tfjs backend webgl) on the self-view
  stream at ~2 fps. No frames stored. Detect signals:
  s1 no_face          (no face > 4s)
  s2 multiple_faces   (>1 face > 2s)
  s3 looking_away     (face yaw/position offset beyond threshold > 5s —
                       use bounding-box center drift as proxy; keep the
                       threshold generous, this signal is NOISY)
  s4 tab_hidden       (document.visibilitychange > 2s)
  s5 window_blur      (blur > 3s, e.g. switching apps)
- Debounce: max 1 event per signal per 30s. Events POST to a new backend
  endpoint /api/session/{id}/focus-event {type, ts} — strings only.
- Escalation ladder (server-side, per session, persisted with the session):
  Level 1 (first 2 events): interviewer, next turn, adds ONE gentle line in
    persona voice, e.g. "Before we continue — I'd like your full attention
    on this one." Normal tone.
  Level 2 (3rd–4th event): firmer, still professional: "I'll be direct:
    in a real panel, looking away this often would cost you. Let's stay
    with me for the remaining questions."
  Level 3 (5th+): interviewer notes it will be reflected in feedback; no
    scolding, no threats. The readout gains a "Professional presence"
    line: what was observed (counts only) + one coaching fix.
  Persona: inject current escalation level into the identity prompt so the
  improvised interviewer (migration 005) phrases reminders in-character.
- Fairness guardrails: signals s1–s3 are heuristic — NEVER use the word
  "cheating" in user-facing copy; say "attention"/"presence". If the student
  JOINED camera-off from the lobby (accessibility path), s1–s3 are disabled
  and the readout omits the camera-based presence lines — no penalty for a
  camera-off join. Mid-interview device changes are governed by PHASE E.
  tab_hidden/window_blur work regardless of camera.

## PHASE D — Presence engine (face, posture, activity — "be a real interviewer")
Upgrade the Phase C detector from face-detection to MediaPipe FaceMesh (or
tfjs face-landmarks-detection) at ~2 fps, still 100% on-device, and compute
CONTINUOUS METRICS, not just events. Follow the delivery-metrics philosophy
already in the product: COMPUTE-AND-DISCARD — raw landmarks/frames are
processed in memory and dropped; only per-question aggregate NUMBERS are
sent with the answer payload.
Metrics (per question, aggregated):
  m1 eye_contact_pct   — % of samples with head yaw/pitch within a generous
                         forward cone (proxy for looking at the panel)
  m2 posture_stability — face-center vertical drift + face-size change over
                         the question (slouching/leaning proxy), 0–100
  m3 composure_index   — inverse of bbox jitter + head-movement variance
                         (fidgeting proxy), 0–100
  m4 presence_pct      — % of the question with exactly one face in frame
  m5 engagement_note   — derived label from m1–m4 bands only (e.g. "steady",
                         "restless", "drifting") — NEVER an emotion word.
HONESTY CONSTRAINT (hold this line in code review): facial "emotion" or
"seriousness" inference is unreliable and bias-prone. We measure OBSERVABLE
BEHAVIOUR (where the head points, how still the body is, whether the person
stayed in frame) and coach on that. No emotion labels, no personality
claims, anywhere — UI, prompts, readout, or DB.
Readout: new "Presence Profile" card next to the Delivery Profile, same
visual language (DM Mono numbers, band pills: Gold/Teal/Navy/Orange):
  Eye contact · Posture · Composure · In-frame presence, each with band +
  ONE coaching line ("You looked away on 40% of the case question — in a
  panel, hold the interviewer's eye while you think.").
Persona integration: after each answer, the current metric bands are
injected into the interviewer identity context so reactions feel human
("You seemed to settle in on that one — good.") — sparing, max once per
round, never sarcastic.

## PHASE E — Device commitment (mic/camera mid-interview policy)
Students can always toggle devices — the buttons stay live — but the
interviewer responds like a real one:
- CAMERA turned off mid-interview (only if they JOINED with camera):
  1st: interviewer, in persona, normal tone: "I'd like to see you for the
  rest of this — could you turn your camera back on?" 60s grace.
  2nd (still off after grace or turned off again): firmer, professional:
  "I do need the camera on to continue the full interview. If it stays
  off, we'll wrap up here with what we've covered."
  Still off after 2nd + 60s → EARLY WRAP: interviewer closes courteously,
  session goes to scoring with rounds completed so far; readout notes
  "Interview ended early — camera was turned off" in neutral language and
  the re-attempt window is suggested as usual. No score zeroing — score
  what happened, mark what didn't.
- MIC turned off mid-interview: interviewer immediately offers the fork:
  "You're on mute — unmute, or switch to typing and we'll continue."
  Typing keeps the interview fully alive (typed answers are first-class).
  If BOTH mic stays off and no typed answer arrives within 90s of a
  question, treat as abandonment → same courteous EARLY WRAP + scoring.
- All wrap decisions are server-side (stage machine gets an EARLY_WRAP
  transition) so a refresh can't dodge them; persisted with the session.
- Timer/state chips in the HUD show device expectations ("Camera expected"
  chip when the policy is active) so nothing feels like a hidden trap.
- Consent: lobby card gains one line when camera enabled: "During the
  interview, InterviewIQ notices attention cues (like looking away) on your
  device to coach your interview presence. No video is recorded."
  [PENDING LEGAL REVIEW]
- Dev flag to disable the whole engine: VITE_FOCUS_MONITOR=off.

## Data / migrations
- Migration 006: focus events (counts + timestamps) AND per-question
  presence aggregates {eye_contact_pct, posture_stability, composure_index,
  presence_pct} per session. Numbers and enum strings only — no media, no
  landmarks, ever.
- Session gains early_wrap {reason, at_stage} nullable.
- Readout schema: professional_presence {bands, events_total, by_type,
  coaching_note}; early-wrap flag surfaces in the readout header.

## Tests
Extend the suite (keep 90/90 green, add):
- lobby permission fallbacks (both denied → type-only join)
- focus-event debounce; presence aggregates compute-and-discard (assert no
  raw landmark persistence)
- escalation ladder level transitions
- camera-off ladder → EARLY_WRAP transition; mic-off → typing fork keeps
  session alive; 90s silence+no-text → EARLY_WRAP
- early-wrapped session still produces a valid scored readout from
  completed rounds
- presence lines omitted for camera-off-at-join sessions.

## Deliverables
Working room behind the existing voice-stage flag, all tests green,
REPORT file (MEETROOM_PHASE_REPORT.md) in repo root per house convention.
Do not push to hf until the PNG/LFS decision from the maintainer is done.
