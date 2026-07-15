# INTAKE_AND_MODES_PHASE_PROMPT.md — one intake skill, TEXT/VOICE/HYBRID modes,
# and Phase D presence metrics
# Updated 2026-07-15 — supersedes any earlier version of this prompt.
#
# RUNTIME CONTEXT (new): the meet room serves INSIDE the LMS shell as a
# same-origin iframe at lms.upskillize.com (sidebar → InterviewIQ). All UI in
# this sprint lays out to its container (~1100–1400px), never assumes full
# viewport, no horizontal overflow. The readout is ONE unified structure
# (what-went-well → Delivery → Presence → fixes → readiness block). Nothing
# in this sprint may add a second readout block.
#
# RULES: commit to origin as you go. NEVER push hf without explicit
# confirmation — if backend changes are needed, list them in the report and
# wait. Keep all suites green (22 Critical guardrails, capture-gate mutation
# test, readout empty-session tests). Brand: navy #0B1628/#1a2744, gold
# #C8992A/#F5B800, teal #00C4A0, Plus Jakarta Sans, no emojis on the
# interview surface. Behaviour words only, never emotion attributions.
# Nothing student-visible ships with [PENDING LEGAL REVIEW] copy.

## PHASE A — ONE INTAKE SKILL (single boundary for all session context)

A1. GATHER: pull LMS context for the logged-in student — ProfileIQ profile,
    course history, experience level — plus the lobby form fields (JD paste,
    quick self-introduction, role, level, difficulty, duration, mode).
A2. MERGE, FORM WINS: one merge step produces the definitive session config.
    Anything the student typed in the form overrides LMS-derived values.
A3. SANITIZE ONCE: all free text (JD, self-intro) is sanitized at this single
    boundary — length caps, stripped markup, prompt-injection defused (JD text
    is DATA for question tailoring, never instructions to the persona).
    Downstream code trusts the sanitized object and never re-sanitizes.
A4. VALIDATE BEFORE SPEND: every validation (required fields, session length
    vs remaining allowance, vendor health) completes BEFORE the first LLM or
    TTS rupee is spent. Invalid config = no paid call, ever.
A5. VENDOR SEATBELT: if TTS is unavailable or the Sarvam account is dry at
    validation time, do not fail the session — offer TEXT mode with honest
    copy ("Voice is unavailable right now — continue in text?"). Aligns with
    the startup-survival hardening from ROOM_EMBED_FIXUP item 5.
A6. CONFIRMATION CARD: the lobby shows one confirmation card with the final
    merged config (role, level, difficulty, duration, mode, rounds, JD-used
    yes/no). This object is the SINGLE SOURCE OF TRUTH — the same object
    populates the readout's Session Profile strip (SCORING_CONTEXT sprint)
    and the attempt record. Defined once, rendered everywhere, no drift.

## PHASE B — MODES: TEXT / VOICE / HYBRID

B1. VOICE (current behaviour, now explicit): mic consent, TTS on, existing
    capture gate untouched — the mic must never arm while interviewer
    segments are unplayed (mutation-tested invariant stays green).
B2. TEXT: no mic consent prompt at all (never ask for a permission the mode
    doesn't use), TTS off (zero Sarvam spend), typing drawer is the primary
    input, per-question timers unchanged. Metrics are honest text metrics:
    typed-communication quality only — NEVER voice Delivery metrics, no
    fabricated pace/filler scores. Typed = spoken for content scoring.
B3. HYBRID: interviewer speaks (TTS on); the student may answer by voice or
    typing per question, switching freely. Each answer is tagged with its
    input channel; Delivery metrics compute only over voice answers and say
    so in the readout ("Delivery measured on your 4 spoken answers").
B4. MODES × SCORING: mode weight factors live ONLY in the SCORING_CONTEXT
    constants table (Interview 1.00 / Coach 0.90; TEXT 0.90, HYBRID 1.00
    reserved rows). Do not invent a second weighting anywhere in this sprint.
    Mode always visible in the confirmation card and Session Profile.
B5. Mode selection UI in the lobby follows the existing Session Settings
    pattern (chips, same card), works inside the embed width.

## PHASE D — PRESENCE (interviewee expression/posture metrics)

D1. ASSETS SELF-HOSTED: MediaPipe models served from our own origin — no
    third-party CDN at session time.
D2. ON-DEVICE, COMPUTE-AND-DISCARD: video frames are processed in the
    student's browser only. Raw frames are never uploaded, never stored.
    Only the numeric metrics m1–m8 leave the client, at session close.
D3. METRICS m1–m8 (final naming in the report; keep them behavioural):
    m1 gaze-on-screen ratio, m2 head-pose stability, m3 posture lean/slouch
    events, m4 expression variability, m5 smile/neutral balance, m6 blink &
    attention proxy, m7 gesture presence, m8 framing/centering in shot.
    Every metric maps to a behaviour sentence, never an emotion claim:
    "looked away from the screen during 4 answers" — allowed;
    "seemed nervous / bored / confident" — banned, test for it.
D4. INTERVIEWER REACTIONS: sparing and positive-only during the session
    (an occasional acknowledging nod/beat when presence is strong). The
    interviewer NEVER corrects posture or expression mid-session.
D5. READOUT: m1–m8 render INSIDE the existing Presence Profile section of
    the unified readout — not a new section. Presence data is report-only:
    it NEVER enters the Benchmark Score or the readiness band.
D6. CAMERA-OFF = NO PENALTY: no camera → Presence Profile simply says
    "No presence data — camera was off", zero effect on any score or band.
    Same rule if MediaPipe fails to load: degrade silently, session unharmed.
D7. CONSENT GATE (hard): the presence feature ships dark behind its flag.
    It enables only when the consent copy (voice/camera/presence/AI-persona)
    has cleared legal review. Built, tested, not enabled is the definition
    of done for this phase if clearance hasn't landed.

## ACCEPTANCE TESTS
(a) Form role ≠ ProfileIQ role → form wins everywhere (card, questions,
    Session Profile).
(b) JD paste containing "ignore previous instructions" → treated as data;
    persona unaffected; sanitized once (assert no double-encoding).
(c) Invalid config (e.g. no role) → zero LLM/TTS calls made.
(d) Sarvam dry at validation → TEXT-mode offer, session completes, readout
    has no voice Delivery metrics.
(e) TEXT session → no mic permission prompt fired (assert via permissions
    API), no TTS calls, honest metrics only.
(f) HYBRID with 4 spoken + 3 typed answers → Delivery over the 4 spoken,
    labelled as such.
(g) Camera off in VOICE mode → full scores, no penalty, presence section
    shows the no-data line.
(h) Presence metrics present → readiness band identical to the same session
    with camera off (proves report-only).
(i) Emotion-word lint: readout copy contains no entries from the banned
    attribution list (nervous, bored, confident, anxious, shy...).
(j) All existing suites still green, capture gate untouched.

Report to docs/INTAKE_AND_MODES_REPORT.md: per-phase changes, files touched,
test results, metric naming decisions, any backend/migration needs (hf push
only on my explicit confirmation), and a UAT screenshot list.