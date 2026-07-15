# ROOM_EMBED_FIXUP_REPORT.md

Surgical fixes for the embedded meet room (serves same-origin inside the LMS shell at
`lms.upskillize.com/student/mock-interview`, an embed of `/interview/`). Target container
~1100–1400px wide. All items landed as separate commits on `main`; the frontend suite is
green (61 tests, incl. the 22 Critical guardrails and the capture-gate mutation checks) and
the backend suite is green (244 tests). Items 1–4 are frontend-only; item 5 is backend and
ships to the Space via an **hf push that is pending your confirmation** (not pushed).

## Commits (in order)

| Item | Commit | Summary |
|------|--------|---------|
| 1 | `040d69e` | Room fits its container: kill the negative-margin breakout (no h-scroll) |
| 1b | _this commit_ | App-wide: remove the same breakout from Setup / History / Settings |
| 2 + 3 | `5c893ad` | Readout is one report: merge the verdict, and stop scoring no-shows |
| 4 | `b689f02` | Embedded audio seatbelt: unlock on gesture, never fail a play() silently |
| 5 | `77d8b31` | Startup survives a dead TTS account: hard-bounded warming, captions carry on |

(Items 2 and 3 are the same `DebriefScreen` rewrite and are inseparable in one file, so they
share a commit. Both are covered below. Item 5 is backend — see the hf note at the end.)

---

## Item 1 — Responsive fit (no horizontal overflow)

