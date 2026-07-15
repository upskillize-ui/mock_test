# GOLIVE_LMS_AMENDMENT.md — supersedes Stages 2–3 of GOLIVE_PHASE_PROMPT.md
# Decision (founder): NO separate hosting. Students access InterviewIQ only
# through lms.upskillize.com. The interview app ships INSIDE the LMS deploy
# at the path /interview. Stage 1 (backend → HF) is unchanged.

## STAGE 2 (revised) — the interview app inside the LMS build
Precondition: the LMS repo is available locally; the maintainer provides
its path. Work happens in BOTH repos; ask before every cross-repo write.

Approach — keep InterviewIQ as its own Vite app, co-built into the LMS
publish directory (do NOT attempt to merge it into the LMS's component
tree in this sprint; that entanglement is a later refactor if ever):
1. Copy vyom_build/frontend into the LMS repo as apps/interview/ (git
   history not needed; the source of truth for interview code remains
   vyom_build — add a README in apps/interview saying exactly that, with
   the sync rule: changes flow vyom_build → LMS via copy, never edited
   in place here).
2. Vite config: base '/interview/'. Fix any absolute asset paths.
3. LMS build pipeline: after the LMS's own build, run the interview
   app's build and place its dist at <publish>/interview/. Netlify SPA
   redirects: /interview/* → /interview/index.html 200 (BEFORE the LMS's
   own /* catch-all).
4. Pose/portrait PNGs ride the LMS repo — confirm its LFS/size policy
   first; if the LMS repo has no LFS, plain-add is acceptable (Netlify
   doesn't care) but flag repo-size growth in the report.
5. Env: VITE_API_BASE=<HF Space URL> set in the LMS site's Netlify env.

## STAGE 2b — auth, now same-origin (simpler than the old plan)
The fragment-token handoff is retired. Same origin means:
- The interview app reads the LMS session JWT from wherever the LMS
  stores it (inspect the LMS auth code for the exact key/shape — do not
  guess) and presents it to the backend.
- Backend /auth/exchange validates the LMS JWT (audience/issuer/expiry)
  and issues the interview session token as today. CORS allowlist
  collapses to https://lms.upskillize.com (+ localhost for dev).
- No LMS token found → the "Please log in to your LMS" screen with a
  link to the LMS login — never a broken app.
- /dev/login remains dev-only, verified off in prod env (unchanged).

## STAGE 3 (revised) — the launch card
Same EcoPro-branded card in the student dashboard, but its action is now
just a navigation to /interview (same tab is fine — it's the same site).
Still behind ALLOW_STUDENT_ACCESS=false server-side; the card itself can
render for staff roles only until launch, per the LMS's existing role
system (inspect, don't invent).

## What this changes elsewhere
- The LMS site's Netlify deploy now builds two apps: note the build-time
  increase in the report.
- Interview releases ship via LMS deploys: document the release steps
  (copy from vyom_build → commit LMS → Netlify auto-deploy) in the README
  from step 1.
- GOLIVE definition-of-LIVE updates: a staff account on
  lms.upskillize.com clicks the card and completes a full voice interview
  at lms.upskillize.com/interview on production infrastructure.

## If the LMS repo is NOT available yet
Stage 1 (backend → HF, env audit, health check, cold-start mitigation)
executes now regardless. Stages 2–3 wait for repo access — produce
LMS_PORT_CHECKLIST.md capturing everything above as a ready-to-run plan,
so the port is a same-day job once the repo lands.
