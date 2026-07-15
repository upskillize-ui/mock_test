# INTERVIEWIQ_MASTER_ROADMAP.md
# Everything discussed, decided, and pending — one document. (July 2026)

═══════════════════════════════════════════════════════════════
PART A — WHERE THE PRODUCT STANDS
═══════════════════════════════════════════════════════════════
DONE & IN REPO (via Claude Code sprints):
- Meet-style interview room: lobby (single mic+camera consent), interviewer
  tile + name chip, self-view corner tile, control bar, CC captions
  (sentence-synced, overflow fixed structurally), typing always available
- Mic = persistent Meet-style mute toggle (single capture gate)
- Backend: interviewer name adoption (client roster ↔ server persona),
  migration 006 (focus events + presence schema + early_wrap),
  focus-event endpoint, EARLY_WRAP stage-machine transition
- Tab/window focus signals + device policy (camera ladder → early wrap;
  mic-off → unmute-or-type fork); escalation server-side, persisted,
  vocabulary-ban tested (no emotion words, no accusation words)
- 127 backend tests + 9 pose tests green

ASSETS DELIVERED (must exist in frontend/src/):
- interviewers/  → 10 PNGs (6 human, 4 robot), InterviewerCharacter.jsx v4.1
- interviewers/poses/ → Riya's 4 pose PNGs (smile/asking/emphasis/thinking)
- SelfView.jsx · RobotInterviewer.jsx (Nova v2: square shoulders, open
  blazer, white shirt, gold tie, LED waveform mouth)

DECISIONS LOCKED:
- Asha (cartoon human SVG) retired — humans-as-vectors read as laughable
- Riya = free-tier realistic face (poses, no lip-sync, waveform badge)
- Nova = free-tier animated android (true amplitude "lip"-sync via LED)
- LiveAvatar (Lite mode) = premium tier; D-ID = scripted clips + the
  one-time Riya face test ONLY (never live)
- PNGs dropped from git history (HF unblock); ship with frontend, not Space
- ML/CSP: self-host model assets when the detector sprint runs
- No interviewer-mute control; auto-submit on timer expiry (skip ≠ fail)

═══════════════════════════════════════════════════════════════
PART B — THE RUN ORDER (one sprint at a time, report between each)
═══════════════════════════════════════════════════════════════

SPRINT 1 — GO LIVE  → GOLIVE_PHASE_PROMPT.md
  Backend → HF Space (env audit, /health, cold-start mitigation: keep-warm
  ping or always-on tier). Frontend → new Netlify site at
  interview.upskillize.com (VITE_API_BASE, SPA redirects, font link).
  Auth: LMS opens /launch#token=<short-lived JWT> → exchanged server-side
  (fragment, never query string). LMS launch card (EcoPro brand) behind
  ALLOW_STUDENT_ACCESS=false until legal clears.
  YOUR TASKS: create Netlify site; DNS record; run first production
  interview yourself; capture the two original UAT screenshots (Hinglish
  "Heard:" caption + Delivery Profile) on prod.

SPRINT 2 — POSES + NON-VERBAL  → POSES_PHASE_PROMPT.md
  Riya's 4-pose crossfade engine: greeting→smile; speaking→asking;
  amplitude peaks (sustained >0.65, revert <0.4, min 1.5s between)→
  emphasis, so her hands move with her voice; listening/thinking→
  chin-on-hands. Preload all poses; 350–450ms opacity fades; shared
  object-position anchor. Nova wired as roster kind "vectorbot".
  Phase D detector (when it runs): self-hosted MediaPipe assets (CSP),
  metrics m1–m8 incl. expressiveness, smile moments, nod count —
  compute-and-discard, behaviour words only.
  YOUR TASK: say "generate all" and I run the pose-grid pipeline for the
  remaining cast (male + stern variants), slice, and hand you the folder.

