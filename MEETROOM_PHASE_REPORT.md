# InterviewIQ — Interview Room Sprint Report

Backend suite **109/109 green**; `vite build` passes. **Not pushed to HF** (per the
maintainer's instruction), though the PNG/LFS blocker is now resolved — see §6.

---

## 0. What I found before writing code (read this first)

Three of the prompt's premises did not match the repo. Two were factual, one would have
shipped a silent production failure.

1. **`pickInterviewer` / the "v4.1 roster" did not exist.** Grepped the whole repo: no
   `pickInterviewer`, no roster, and `InterviewerCharacter.jsx` was the v2 anime-style
   **male-only** component. You then supplied the v4.2 roster module, which I wrote in
   verbatim — except that it imports **six** portraits and only **four** are in the repo
   (`ananya`, `kavya` are missing). An unresolved import is a hard Vite failure, so those
   two roster rows are **commented out** with a one-line re-add each. Drop the PNGs in and
   uncomment to restore the full six.

2. **MediaPipe/tfjs would have been blocked by our own CSP** — this is why Phases C/D are
   deferred (your call). Our production CSP is `script-src 'self'; connect-src 'self'`.
   MediaPipe and tfjs fetch their **WASM runtime and model weights from a CDN at runtime**.
   That is blocked in production, but **works fine in `vite dev`** — so local UAT would
   have passed and the deployed proctoring would have silently done nothing. Same class of
   bug as the hosted-backend 401 and the CSP-killed `/dev/login`. It needs self-hosted
   model assets (or a scoped CSP relaxation) before the detector can ship.

3. **The PNGs were build-critical but not in git.** Last sprint we removed them (HF rejects
   raw binaries). The v4.2 roster now *imports* them, so a fresh clone couldn't build.
   Fixed properly — see §6.

---

## 1. Phase A — Pre-join lobby (`Lobby.jsx`) ✅

- **ONE permission moment.** A single `getUserMedia({audio, video})`, fired only *after*
  our own pre-prompt card explains what each device is for. The browser's permission
  dialog is never the first thing the learner sees.
- **Camera preview** (mirrored) or an **initial-letter tile** when off/denied. Mic +
  camera toggles under the tile.
- **Mic check**: a live level meter from a temporary audio stream — *"Say something — the
  bar should move."* The stream is **torn down before Join**.
- **Never hard-blocks.** Camera denied → continue **mic-only** (we retry audio alone, so a
  camera denial never costs them the mic). Both denied → **type-only join**; the interview
  always happens.
- **Consent** recorded via the existing `recordConsent()` / `CONSENT_COPY_VERSION`:
  `data_processing` always, `voice_recording` if mic, `camera_selfview` if camera. Draft
  copy is marked **`[PENDING LEGAL REVIEW]`** on screen and in code.
- The mid-session `VoiceConsentModal` trigger is gone from the room (consent happens once,
  in the lobby); the component is retained for classic mode.
- **Flow rewired**: Setup → **Lobby** → `/session/start` → Room. The session now starts on
  *Join*, so `camera_at_join` and the roster-picked `interviewer_name` ride along on it.

## 2. Phase B — The room ✅

- **Main tile**: `InterviewerCharacter` (v4.2, unchanged) with a Meet-style **name chip**
  bottom-left (`"Priya · InterviewIQ"`).
- **Corner tile**: student self-view bottom-right (`RoomSelfView`, absorbing SelfView's
  stream logic **and its privacy comments**) with a mic-status dot. Drag was skipped
  deliberately — it added risk for no interview value.
- **Control bar** (centred, Meet-style pills): **mic** (doubles as push-to-talk in the
  auto-listen gaps, preserving tap-to-speak) · **camera** · **CC** · **keyboard** · **End**.
- **CC captions (default ON)**: the interviewer's line is split on sentence boundaries and
  advanced by the audio's own `timeupdate` progress — no extra vendor call, no timestamps
  needed. While idle it shows the whole question, so a muted learner can always read it.
  Font stack includes `'Noto Sans Devanagari'`. The student's `"Heard:"` caption is unchanged.
- **Typing is always available**, on every question, via the keyboard button — it routes
  through the identical answer path. A voice failure also opens it automatically.
- **Voice pipeline untouched**: STT (transcribe-and-discard), TTS + analyser lip-sync,
  silence detection, spoken ratings, Hinglish parsing — all reused, none rewritten.

## 3. Phase C (partial) — Focus monitoring ✅ / ⏸

**Shipped now (`focusMonitor.js`)** — the two signals that need **no camera and no ML**:
- `s4 tab_hidden` (document hidden > 2s), `s5 window_blur` (blurred > 3s).
- Debounced **1 event per signal per 30s** on the client — and **re-applied on the server**,
  which is the authority (a buggy or hostile client cannot spam the ladder).
- Kill switch: **`VITE_FOCUS_MONITOR=off`**.
- These work on **every** join path, including camera-off.

**Deferred (your call): `s1 no_face`, `s2 multiple_faces`, `s3 looking_away`** and all of
**Phase D (presence metrics)** — they need a face model, which is CSP-blocked (§0.2). The
schema for them is already landed (migration 006), so the detector sprint needs no further
migration.

**Escalation ladder (server-side, persisted):**
| Events | Level | Interviewer behaviour |
|---|---|---|
| 1–2 | 1 | ONE calm line asking for full attention. Normal tone. |
| 3–4 | 2 | Direct and professional: in a real panel this would cost you. |
| 5+ | 3 | States plainly it will be reflected in feedback. No scolding. |

The level is injected into the **persona** (migration-005 identity), so the reminder is
phrased by the same improvised interviewer — and it is *prepended* to the turn directive,
so the round plan underneath is **byte-identical**. The ladder changes **tone, never
difficulty or structure** (there's a test asserting exactly that).

## 4. Phase E — Device commitment ✅ (partial)

- **Camera off mid-interview** (only if they *joined* with it on): `camera_off` event →
  server ladder → **nudge** → **warn** → **`wrap`**. On `wrap` the client calls
  `POST /session/wrap`.
- **`EARLY_WRAP` is a server-side, persisted transition** (`stages.early_wrap_transition`):
  stage → `READOUT`, reason + the stage it happened at stored on the session. **A refresh
  cannot dodge it.** Scoring is untouched — the debrief runs over the rounds actually
  completed. **We score what happened and mark what didn't. Nothing is zeroed.**
- **Mic off** → the typing drawer is always right there; typed answers are first-class, so
  the interview stays fully alive.
- ⏸ **Not yet wired**: the 60s camera grace timer and the 90s no-answer abandonment timer.
  The ladder, the wrap endpoint and the persistence are all in place; these two timers are
  the remaining client-side piece.

## 5. Privacy, fairness, honesty — enforced, not just promised

- **Camera frames never leave the browser.** There is no `MediaRecorder` on any video
  track, no canvas capture, no frame upload anywhere in the codebase. The focus endpoint
  accepts **a string and nothing else** — the Pydantic schema *is* the enforcement point,
  and `migration_006` has no column that could hold media. A test asserts the event type
  set is closed (`"frame"`, `"screenshot"` are rejected).
- **A camera-off join is never penalised.** Camera signals are dropped server-side, the
  camera ladder never fires, and the readout **omits camera-based lines entirely**. Tested.
- **The word "cheating" appears nowhere** — not in UI copy, not in the readout, and **not
  even in the prompt**. My first draft of the level-2 directive said *"no accusation of
  cheating"*; my own test caught it, and I removed the word entirely — **naming it in the
  prompt primes the model to echo it.** The vocabulary is "attention" and "presence".
- **No emotion or personality inference**, anywhere. A test bans a list of emotion,
  personality and accusation words across every user-facing string this engine produces.

## 6. The PNG/LFS blocker — resolved

The roster now *imports* the portraits, so they are **build-critical**: a fresh clone (and
the HF Space build) would fail without them. But HF rejects raw binaries.

Because I had already scrubbed the PNGs from history last sprint, I could set up **Git LFS
with no history rewrite**: they are now tracked via `.gitattributes` and committed as
**132-byte pointers** instead of 4 MB blobs. This makes the repo coherent *and*
HF-compatible. **I have not pushed to HF** — that is still your call, but the blocker that
prompted the instruction is gone.

## 7. Migration 006

`db/migration_006_interview_room.sql` (+ rollback). Additive only:
- `vyom_focus_events` — session_id, event_type (enum string), created_at. **Nothing else.**
- `vyom_messages.presence_metrics` JSON — for the deferred Phase D. Derived numbers only.
- `vyom_sessions.early_wrap_reason` / `early_wrap_stage` / `camera_at_join`.

All new backend reads/writes are **defensive**: an un-migrated DB logs a warning and the
room simply runs without the ladder — it never breaks a turn or a session start. (I added
this after the migration-005 identity write caused a real 500 during probing.)

## 8. UAT script

1. **Lobby** — Setup → the green room appears. The consent card is shown *before* any
   browser prompt. "Allow mic & camera" → one permission dialog → preview + the mic bar
   moves when you speak. ✅
2. **Deny camera** → continues **mic-only** with a notice; the mic still works. ✅
3. **Deny everything** → you can still **Join** and do the whole interview by typing. ✅
4. **Room** — interviewer tile with the name chip; your self-view bottom-right with a mic
   dot; the control bar centred below. ✅
5. **The name matches the face.** The chip says e.g. "Priya" and the interviewer introduces
   herself as Priya — the persona adopts the roster's name. ✅
6. **CC** — captions advance sentence-by-sentence as she speaks; toggle off hides them. ✅
7. **Typing** — the keyboard button opens the drawer on *any* question; Send routes
   normally. ✅
8. **Attention ladder** — switch tabs for >2s a couple of times; on the next turn the
   interviewer raises it **once, in her own voice**, then carries on with the same question
   plan. Do it 3–4 times → the tone becomes firmer. ✅
9. **Camera-off ladder** — join with camera on, then turn it off: nudge → warn → the
   interview wraps early and goes to the readout. Refreshing does **not** resume it. ✅
10. **Camera-off join** — join with camera off: no camera nudges ever fire, and the readout
    shows **no** camera-based presence lines. ✅
11. **`VITE_FOCUS_MONITOR=off`** → no events at all. ✅

## 9. Known gaps

- **Phase C camera signals + Phase D presence metrics** are deferred pending the model-asset
  decision (§0.2). Migration + readout schema are already in place for them.
- **The 60s camera grace and 90s abandonment timers** (Phase E) are not wired yet; the
  ladder and wrap plumbing are.
- **Two roster portraits missing** (`ananya`, `kavya`) — rows commented out.
- **Endpoint path**: I used `/session/focus-event`, not `/api/session/{id}/focus-event`.
  Every existing route is `/session/...` and the SPA catch-all whitelists that prefix; an
  `/api/...` path would have fallen through to the SPA and served `index.html` instead of a
  404. Flagging in case the `/api` prefix was deliberate.
- **Lobby fallbacks are not unit-tested** — there is no JS test runner configured in this
  repo. They're covered by the UAT script above. Worth adding Vitest if we want them pinned.
