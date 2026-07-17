# INTAKE_AND_MODES_REPORT.md — one intake boundary, and TEXT / AUDIO / VIDEO

**Sprint:** Phases A and B. **Phase D (presence) is excluded** and runs as a later sprint —
nothing here computes a presence metric, and no MediaPipe asset was added.

**Suites:** 377 backend (was 341) + 103 frontend (was 100). All green.
**Migration 009 applied** to `defaultdb`. **Nothing pushed to `hf`** — awaiting explicit
confirmation (§8). No screenshots committed (`.gitignore`, §9).

---

## 0. The thing that was actually broken

Before a line of this sprint was written, the gather was dead — and it had been for weeks,
silently.

`db.get_student_context` read three sources. **None of them existed.**

| It read | Reality | Consequence |
|---|---|---|
| `student_profiles` | table GONE; columns now on `users` | education, skills, résumé, psychometrics → dead |
| `student_ai_profiles` | RENAMED to `ai_profiles` (29 live rows) | ProfileIQ → dead |
| `enrollments.student_id = user_id` | it is a `students.id`, not a user id | course history → dead (0 of 10 rows matched, always) |

Every read was wrapped in `except: log.debug(...)`. So nothing failed. The function just
returned a dict of `None`s and the interview carried on knowing a first name.

Measured, before the fix, for **user 74 (Andrew Carter)** — a real student with three
enrolments, a COMPLETED ProfileIQ summary, a résumé and a London address on file:

```
name             = Andrew Carter
ai_profile       = None
enrollments      = []
education        = None
skills           = None
source           = []          <- seven feeds of data, none of them read
```

**The ice-breaker was not skipping because of the prompt.** `prompts.py` forbids inventing
personal facts and skips the beat when it has nothing safe — correctly. It had nothing
because the gather handed it nothing. The prompt was doing its job perfectly on empty input.

`schema_check` could not have caught this: `_read_schema` filtered `LIKE 'vyom\_%'`, so the
one thing built to notice a schema moving was structurally blind to the half we do not own.

After the repair, the same user:

```
source = ['education','work_profile','city','ai_enhancer','enrollments']
city   = London
```

and user 87: `city = Bangalore`, `interests = "Reading, watching movie"`, plus psychometrics
and a ProfileIQ summary.

---

## 1. Naming, reconciled (this sprint's call)

`SCORING_CONTEXT_REPORT.md:44-49` left this decision here, deliberately:

> *this prompt says TEXT/AUDIO/VIDEO; INTAKE_AND_MODES says TEXT/VOICE/HYBRID. I implemented
> this prompt's rows as authoritative and added `MODE_ALIASES`... **Reconciling the two names
> is that sprint's call.***

**Resolved: TEXT / AUDIO / VIDEO.** The constants table was already authoritative and your
override agreed with it. `MODE_ALIASES` (`VOICE→AUDIO`, `HYBRID→VIDEO`) is kept in both
`scoring.py` and `intake.py` so stored rows and older clients resolve rather than silently
scoring 1.00 for a name nobody recognises. A test asserts the two copies agree.

**The other "mode" is untouched.** `vyom_sessions.mode` holds the FEEDBACK style
(`interview`|`coach`). It keeps its name; the lobby heading already says FEEDBACK. Two live
factors with different weights share that word, and reading the wrong one silently
re-weights a session — which is exactly why migration 009 adds a **new column** rather than
overloading the old one.

| | means | column | weights |
|---|---|---|---|
| **MODE** | *how* they answer | `session_mode` (009) | TEXT 0.90 / AUDIO 1.00 / VIDEO 1.00 |
| **FEEDBACK** | *when* they hear about it | `mode` (unchanged) | interview 1.00 / coach 0.90 |

**VIDEO** = camera on + self-view, speak **or** type per question (your decision). Presence
metrics stay Phase D. The camera is on because the chip says Video — a chip promising video
while nothing video happens is a lie we would be shipping.

---

## 2. Phase A — the intake boundary (`backend/app/intake.py`, new)

| Rule | Where | Note |
|---|---|---|
| A1 GATHER | `intake.gather` → `db.get_student_context` | repaired; §0 |
| A2 MERGE, FORM WINS | `intake.merge` | deliberately dumb: if the student typed it, it is true |
| A3 SANITIZE ONCE | `intake.merge`, caps declared in one place | one documented exception, below |
| A4 VALIDATE BEFORE SPEND | `intake.validate` | now literally before the first LLM/TTS call |
| A5 VENDOR SEATBELT | `IntakeError(offer_text_mode=True)` → 422 | an offer, not a dead end |
| A6 ONE OBJECT | `SessionConfig.card()` | card + Session Profile + attempt record |