SPRINT 3 — PRESENCE (highest realism per rupee)  → ask me for
  PRESENCE_PHASE_PROMPT.md when ready. Contents agreed:
  - sentence-streamed TTS (speak sentence 1 while the rest generates:
    perceived wait ~4s → ~1.5s — the single biggest upgrade)
  - instant acknowledgments: pre-cached Bulbul clips ("Hmm." "Accha."
    "Okay…") played the moment the answer lands
  - listening backchannels: soft "mm-hmm" at natural pauses in long answers
  - barge-in: student speaks → interviewer audio ducks and stops
  - ambience: faint pen/paper sounds after answers (pairs with Riya's pen)

SPRINT 4 — AVATAR PREMIUM TIER  → AVATAR_PHASE_PROMPT.md
  INTEGRATION STEPS (as discussed):
  1. LIVEAVATAR_API_KEY in backend/.env only (done — verify .gitignore)
  2. Backend avatar.py creates the Lite-mode session; browser gets only
     short-lived join credentials, never the key
  3. PRE-FLIGHT in the lobby: create the avatar session during mic check —
     if it fails, lobby offers Standard mode; mid-interview fallback
     becomes a rarity, not a plan
  4. Bulbul audio per turn is ALSO piped to the avatar session (their
     audio-input API — read docs, don't guess transport); our captions/
     timing pipeline unchanged
  5. Tile swaps to the WebRTC stream inside the SAME chrome; Riya poses
     stay mounted-hidden as hot fallback; retry once (~2s) before swapping
  6. Stream starts at FIRST QUESTION, stops at the close (lobby + readout
     burn zero minutes ≈ 15% saved); streamed_seconds tracked per session
  7. Lobby choice: Riya (Standard) | Video Interviewer (Premium), gated by
     AVATAR_TIER_ENABLED + credit balance
  8. Pilot on free credits (≈5-min session cap — use AVATAR_MAX_MINUTES=4
     mini-interviews); report measured latency + cost per interview
  9. If the D-ID Riya face test passed → upload Riya as custom LiveAvatar
     on the paid plan (1,000-credit tier, $100, 20-min sessions) so both
     tiers wear one face
  ECONOMICS: Lite ≈ $0.10/min → ~₹175/20-min interview → premium tier
  priced in credits, never the default. LLM+TTS session today ≈ a few ₹.

═══════════════════════════════════════════════════════════════
PART C — THE AGENT ROADMAP (product suggestions, sequenced)
═══════════════════════════════════════════════════════════════
1. PERSONA SWITCH platform-wide: Student / Fresher / Professional set once
   — InterviewIQ rounds adapt (campus drives / walk-ins / switch +
   salary-negotiation round); TestGen adds APTITUDE mode (TCS NQT /
   Infosys patterns) for freshers
2. AGENT HANDOFF LOOP: debrief gap → TestGen auto-generates practice →
   NudgeAI schedules the (already-produced) 7-day plan → CareerIQ tracks
   band improvement next attempt. One shared career graph
   (get_student_context is the seed). "Your agents talk to each other."
3. GROUP DISCUSSION MODE: 3 AI participants (dominant/quiet/tangent) via
   existing multi-voice TTS + personas — the Indian campus-placement gap
   nobody has filled
4. TPO / PLACEMENT-CELL DASHBOARD: batch readiness distribution, common
   gaps, drive-readiness lists — the institution is the buyer; this is
   what the buyer sees. Pure aggregation of stored data
5. PROFESSIONAL TIER: ProfileIQ → LinkedIn + ATS-keyword match vs pasted
   JD; CareerIQ → switch-path plans; AiRev → real work-sample reviews
6. SHARPENERS: NudgeAI placement-season countdowns; "Communication band"
   packaged from existing delivery metrics
MARKETING (from NxtJob teardown): name the six agents as one career team;
outcome-led proof (readiness-band improvement, calibration delta —
metrics no competitor has); bundle human touch (faculty POP sessions,
Ramesh's guest-lecture offering) for institutions. Avoid their failure:
overpromise + high consumer sticker = Trustpilot backlash; your anti-
flattery scoring is the long-term trust moat.

═══════════════════════════════════════════════════════════════
PART D — THE AMIT BUNDLE (one conversation, six items)
═══════════════════════════════════════════════════════════════
1. LEGAL REVIEW (blocks student launch, nothing else): voice consent,
   camera self-view notice, presence-monitoring line, AI-persona
   disclosure ("your interviewer is an AI persona") — all marked
   [PENDING LEGAL REVIEW] in code
2. DNS record: interview.upskillize.com → Netlify
3. HF Space always-on tier cost (kills mid-interview cold starts)
4. LMS repo name (now optional — subdomain path shipped instead — but
   settle it for the eventual port)
5. Avatar premium-tier pricing → credit system (bring the pilot's
   measured cost number)
6. Sarvam Startup Programme application (TTS credits → free tier cost
   → ~0; the Hinglish voice stage is the showcase they want)

═══════════════════════════════════════════════════════════════
PART E — STANDING RULES (why this build has stayed clean)
═══════════════════════════════════════════════════════════════
- One phase prompt at a time; REPORT file reviewed before the next starts
- Fresh Claude Code session per sprint (never run one at 97% context)
- Nothing student-visible ships with [PENDING LEGAL REVIEW] copy
- Fallbacks are seatbelts: pre-flight so they rarely fire, never remove them
- Skipped ≠ failed; typed = spoken; behaviour words only, never emotions
- Local and prod share one Aiven DB — every local test writes real rows
