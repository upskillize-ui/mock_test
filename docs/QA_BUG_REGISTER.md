# QA_BUG_REGISTER.md — full-product defect register

**Sprint:** QA sweep, 2026-07-17. **Rule:** test only. No product code was changed.
Harness lives in `tests/qa_sweep/` (new). Evidence in `tests/qa_sweep/evidence/`.
Screenshots deliberately kept out of git (scratchpad only); the register cites what
they show.

**How this was tested.** Not by reading the source and reasoning about it. Three
real sessions were driven over HTTP against the running backend and the real
database (`tests/qa_sweep/drive_api.py`), and the real app was driven in real
Chromium with fake-but-live media devices, with `getUserMedia` and
`HTMLMediaElement.play` wrapped before app code ran, so every layer reports for
itself (`tests/qa_sweep/drive_browser.py`, `probe_pacing.py`). Real Sonnet and
real Sarvam money was spent. Where a claim could not be proven, it is marked
NOT REPRODUCIBLE rather than asserted.

**Four things a static read would have gotten wrong, and driving corrected:**

1. The audio pipeline is **healthy** — all three layers pass in AUDIO and VIDEO
   (~400 KB fetched and played, zero playback rejections, even with autoplay
   blocked). The #1 complaint does not reproduce here.
2. The debrief 502 is **not** a flake. It is a token cap, it is provable, and it
   gets **more** likely the more complete the interview is. Nothing in the source
   says "2500 is too small"; the API's `stop_reason` does.
3. Typing **does** suppress the mute nudge. The bug hits the student who is
   *reading and thinking*, not the one typing. That distinction is the whole fix.
4. Three of the seven known suspects **do not reproduce** (below). Reporting them
   as bugs would have sent someone hunting ghosts.

---

## 1. The mode contract matrix — every cell, driven and asserted

`PASS` = observed to hold. `FAIL` = observed to break, with a defect ID.

### TEXT

| Contract cell | Result | Evidence |
|---|---|---|
| Pre-flight has NO device UI/copy | **PASS** | Only copy is *"No microphone needed, so we won't ask for one."* — names the device to refuse it. Buttons: `Join interview` only. |
| Zero `getUserMedia` calls | **PASS** | Instrumented wrapper: **0 calls** across the whole session. |
| TTS OFF — zero `/session/speech` audio | **PASS** | 0 `/session/speech` calls; server returns `audio_url: null` even when asked directly. |
| Zero clip fetches | **PASS** | 0 clip-pack fetches from the client. |
| Zero Sarvam TTS spend | **PASS** | Readout's own meter: `tts: {vendor_calls: 0, vendor_seconds: 0.0}`. |
| Typing drawer primary | **PASS** | Composer present and permanent. |
| No mic/camera buttons | **PASS** | Room buttons: `Voice settings, End, Send, Toggle captions, End` — no mic/camera. But see **QA-07**. |
| **Persona never says mute/mic** | **FAIL** | **QA-02** — *"You're on mute"* at ~5s, every question. |
| Nudges patient per typing | **FAIL** | **QA-02** / **QA-03** — first nudge at ~5s, not 60–90s. |
| Scored on content only, no Delivery | **FAIL** | **QA-08** — readout renders *"try answering aloud next session."* |

### AUDIO

| Contract cell | Result | Evidence |
|---|---|---|
| **Pre-flight asks MIC ONLY** | **FAIL** | **QA-04** — primary CTA is `Allow mic & camera`; camera copy present. |
| **No camera request** | **FAIL** | **QA-04** — `getUserMedia({audio:true, video:{...facingMode:"user"}})` actually fires. |
| TTS ON (bytes returned + played) | **PASS** | 11 audio fetches, 399,145 bytes, 3 `play()` calls, 0 rejected. |
| STT captures speech | **PASS** | Endpoint live; vendor reached. |
| Self-captions from Saarika | **PASS** | Captions control present; STT path live. |
| No camera button | **FAIL** | **QA-04** — camera button renders in AUDIO. |
| Delivery metrics from voice | **PASS (dark)** | `DELIVERY_METRICS_ENABLED` unset → off. See **QA-11**. |