**A3's one honest exception.** `prompts.py` still sanitises what it renders, and it must:
every session stored *before* this boundary holds **raw** text (sanitising used to happen at
render time, so it was never applied at rest). Removing that pass would replay old
un-defused JDs into the model — a security regression bought for a tidier diagram. It is
free to keep because `sanitize_untrusted` is **idempotent**, which acceptance (b) pins.

**Phase A addition — city + interests.** No migration needed: they were already on `users`
(`city`, `hobbies`). Sparse on real data (**city 3/14, interests 1/14**), so "where
available" is exactly right and the beat must still skip gracefully. Sanitized once at the
same boundary. The gather reaches for **exactly these two** personal fields — `users` also
carries parents' phone numbers, bank details, caste-adjacent fields and salary
expectations, and `SessionConfig` has nowhere to put any of it (tested).

The ice-breaker rule now has two forms. **The ban on invention is word-for-word identical in
both.** What changed is whether there is anything real to be friendly *with*:

- no facts on file (most students) → *"You do not know their city..."* — unchanged
- facts on file → *"...the personal facts written in CANDIDATE BACKGROUND are REAL... you may
  use ONE of them"*, plus an explicit ban on extrapolating from a city to its weather/traffic
  or from an interest to a skill.

---

## 3. Two bugs found while wiring Phase A

**The JD was never in the JD slot.** The blob was assembled
`[intro] --- JOB DESCRIPTION --- [jd] [background] --- RESUME --- [resume]`, and
`prompts._split_intro` looks for `RESUME` **first**. So for any student with a résumé on
file, the JD was swallowed whole into `self_intro` and `jd_section` came out **empty**. The
JD reached the model; it never reached the instructions that read a JD. Order now matches
the split, and the JD travels as its own field — a field cannot be forged by its own
contents (the old delimiter could be re-partitioned by a student pasting it).

**A test that tested nothing.** `test_stt` patched `main.get_student_context`; the gather had
moved to `intake`, so the patch bound nothing and the test passed only because
`intake.gather` swallows the error. Green for the wrong reason. It now patches where the
code runs, and `main` no longer imports the name at all.

---

## 4. Phase B — modes

**TEXT never asks for the mic.** Not "defaults to off": the green room returns before any
control that could call `getUserMedia`, so the dialog is unreachable on that path.

**TEXT spends nothing at Sarvam, gated server-side** (`_try_tts`, `_try_tts_segments`,
`_greeting_segments`, and inside `_on_delta` — that clip fires *mid-generation*, so a gate
added only downstream would already have paid). A spend promise kept only by the client not
asking is not kept: a stale tab or a replayed request would bill us anyway. Counted at the
vendor boundary:

| mode | vendor calls |
|---|---|
| AUDIO | 5 |
| VIDEO | 5 |
| **TEXT** | **0** |
| unknown (pre-009 DB) | 5 — behaves exactly as it always did |

**An unknown mode is never charged the TEXT discount** (1.00, not 0.90). A database without
009 has no `session_mode`, and marking a spoken session down for a missing column would be
charging the student for our deploy state.

---

## 5. Scoring (`WEIGHTS_VERSION` 2026.07-1 → **2026.07-2**)

`MODE_FACTOR_ACTIVE = True`. The rule the dormancy guarded is now satisfied rather than
deferred: nothing may be weighted by a mode nobody can choose — there is a picker.

**No existing session moved.** AUDIO and VIDEO are 1.00 and every session that ever ran was
spoken. The bump exists because the *meaning* changed, and a benchmark whose meaning changes
silently is what the version field is for. Only TEXT moves: raw 80 → benchmark 72.

The readout shows a Mode row **only when a mode is known** — "Mode — Unknown ×1.00" is a row
that explains nothing while implying we measured something. A TEXT session gets
`Mode — Text ×0.90` and the reason, because an unexplained 0.90 is the "score with no
context" that table exists to stop.

```
raw          Your answers, scored for your level    80
difficulty   Difficulty — Realistic                 ×1.00
evidence     Evidence — 20 min                      ×1.00
feedback     Feedback style — Interview             ×1.00
coverage     Coverage — 4 of 4 rounds               ×1.00
mode         Mode — Text                            ×0.90
total        Benchmark                              72
```

