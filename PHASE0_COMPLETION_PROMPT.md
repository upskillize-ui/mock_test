\# InterviewIQ Phase 0 Completion — INT-06 + INT-07 Technical Foundation



You are completing the final two tickets of the Phase 0 spec-alignment work in the InterviewIQ codebase (FastAPI backend + React/Vite frontend, Aiven MySQL, HuggingFace Spaces). The four spec tickets (INT-01/02/03/04) shipped in the previous sprint — do not modify that work except where these tickets require it.



Two tickets, in order. Print a one-line status after each phase.



═══════════════════════════════════════════════

PHASE 1 — DISCOVERY

═══════════════════════════════════════════════

Read the current session flow (main.py, stages.py, App.jsx), the vyom\_sessions schema including the new stage columns, and the existing consent/retention state (there is none — the audit confirmed DPDPA is Red). Print a short plan.



═══════════════════════════════════════════════

PHASE 2 — INT-06 · Session survives page refresh

═══════════════════════════════════════════════

Backend:

\- The state machine already persists everything server-side (current\_stage, round\_index, awaiting\_rating, last\_answer\_id). Verify GET /session/{id}/state returns everything the frontend needs to resume.

\- Add GET /session/{id}/messages returning the full message history for an active session (auth: session must belong to the requesting user).

\- Add a resumable check: sessions idle > 30 minutes (last message timestamp) return state with a "stale": true flag.



Frontend:

\- Persist session\_id + config in localStorage the moment a session starts (key: interviewiq\_active\_session).

\- On app load, if that key exists: call /session/{id}/state. If active and not stale → restore InterviewScreen with fetched message history, correct stage header, correct timer remaining (persist started\_at, compute remaining client-side). If stale → show a resume-or-restart prompt: "You have an unfinished interview. Resume or start fresh?" If DONE/READOUT → route to the debrief. If 404 → clear the key silently.

\- Clear the key on session end, abandon, or restart.

\- The awaiting\_rating state must also survive refresh: if state says awaiting\_rating, show the rating widget immediately on restore.



Acceptance:

\- Start session, answer 3 questions, F5 → learner lands back mid-interview on question 4 with history visible.

\- Refresh while rating widget is showing → widget still showing.

\- Refresh after session end → debrief, not a broken interview.

\- Second browser/incognito with same account does not hijack the session (state fetch is auth-guarded).



═══════════════════════════════════════════════

PHASE 3 — INT-07 · DPDPA technical foundation

═══════════════════════════════════════════════

Legal copy review happens outside this sprint — build the machinery with placeholder copy marked clearly as \[PENDING LEGAL REVIEW].



Backend:

\- Migration 003: add vyom\_consents table (user\_id, session\_id, consent\_type, copy\_version, granted\_at); add retention config (TRANSCRIPT\_RETENTION\_DAYS=90, DEBRIEF\_RETENTION\_DAYS=365 in config.py, env-overridable).

\- Consent recording: POST /consent with {consent\_type, copy\_version}; session start for any future voice mode will require an active consent row (build the check, gate it behind a feature flag VOICE\_ENABLED=false for now).

\- Nightly purge job (APScheduler or a simple /admin/purge endpoint callable by cron): hard-delete vyom\_messages older than TRANSCRIPT\_RETENTION\_DAYS for completed sessions; keep debriefs until DEBRIEF\_RETENTION\_DAYS.

\- GET /me/data: returns all data held for the requesting user (sessions, messages, ratings, debriefs, consents) as JSON.

\- DELETE /me/data: soft-delete (deleted\_at timestamp) immediately, hard-delete after 30 days via the purge job. Confirmation token required (two-step: request → confirm).

\- PII redaction: audit every logger call; ensure no learner message content, name, or email is written to logs. Redact at log-write.



Frontend:

\- Settings → "Your data" section: Download my data (calls /me/data, saves JSON), Delete my data (two-step confirm with explicit copy).

\- Placeholder consent copy displayed at first session start, marked \[PENDING LEGAL REVIEW] in a code comment, stored with copy\_version="v0-draft".



Acceptance:

\- /me/data returns complete JSON for a test user.

\- Delete flow soft-deletes and the user can no longer log in to see old data.

\- Purge respects retention windows (unit test with mocked dates).

\- Grep of logging calls shows zero raw learner content.



═══════════════════════════════════════════════

PHASE 4 — VERIFY \& REPORT

═══════════════════════════════════════════════

\- Extend tests/test\_stages.py or add test\_phase0.py: staleness check, retention-window math, consent-gate logic. All tests green.

\- Backend compiles, frontend vite build succeeds.

\- Write PHASE0\_COMPLETION\_REPORT.md in the project root (plain English, business-analyst reader): what shipped, new tables/endpoints, what still needs LEGAL (the consent copy, the retention windows sign-off), UAT checklist for Haritha, deploy steps including migration 003.



Rules: never rename vyom\_ tables, no STT/TTS code in this sprint, no punitive copy, no emojis, brand palette only if UI is touched. If a decision requires product judgment, list it in the report — do not guess.



Begin Phase 1 now.