### VIDEO

| Contract cell | Result | Evidence |
|---|---|---|
| Pre-flight asks mic+camera | **PASS** | `{audio:true, video:{640x480, facingMode:user}}`. |
| Self-view renders | **PASS** | Student tile renders with the camera stream. |
| Everything AUDIO has | **PASS** | 11 fetches, 420,462 bytes, 3 plays, 0 rejected. |
| Presence NOT computed (Phase D dark) | **PASS** | Phase D gaze/posture/expression not implemented at all. The shipping "presence" is the *focus/attention* engine (tab-switch/blur) — a different feature. |

---

## 2. Audio pipeline, layer by layer — "audio not working" is not a mystery

Output path:

| Layer | AUDIO | VIDEO | TEXT (should be silent) |
|---|---|---|---|
| (a) server/Sarvam — does `/session/speech` return real bytes? | **PASS** — 399 KB, `content-type: audio/mpeg`, magic `fffb90c4` (MPEG frame) | **PASS** — 420 KB | **PASS (silent by design)** — all `audio_url: null`, `vendor_calls: 0` |
| (b) app — does the client create and play an audio element? | **PASS** — 2 `Audio()`, 3 `play()` | **PASS** — 2 / 3 | **PASS (silent)** — 0 speech plays |
| (c) permission/autoplay — is playback blocked? | **PASS** — 0 rejections, *"Tap to enable audio"* never shown, **even with `--autoplay-policy=document-user-activation-required`** | **PASS** | n/a |

Input path: `getUserMedia` granted **PASS** (tracks returned); STT endpoint reached the
vendor **PASS** (`POST https://api.sarvam.ai/speech-to-text` in the log).

**Verdict: the audio pipeline is not broken in this environment.** All three layers
pass, including the autoplay path that usually explains "no sound". Because the
student's own click supplies user activation before the first audio, the unlock
runs and playback is never blocked.

So "audio not working" is **not reproducible as a pipeline failure**, and the
register does not claim it is. Two named, testable candidates remain for what
students are actually hitting — both are real code defects found this sprint:

- **QA-05** (`setTypeOpen` ReferenceError) — when STT *fails*, the fallback meant to
  rescue the student throws instead. The student is left with a dead mic and no
  composer. That reads exactly like "audio not working" and is on the failure path,
  which is the path a student with a bad mic lives on.
- **QA-04** — a student in AUDIO gets a camera prompt; denying it or dismissing the
  browser dialog is a plausible way to end up with no working session.

Recommended next step (needs a real student, not a harness): capture one failing
session's console + network. The instrumentation in `drive_browser.py` is built to
be pointed at it.

---

## 3. Conversation pacing — measured

| Measure | TEXT (observed) | Contract | Verdict |
|---|---|---|---|
| Question → first nudge, idle student | **~5s** (3.6s / 6.8s / 0.5s across runs) | 60–90s true idle | **FAIL — QA-02** |
| Nudge frequency | **once per question, every question** — fired again at 93.8s on Q2 | max one per question | Cadence per-question is correct; the *trigger* is wrong |
| Does typing suppress nudges? | **YES — 0 nudges across 60s of steady typing** | must suppress | **PASS** |
| Rebuke from slow typing? | **None** | never | **PASS** |
| Open question replaced while turn open? | **No** — `/session/reask` inserts no message, changes no stage | never | **PASS** |
| Question auto-expiry | **90s → auto-submits "(No answer — the time on this question ran out.)"** | — | **QA-03** |
| Escalation triggers | Attention ladder needs 3+ tab-hide/blur events (30s debounce); not reached | — | See **QA-12** |

The AUDIO/VIDEO nudges follow the silence rules and did not misfire.

---

## 4. Full-session completion per mode

One full session driven per mode (13 answers each, unique answers, rated between
turns as a real client does), through `/session/end`:

