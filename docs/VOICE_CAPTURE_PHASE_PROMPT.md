# VOICE_CAPTURE_PHASE_PROMPT.md — voice input, turn-taking, lobby fixes
# The product's ears. Prod bugs with screenshot evidence included.
# Rules: commit to origin as you go; NEVER push hf without explicit
# confirmation (list backend changes in report as pending). All suites stay
# green incl. 22 Critical guardrails + capture-gate mutation test. Runs in
# the LMS embed (~1100-1400px container). Brand: navy/gold/teal, Plus
# Jakarta Sans, DM Mono for data, no emojis on the interview surface.
# GLOBAL COPY RULE: every user-facing string proofread — no redundancy, no
# grammar/spelling errors, tone matched to context. GLOBAL LAYOUT RULE:
# consistent spacing rhythm, zero overflow, nothing clipped at any width.

1. UNMUTE MUST ARM CAPTURE (prod bug): LISTENING state must engage whenever
   ALL are true — question open, student unmuted, interviewer audio finished
   — regardless of the order they became true. Today unmuting mid-question
   leaves READY and the recorder never arms. Fix the state machine; keep the
   capture-gate invariant. Tests: unmute-before-question, unmute-mid-
   question, unmute-during-reask → all reach LISTENING. While muted during
   an open question, UI actively points at the mic button ("You're muted —
   tap the mic to answer").
2. NO AUDIO BEFORE JOIN (prod bug): on the "Ready to join?" pre-flight, no
   session brain, no question generation, no TTS playback may start until
   Join is pressed. Backend may pre-warm connections silently; nothing
   audible or stateful.
3. INSTRUMENT EVERY ANSWER: log client+server per attempt: granted
   MediaTrackSettings, audio RMS/peak, capture duration, bytes sent, STT
   status, transcript length+confidence, and per-hop turn latency
   (capture→STT→LLM→TTS→playback). One line per answer; future audio
   complaints must be diagnosable from logs alone.
4. CAPTURE QUALITY: getUserMedia with echoCancellation, noiseSuppression,
   autoGainControl true; log when refused; match Saarika's preferred sample
   rate/encoding. Near-zero RMS on a full answer → the re-ask says WHY:
   "Your mic seems very quiet — come closer, or type your answer."
5. PRE-FLIGHT MIC CHECK: on the pre-flight screen — live input level bar +
   5-second test line, then "We heard: '<transcript>'. Sound right?"
   [Sounds right / Try again / Switch to typing]. Also measures noise
   floor: too noisy → "Your surroundings are quite noisy — a quieter spot
   will help the interviewer hear you." Skipped appropriately in Text mode.
6. LIVE SELF-CAPTIONS: while the student speaks, a "You:" line shows the
   running transcript (chunked partials fine, streamed if supported).
   Verbatim — never beautified. DM Mono, visually distinct from the
   interviewer's captions.
7. TURN-TAKING BY SILENCE: student spoke ≥2s then silent ~1.8-2.5s →
   end-of-answer: auto-submit, interviewer responds. Latency targets:
   LISTENING arms instantly; ack clip ("Hmm/Accha", already warmed) within
   ~1s of end-of-speech; full response starts ~2-3s (fast-start). The
   per-question timer becomes an INVISIBLE failsafe — existing expiry
   ladder unchanged (auto-submit partial / skip empty / EARLY_WRAP) — its
   chip surfaces only in the final 30s or when no speech detected at all.
   Barge-in and typing unchanged.
8. NOISE COACHING IN-SESSION: repeated low-confidence transcripts while
   speech is clearly present → interviewer says once, in persona: "There's
   a lot of noise on your end — move somewhere quieter if you can, or type
   your answers." Environment NEVER affects scores.
9. STT-NOISE-PROOF SCORING: transcripts are speech — the scorer never
   penalizes spelling/punctuation/word-garble plausibly from STT; judges
   content, structure, specifics. Indian English is the standard, never
   flagged. Readout quotes lightly cleaned for readability, meaning never
   altered.
10. LOBBY FIXES: (a) DIFFICULTY = ONE row of four equal chips (Easy/
    Realistic/Stretch/Critical); Critical is a chip (red dot + "Pressure
    panel" subtext); its full warning copy appears below the row ONLY when
    selected; chips may wrap 2×2 under ~700px. (b) Relabel the "MODE"
    heading to "FEEDBACK" — Interview/Coach options and behaviour fully
    unchanged, heading text only. (c) Lobby renders instantly without
    waiting on the backend; fire a warm-up /health ping on page load;
    show "connecting to your interviewer…" only where true.
11. RANGE GUIDANCE COPY in pre-flight: "Best within arm's reach of your
    mic, in a quiet room."

Report to docs/VOICE_CAPTURE_REPORT.md: per-item changes, instrumentation
log format, granted mic settings on Chrome/Windows, measured turn latency
per hop, backend changes with hf push pending my explicit confirmation.