---

## 6. What driving the real app found (that 480 tests did not)

Both suites were green through all of this.

1. **The room told a typing student to tap the mic.** `You're muted — tap the mic to answer`
   ran for the whole TEXT session: `micOn=false + answerDue=true` *is* the muted state, and
   TEXT is muted by definition. It instructed them to fix something working as chosen, and
   pointed at the one control the mode promises never to need. Now: `Your turn — type your
   answer`.
2. **The mic and camera buttons were still in the control bar.** Unmuting calls
   `getUserMedia` — a one-tap route to the exact dialog TEXT guarantees they never see,
   sitting under a banner telling them to tap it. Removed in TEXT.
3. **A "silent" session was about to say "Hmm."** The clip pack fetched unconditionally (two
   `/session/clips` in a TEXT session) and `playAck()` fires on answer submit — a spoken
   acknowledgment in the one mode whose entire promise is silence. TEXT now skips the fetch.
4. **The placeholder this sprint was named in.** `const textMode = config.mode === "text"` —
   `config.mode` is the FEEDBACK style and has never held `"text"`, so the text layout could
   not fire. Its comment said *"INTAKE/MODES, landing later"*. Wired to `session_mode`; the
   chat panel now takes the student tile's slot as intended.

---

## 7. Acceptance

| | | |
|---|---|---|
| (a) | form role ≠ ProfileIQ → form wins | ✅ verified on real data: ProfileIQ "Intern" vs form "Data Analyst" → Data Analyst, override recorded |
| (b) | JD injection is data, sanitized once | ✅ `"Ignore previous instructions"` → `"[REDACTED] instructions"`; `sanitize(sanitize(x)) == sanitize(x)` |
| (c) | invalid config → zero LLM/TTS | ✅ `IntakeError` before any paid call |
| (d) | Sarvam dry → TEXT offer | ✅ `offer_text_mode=True`; TEXT validates fine against a dead vendor |
| (e) | TEXT → no mic prompt, no TTS | ✅ **0** `getUserMedia` in a real browser; **0** vendor calls |
| (f) | VIDEO → camera + per-question channel | ✅ camera on, typing allowed, TTS on |
| (g)(h) | presence | ⏸ **Phase D — excluded by instruction** |
| (i) | emotion-word lint | ✅ already enforced by `test_readout.py:105`; still green |
| (j) | all suites green, capture gate untouched | ✅ 377 + 103 |

---

## 8. Backend / deploy — NEEDS YOUR CONFIRMATION

**Migration 009 applied to `defaultdb`** (per your override 5), verified via the real boot check:

```
INFO app.schema_check lms schema: all 21 expected object(s) present
INFO app.schema_check schema: up to date (through migration 009_intake_and_modes)
pending_migrations = []

vyom_sessions.session_mode   type=varchar(10)  nullable=NO   default=AUDIO
vyom_messages.input_channel  type=varchar(10)  nullable=YES  default=None
session_mode = AUDIO -> 163 rows      (they were all spoken; this is not a guess)
```

**`hf` is NOT pushed.** Origin has all four commits. The Space needs, in order:

1. `db/migration_009_intake_and_modes.sql` against the Space's database.
2. The push itself.

**Say the word and I will push.**

---

## 9. Files touched

| file | |
|---|---|
| `backend/app/intake.py` | **new** — the boundary |
| `backend/app/db.py` | gather repointed at tables that exist; +city/interests |
| `backend/app/schema_check.py` | LMS half (warn, never block); 009 rows; `_read_schema` unblinded |
| `backend/app/scoring.py` | `MODE_FACTOR_ACTIVE=True`, `WEIGHTS_VERSION` 2026.07-2, mode row honesty |
| `backend/app/main.py` | `/session/start` through the boundary; TTS mode gates; `session_mode` in profile/score |
| `backend/app/prompts.py` | conditional ice-breaker rule; fact-label contract |
| `backend/app/schemas.py` | `session_mode`, `jd` as its own field |
| `frontend/src/App.jsx` | MODE picker, confirmation card, seatbelt UI, `textMode` wired, clip-pack gate |
| `frontend/src/Lobby.jsx` | TEXT green room (no permission moment); VIDEO camera-first |
| `frontend/src/roomLayout.js` | `statusStrip` textMode |
| `db/migration_009_intake_and_modes.sql` + rollback | **new** — additive only |
| tests | `test_intake_and_modes.py` (new, 21); `test_schema_check` +8; `test_scoring` +5; `roomLayout.test.mjs` +3 |