| Mode | Turns | `/session/end` | Readout | Debrief row | Session status | History row |
|---|---|---|---|---|---|---|
| TEXT | 13 | **200** (after 502s on an earlier run) | one document | `benchmark=12`, `weights_version=2026.07-2`, `gated_band=Not Ready`, `scored=1`, `substantive=13` | `completed` | correct — `band: Not Ready`, `benchmark: 12` |
| AUDIO | 13 | **502 × 6** | **none** | **NULL — no row** | **stuck `active`** | **`status: active`, `actual_duration_seconds: null`** |
| VIDEO | 13 | **502 × 6** | **none** | **NULL — no row** | **stuck `active`** | **`status: active`, duration null** |

Where it works, it works properly: the readout renders as ONE document, `mode` is
recorded (`session_mode` = TEXT/AUDIO/VIDEO on the session row), and `benchmark` +
`weights_version` are non-null. **But two of three modes could not produce a readout
at all.** See **QA-01**.

---

## 5. Known-suspect list — verified

| Suspect | Status | Note |
|---|---|---|
| Stale role on pre-flight | **NOT REPRODUCIBLE** | Chose `Data Analyst`; pre-flight said *"Data Analyst interview"*. Role is set fresh on each configure. (A related stale-state path exists — **QA-13**.) |
| Pre-flight top gap | **CONFIRMED** | **QA-09** — ~280px cream band above the dark lobby. |
| "You're on mute" in TEXT | **CONFIRMED** | **QA-02** — reproduced in a real browser, ~5s, every question. |
| DRAFT NOTICE visible | **CONFIRMED** | **QA-06** — visible to students on AUDIO/VIDEO pre-flight and in the setup consent. |
| Engagement rebuke fired by typing speed | **NOT REPRODUCIBLE** | 60s of slow, steady typing produced no rebuke, no escalation, 0 reasks. The rebuke needs 3+ tab-hide/blur events — reachable, but not by typing speed (**QA-12**). |
| Per-question timer visible while engaged | **CONFIRMED** | **QA-10** — `THIS QUESTION 1:07` visible for the entire question, including all 60s of active typing. |
| Cold-start lobby delay | **NOT REPRODUCIBLE** | Setup→lobby **0.14s**; join→first question **4.65s**. |

---

## 6. The register

Ranked: launch-blockers first.

---

### QA-01 — A completed interview returns no readout: the debrief truncates and 502s
| | |
|---|---|
| **Severity** | **LAUNCH-BLOCKER** |
| **Mode(s)** | ALL (worst on AUDIO/VIDEO; length-driven, not mode-driven) |
| **What happens** | The student finishes a full interview. `/session/end` returns **502 "Debrief generation failed"**. AUDIO and VIDEO failed **6/6 consecutive attempts** — the readout is unobtainable. The session stays `status='active'` forever, so a completed interview shows in history as abandoned, with `actual_duration_seconds: null`. Every retry bills another Sonnet call (the cost-guard only replays a **stored** debrief; nothing was stored). |
| **Root cause (proven, not inferred)** | `max_tokens=2500` at `backend/app/main.py:2311`. Replaying the exact request returns `stop_reason: "max_tokens"`, `output_tokens: 2500` — truncated mid-`perAnswerScores` → `json.loads` raises → `raise HTTPException(502)` at `main.py:2326`. **The same request at `max_tokens=4000` returns `stop_reason: "end_turn"` at 2631 tokens and parses cleanly.** The readout needs ~2631 tokens for 13 answers; the cap is 2500. `perAnswerScores` grows per answer, so **the more complete the interview, the more certain the failure**. A 3-answer session passed; every 13-answer session failed. |
| **What should happen** | A finished interview always yields a readout. Cap raised well above worst-case (13 answers ≈ 2631; a 20-answer cap session needs more), plus a retry and a fallback so one bad generation cannot destroy a 20-minute session — and never re-bill for a failure. |
| **Repro** | `python tests/qa_sweep/drive_api.py --mode AUDIO` (13 answers) → `POST /session/end` → 502. Then `python tests/qa_sweep/probe_debrief_cap.py <session_id>` → prints `stop_reason: max_tokens` at 2500 and `end_turn` at 4000. |
| **Evidence** | `evidence/debrief_cap_probe.json`, `evidence/completion.json`, `evidence/api_AUDIO.json` |
| **Layer** | backend |

