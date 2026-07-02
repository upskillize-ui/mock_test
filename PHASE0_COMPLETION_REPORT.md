# InterviewIQ — Phase 0 Completion Report (INT-06 + INT-07)

**Audience:** business / product (plain English).
**Scope:** the final two tickets of the Phase 0 spec-alignment work.
**Status:** both tickets built, unit-tested, and building cleanly (backend imports, frontend `vite build` succeeds). Nothing in this sprint touches the interview scoring, bands, or calibration shipped previously.

---

## 1. What shipped

### INT-06 — Your interview survives a page refresh
Until now, if a learner hit refresh (or their laptop slept, or the tab crashed) mid-interview, the whole session was lost — they had to start over. That is fixed.

- The browser now remembers the active session (its ID, the setup choices, and the start time).
- On reopening the app, InterviewIQ checks with the server and puts the learner back exactly where they were:
  - **Still going** → dropped straight back into the interview, with the full conversation visible and the countdown timer showing the correct remaining time (not reset).
  - **Left open too long (idle > 30 minutes)** → a friendly choice: *"You have an unfinished interview. Resume or start fresh?"*
  - **Already finished** → taken to their results (debrief), never a broken half-interview.
  - **Session no longer exists** → the stale pointer is quietly cleared and they start fresh.
- If the learner was on the "rate your confidence" step when they refreshed, that rating widget comes right back — they don't lose their place.
- The server remains the single source of truth. A second browser or incognito window cannot hijack a session: the "resume" data lives only in the learner's own browser, and every server check is tied to the logged-in account.

### INT-07 — DPDPA technical foundation
This builds the *machinery* for India's Digital Personal Data Protection Act. The **legal wording and the final retention periods are deliberately left for Legal to sign off** — everywhere copy is shown to a learner it is clearly marked as a draft.

- **Consent is now recorded.** At the first interview start, the learner sees a short (draft) notice and must accept it to begin. We store *which version of the wording* they agreed to, so there is a clean audit trail.
- **Voice consent gate is pre-built but switched off.** Voice mode is not part of this sprint. The check that "a voice session needs recorded voice consent" exists in code but is disabled behind a feature flag (`VOICE_ENABLED=false`). It turns on the day voice ships — no rework needed.
- **Learners can download all their data** (Settings → Your data → *Download my data*): sessions, transcripts, confidence ratings, reports, and consents, as a single JSON file.
- **Learners can delete all their data** (Settings → *Delete my data*), with a deliberate two-step confirmation so it can't happen by accident. Deletion hides everything immediately; it is permanently erased after a short recovery window.
- **Automatic clean-up (retention).** A purge job removes old transcripts and reports on a schedule, and finishes erasing deleted accounts after the grace window — so we don't hold personal data longer than the (to-be-confirmed) policy allows.
- **Logs no longer carry personal data.** Every logging line was audited; the two places that could echo learner answers were changed to log only diagnostics, and a safety net now masks any email/phone number before it can be written to a log.

---

## 2. New database objects (migration 003)

Run `db/migration_003_dpdpa_foundation.sql` once against the Aiven MySQL database. It:

| Object | What it is |
|---|---|
| **`vyom_consents`** (new table) | One row per consent grant: `user_id`, optional `session_id`, `consent_type`, `copy_version`, `granted_at`. A consent record deliberately survives a transcript purge (audit proof). |
| **`vyom_sessions.deleted_at`** (new column) | Marks a soft-deleted session. Empty = live; timestamp = scheduled for erasure. |

No existing `vyom_` table was renamed or dropped. (Consistent with the existing pattern, migrations 001/002/003 layer on top of `schema.sql`.)

---

## 3. New / changed API endpoints

| Method & path | Purpose |
|---|---|
| `GET /session/{id}/messages` | INT-06: full transcript of an active session, for resume. Auth-guarded. |
| `GET /session/{id}/state` *(extended)* | Now also returns `status`, `started_at`, and a `stale` flag so the app can resume correctly. |
| `POST /consent` | Record a consent grant (`consent_type`, `copy_version`). |
| `GET /me/data` | Download everything held for the logged-in learner as JSON. |
| `POST /me/data/delete-request` | Step 1 of deletion — issues a short-lived confirmation token. Deletes nothing. |
| `DELETE /me/data` | Step 2 — verifies the token, then soft-deletes immediately. |
| `POST /admin/purge` | Retention clean-up job. Protected by an admin token; intended to be called by a scheduler/cron. |