---

## 10. UAT screenshots

On disk, **not committed** (`.gitignore` — build evidence never goes in git). Referenced by
filename only:

| file | shows |
|---|---|
| `01_setup.png` | MODE picker in the left column below Target Role, above Focus Areas; three equal chips; Audio default; confirmation card |
| `02_Text_card.png` | confirmation card with MODE=Text, FEEDBACK=Interview as distinct fields |
| `03_Text_lobby.png` | the TEXT green room — no permission moment, no device controls |
| `04_Text_after_join.png` | the TEXT room: "Your turn — type your answer", no mic/camera buttons, chat in the student tile slot |
| `05_audio_greenroom.png` | AUDIO green room unchanged — pre-prompt, mic test, camera offer |

---

## 11. Two things I did not touch, that you should know about

1. **`[PENDING LEGAL REVIEW]` is student-visible today.** The AUDIO/VIDEO green room renders
   `DRAFT NOTICE — PENDING LEGAL REVIEW` plus draft consent copy (`Lobby.jsx:62-70`), and the
   setup consent card carries the same. The sprint rules say nothing student-visible ships
   with that copy. It predates this sprint and I did not rewrite legal copy without review —
   flagging it rather than silently changing it. (The new TEXT green room sidesteps it
   entirely: it makes no device claims, because it uses no devices.)

2. **`CONSENT_COPY_CAMERA` mentions attention cues.** It is accurate *today* — camera-on
   attention drift check-ins already exist and predate this sprint. But when Phase D lands
   m1–m8, this copy is the one that needs re-reading against D7's consent gate.

---

# PHASE D — PRESENCE METRICS m1–m8 (added in a follow-up sprint)

> The header at the top of this file says "Phase D is excluded." That was the A/B sprint.
> This section is Phase D, built now. **Definition of done met: built, tested, and DARK
> behind its flag.** It is NOT enabled for students — that waits on legal sign-off of the
> camera/attention-cue consent block (D7). Nothing here was pushed to `hf`.

**Suites after Phase D:** **402 backend** (+16 `test_presence_metrics.py`) + **117 frontend**
(+11 `presenceMetrics.test.mjs`). All green. The capture-gate mutation test is untouched and
still green — I added no arming site, and the presence monitor never touches the mic.

## The one-paragraph shape

In VIDEO mode, when the feature is enabled, the browser runs MediaPipe over the student's
**local** camera tile, folds each frame into eight numbers, and **discards the frame**. At
session close the eight numbers — and only the eight numbers — are POSTed once. They render
as **behaviour sentences inside the existing Presence Profile card** (a sub-block, never a
new section) and are **report-only**: they touch no benchmark and no band. Camera off,
AUDIO/TEXT, or a MediaPipe that fails to load all degrade to one no-data line and **no
penalty**. With the flag off (today) none of this exists for a student: MediaPipe is never
imported, `/session/presence` 404s, and the readout is byte-for-byte what it was.

## Metric naming decision (D3) — final: m1–m8

The prompt's D3 names are the contract. Migration 006 had reserved a per-answer column with
tentative names (`eye_contact_pct`, `composure_index`, …); **`composure_index` was dropped
deliberately** — "composure" is an emotion attribution, exactly the class of word D3 bans.
Each id maps to a behaviour, never a feeling:

| id | behaviour measured | render (high band) |
|---|---|---|
| m1 | gaze-on-screen ratio | "held your eyes on the screen for most of the interview" |
| m2 | head-pose stability | "kept your head steady while you spoke" |
| m3 | posture lean/slouch **events** (count) | "changed posture N times" |
| m4 | expression variability | "your expression changed with what you were saying" |
| m5 | smile/neutral balance | "smiled during much of the interview" |
| m6 | blink & attention proxy | "blinked at a steady, natural rate" |
| m7 | gesture presence | "used your hands as you spoke" |
| m8 | framing/centering | "stayed centred and well-framed in the shot" |

Every sentence at every band is emotion-linted (bans nervous / bored / confident / composed /
seemed / feel / …).

## Where the numbers live (schema decision)