---

### QA-02 — TEXT mode accuses the student of being on mute, ~5s in, on every question
| | |
|---|---|
| **Severity** | **LAUNCH-BLOCKER** |
| **Mode(s)** | TEXT |
| **What happens** | ~5 seconds after a question opens, before the student has touched the keyboard, the interviewer says **"You're on mute — go ahead and unmute, or if you'd rather type it out we can roll with that."** In a mode whose own pre-flight promises *"No microphone needed, so we won't ask for one."* It repeats **once per question, for every question** (observed again at 93.8s on Q2). Reading the question is enough to trigger it. |
| **Why** | Three independent gates all fail open in TEXT: (1) `stt_available` is computed from global flags only (`main.py:608`), never mode → the client's `voiceMode` is **true** in TEXT; (2) the client guard is `if (!voiceMode \|\| micOn \|\| typingNow) return;` (`App.jsx:3268`) — TEXT is permanently `micOn:false`, so the mic guard **passes** rather than blocks, and there is no `textMode` term; (3) `/session/reask` has **no mode check** (`main.py:1531`), so the text is returned and rendered (TTS is correctly suppressed, so it is silent — but printed). The persona also carries an un-gated `DEVICE MOMENTS` mute line in **every** mode's system prompt (`prompts.py:564-568`), pinned by `tests/test_persona.py:175`. |
| **What should happen** | TEXT never mentions mute/mic. Nudges only after 60–90s of true idle, max one per question, and never an escalation from slow typing. |
| **Repro** | `python tests/qa_sweep/drive_browser.py --mode TEXT --idle 105` → watch the transcript; two `POST /session/reask` calls in the network log. |
| **Evidence** | `evidence/browser_TEXT.json` → `device_lines_while_idle`: `[{"at_s": 0.5, "line": "You're on mute — ..."}, {"at_s": 93.8, ...}]` |
| **Layer** | frontend (guard) + backend (`/session/reask`, `stt_available`) + prompt (persona) |

---

### QA-03 — TEXT takes the question away from a student who is still reading it
| | |
|---|---|
| **Severity** | **MAJOR** |
| **Mode(s)** | TEXT (mechanism is all modes; the harm is TEXT) |
| **What happens** | The per-question clock (WARMUP 90s) runs while the student reads and thinks. At 90s with an empty composer it auto-submits **"(No answer — the time on this question ran out.)"**, the interviewer says *"We're out of time on that one — let's move on"*, and the question is gone. Observed on a student who never typed. In voice, 90s of silence is a real signal; in TEXT, 90s is *reading a case prompt and composing an answer*. The clock is keyed to `questionKey` only, so it never resets on typing. |
| **Nuance (argues by-design)** | The TEXT pre-flight explicitly promises *"Every question is timed the same way."* A student mid-draft at expiry submits a `partial`, so their words are not lost — only the idle/reading student loses the question outright. |
| **What should happen** | Product decision. Either TEXT gets reading-aware timing, or the 90s WARMUP clock is long enough to read and compose. As shipped, a deliberate thinker is punished for thinking. |
| **Repro** | `python tests/qa_sweep/drive_browser.py --mode TEXT --idle 105`, do not type. |
| **Evidence** | `evidence/browser_TEXT.json` → `room_text` contains `(No answer — the time on this question ran out.)` + `Time ran out` |
| **Layer** | frontend |

---