All learner-facing read paths (history, stats, session load) now ignore soft-deleted data, so a deleted account genuinely sees nothing.

---

## 4. What still needs LEGAL / product sign-off

These are intentionally **not guessed** — they need a decision:

1. **Consent copy wording.** The notice shown at session start and the Settings copy are placeholders, marked `[PENDING LEGAL REVIEW]` in the code, and stored under `copy_version="v0-draft"`. When Legal finalises wording, update the copy and bump the version string (e.g. `v1`).
2. **Retention windows.** Current defaults: transcripts **90 days**, debriefs/reports **365 days**, deleted-account recovery grace **30 days**. These are configurable via environment variables but need a formal policy sign-off before go-live.
3. **Is consent mandatory to use the product at all?** Current build: yes — the learner must accept the notice before the first interview can start. Confirm this is the desired stance for text mode.
4. **Consent scope.** Today one consent row is recorded at first start per browser. Product to confirm whether we also want a server-side "already consented" lookup (e.g. so a returning learner on a new device isn't re-shown the notice), and whether consent should be re-collected when the copy version changes.
5. **Who runs the purge, and how often?** We built `/admin/purge` (call it from a cron/scheduler) rather than an always-on in-process timer, because the hosting containers restart and an external schedule is more reliable. Ops to decide cadence (nightly recommended) and wire the scheduler.

---

## 5. UAT checklist (for Haritha)

**INT-06 — refresh resilience**
- [ ] Start an interview, answer 3 questions, press **F5** → you land back mid-interview on the next question, with all previous messages visible and the timer showing the *correct* remaining time.
- [ ] Refresh while the "rate your confidence" widget is on screen → the widget is still there afterwards.
- [ ] Finish an interview (reach the report), then refresh → you see the **report**, not a broken interview.
- [ ] Leave an interview open, wait past the idle window, refresh → you get the **"Resume or start fresh?"** prompt; both buttons work.
- [ ] Log into the **same account in a second browser / incognito** → it does **not** silently jump into the first browser's live session.

**INT-07 — data rights & consent**
- [ ] On a brand-new browser, the consent notice appears at setup and **Start Interview is disabled** until you accept it.
- [ ] Settings → **Download my data** produces a JSON file containing your sessions, messages, ratings, debriefs, and consents.
- [ ] Settings → **Delete my data** → confirm → you are told it's deleted, and afterwards **History shows nothing** for that account.
- [ ] (Ops-assisted) After deletion, the account cannot see its old data anywhere in the app.

**Automated checks already passing**
- Backend stage/band/calibration tests: `python backend/tests/test_stages.py` → 6/6.
- New Phase 0 logic tests (staleness, retention math, consent gate, log redaction): `python backend/tests/test_phase0.py` → 12/12.

---

## 6. Deployment steps

1. **Database:** run the new migration against Aiven MySQL:
   `db/migration_003_dpdpa_foundation.sql` (adds `vyom_consents` + `vyom_sessions.deleted_at`).
   (Assumes migrations 001 and 002 were already applied.)
2. **Backend environment variables** (all have safe defaults except the admin token):
   - `ADMIN_TOKEN` — **required to enable purge.** If unset, `/admin/purge` safely refuses (401). Set a strong secret.
   - `TRANSCRIPT_RETENTION_DAYS` (default 90), `DEBRIEF_RETENTION_DAYS` (default 365), `DELETE_GRACE_DAYS` (default 30), `SESSION_IDLE_MINUTES` (default 30) — override once Legal confirms the policy.
   - `VOICE_ENABLED` — leave `false` (default) for this sprint.
3. **Deploy backend** (FastAPI) and **rebuild/deploy frontend** (`npm run build` in `frontend/`, then ship `dist/`). No new backend Python packages were added (`jose` was already a dependency).
4. **Schedule the purge:** add a nightly cron / scheduled task that calls
   `POST /admin/purge` with header `X-Admin-Token: <ADMIN_TOKEN>`.
5. **Smoke test** with the UAT checklist above.

---

## 7. Guardrails honoured
No `vyom_` table renamed. No speech-to-text / text-to-speech code added. No punitive copy. Brand palette used for the new UI (Settings, resume prompt, consent notice). Any decision needing product judgment is listed in section 4 rather than guessed.
