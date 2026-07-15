# GOLIVE_PHASE_PROMPT.md — InterviewIQ: local → production → LMS
# ⚠ READ WITH docs/GOLIVE_LMS_AMENDMENT.md — it SUPERSEDES Stages 2–3
# (founder decision: no separate hosting; the app ships inside the LMS
# at lms.upskillize.com/interview). Stage 1 and Stage 4 apply as written.
# Run in a FRESH Claude Code session (previous one is at 97% context).
# Goal: everything built so far running in production, reachable from the
# LMS — deployed fully, gated for students until legal sign-off.

## Ground rules
- Nothing student-visible ships with copy still marked [PENDING LEGAL
  REVIEW]. Deploy behind ALLOW_STUDENT_ACCESS=false (server-checked flag);
  staff/UAT access only until the maintainer flips it.
- The shared Aiven DB serves local AND prod. Never run destructive
  migrations casually; verify 006 is applied before the backend deploy.
- Dev conveniences MUST be dead in prod: /dev/login returns 404 unless
  DEV_LOGIN=true; session-cap bypass off; CORS locked to the real origins.

## STAGE 1 — Backend live (HF Space)
1. Confirm the PNG/git-history cleanup (chosen: drop from history) is
   complete on both remotes' expectations; interviewer PNGs stay
   gitignored in this repo (they ship with the frontend, not the Space).
2. Env audit for the Space: DATABASE_URL, SARVAM key, LLM key,
   DEV_LOGIN unset, ALLOW_STUDENT_ACCESS=false, CORS_ORIGINS=
   https://interview.upskillize.com,https://lms.upskillize.com.
3. Push to hf, watch the build, hit /health (add one if missing: returns
   version + db-ping) from outside.
4. COLD START reality: free/basic HF Spaces sleep; first request after
   idle can take 30–60s — mid-interview that's fatal. Mitigate now:
   document the Space hardware tier, and add a lightweight keep-warm ping
   (scheduled GET /health every 10 min) or recommend the always-on tier
   to the maintainer with its monthly cost.

## STAGE 2 — Frontend live (own Netlify site, fastest path to students)
1. New Netlify site from this repo, base=frontend, build=npm run build,
   publish=frontend/dist. Custom domain interview.upskillize.com
   (maintainer adds the DNS record in the same place upskillize.com is
   managed).
2. Env: VITE_API_BASE=<the HF Space URL>. Remove every hardcoded
   localhost:8000.
3. Auth handoff (replaces /dev/login): the LMS opens
   interview.upskillize.com/launch#token=<short-lived JWT>. The app reads
   the fragment (never query string — fragments don't hit server logs),
   exchanges it at POST /auth/exchange for the session JWT, stores it,
   strips the fragment from history. Direct visits without a token see a
   clean "Please open InterviewIQ from your LMS dashboard" screen with a
   link to lms.upskillize.com — never a broken app.
   (This is the successor to the old cross-origin localStorage bug —
   token travels explicitly, nothing assumes a shared origin.)
4. SPA redirects (netlify.toml /* → /index.html 200), and the Noto Sans
   Devanagari font link verified in the built index.html.

## STAGE 3 — The LMS launch card
In the LMS student dashboard, add an "AI Mock Interview — InterviewIQ"
card (EcoPro brand: navy/gold, Lucide-style icon, "Industry-Validated"
framing) whose click: requests the short-lived launch token from the LMS
backend, then opens interview.upskillize.com/launch#token=... in a new
tab. Behind the same ALLOW_STUDENT_ACCESS flag → staff see it now,
students the day it flips. If this repo doesn't contain the LMS code,
output LMS_CARD_SNIPPET.md with the exact component + endpoint spec for
the maintainer to apply in the LMS repo.

## STAGE 4 — Production hygiene (same sprint, not later)
- Error visibility: minimal client error reporting (console capture →
  backend log endpoint) so broken student sessions are diagnosable.
- Session caps ON in prod (the dev bypass must not leak).
- Smoke script: scripted run-through — launch token → lobby → 2 questions
  (one voice, one typed) → early End → readout renders. Runs against prod
  URLs; document it in the report.
- MEETROOM tasks left open in the tracker: finish or explicitly de-scope
  each in the report — nothing silently half-shipped.

## Definition of LIVE
A staff account, from lms.upskillize.com on a normal laptop + phone,
completes a full voice interview on production infrastructure with no
local processes running — captions, poses, readout, all of it. Then the
report: GOLIVE_REPORT.md with URLs, env matrix, flag states, cold-start
mitigation chosen, and the exact one-line change that later flips student
access.
