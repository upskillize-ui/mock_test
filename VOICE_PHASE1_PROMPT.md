\# InterviewIQ Voice Phase 1 — TTS Only



You are adding text-to-speech to InterviewIQ (FastAPI + React/Vite, HuggingFace Spaces). Scope is strictly Phase 1 of the voice roadmap: THE INTERVIEWER SPEAKS, THE LEARNER STILL TYPES. No STT, no mic access, no recording, no delivery scoring — those are later phases.



Vendor: Sarvam AI Bulbul TTS. API key is in env var SARVAM\_API\_KEY (never hardcode, never log).



═══════════════════════════════════════════════

PHASE 1 — DISCOVERY

═══════════════════════════════════════════════

Read main.py session endpoints, claude\_client.py, App.jsx InterviewScreen. Read Sarvam's TTS API docs via web access if available; otherwise implement against their documented REST shape (POST https://api.sarvam.ai/text-to-speech, api-subscription-key header, target\_language\_code, speaker, returns base64 audio). Print the plan.



═══════════════════════════════════════════════

PHASE 2 — BACKEND

═══════════════════════════════════════════════

\- New module app/tts.py: async synthesize(text, voice) → audio bytes. Timeout 5s. On any failure return None — TTS failure must NEVER block the interview; the question text always goes out.

\- Config: SARVAM\_API\_KEY, TTS\_ENABLED (default false — feature flag), TTS\_VOICE\_FEMALE / TTS\_VOICE\_MALE (Sarvam speaker ids), TTS\_CACHE\_DIR.

\- Cache: hash(question\_text + voice) → cached audio file; serve repeat questions from cache (greetings and common warm-ups repeat constantly — this cuts vendor spend \~30%).

\- Extend /session/start and /session/turn responses with audio\_url (nullable). Serve audio via GET /session/audio/{hash} with auth. Do not inline base64 in JSON responses (payload bloat).

\- Preprocess text before synthesis: strip markdown, expand BFSI acronyms for pronunciation (CIBIL → "sibil", NPA → "N P A", FOIR → "F O I R", EMI → "E M I", KYC → "K Y C", CAGR → "C A G R", DSCR → "D S C R") via a maintainable dict in tts.py.

\- Voice selection: learner preference stored per user (default female voice), settable via existing settings pattern.

\- Rate/cost guard: TTS calls count against the session, capped at MAX\_ANSWERS\_PER\_SESSION + 5.



═══════════════════════════════════════════════

PHASE 3 — FRONTEND

═══════════════════════════════════════════════

\- Auto-play question audio when a new assistant message with audio\_url arrives. iOS Safari blocks autoplay: unlock audio context on the "Start Interview" button press (play a silent buffer), and if playback still fails show a small tap-to-play affordance instead of an error.

\- Controls in the interview header: mute toggle (session-sticky, persisted in localStorage) and a replay button on the latest question. Inline SVG line icons only (Lucide-style, 1.6px stroke) — speaker, speaker-off, rotate-ccw. No emojis.

\- Subtle teal (#00C4A0) pulse on the interviewer avatar while audio plays.

\- Voice picker in Setup: Female / Male, minimal, brand palette.

\- If audio\_url is null (TTS failed or disabled), UI shows text exactly as today — zero degradation.



═══════════════════════════════════════════════

PHASE 4 — VERIFY \& REPORT

═══════════════════════════════════════════════

\- Unit tests: acronym preprocessing, cache-key stability, graceful None on vendor failure. All green.

\- Backend compiles, frontend builds.

\- Write VOICE\_PHASE1\_REPORT.md: what shipped, cost notes (cache hit expectations), the feature-flag rollout plan (TTS\_ENABLED=true for 10% first), UAT checklist for Haritha including the mobile Safari and acronym pronunciation cases, and known gaps.



Rules: feature-flagged off by default; no STT/mic code whatsoever; never log the API key or learner content; vyom\_ tables untouched.



Begin Phase 1 now.