### QA-04 — AUDIO mode asks for the camera, and opens it
| | |
|---|---|
| **Severity** | **LAUNCH-BLOCKER** (consent/privacy) |
| **Mode(s)** | AUDIO |
| **What happens** | The AUDIO pre-flight's **primary, highlighted CTA is `Allow mic & camera`**; `Mic only` is secondary. The consent copy says *"Your camera stays on your device — never recorded or uploaded"* and *"InterviewIQ notices attention cues (like looking away) on your device"* — camera copy, in a mode that should not mention it. A student taking the default path triggers a **real camera permission prompt**, and the camera opens: instrumented `getUserMedia({audio:true, video:{width:640,height:480,facingMode:"user"}})`, then two more video-only calls for the self-view tile. |
| **Why** | `isVideo` is used in exactly **one** place in `Lobby.jsx` — a button label (`:421-423`). Everything else (primary CTA, camera toggle, consent copy) is identical for AUDIO and VIDEO. The room's mic/camera buttons share one gate, `{!textMode && ...}` (`App.jsx:3862`), so AUDIO renders a camera button. The self-view is gated on `camera`, not on VIDEO. |
| **What should happen** | AUDIO asks for **mic only**: no camera request, no camera copy, no camera button, no self-view. |
| **Repro** | `python tests/qa_sweep/drive_browser.py --mode AUDIO` → read `getUserMedia_calls`. |
| **Evidence** | `evidence/browser_AUDIO.json` → `getUserMedia_calls` shows video constraints; lobby buttons `['Allow mic & camera', 'Mic only', 'Type instead']`. Screenshot `AUDIO_2_lobby.png`. |
| **Layer** | frontend |

---

### QA-05 — The voice-failure fallback throws: `setTypeOpen is not defined`
| | |
|---|---|
| **Severity** | **LAUNCH-BLOCKER** |
| **Mode(s)** | AUDIO, VIDEO |
| **What happens** | `voiceFallback()` — the "a voice failure is never a dead end" path — calls `setTypeOpen(true)` (`frontend/src/App.jsx:2635`). **`setTypeOpen` is not defined anywhere in the codebase**: one reference, zero definitions. Every STT failure / mic-denied path in voice mode raises a `ReferenceError`, so the rescue meant to hand the student a composer throws instead. The student with a broken mic gets a dead end — precisely the fallback's stated contract, inverted. |
| **Not reproduced at runtime** | Our fake mic never failed, so this is CONFIRMED by inspection, not by observation. The grep is unambiguous (`grep -rn "setTypeOpen" frontend/src` → 1 hit, the call site). Flagged rather than proven, and it is a strong candidate for the "audio not working" reports. |
| **What should happen** | A voice failure shows a toast and opens the typed composer. |
| **Repro** | `grep -rn "setTypeOpen" frontend/src/` → one hit, the call. Runtime: force `/session/stt` to fail while in voice mode. |
| **Evidence** | `frontend/src/App.jsx:2635` |
| **Layer** | frontend |

---

### QA-06 — "DRAFT NOTICE — PENDING LEGAL REVIEW" is shown to students
| | |
|---|---|
| **Severity** | **LAUNCH-BLOCKER** (legal) |
| **Mode(s)** | ALL (pre-flight: AUDIO/VIDEO; setup consent: all) |
| **What happens** | The AUDIO/VIDEO pre-flight renders **`DRAFT NOTICE — PENDING LEGAL REVIEW`** (`Lobby.jsx:410-412`, unconditional, not dev-gated), directly under the DPDPA consent copy. The setup screen's consent checkbox carries *"(Draft notice — pending legal review.)"* (`App.jsx:1323`). Consent is recorded against `copy_version: "v0-draft"`. Shipping this to 2,500 students means collecting consent under wording that says, on its face, that it is not approved. |
| **Related** | TEXT shows no DRAFT NOTICE — because the TEXT lobby shows **no consent/DPDPA copy at all** (the whole panel sits inside the non-TEXT branch). That is arguably the larger problem. |
| **What should happen** | Legal signs off the copy; the notice goes; `copy_version` pins the approved wording. TEXT gets its own consent copy. |
| **Repro** | `python tests/qa_sweep/drive_browser.py --mode AUDIO` → `lobby_text`. |
| **Evidence** | `evidence/browser_AUDIO.json`, screenshot `AUDIO_2_lobby.png` |
| **Layer** | frontend + legal |

---

