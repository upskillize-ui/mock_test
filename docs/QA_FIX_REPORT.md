# QA_FIX_REPORT.md — every LAUNCH-BLOCKER and MAJOR from the register, fixed

**Sprint:** fix pass over `docs/QA_BUG_REGISTER.md`, 2026-07-17.
**Scope:** all 5 launch-blockers + all 3 majors. One commit per defect (or tight group),
each named for its register ID.
**Verification:** the register's own harness (`tests/qa_sweep/`), re-driven — real
sessions, real Chromium, real vendors. Not the unit suite alone: the suite passed 377/377
on the day the register was written, while AUDIO and VIDEO could not produce a readout at
all.

**Suites:** 386 backend (was 377: +9), 106 frontend (was 103: +3). All green.
**Deployed:** pushed to `hf` on explicit confirmation — `abe6b6a..6a7b621`, 14 commits (HF
was six behind origin from earlier sprints). No pre-receive rejection: the range is
text-only, checked before pushing, because one raw binary in the *history* of a pushed
range permanently blocks every future deploy (this has already happened twice — see
`.gitignore`). Verified live by **behaviour, not `/health`**: `/health` returned 200
immediately, which proves only that *a* container is up. The decisive marker is
`/session/reask kind=mute` → **404** on production (it was an unconditional 200 before, so
unlike `stt_available` it cannot be faked by a flag being off). Pending: `git push origin
main` — blocked by the sandbox's permission classifier, 8 commits still queued locally.

---

## The one-line version

Every mode now completes an interview and returns its readout on the **first** attempt.
TEXT no longer accuses a typing student of being on mute, no longer takes their question
away for thinking, no longer reaches Sarvam, and no longer tells them to answer aloud.
AUDIO no longer asks 2,500 students for a camera it never opens. The rescue for a broken
mic no longer throws.

**Two of my own fixes were caught by re-driving, not by the suite** — see *What driving
caught that tests didn't*. That is the headline for anyone deciding how to verify the next
sprint.

---

## Per-defect

### QA-01 — a completed interview returned no readout · `c5d3bd7`, `f1552bb`
**Was:** `/session/end` 502'd **6/6** on AUDIO and VIDEO. The session stayed `active`
forever, so a finished interview read as abandoned in history, and every retry billed
another Sonnet call.

**Root cause (proven, not inferred):** `max_tokens=2500` against a readout needing ~2631
output tokens for 13 answers. `perAnswerScores` carries one entry per answer, so the
requirement grows with the interview — the cap fit a short session and truncated a
complete one. The student who answered everything was the most certain to lose their
readout.

**Fix:**
- `_DEBRIEF_MAX_TOKENS = 8000`, sized against `MAX_ANSWERS_PER_SESSION` (20), not the
  typical case. `max_tokens` is a ceiling, not a spend — the headroom is free, and it
  stays under the ~16k line where a non-streaming call risks an HTTP timeout.
- One retry on unusable JSON.
- `claude_client` now logs `stop_reason=max_tokens`. The product discarded it, which is
  exactly why a truncation read as "the model returned garbage" for a whole sprint.
- **`_DEBRIEF_TIMEOUT` (240s read).** See below — this half was found by re-driving.
- **No stored fallback, deliberately.** Storing an unscored card so the session could
  finalise would be replayed forever by the cost guard, permanently locking a 13-answer
  student out of the readout they earned. A retryable 502 beats a stored lie.

**Now:** `end attempts=[200]` in all three modes, first try. The two sessions that failed
6/6 were rescued in place (`active → completed`, benchmark 72).

### QA-02 — "You're on mute", in a mode with no microphone · `85ba80b`
**Was:** ~5s into every question, before the student touched the keyboard, in a mode whose
pre-flight promises *"No microphone needed, so we won't ask for one."* Reproduced at 3.6s
and again at 93.8s on the next question. Typing suppressed it — so it hit precisely the
student who was reading and thinking.

**Four gates failed open at once.** Each is fixed at its own layer:
1. `stt_available` answered *"are the flags on?"*, never *"can this session use STT?"* —
   now mode-aware.
2. `_build_state` let callers omit the mode; half of them pass a synthetic dict where
   `row.get("session_mode")` is `None`, which reads as "not TEXT". **That is why the
   client saw `stt_available` flip back to `true` after the first turn.** The mode is now
   a **required keyword** — forgetting it is a TypeError the tests catch, not a wrong
   answer a student hears. It immediately caught two callers and one existing test.
