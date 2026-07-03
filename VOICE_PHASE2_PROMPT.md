\# InterviewIQ Voice Phase 2 — STT for the Behavioural Round



You are adding speech-to-text to InterviewIQ (FastAPI + React/Vite, Sarvam AI vendor, TTS Phase 1 already shipped). Scope: THE LEARNER SPEAKS THEIR ANSWERS — in the BEHAVIOURAL round only. All other rounds stay typed. No delivery scoring yet (that is Phase 3).



Hard rules:

\- Feature-flagged: STT\_ENABLED default false. Additionally gated by the existing consent machinery — a session may only use STT if VOICE\_ENABLED is true AND the user has a vyom\_consents row with consent\_type='voice\_recording'. Both gates already exist from INT-07; wire them, do not rebuild them.

\- DO NOT STORE RAW AUDIO in v1. Transcribe and discard immediately — audio bytes never touch disk or DB. Only the text transcript is persisted (as a normal vyom\_messages row). This keeps the DPDPA surface minimal; recording playback is a Phase 3 decision.

\- Never log audio content, transcripts, or the API key.

\- vyom\_ tables untouched except normal message inserts.



═══════════════════════════════════════════════

PHASE 1 — DISCOVERY

═══════════════════════════════════════════════

Read main.py session flow, stages.py, tts.py (reuse its Sarvam client patterns), App.jsx InterviewScreen, and the consent gate in main.py. Check Sarvam Saarika STT docs via web access if available; otherwise implement against their documented REST batch shape (POST speech-to-text, api-subscription-key header, audio file upload, language auto-detect or en-IN, Hinglish supported). Print the plan.



═══════════════════════════════════════════════

PHASE 2 — BACKEND

═══════════════════════════════════════════════

\- New module app/stt.py: async transcribe(audio\_bytes, mime) → transcript text or None. 15s timeout. On any failure return None — the learner falls back to typing, never a dead end.

\- Batch, not streaming: the browser records the full answer, uploads once, gets the transcript back. (Streaming WebSocket is a Phase 3 upgrade — batch is more robust for v1 and campus WiFi.)

\- New endpoint POST /session/stt with multipart audio upload. Auth-guarded. Validates: session belongs to user, current\_stage is BEHAVIOURAL, consent row exists, STT\_ENABLED true. Size cap 10 MB, duration implicitly capped by the answer flow. Returns { transcript } — it does NOT submit the turn; the learner reviews/edits the transcript before sending.

\- Cost guard: STT calls capped per session at the behavioural question count + 3 retries.

\- Config: STT\_ENABLED, STT\_MODEL, STT\_LANGUAGE (default auto/en-IN), reuse SARVAM\_API\_KEY.



═══════════════════════════════════════════════

PHASE 3 — FRONTEND

═══════════════════════════════════════════════

\- In the BEHAVIOURAL round only (state.current\_stage === 'BEHAVIOURAL'), when STT is available (flag + consent), show a mic button beside the text input. Tap to record (MediaRecorder API), tap again to stop. Recording state: orange pulse ring on the mic, elapsed timer in DM Mono. Max 3 minutes per recording, auto-stop.

\- On stop: upload to /session/stt, show a subtle "Transcribing…" shimmer, then INSERT THE TRANSCRIPT INTO THE TEXT INPUT — editable. The learner reviews, fixes anything, and presses Send as normal. Speech assists typing; it does not bypass review.

\- Mic permission denied, STT failure, or null transcript → toast "Voice input unavailable — please type your answer" and normal typing continues. Zero degradation.

\- Consent modal on first mic use per session: existing POST /consent with consent\_type='voice\_recording', copy\_version='v0-draft', copy clearly marked \[PENDING LEGAL REVIEW] in a code comment. Modal copy (draft): "InterviewIQ will convert your spoken answer to text. Your audio is transcribed and immediately discarded — it is never stored. Only the text of your answer is saved, exactly as if you had typed it."

\- Brand rules: mic/stop/waveform icons inline Lucide-style SVG 1.6px stroke; navy #0B1628 base, orange #E8521A recording state, teal #00C4A0 success states; Plus Jakarta Sans UI text, DM Mono timer. No emojis.



═══════════════════════════════════════════════

PHASE 4 — VERIFY \& REPORT

═══════════════════════════════════════════════

\- Unit tests: consent gate logic, stage restriction (STT rejected outside BEHAVIOURAL), size cap, graceful None. Full backend suite green.

\- Backend imports, routes register, vite build succeeds.

\- Write VOICE\_PHASE2\_REPORT.md: what shipped, the no-audio-storage design decision and why it minimises DPDPA exposure, cost per behavioural round estimate, activation checklist (flags + consent copy from legal), UAT script for Haritha including Hinglish answers, mic-deny fallback, mid-recording refresh, and known gaps.



If any decision needs product judgment, list it in the report — do not guess.



Begin Phase 1 now.