### QA-07 — A TEXT session can spend Sarvam STT: the gate is consent, not mode
| | |
|---|---|
| **Severity** | **MAJOR** |
| **Mode(s)** | TEXT |
| **What happens** | `/session/stt` and `/session/stt/partial` have **no mode check** (`main.py:1707`, `:1795`). Gates are: flags → ownership → **consent** → caps. Voice consent is **per-user and durable**, so any student who did one AUDIO session carries it forever. Driven: a fresh TEXT session got `403` (consent) → `POST /consent` → the same TEXT session then returned **`200`**, and the log shows **`POST https://api.sarvam.ai/speech-to-text`** — the vendor was reached **from a TEXT session**. Exposure: 25 answer calls + up to 400 partials per session. |
| **Note** | Live in this environment (`STT_ENABLED=true`, `VOICE_ENABLED=true`); both default false in code. The client does not call STT in TEXT — but the codebase's own rule (`main.py:406-409`) is *"a promise kept only by the client not asking is not kept at all"*, which is exactly why TTS is gated server-side. That reasoning was never applied to the input side. `intake.mode_wants_mic()` (`intake.py:89-93`) already returns the right answer and **is never called on any server path**. |
| **What should happen** | `_mode_is_text(_session_mode(db, session_id))` → 404, same as TTS. |
| **Repro** | Start `session_mode: TEXT` → `POST /session/stt` (403) → `POST /consent {consent_type: voice_recording, copy_version: v0-draft}` → `POST /session/stt` → **200**, Sarvam called. |
| **Evidence** | backend log: `POST https://api.sarvam.ai/speech-to-text` + `stt_attempt session=9a42bc37-... bytes=4100` |
| **Layer** | backend |

---

### QA-08 — The TEXT readout tells the student to answer aloud next time
| | |
|---|---|
| **Severity** | **MAJOR** |
| **Mode(s)** | TEXT |
| **What happens** | The TEXT readout renders a **Delivery Profile** block reading **"Not enough voice data — try answering aloud next session."** The student chose a typing mode and is coached, in their scorecard, for not speaking. `_delivery_profile` runs on every `/session/end` with no mode gate (`main.py:311-333`, `:2255`); `DeliveryBlock` is not mode-gated (`App.jsx:4118-4124`). |
| **Contradiction** | `scoring.py:78-80` states *"the readout NEVER fabricates a voice Delivery metric for a session that had no voice"* — narrowly true (no fake WPM), but the block still appears and still coaches. Migration 009's own header says TEXT delivery metrics are *"NOT computed: inventing a pace score for a typed answer would be a lie with a number on it."* |
| **What should happen** | TEXT readouts omit the Delivery Profile entirely. |
| **Repro** | `python tests/qa_sweep/drive_api.py --mode TEXT` → `POST /session/end` → `delivery`. |
| **Evidence** | `evidence/readout_TEXT.json` → `"message": "Not enough voice data — try answering aloud next session."` |
| **Layer** | backend + frontend |

---

### QA-09 — Pre-flight has a large cream band above the dark lobby
| | |
|---|---|
| **Severity** | **MINOR** (cosmetic, but it is the first screen of a paid product) |
| **Mode(s)** | ALL |
| **What happens** | ~280px of cream/off-white page background sits above the dark lobby panel, with `History` / `Settings` floating in it. Reads as a broken layout / failed load. |
| **What should happen** | The lobby fills the viewport; one background. |
| **Repro** | `python tests/qa_sweep/drive_browser.py --mode AUDIO` → screenshot. |
| **Evidence** | screenshot `AUDIO_2_lobby.png` (scratchpad, not in git) |
| **Layer** | frontend |

---

### QA-10 — The per-question countdown is visible the whole time in TEXT
| | |
|---|---|
| **Severity** | **MINOR** |
| **Mode(s)** | TEXT |
| **What happens** | The `THIS QUESTION 1:07` chip is visible for the entire question, including all 60s of active typing — a clock ticking down at a student mid-sentence. The chip is designed as an "invisible failsafe" that appears only near expiry: `showQChip = qLeft != null && (!voiceMode \|\| qWarnNow \|\| (!recording && !heardSpeechThisQ))` (`App.jsx:3602`). In TEXT, `recording` is always false and `heardSpeechThisQ` is only ever set by the mic meter — so the last clause is permanently true and the design is inverted. |
| **What should happen** | Hidden while the student is engaged; appears at the 30s warning. |
| **Repro** | `python tests/qa_sweep/probe_pacing.py` → `q_chip_visible_while_typing: true` at every sample. |
| **Evidence** | `evidence/pacing.json` |
| **Layer** | frontend |