3. The client guard was `if (!voiceMode || micOn || typingNow) return;` — TEXT is
   permanently `micOn:false`, so the mic check **passed rather than blocked**. A mic-off
   test cannot gate a mode with no mic.
4. `/session/reask` had no mode check, so the line was returned and printed even though
   TTS correctly silenced it. Now 404s server-side.

Plus the persona itself carried the mute line in **every** mode's cached system prompt —
`build_persona` never read the mode (`session_mode` wasn't even in `cfg`; `mode` there is
the *feedback style*, one letter apart).

**The `voiceMode` split is the load-bearing part.** It meant two things at once — *the
room is live* and *voice is usable* — and the room renders on it. Making `stt_available`
honest without splitting it would have dropped TEXT into the old chat log. Now: `roomMode`
(all three modes) and `voiceLive` (never TEXT).

**Now:** 105s idle in TEXT → **zero device lines**, `stt_available=false` throughout.

### QA-03 — TEXT stopped timing thought · `89176ce` *(your design)*
**Was:** the per-question clock is a **voice** clock. In a spoken interview, elapsed time
and thinking time are the same thing because silence is the signal. In a typed one they
are not — reading, thinking and typing all cost wall-clock and none is disengagement. A
student who read a case prompt for 90s had the question taken away, auto-submitted as
"(No answer — the time on this question ran out.)".

**Now:** in TEXT the deadline counts **continuous inactivity**; every keystroke pushes it
out. One gentle nudge at 75s of true idle ("Take your time — type when you're ready"),
once per question, naming no device. The expiry ladder fires only after 3 minutes of
continuous idle, unchanged (draft → partial, empty → skip). The session clock remains the
real limit.

The pre-flight promised *"Every question is timed the same way"* — true, and exactly the
problem. It now reads *"Take the time you need to think and type — your session length is
the only clock."* **Verified: 105s idle no longer loses the question.**

### QA-04 — AUDIO asked 2,500 students for their camera · `512eec0`
**Was:** the AUDIO pre-flight's primary, highlighted CTA was "Allow mic & camera", so the
default path raised a real camera prompt and opened the device — instrumented
`getUserMedia({audio:true, video:{640x480, facingMode:"user"}})`, plus two video-only
calls for the self-view. "Mic only" existing as the *second* button is not the same
promise as never asking.

The whole AUDIO/VIDEO device split was **one string**: `isVideo` appeared exactly once in
`Lobby.jsx`, as a button label. It now decides the device story — consent copy, the
attention-cue paragraph, the primary CTA, the camera pill, the CAMERA OFF label. In the
room the mic and camera buttons shared one `!textMode` gate; the camera is now VIDEO's.
`camOn` is derived `config.camera && videoMode` — belt to the lobby's braces, since the
self-view opens the camera from that flag alone.

**Now:** AUDIO requests `{audio:true}` only, no camera copy — while still playing 377KB
with 0 rejections. VIDEO unchanged.

### QA-05 — the rescue for a broken mic threw · `512eec0`
**Was:** `voiceFallback` called `setTypeOpen()` — one reference in the codebase, **zero
definitions**. So "a voice failure is never a dead end" threw a `ReferenceError` on every
STT failure and mic denial: the student with the broken mic got precisely the dead end the
function exists to prevent.

**Now:** calls `openChat()` (opens the panel, lands the caret in the composer).

**The register could only flag this by inspection** — our fake mic never failed. It is now
driven for real (`probe_voice_fallback.py`: Chromium with no mic permission, so
`getUserMedia` rejects like a blocked or claimed device). Before/after on the same harness:

| | `ReferenceError: setTypeOpen is not defined` | composer offered |
|---|---|---|
| before | **×7** | no |
| after | 0 | yes |

### QA-06 — students read our internal process notes · `89176ce` *(partially deferred — see below)*
**Was:** "DRAFT NOTICE — PENDING LEGAL REVIEW" rendered to students on the AUDIO/VIDEO
pre-flight, and "(Draft notice — pending legal review.)" in the setup consent — asking
students to consent under a notice that says on its face that it is not approved.

**Fix (your call — "dev-gate + write TEXT consent copy"):** both markers are dev-gated,
matching the `isDev` pill this file already had. Vite strips the string from the
production bundle entirely (`grep dist`: **0 hits**), confirmed by driving the real
production build.