**Root cause.** `index.css` gives `#root` no padding, but every screen used
`margin:-24px -28px` to "break out" of a padded outer shell that the LMS embed (and the
current standalone app) does not provide. With no parent padding, that negative margin made
the room **56px wider than the viewport** (the horizontal scrollbar; the clipped "You're
muted" pill and End button) and pulled the HUD's top 24px off-screen. The room also
hard-coded `height:calc(100vh - 70px)` for a 70px outer header the embed doesn't have.

**Change.** The interview-room root (`InterviewScreen`, App.jsx ~2753) now lays out to its
container: `width:100%`, `height:100%`, `box-sizing:border-box`, `overflow-x:hidden`. The
HUD, stage, and control bar already flex/wrap, so once the root stops overflowing they fit at
any width; the interviewer tile stays centred and the self-view stays docked.

**Files touched:** `frontend/src/App.jsx` (one line).

**Verified** in headless Chrome at **1100, 1280, 1920** with a static harness built from the
app's real CSS: `document.scrollWidth === clientWidth` at every width (no h-scroll), control
bar + End + muted pill + docked self-view all visible.

**App-wide follow-up (done — commit `see table`):** the *same* negative-margin breakout was
removed from every remaining screen that shares it — the Setup screen (and its "Preparing…"
loading state), History, History Detail, and Settings (App.jsx: 5 sites). Each now lays out to
its container (`width:100%; box-sizing:border-box`, existing padding kept; Settings keeps its
`max-width:720` and is now centred). So the whole embedded app — not just the room and readout
— is free of the horizontal scrollbar. Verified with a representative content-screen harness
(navy header + grids + long-title list rows) at 1100px: `scrollWidth === clientWidth`, long
row titles wrap rather than overflow. The live screens still warrant a UAT glance since they
can't be driven here without the backend, but the container mechanism is identical to the
room fix above.

---

## Item 2 — One readout, not two

**Before.** `DebriefScreen` read as two stacked reports: the narrative
(what-went-well → Delivery → Presence → fixes), then a legacy scorecard restating the verdict
as a band block, a **separate** `/10` tile row, and a **standalone** `CalibrationBlock` card.

**After.** The verdict is stated **once**, in a single Readiness block, in the required order:
what-went-well → Delivery → Presence → fixes → **readiness band + per-round pills +
calibration delta**, with the competency `/10` tiles folded into that same block. The separate
tile row and the `CalibrationBlock` component were removed (its logic is inlined). Band pill
colours are the unchanged locked brand semantics (`BAND_STYLE`): **Offer-Ready gold,
Interview-Ready teal, Building navy, Not Ready orange**. The deeper "working" (STAR breakdown,
interviewer thoughts, 7-day plan, next focus) is unchanged supporting detail below the verdict
— it is not a second verdict. The readout container also drops the negative-margin breakout
(`max-width:820; margin:0 auto`), so the readout fits the embed with no h-scroll.

**Files touched:** `frontend/src/App.jsx`.

**Verified** in-browser (Vite + mock `/session/end`): the full readout renders one Readiness
block containing band + round pills + calibration (avg confidence / avg score / delta +
coaching) + competency `/10`s, with no separate scorecard.

---

## Item 3 — Empty session = no scorecard

**Before.** A session that ended before any substantive answer still rendered "Not Ready" +
`0/10`-style tiles — a verdict on a no-show.

**After.** New **pure, unit-tested** helper `isEmptyReadout(d)` (`frontend/src/readoutPolicy.js`)
detects an empty readout from what the server actually scored (no strengths, no STAR rows, no
sub-scores) — robust even when the server still fills a default band string. When empty,
`DebriefScreen` renders **only** the "session ended before any substantive answers" card plus
the **Presence Profile if data exists** (camera cues can exist without an answer), and the
navigation buttons. **No readiness band, no tiles.** Skipped ≠ failed.

**Files touched:** `frontend/src/App.jsx`, new `frontend/src/readoutPolicy.js`, new
`frontend/src/readoutPolicy.test.mjs`.

**Test (the one the brief asked for):** `readoutPolicy.test.mjs` — "end-at-question-1: nothing
scored → empty (no band, no tiles)", plus back-compat and null-safety cases. Runs under
`npm test`.

**Verified** in-browser: an empty report renders the ended card + Presence Profile only — no
band, no tiles.

---

## Item 4 — Embedded audio seatbelt

**Change (three parts, none touching the single-capture-gate invariant):**

1. **Create/resume the AudioContext on the room-entry gestures.** The Lobby **Join** click now
   calls `unlockAudioPlayback()` synchronously, before its `await` breaks the gesture context;
   **unmuting** resumes the context via `resumeTtsAnalyser()` (a room reached by deep-link may
   never have seen the Start gesture). Both touch only Web Audio — the mic gate is unchanged.
2. **No silent play() failures.** New `logAudioBlocked(where, err)` records the rejection
   reason (name + message) at every TTS play site — `playAudio`, `playOne`, and the backchannel
   `playClip` — so a muted room is diagnosable instead of invisible.
3. **In-brand affordance.** The essential-voice paths raise a **"Tap to enable audio"** chip
   (reworded from "Tap to hear the question"); one tap runs `enableAudio()`, which unlocks
   playback / resumes the context and replays the current question. Backchannels stay chip-free
   (a blocked "mm-hmm" is not worth a nag) but are still logged.

**Files touched:** `frontend/src/App.jsx`.

**Verified:** the full suite is green — critically the capture-gate mutation checks still pass
(`openMicUnsafe` has exactly one caller, `armCapture` still consults `canArmCapture`), so the
invariant is intact. End-to-end playback inside the live iframe needs UAT (below) — it requires
the deployed backend + real Bulbul audio, which isn't runnable here.

---

## Item 5 — Startup must survive a dead TTS account (backend)

**Before.** Boot warming was already fire-and-forget and `tts.synthesize()` already returned
`None` on any failure — but a *hung* vendor could leave a multi-minute zombie warm task
(≈18 clips × the 30s mid-session read timeout), and warming fired a doomed vendor call per
clip even when the key was absent.

**Change (all in `backend/app/tts.py` + `backend/app/main.py`):**

1. **Hard-bounded warming.** `warm_clip_pack` now gives each synth a hard per-call ceiling via
   `asyncio.wait_for` (cancels a hung call — and closes its HTTP client — even if httpx's own
   timeout doesn't fire), and the whole pass an overall **budget** after which the remaining
   clips are *left to synthesise on first use* (new `skipped` count). It still never raises.
2. **Skip + log when there's nothing to warm with.** The boot hook (`warm_clip_pack_on_boot`)
   returns early — with a log — when TTS is enabled but `SARVAM_API_KEY` is missing, and wraps
   the warm task so it can never take the app down. *"If TTS is unavailable at boot, log it,
   skip warming, and start anyway."* Boot never awaits TTS, so the Space becomes healthy
   immediately regardless of the vendor.
3. **Mid-session unchanged and already correct.** A failed synth yields a null `audio_url`; the
   reply text/captions go out regardless; the session completes. (`_try_tts` / `_try_tts_segments`
   / the greeting/speech/turn handlers all degrade to text, never 500.)

**Files touched:** `backend/app/tts.py`, `backend/app/main.py`, new
`backend/tests/test_boot_resilience.py`, and `backend/tests/test_fast_start.py` (one existing
warm-summary shape assertion updated for the new `skipped` key).

**Test (the one the brief asked for), offline — no vendor, DB, or server:**
`test_boot_resilience.py` pins that a **hanging vendor is bounded** in well under its hang, that
**total vendor failure** warms nothing and never raises, that the **boot hook skips warming
(and never calls it) with no key**, and that a **mid-session TTS failure is caption-only**, never
a crash. The literal "boot with an invalid `SARVAM_API_KEY`" is the union of these:
warming is skipped/best-effort and the reply path stays caption-only — a full live boot is in
the UAT list.

## Test results

Frontend — `npm test` → **61 passing, 0 failing** (55 pre-existing + 6 new `readoutPolicy`
cases); includes the 22 Critical guardrails and the capture-gate structural/mutation checks.
`npm run build` → clean.
Backend — `python -m pytest` → **244 passing, 0 failing** (incl. 5 new `test_boot_resilience`
cases; the previously-failing warm-summary shape test updated and green).

## Anything needing a backend (hf) change — **hf push PENDING your confirmation**

**Item 5 is a backend change and reaches production only via an `hf` push, which I have NOT
done.** Nothing was pushed to `hf`. On your go-ahead: `git push hf main` deploys it to the
Space (the Space rebuilds from the Dockerfile and restarts on the new revision). Items 1–4 are
frontend-only and unrelated to `hf`.

- *Optional (not required):* item 3's empty-session detection is a frontend content heuristic
  (no strengths / STAR / sub-scores). A server-provided `substantive_answer_count` on the
  `/session/end` response would be a more explicit signal; the current heuristic is correct for
  today's payloads and needs no backend work to ship.

## Screenshots for UAT

Layout + readout shots were captured during verification; the live-audio checks need a real
embedded session:

1. **Room @ 1100 / 1280 / 1920**, embedded and full-page — no horizontal scrollbar; End,
   "You're muted" pill, and docked self-view all fully visible; interviewer tile centred.
2. **Readout (answered session)** — one Readiness block: band + per-round pills + calibration
   delta + competency `/10`s, no separate scorecard below.
3. **Readout (end-at-question-1)** — the "ended before any substantive answers" card +
   Presence Profile only; no band, no tiles.
4. **Embedded audio (live, in the iframe):**
   - Greeting autoplays after **Join**; the LED-mouth lip-sync tracks the real voice.
   - If autoplay is blocked, the **"Tap to enable audio"** chip appears; one tap plays.
   - **Unmute** while muted resumes a suspended context (voice audible again).
   - Console shows a `[InterviewIQ audio] play() blocked at …` line on any block (not silent).
5. **Dead-TTS boot (item 5, needs the hf deploy):** start the Space with an invalid/empty
   `SARVAM_API_KEY` (TTS_ENABLED=true) → `/health` returns 200 within seconds, the boot log
   shows the "skipping clip-pack warming" or a hard-bounded warm summary (never a 9-minute
   hang), the Space does **not** enter "Restarting", and a session runs silently with captions
   through to the readout.