---

### QA-11 — A TEXT client can fabricate a Delivery Profile (latent)
| | |
|---|---|
| **Severity** | **MINOR** (latent — flag off by default) |
| **Mode(s)** | TEXT |
| **What happens** | `TurnRequest.delivery_metrics` is client-supplied and persisted with no provenance or mode check (`main.py:1142`); `delivery.sanitize` validates shape, not origin. A TEXT turn can POST `{wpm: 155, filler_count: 9, ...}` and have it stored, then rendered as a Delivery Profile for a session with no voice. Driven: sent on a TEXT turn → **not stored**, because `DELIVERY_METRICS_ENABLED` is unset. It is held shut by a flag, not a gate. |
| **Related** | `vyom_messages.input_channel` (migration 009, `'voice'\|'text'`) is a **dead column** — nothing writes or reads it. It is what VIDEO needs to scope delivery to spoken answers only, and it is unimplemented. |
| **What should happen** | Gate on mode; write `input_channel` per answer. |
| **Evidence** | `evidence/db_rows.json` → `messages_with_delivery_metrics: 0` |
| **Layer** | backend |

---

### QA-12 — The attention rebuke is reachable in TEXT by alt-tabbing
| | |
|---|---|
| **Severity** | **MINOR** (not reproduced end-to-end) |
| **Mode(s)** | ALL |
| **What happens** | The level-2 attention line — *"in a real panel this would cost them"* (`presence.py:96-101`) — fires at 3+ `tab_hidden`/`window_blur` events (>2s hidden / >3s blurred, 30s debounce). A TEXT student alt-tabbing to the JD or their notes while composing earns those events. **Not reproduced**: 60s of typing produced no rebuke. Flagged as a plausible path, not a confirmed defect. |
| **What should happen** | Alt-tabbing to read a JD in a typing mode should not read as absence. |
| **Layer** | backend + frontend |

---

### QA-13 — Stale join-error / seatbelt banners survive a restart
| | |
|---|---|
| **Severity** | **MINOR** (not reproduced) |
| **Mode(s)** | ALL |
| **What happens** | `restart()` (`App.jsx:4945-4952`) clears `config`/`sessionId`/`greeting` but **not** `pendingConfig`, `joinError`, or `seatbeltOffer` — so a stale red join-error banner or the gold "Continue in text" offer can persist into a later lobby visit. The **role itself is fresh** (this is the residue of the "stale role on pre-flight" suspect, which did not reproduce). Found by inspection; not driven. |
| **Layer** | frontend |

---

### QA-14 — `/session/clips` has no mode gate (defense-in-depth)
| | |
|---|---|
| **Severity** | **COSMETIC** |
| **Mode(s)** | TEXT |
| **What happens** | `GET /session/clips` takes **no `session_id`** (`main.py:721`), so it cannot know the caller is TEXT; it served 10 synthesized clips to a TEXT session on request. **The client correctly does not call it in TEXT** (0 fetches observed), and the pack is cache-first and boot-warmed, so real spend requires a cold cache. Contained today; it is the one un-gated TTS path, and it contradicts *"TEXT spends nothing at Sarvam. Not 'less' — nothing"* (`intake.py:85`). |
| **Evidence** | `evidence/api_TEXT.json` (10 clips served) vs `evidence/browser_TEXT.json` (`clip_pack_calls: 0`) |
| **Layer** | backend |

---