**And the larger, untitled half:** TEXT had **no consent copy at all** — the whole DPDPA
panel sat inside the non-TEXT branch, so a typing student was told nothing about what
happens to what they write. TEXT now carries retention/deletion copy mirroring the setup
notice, minus the devices it doesn't have.

> **QA-06 is NOT closed.** Hiding the marker does not grant the sign-off. The consent copy
> — all four blocks, including the new TEXT one — is unchanged and still `copy_version:
> "v0-draft"`. **Legal sign-off remains an open launch-blocker owned by legal**, and it has
> the longest lead time of anything left. When copy is approved: swap it in and bump
> `CONSENT_COPY_VERSION` so the new wording is pinned in `vyom_consents`.

### QA-07 — a TEXT session could spend Sarvam STT · `fb07678`
**Was:** `/session/stt` and `/session/stt/partial` had no mode check. Gates were flags →
ownership → **consent** → caps, and voice consent is **per-user and durable**: a student
who ever did one AUDIO session carries it into every TEXT session afterwards. So the only
thing between TEXT and the vendor was a wall already walked through. The sweep drove it:
consent → 200 → `POST https://api.sarvam.ai/speech-to-text`, from a TEXT session.
Exposure: 25 answer calls + 400 partials per session.

**Fix:** both endpoints call `intake.mode_wants_mic()` — which returned the right answer
since the day it shipped and **was called by nothing**. The gate goes **before** consent,
or the durable-consent hole stays open; a test pins that ordering.

**Now:** TEXT → 404 on both, zero vendor calls, *with consent granted*. AUDIO → 200 and
reaches Sarvam as it should.

> **Severity correction — QA-07 was LIVE in production, not latent.** The register hedged
> this ("gated by flags off by default"), and I carried the hedge into the deferred notes
> as something for you to confirm. Confirmed at deploy time instead: production reports
> `stt_available=true` for AUDIO, so `STT_ENABLED` and `VOICE_ENABLED` are **on** in the
> Space. Every student who had ever granted voice consent could have spent Sarvam STT from
> a TEXT session — up to 25 answer calls + 400 partials each. The hole was real and open
> until this deploy; it is closed now.

### QA-08 — the typed readout told them to speak up · `fb07678`
**Was:** "Not enough voice data — try answering aloud next session" on the scorecard for
the typing mode they chose. `_delivery_profile` ran for every mode, and `DeliveryBlock`
had three branches all reporting on a voice a typed session never had — including the
"kind" one.

**Fix:** the server no longer queries delivery metrics for TEXT (a test asserts it, by
handing it a DB that throws); the client omits the block on a TEXT profile. `scoring.py`
already promised the readout *"NEVER fabricates a voice Delivery metric for a session that
had no voice"* — this applies that rule to the block, not just the numbers in it. The
empty dict still carries the **internal TTS meter**, which is the thing that proves TEXT
spent nothing.

**Now:** TEXT `delivery` keys are `['tts']`, no "aloud" anywhere. AUDIO keeps its profile.

---

## MINORs fixed in passing (trivial, same files)

| ID | What | Where |
|---|---|---|
| **QA-10** | The per-question countdown sat on screen the whole question in TEXT — its dead-air clause is a voice failsafe and was permanently true. Now appears at the 30s warning only. | `85ba80b` |
| **QA-15** | Voice-settings and captions controls removed from the TEXT room (captions caption a spoken line). | `85ba80b` |
| **QA-11** | `delivery_metrics` is client-supplied and `sanitize()` validates *shape, not provenance* — a TEXT session could POST `{wpm:155}` and have it rendered. "Typed answers stay NULL" was true only because a typed client doesn't send the field. Now gated on mode. | `f1552bb` |
| **QA-13** | `restart()` carried a stale join-error / seatbelt banner into the next lobby — a warning about a failure that already happened, shown to someone who hasn't failed yet. | `f1552bb` |

Also fixed as part of QA-02: the **90s silent-abandon timer** armed in TEXT ("two dead
channels" presumes a second channel; TEXT's mic is off by definition, so it read every
reading student as an abandonment).

---

## Deferred, and why