m1–m8 are ONE aggregate over the whole session, emitted once at close — so the store is a
single JSON blob on the **session** row, `vyom_sessions.presence_metrics` (**migration 010**,
additive, nullable). The **per-message** `vyom_messages.presence_metrics` column that 006
reserved is left **in place and unused**: the shipped design has no per-answer presence
payload, so a once-per-session aggregate belongs on the session row. 010 does not touch the
006 column.

## The privacy boundary, in three places

1. **The wire is eight numbers.** `PresenceMetricsRequest` has no field that could carry an
   image, a frame, or a landmark. There is no media path to the server, by construction.
2. **The server re-clamps.** `presence.sanitize_presence_metrics` is the whole trust
   boundary: unknown keys dropped, ratios clamped to [0,1], counts to [0,999], NaN/inf
   dropped, empty → None. The request schema deliberately carries **no** ge/le bounds so a
   marginal value is *clamped and used*, not *refused* — sanitisation is the authority.
3. **The client discards frames.** `presenceMonitor.js` hands each frame to MediaPipe, reads
   derived numbers, and lets it go — no canvas, no array, no MediaRecorder. `presenceMetrics.
   js` (the pure fold) holds running sums only; a test asserts it retains no frame array.

## Report-only, proven

`presence_metrics_readout` returns counts and sentences with **no band/score/benchmark key**
(a test greps for them). The block is attached to the `professional_presence` field only — it
never reaches `overall_band`, `score`, or `ecopro` (the NudgeAI hand-off, which already
excludes presence). So a camera-on VIDEO session and the same session camera-off compute an
**identical** readiness band; the only field that differs is the report-only presence card
(acceptance h, structurally guaranteed).

## VIDEO-only, and every other path is a silent no-op (D6)

`presence_metrics_available` is true only for VIDEO + camera-on + at-least-one-number.
AUDIO, TEXT, a camera-off join, and a MediaPipe failure all resolve to the same no-data line
("No presence data — camera was off. Presence is never scored…") and never a penalty. The
monitor's every failure path (`@mediapipe/tasks-vision` absent, WASM won't compile, model
load throws, no WebGL) resolves to a `nullMonitor()` whose `stop()` returns null → nothing
posted → no-data line.

## Self-hosted assets (D1)

`presenceMonitor.js` loads the WASM runtime and the two `.task` models from **our own origin**
(`/mediapipe/…`), never a CDN. `scripts/fetch_mediapipe_assets.mjs` populates
`frontend/public/mediapipe/` (copies the WASM out of the installed package so the runtime
matches the JS; downloads the two models). Verified end-to-end here: WASM copied,
`face_landmarker.task` 3.8 MB + `pose_landmarker_lite.task` 5.8 MB downloaded. The binaries
are **gitignored** (a deploy step, like the UAT screenshots and the migrations); the README
that documents them is tracked. The dynamic `import()` keeps MediaPipe in its own bundle
chunk (`vision_bundle`, 136 KB) that is **never loaded while dark**.

## CSP

`_STRICT_CSP` gains `'wasm-unsafe-eval'` (MediaPipe compiles its WASM via
`WebAssembly.instantiate`, which `script-src 'self'` alone blocks) and `worker-src 'self'
blob:` (its graph runs in a blob worker). Both are same-origin and inert while dark. WASM
compilation only — `eval()` for JS stays closed. `test_security_headers` still green.

## The flag, and how "dark" is enforced

- **Backend** `PRESENCE_METRICS_ENABLED` (default **false**). While false,
  `/session/presence` returns **404** (not 403 — the route reads as simply not mounted), and
  the readout never attaches the metrics sub-block.
- **Frontend** `VITE_PRESENCE_METRICS` (default off). While off, `isPresenceMonitorEnabled()`
  is false, so App never even reaches the dynamic `import("@mediapipe/tasks-vision")` and not
  a single frame is processed.
- Both documented (off) in the `.env.example` files. Verified: `settings.
  PRESENCE_METRICS_ENABLED == False`; no env sets either flag on.

## Files touched