### QA-15 — TEXT rooms show "Voice settings" and "Toggle captions"
| | |
|---|---|
| **Severity** | **COSMETIC** |
| **Mode(s)** | TEXT |
| **What happens** | Room buttons: `Voice settings, End, Send, Toggle captions, End`. Mic/camera are correctly hidden by `{!textMode && ...}`, but the voice-settings menu (`{sttAvailable && ...}`, `App.jsx:3675`) and captions button (unconditional, `:3890`) are not, so a TEXT student gets "Voice mode / Captions / Interviewer voice" controls for a voice that never speaks. Same root cause as **QA-02**: `sttAvailable` is not mode-aware. Also note `End` renders twice. |
| **Evidence** | `evidence/browser_TEXT.json` → `room_buttons` |
| **Layer** | frontend |

---

## 7. One-page summary — is each mode shippable to 2,500 students next week?

### TEXT — **NO**
Its money promise is real and provable: **zero `getUserMedia`, zero speech calls,
zero audio bytes, `vendor_calls: 0`.** That half of the sprint landed and the
server-side gate is well built. But the student experience is broken in a way that
is worse than a missing feature: **five seconds into every question, a mode that
promised "no microphone needed" accuses them of being on mute** (QA-02) — and if
they pause to read, it takes the question away at 90s (QA-03) while a countdown
ticks at them (QA-10). Their scorecard then coaches them to answer aloud (QA-08).
Must fix: **QA-02, QA-01**. Should fix: QA-03, QA-08, QA-10.

### AUDIO — **NO**
The audio pipeline genuinely works — all three layers, ~400 KB played, no autoplay
block. But **a mode that should ask for a microphone asks 2,500 students for their
camera and opens it** (QA-04), under a consent notice that says it has not passed
legal review (QA-06); when the mic *does* fail, the fallback that is supposed to
rescue the student throws a ReferenceError (QA-05); and **the readout at the end
did not arrive once in six attempts** (QA-01).
Must fix: **QA-01, QA-04, QA-05, QA-06**. Should fix: QA-07.

### VIDEO — **NO**
VIDEO's own contract passes cleanly — mic+camera requested, self-view renders,
audio works, Phase D correctly dark. It fails on what it inherits: **QA-01** (no
readout, 0/6), **QA-05**, **QA-06**.
Must fix: **QA-01, QA-05, QA-06**.

### The one that decides the date

**QA-01 blocks all three modes and is the cheapest to fix.** Today, the more
complete a student's interview is, the more certainly their readout dies — a
20-minute session ends in a 502 and looks abandoned in their history. `max_tokens`
is 2500; the real requirement is ~2631 for 13 answers and grows with every answer.
Nothing here is architectural: raise the cap above worst case, add a retry, add a
fallback so one bad generation cannot destroy a paid session, and stop billing for
failures. Fix QA-01 and QA-02, and TEXT is a week from shippable; add QA-04/05/06
and so are AUDIO and VIDEO.

**Do not ship any mode next week without QA-01 fixed.** A student who finishes the
interview and gets nothing is worse than a student who never started.

---

## Appendix — harness

| File | What it does |
|---|---|
| `tests/qa_sweep/drive_api.py` | Drives a full session per mode over HTTP; asserts each contract cell; reads the DB rows. |
| `tests/qa_sweep/drive_browser.py` | Drives the real app in real Chromium; wraps `getUserMedia` + `play()`; separates the audio layers. `--autoplay-blocked` tests the blocked path. |
| `tests/qa_sweep/probe_pacing.py` | Typing-suppression, chip visibility, rebuke, cold-start timings. |
| `tests/qa_sweep/probe_debrief_cap.py` | Replays the debrief call and reads `stop_reason` — proves QA-01. |
| `tests/qa_sweep/finish_and_verify.py` | Retries `/session/end`, counts billed failures, verifies row-level contract. |
| `tests/qa_sweep/probe_dom.py` | DOM discovery for honest selectors. |

Harness bugs found and fixed while driving (recorded so the numbers are trusted):
the AUDIO/VIDEO "no audio" result was **my driver stopping in the lobby** — the
device grant and the join are two clicks; audio-byte totals read `0` until sized
from `content-length`; the naive device-word scan flagged *"No microphone needed"*
as a defect; the silent-WAV autoplay unlock was miscounted as TEXT playing audio;
and "history has no band" was my own wrong key (`overall_band` vs `band`). Each
would have been a false defect in this register.