| ID | Sev | Why it's still open |
|---|---|---|
| **QA-06 (legal)** | **BLOCKER** | The *code* is fixed; the **copy is not approved**. Not mine to sign. Start it now — longest lead time of anything left. |
| **QA-09** | MINOR | ~280px cream band above the dark lobby. Not trivial: it's a layout interaction between the lobby's `minHeight: calc(100vh - 70px)` and the app shell, and per your rule I didn't let cosmetics delay blockers. First screen of a paid product — worth a small dedicated pass. |
| **QA-14** | COSMETIC | `/session/clips` takes **no `session_id`**, so it cannot know the caller is TEXT — closing it properly needs a signature change, not a gate. Contained: the client correctly doesn't call it in TEXT (0 fetches), the pack is cache-first and boot-warmed. Still the one un-gated TTS path. |
| **QA-12** | MINOR | Never reproduced (60s of typing produced no rebuke). The attention ladder needs 3+ tab-hide/blur events; alt-tabbing to a JD in a typing mode is a plausible path, not a confirmed defect. Would need a dedicated focus-event drive. |

**Browser-setting defects: none.** Your rule (detect and explain them in the pre-flight
rather than "fix" them) had nothing to bind to — the register attributed no defect to a
browser setting. The nearest candidate, autoplay, was tested explicitly and **passes**:
with `--autoplay-policy=document-user-activation-required` playback still succeeds,
because the student's own clicks supply user activation before the first audio. The
pre-flight already detects and explains the real device failures — a denied mic produces
"No mic or camera access. You can still do the full interview by typing", which QA-05's
probe now asserts.

---

## What driving caught that the tests didn't

Both of these were **my own fixes**, and both passed every unit test at the moment they
were wrong.

1. **QA-01's cap fixed the truncation and created a timeout.** With the model free to
   write a complete readout, a fresh TEXT session still 502'd — now on an httpx **read
   timeout**. `claude_client` hardcodes `read=60.0` for every call: right for a turn,
   wrong for one long non-streaming generation where the read clock covers the model's
   entire writing time. It was already marginal (~50s at the old cap). I had traded a
   truncated readout for a timed-out one — the same 502 wearing a different hat — and
   would have shipped it. The measurement that settles it: the readout takes **55.1s**.
   60s never had headroom.
2. **A stale `uvicorn` masked the QA-01 fix.** The first verification run showed 502 and
   the old log string. The fix was fine; my server wasn't. Had I trusted the run, I'd have
   "re-fixed" a working fix.

Also worth recording: **my own guardrail text tripped my own test.** The first TEXT
persona said *"never say they are muted"* — and `build_persona`'s docstring already
explains why that's wrong: the word "cheating" *"appears nowhere — not even to forbid it,
because naming it primes the model to echo it."* The TEXT block now names no device at
all.

---

## Regression proof — the register's launch-blockers

Same harness, same cells. `before` = `docs/QA_BUG_REGISTER.md`; `after` = re-driven today
(browser cells against the **production bundle**).

| Cell | Before | After |
|---|---|---|
| `/session/end` — TEXT | 502 (intermittent) | **`[200]`** first try |
| `/session/end` — AUDIO | **502 × 6** | **`[200]`** first try |
| `/session/end` — VIDEO | **502 × 6** | **`[200]`** first try |
| Debrief row (all modes) | AUDIO/VIDEO: **no row** | benchmark 56/72/72, `weights_version 2026.07-2`, `scored` |
| Session status after end | AUDIO/VIDEO stuck **`active`** | **`completed`** |
| History row | "active", duration null | band + benchmark, `completed` |
| TEXT: device lines in 105s idle | **"You're on mute"** @5s, again @93.8s | **`[]`** |
| TEXT: `stt_available` | **true** (then flipped true mid-session) | **false** throughout |
| TEXT: `/session/reask kind=mute` | **200** + "You're on mute" | **404** |
| TEXT: question after 105s idle | **taken away** @90s | **still theirs** |
| TEXT: per-question countdown | **visible all question** | hidden until 30s warning |
| TEXT: voice-only controls | Voice settings, Toggle captions | **none** |
| TEXT: `/session/stt` **with consent** | **200** → Sarvam called | **404**, zero vendor calls |
| TEXT: readout delivery | "try answering aloud next session" | keys `['tts']` only |
| TEXT: consent copy | **none at all** | present |
| TEXT: zero audio bytes / `vendor_calls` | 0 ✓ | **0 ✓ (not regressed)** |
| AUDIO: pre-flight | **"Allow mic & camera"** + camera copy | **"Allow mic"**, mic only |
| AUDIO: `getUserMedia` | `{audio, video:{640x480}}` | **`{audio:true}`** |
| AUDIO/VIDEO: DRAFT NOTICE | **visible** | **absent** (0 hits in `dist`) |
| Voice-failure rescue | **ReferenceError ×7**, no composer | 0 errors, composer opens |
| AUDIO audio pipeline | 3 layers pass (399KB) | **3 layers pass (377KB)** |
| VIDEO audio pipeline | 3 layers pass (420KB) | **3 layers pass (396KB)** |
| `/session/clips` in TEXT | 10 clips served | 10 clips served — **QA-14 deferred** |