| file | |
|---|---|
| `backend/app/presence.py` | **+m1–m8**: metric spec, `sanitize_presence_metrics`, `presence_metrics_available`, `presence_metrics_readout`, emotion-free behaviour sentences |
| `backend/app/config.py` | `PRESENCE_METRICS_ENABLED` (default false) |
| `backend/app/schemas.py` | `PresenceMetricsRequest` / `PresenceMetricsResponse` (types only, no range bounds — server clamps) |
| `backend/app/main.py` | `POST /session/presence` (dark → 404; VIDEO+camera only; report-only), readout attaches the sub-block only when enabled, `_load_presence_metrics`, CSP `wasm-unsafe-eval`/`worker-src` |
| `backend/app/schema_check.py` | 010 row in `EXPECTED`; `LATEST_MIGRATION` → 010 |
| `db/migration_010_presence_metrics.sql` + rollback | **new** — additive session-level JSON column |
| `frontend/src/presenceMetrics.js` | **new** — pure frame→m1–m8 fold, dependency-free |
| `frontend/src/presenceMonitor.js` | **new** — MediaPipe glue; self-hosted assets; discard-and-fold; fails to a no-op |
| `frontend/src/App.jsx` | monitor lifecycle in `StudentTile` (VIDEO+camera+flag), `flushPresence` at all three end paths, `submitPresenceMetrics`, `PresenceMetricsSubBlock` inside the Presence Profile card |
| `frontend/package.json` | `@mediapipe/tasks-vision` |
| `frontend/public/mediapipe/README.md` | **new** — the deploy step |
| `scripts/fetch_mediapipe_assets.mjs` | **new** — populates the self-hosted assets |
| `.gitignore`, `.env.example` (×2) | ignore the binaries; document the flags (off) |
| tests | `test_presence_metrics.py` (**new, 16**), `presenceMetrics.test.mjs` (**new, 11**), `test_schema_check` (010 pin) |

## Acceptance (D-relevant)

| | | |
|---|---|---|
| (g) | camera off in VIDEO → full scores, presence shows no-data | ✅ `presence_metrics_available` false → no-data line; band unaffected |
| (h) | metrics present → band identical to camera-off | ✅ presence block carries no band/score key; attaches only to `professional_presence` |
| (i) | emotion-word lint | ✅ over every sentence × every band + the no-data line + labels |
| (j) | all suites green, capture gate untouched | ✅ 402 + 117; no new arming site |
| D1 | assets self-hosted | ✅ `/mediapipe`; fetch script verified downloading both models |
| D2 | on-device, compute-and-discard | ✅ no media path server-side; monitor discards frames; fold retains no frame array |
| D5 | renders inside Presence Profile | ✅ `PresenceMetricsSubBlock` is a sub-block of the same card |
| D6 | camera-off / MediaPipe-fail = no penalty | ✅ every failure path → null → no-data line |
| D7 | ships dark behind the flag | ✅ default off; 404 + no MediaPipe import while dark |

## NEEDS YOUR CONFIRMATION / deploy notes

1. **`hf` NOT pushed.** Awaiting your explicit confirmation, as instructed.
2. **Migration 010** must be applied wherever the flag is later turned on (additive; safe to
   apply now — it enables nothing on its own). I did **not** apply it to any database.
3. **Self-hosted assets** must be populated (`scripts/fetch_mediapipe_assets.mjs`) before the
   flag is flipped. The build is fine without them while dark.
4. **The consent gate is the real switch (D7).** The flag stays false until the
   camera/attention-cue consent block clears legal review. `CONSENT_COPY_CAMERA` (flagged in
   §11.2 above) is the copy that must be re-read against m1–m8 before enabling.

## Honestly not verified

The **enabled** path's frame-derivation (MediaPipe reading a live face; the yaw/pitch and
blendshape thresholds) was **not** driven in a real browser — it needs a camera, the
downloaded models, and the consent gate open, none of which apply while the feature is dark.
What IS verified: the pure fold (11 tests), the server contract (16 tests), the build with
MediaPipe code-split, the self-hosting script downloading both models, and the dark path
leaving the app unchanged. The threshold constants in `presenceMonitor.js` are first-pass and
tuned once the feature is un-darkened against real users — flagged in-code as such.

## UAT screenshot list (to capture once un-darkened; not committed — `.gitignore`)

| file | shows |
|---|---|
| `d1_presence_card_video.png` | Presence Profile with the "On-camera presence" sub-block — eight tiles + behaviour sentences + "Report only — not part of your score" |
| `d2_presence_no_data.png` | VIDEO session, camera off → the single no-data line, full scores intact |
| `d3_band_identical.png` | same session camera-on vs off → identical readiness band (report-only proof) |
| `d4_network_tab.png` | session close → one `/session/presence` POST carrying only m1–m8; no frame, no upload during the session |
