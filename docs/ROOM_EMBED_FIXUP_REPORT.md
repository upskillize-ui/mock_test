# ROOM_EMBED_FIXUP_REPORT.md

Surgical fixes for the embedded meet room (serves same-origin inside the LMS shell at
`lms.upskillize.com/student/mock-interview`, an embed of `/interview/`). Target container
~1100–1400px wide. All four items landed as separate commits on `main`; the suite is green
throughout (61 tests, incl. the 22 Critical guardrails and the capture-gate mutation checks).

## Commits (in order)

| Item | Commit | Summary |
|------|--------|---------|
| 1 | `040d69e` | Room fits its container: kill the negative-margin breakout (no h-scroll) |
| 1b | _this commit_ | App-wide: remove the same breakout from Setup / History / Settings |
| 2 + 3 | `5c893ad` | Readout is one report: merge the verdict, and stop scoring no-shows |
| 4 | `b689f02` | Embedded audio seatbelt: unlock on gesture, never fail a play() silently |

(Items 2 and 3 are the same `DebriefScreen` rewrite and are inseparable in one file, so they
share a commit. Both are covered below.)

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

## Test results

`npm test` → **61 passing, 0 failing** (55 pre-existing + 6 new `readoutPolicy` cases).
Includes the 22 Critical guardrail tests and the capture-gate structural/mutation checks.
`npm run build` → clean (Vite production build succeeds).

## Anything needing a backend (hf) change

**None required.** All four fixes are frontend-only; nothing was pushed to `hf`.

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
   5. STARTUP MUST SURVIVE A DEAD TTS ACCOUNT: ack-clip warming and all Sarvam calls
   get hard timeouts and a skip-on-failure path. If TTS is unavailable at boot,
   log it, skip warming, and start anyway; if TTS fails mid-session, captions
   continue and the session completes. The Space must never sit in "Restarting"
   because a vendor account ran dry. Test: boot with an invalid SARVAM key →
   server starts, session playable silently with captions.