**Suites:** backend 377 → **386**; frontend 103 → **106**. All pass.

New tests, chosen to fail if the *cause* returns rather than the symptom: `_build_state`
refuses to guess the mode (signature-level); the STT mode gate precedes the consent gate
(ordering-level); the TEXT persona names no device; `_delivery_profile` doesn't even query
in TEXT; the idle ladder's thresholds. `probe_voice_fallback.py` is QA-05's regression
test.

---

## Is each mode shippable to 2,500 students next week?

The register said no to all three. Every engineering blocker it named is now closed and
proven closed. One non-engineering blocker remains, and it is the same one for all three.

### TEXT — **yes, on legal sign-off**
Its money promise still holds and is still provable (zero `getUserMedia`, zero speech
calls, zero audio bytes, `vendor_calls: 0`) — and the experience now matches it. Nobody is
told they're on mute; nobody loses a question for thinking; the readout doesn't tell a
typing student to speak up; and it now says what happens to what they write.

### AUDIO — **yes, on legal sign-off**
Asks for a microphone and only a microphone. All three audio layers pass. A dead mic gets
a composer instead of a ReferenceError. The readout arrives first try.

### VIDEO — **yes, on legal sign-off**
Its own contract always passed; it failed on what it inherited (QA-01, QA-05, QA-06). Two
of three are fixed.

### The one thing standing between you and the date

**Legal sign-off on the consent copy (QA-06).** Not a code change and not mine to make.
Four blocks need approval — the setup consent, the mic copy, the camera/attention-cue
copy, and the new TEXT copy — after which the swap is `CONSENT_COPY_*` plus a
`CONSENT_COPY_VERSION` bump so the wording is pinned in `vyom_consents`. **Start it today;
it has the longest lead time of anything remaining.**

Recommended before launch, none blocking: **QA-09** (the cream band is the first thing a
student sees) and **QA-14** (the last un-gated TTS path). **QA-12** deserves one focus-event
drive to settle whether alt-tabbing to a JD earns a rebuke.

### Two operational notes

- **Deployed.** `hf push` done on explicit confirmation and verified live by behaviour
  (see the header). `git push origin main` is still blocked by the sandbox's permission
  classifier — **8 commits are queued locally**; run `! git push origin main` or grant a
  Bash rule. GitHub is currently behind what production runs.
- **Production's voice flags are ON** — confirmed at deploy time, not assumed. That
  settles the register's hedge: **QA-07 was live, not latent** (see above). It also means
  the QA-02 mute fork was firing at real TEXT students in production, not just locally.

---

## Appendix — harness changes

Test-only; no product code.

| File | Change |
|---|---|
| `tests/qa_sweep/probe_voice_fallback.py` | **New.** Drives the voice-failure path with a denied mic — QA-05's regression test. |
| `tests/qa_sweep/drive_browser.py` | `QA_BASE_URL` so the same drive runs against the production bundle (a dev-gated notice can only be judged there); taught it AUDIO's new "Allow mic" CTA; stopped the QA-05 toast assertion racing a 4s toast. |
| `backend/tests/test_intake_and_modes.py` | +6: `_stt_available` mode/flag matrix, `_build_state` signature, STT gate ordering, `mode_wants_mic`, TEXT delivery. |
| `backend/tests/test_persona.py` | +2, and one rewritten: it **asserted the bug** (`assert "You're on mute" in s`). Now asserts the contract — present for AUDIO/VIDEO, absent for TEXT, spoken default when the mode is unknown. |
| `backend/tests/test_stt.py` | One test updated: `_build_state` now requires the mode, and this test had to say which one it meant (the required-kwarg change caught it). |
| `frontend/src/roomPolicy.test.mjs` | +3 for the TEXT idle ladder. |

**Re-running the sweep:** needs backend on `:8000` and vite on `:5173`. It costs real
Sonnet + Sarvam money — which is why none of it lives under `backend/tests/` or is named
`test_*`. For production-bundle runs: build with `VITE_INTERVIEWIQ_API_URL` set, or the
bundle points at the **live hf.space deployment**; and vite preview's port must be in the
backend's `ALLOWED_ORIGINS` or CORS silently eats every call and the room never loads
(both cost me a confusing run).
