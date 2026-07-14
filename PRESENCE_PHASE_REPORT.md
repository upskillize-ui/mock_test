# PRESENCE_PHASE_REPORT.md — make it feel like a person, start to finish

Five items from founder UAT (the six-question silent session). All five shipped, plus a
schema-drift check and a capture invariant added on request (§6, §7).
Suites green: **239 backend** (was 163) + **55 frontend** (was 24). Nothing pushed to hf.

Every number below is **measured**, not estimated — against the real backend, the real
Anthropic API, the real Sarvam vendor and the real database. The tools are committed
(`scripts/measure_start_latency.py`, `scripts/presence_smoke.py`) so they can be re-run.

---

## 1. FAST START — measured start latency, before vs after

The complaint was one sentence: *the loading spinner is too long*. Measured, it was
**14.5 seconds** from clicking Join to hearing the first word. Every one of those seconds
was self-inflicted: `/session/start` was doing three things at once — writing a session row
(fast), calling an LLM to improvise a greeting (slow), and waiting for **every sentence** of
that greeting to be read aloud by a voice vendor (slower still). Nothing about a session row
needs an LLM, and nothing about the first spoken word needs sentence four to exist.

### The numbers (median of 3-6 cold sessions each; a fresh greeting is never a cache hit)

| | BEFORE | AFTER |
|---|---|---|
| **Click → room on screen** | **14.5s** (blocked on everything) | **0.15s** |
| **Click → first audible word** | **14.5s** | **3.72s** |
| `POST /session/start` | 14.5s (LLM + all TTS) | 0.15s (the session row, nothing else) |
| `POST /session/greeting` | — | 3.38s (kickoff LLM + sentence one) |
| `GET /session/audio/{..}` | 0.03s | 0.03s |

Raw runs, after: first word at 2.67 / 3.34 / 3.46 / 3.98 / 4.01 / 7.76s. The spread is
Anthropic's generation latency and is not ours to control; the median is **under the 4s
target**, and the room itself is up in **150ms, every time**.

**Verified in a real browser** (Playwright, full setup → lobby → join): room on screen
**890ms** after the Join click, "connecting" band shown, then captions advancing
sentence-by-sentence in lockstep with the audio. No JS errors.

### What actually changed

1. **`/session/start` returns the session row and nothing else.** The room renders on it —
   interviewer tile up, `thinking` pose, a "connecting" shimmer on the caption band. She is
   on screen, visibly composing, instead of a spinner being on screen.
2. **`POST /session/greeting`** (new) runs the kickoff LLM. Idempotent — a double-fire, a
   retry or an impatient refresh returns the greeting the session already has, and never
   buys a second LLM call or invents a second interviewer.
3. **The kickoff is now STREAMED, and `opening` is the first key in its JSON.** This is the
   lever that bought the last four seconds. The interviewer's opening *sentence* exists
   about a fifth of the way into the generation — so we send it to the voice vendor **there
   and then**, and the 1.8s of synthesis runs *underneath* the remaining seconds of writing
   instead of queueing behind them.
4. **Only sentence one is awaited.** The rest come back marked `pending` and are synthesised
   by `POST /session/speech` **while sentence one is playing**. (`pending` is deliberately
   distinct from a null `audio_url` with no flag, which means synth *failed* — the client
   waits for the first and skips past the second.)
5. **The opening is capped at 2-3 sentences** — the same limit the persona already puts on
   every other turn ("2-3 SHORT sentences, then STOP"). It allowed four, and measured
   openings were running to **five**: a paragraph delivered at someone who has just sat
   down. Fixing that is worth ~0.6s *and* is the more human thing anyway.

`/session/speech` takes an **INDEX, never text**. That is the whole security story: it
re-derives the sentence server-side from the reply already stored for that session, so it
cannot be handed a string and made to bill us for reading it aloud.

---

## 2. ENGAGEMENT FLOOR — the test matrix

A real panel never asks six questions into silence. Ours did: it marched down the round
list, paying for an LLM call and a TTS bill on every question nobody heard.

**The counter is DERIVED, not stored.** Consecutive silences are the trailing run of skip
markers in the transcript. That is the whole design, and it is why *"any response resets the
counter"* needed no code at all — a real answer breaks the run **by existing**. It also means
this sprint adds **zero migrations**.

| # | Rule | Test |
|---|---|---|
| 1 | 2 consecutive silences, nothing substantive all session → **CHECK-IN** | `test_two_consecutive_silences_in_a_blank_session_trigger_the_checkin` |
| 2 | The check-in **replaces** the next question — it does not ask one | `test_the_checkin_replaces_the_next_question_entirely` |
| 3 | It carries its own **45s** clock, not the round's 180s | `test_the_checkin_carries_its_own_short_clock`, `roomPolicy: a check-in gets its own short clock` |
| 4 | **Any** response resets it — voice, typed, even a bare "yes" | `test_any_response_at_all_resets_the_counter_including_a_bare_yes` |
| 5 | ...but "yes" is a *response*, not a *substantive answer* (it must not buy the looser threshold) | `test_a_bare_yes_is_a_response_but_it_is_not_a_substantive_answer` |
| 6 | The resumed turn asks the **next planned question**, not a step-down | `test_the_resumed_turn_asks_the_next_question_not_a_step_down` |
| 7 | A **third** consecutive silence → courteous EARLY_WRAP | `test_a_third_consecutive_silence_wraps_the_interview` |
| 8 | The wrap never scolds, accuses, or speculates | `test_the_wrap_is_courteous_and_never_blames_them` |
| 9 | Scored honestly — nothing is zeroed as a punishment | `test_the_wrap_is_scored_honestly_not_zeroed` |
| 10 | **Substantive answers earlier → 3 silences** before the check-in (freezing on a hard question deserves more rope than a blank session) | `test_a_candidate_who_has_answered_gets_a_third_silence_before_the_checkin` |
| 11 | One real answer is enough to earn that rope | `test_one_substantive_answer_is_enough_to_earn_the_rope` |
| 12 | REVERSE is exempt (the question there is *theirs*) | `test_the_reverse_round_is_exempt` |
| 13 | The floor holds in every answering round | `test_the_floor_holds_in_every_answering_round` |
| 14 | Engagement outranks the timeout note AND the presence ladder | `test_the_engagement_action_outranks_the_timeout_and_presence_directives` |
| 15 | An ordinary turn is completely untouched by any of it | `test_an_ordinary_turn_is_completely_untouched_by_all_of_this` |

**Verified end-to-end against the live model** (`scripts/presence_smoke.py`):

- silence #1 → *"We're out of time on that one — let's move on. Tell me about..."* (a normal question)
- silence #2 → **CHECK-IN**: *"Asha, I want to make sure you're still with me — is everything okay on your end? Shall we..."* (`question_kind: "checkin"`, `checkin_seconds: 45`)
- silence #3 → **WRAP**: *"Thanks for joining — I think we'll wrap here for now. The feedback will still be useful..."* (`next_action: "readout"`, `early_wrap_reason: "disengaged"`, persisted — a refresh cannot dodge it)
- and the reset: a bare **"yes"** → *"Good. Let me start fresh then. Tell me about yourself..."* — the march simply resumes.

**Cost.** The check-in is **free**: it replaces the stage directive on a turn that was already
going to call the model. What it *saves* is the LLM+TTS spend on every remaining question that
would otherwise have been asked, and spoken aloud, to an empty room. A blank 20-minute session
used to run the full round plan; it now ends after three turns.

---

## 3. REALISM PACK

### (a) Acknowledgment clips — cache contents + size

Pre-cached at boot, fire-and-forget (a vendor outage at boot costs the acknowledgments and
nothing else). Played **the instant an answer is submitted**, on a seeded rotation, while the
real reply generates — so the thinking gap sounds like a person considering rather than a
machine loading.

```
CLIP PACK — 16 clips, 205.7 KB total on disk, synthesised ONCE for the life of the cache

  female (ritu)                              male (shubh)
    Hmm.                      12.7 KB          Hmm.                      11.4 KB
    Okay.                      9.8 KB          Okay.                     11.4 KB
    Right.        [+backchan] 13.9 KB          Right.        [+backchan] 12.7 KB
    Accha.                    13.9 KB          Accha.                     9.8 KB
    Got it.                   11.4 KB          Got it.                    9.8 KB
    Interesting.              15.1 KB          Interesting.              15.1 KB
    Let me think about that.  18.0 KB          Let me think about that.  18.0 KB
    Mm-hmm.       [+backchan] 11.4 KB          Mm-hmm.       [+backchan] 11.4 KB

boot log: clip pack: 8 lines x 2 voices -> warmed=15 cached=1 failed=0 (205.7 KB on disk)
```

Both backchannel lines are *also* acknowledgments, and the cache is content-addressed — so
they are one clip each, not two. 8 clips per voice, 16 total, **for the life of the product**.
They are served un-metered (`tts.get_shared_audio_hash`): billing 16 shared clips against
whichever candidate happened to open the app first would make the per-session cost meter lie,
and that meter is what the Sarvam credits application is built on.

### (b) Listening backchannels

A soft "mm-hmm" at a natural pause inside a long answer, played at 32% volume on its own
audio element. Every condition exists to stop it becoming an *interruption*, which is worse
than saying nothing: answers longer than **20s** only, pause longer than **1.2s** but strictly
**under the 2.5s end-of-answer threshold** (that silence belongs to the end-of-answer detector
— stepping on it would cut off the answer we asked for), never in the first **10s**, at most
**twice** per answer. Runs off the RMS the waveform already computes, so it costs nothing.

### (c) Barge-in

The mic is held open **while the interviewer speaks**, for exactly one purpose: to hear whether
the candidate has started talking over her. When they have, she **ducks out over 200ms** (a hard
cut sounds like a crash; a fade sounds like someone stopping because you started), abandons the
remaining clips, and the floor is theirs. She does **not** re-say the sentences she was
interrupted out of, and the caption shows only what she **actually said aloud** (`spoken_prefix`)
— captioning the rest would be captioning words the candidate never heard.

The open mic is handed **straight to the recorder** rather than re-acquired, because a second
`getUserMedia` costs ~200ms and those 200ms are their opening word.

The threshold is deliberately high (**RMS > 0.06, sustained 300ms** — 3x the silence floor) and
every mic is now opened with `echoCancellation`. Without that, the interviewer hears *herself*
coming out of the same laptop, concludes she has been interrupted, and stops talking — to
herself.

### (d) Question cadence

The beat before a new question rises from **700ms → 1100ms** when the previous answer was
substantive. A person absorbs an answer before firing the next question; firing at 700ms after
someone has just explained something for two minutes is the "scripted next-next" feel, in one
number. **After a skip it stays at 700ms** — there was nothing to absorb.

---

## 4. CRITICAL — the pressure panel

A fourth difficulty, after Stretch. Selector card reads *"Critical — Pressure panel. Your
answers will be challenged and criticised. Not a gentle experience."* and requires a **second,
explicit tap** ("I want the pressure panel") — verified in the browser: the confirmation
genuinely gates it. Nobody lands here by accident, and nobody lands here uninformed.

- `tone_hint` → new value **`critical`**. The pressure panel **never softens** — not in the
  warm-up, not in the greeting (a smiling opener would be a bait-and-switch on someone who
  asked to be put under pressure). Poses default the face to **`intense`** while speaking.
- **Two curveballs, not one.** Composure under a single surprise is luck.
- Persona addendum (this mode **only** — asserted absent from Easy/Realistic/Stretch): challenge
  every substantive answer at least once; open scepticism of weak reasoning; interrupt rambling
  after ~90s with a redirect; blunt reactions.
- The readout **names the mode**: *"You chose the pressure panel — here is what held up under it
  and what cracked."* — scored honestly against the bar they asked for, written in the **same
  mentor voice** as every other readout.

### The guardrails did not move — this is the half that matters

`tests/test_critical.py` is 22 tests, and the load-bearing ones are not the ones proving the mode
is tough. *"Be harsh with them"* is one bad prompt away from cruelty, and the person on the other
end is a job-seeker who already feels precarious.

- Criticism lands on the **ANSWER** and the **REASONING**. **Never** on the person. (Stated in the
  prompt as a worked example, because the abstract rule is easy to nod along to and then violate.)
- Banned vocabulary — no insults, no mockery, no sarcasm, no contempt — binds all four modes.
- The **attribution ban** holds in Critical *most of all*: no emotion attribution, ever. Under
  pressure is exactly when a model would try to tell someone they seem rattled.
- **Never a word** about their background, English, accent, or college. For an Indian hiring
  product this is the failure mode that would actually hurt somebody.
- A frustrated or rude candidate is *still met calmly* — the mode does not get to escalate.
- "Never shame a wrong answer" holds in **every** mode. What Critical drops is the *gentleness of
  the probe*, not the *protection of the person being probed*.
- Easy mode is asserted **byte-for-byte unchanged** — it is the mode a nervous fresher meets.

### Sample exchange (real session, real model, `difficulty: Critical`)

> **RIYA:** Hi Asha, I'm Riya. We're wrestling with a real problem on our team right now — we've
> got portfolios where the traditional risk buckets work fine, but the moment you layer in
> macroeconomic stress or a sector shock, the correlations we thought we understood just collapse.
> Before we dig into your background, I want to know: when you've looked at credit risk in your
> work, what's been the messiest assumption you've had to revisit once you actually saw it play out
> in the data?
>
> **ASHA:** We'd use a logistic regression on bureau score and DPD buckets. Our model gets about
> 85% accuracy, which is pretty good for this book.
>
> **RIYA:** Eighty-five percent on a portfolio like that — fair enough as a baseline. But here's
> what I'm probing: accuracy on **what** exactly? Are you measuring default prediction on a held-out
> test set, or are you looking at how well the model actually *ranks* risk within your portfolio?
> Because I've seen teams hit 85% accuracy and still miss half the defaults that matter. What does
> "good for this book" mean to you — good relative to what benchmark?
>
> **ASHA:** Honestly the 15% we get wrong is mostly small-ticket, so the rupee impact is limited.
> We just absorb it in provisioning.
>
> **RIYA:** Right — so you're trading prediction precision for provisioning buffer. That's a real
> trade-off, not an evasion. Fair. Let's switch gears. [...one curveball, in full...]

That is the register the mode is for: it goes after the *number* and the *reasoning*, it concedes
when the candidate is actually right ("that's a real trade-off, not an evasion"), and it never once
touches the person. The toughest **fair** interviewer they will meet — not an unkind one.

---

## 5. ROSTER WEIGHTING — posed characters first

`pickInterviewer` now weights characters with a **full pose set 3x** within the eligible pool.
Female/Realistic is `{priya, riya, meera}`; only Riya has a pose grid on disk, so she is 3 of 5
slots — **60%, a majority**. A Female/Realistic session is now usually Riya, and the founder will
actually *see* the pose system instead of drawing an un-posed character and concluding it never
shipped. Un-posed characters stay in the pool: weighting is not exclusion.

Critical was also added to the `temperaments` of the characters that **have an `intense` pose**
(Riya, Meera, Vikram) — the mode's whole face is that frame, and a character without it would run
the pressure panel smiling.

**This is scaffolding with a delete-by date.** When the cast's pose grids land, set `POSED_WEIGHT`
to `1` (one constant, `posePolicy.js`) and the roster is uniform again. The two tests that pin the
weighting go with it.

---

## 7. THE CAPTURE INVARIANT (added on request)

> **The mic never opens while the interviewer still has words she has not said.**

Adding this as a regression test found that **three of the six arming sites were violating
it**: unmuting mid-reply, tapping the mic mid-reply, and accepting the voice-consent modal
mid-reply all called the recorder immediately. The recorder then captured *the interviewer's
own voice* coming out of the laptop speakers, the trailing-silence detector "heard" her stop,
and the whole thing was submitted as the candidate's answer to the question she was still in
the middle of asking.

It had been enforced by **convention** — every arming site remembering to check
`audioPlaying` — which is the kind of rule that holds right up until someone adds a seventh
arming site. It is now enforced three ways.

### 1. Policy — one function, and it is the only decision

`roomPolicy.canArmCapture()` (pure, tested). Three distinct states mean "she is not finished",
and any one of them shuts the mic:

| state | meaning |
|---|---|
| `connecting` | FAST START: the room is up but her opening has not arrived. **The session row already says it is the candidate's turn. It is not.** |
| `speaking` | a clip is in the air right now |
| `speechQueued` | her reply has ARRIVED but playback has not begun — a few milliseconds wide, and exactly the window a React state update slips through |

All three are tracked in **refs, not state**: the mic is armed from callbacks and rAF loops
that would otherwise read the previous render's value, and one stale read is a recording over
the top of a question.

### 2. Structure — one door, and the test slams it

`beginRecording` is renamed **`openMicUnsafe`** and has exactly **one** caller: `armCapture()`,
which asks the policy first. `captureInvariant.test.mjs` reads App.jsx as text and **fails the
build if anything else calls it** — a future arming site cannot bypass the gate without
turning it red. Mutation-tested: introducing a bypass produces

```
AssertionError: The microphone must have exactly one door.
  App.jsx:2224  openMicUnsafe(stream);
  App.jsx:2382  openMicUnsafe();
If you are adding a new way to start capture, call armCapture() — it asks canArmCapture()
first, which is what stops the mic opening while the interviewer is still talking.
```

### 3. Wiring — proved in a real browser, on all four paths

18 unit tests walk each path **step by step**, asserting the mic is shut at every step and
open only on the last: **session start** (room up → greeting queued → sentences 1..n in the
air → she finishes), **next question**, **restart/resume**, **re-ask**, plus the spoken rating.

Then a Playwright harness instruments `MediaRecorder` and `HTMLMediaElement` inside the page,
drives a real session against the real backend, and asserts the recorder never starts while
the interviewer's player still has clips to play. It **mutes and unmutes her mid-sentence** —
the exact broken path. The before/after is unambiguous:

```
OLD (ungated unmute)                         NEW (gated)
  audio.play      [her voice]                  audio.play      [her voice]
  --- CLICK: mute (mid-sentence)               --- CLICK: mute (mid-sentence)
  --- CLICK: unmute (still mid-sentence)       --- CLICK: unmute (still mid-sentence)
  recorder.start   <-- OPENS HERE              audio.play      [her voice]
  audio.play      [her voice]                  audio.play      [her voice]
  audio.play      [her voice]                  audio.play      [her voice]
                                               audio.play      [her voice]
*** VIOLATED: the recorder opened with         recorder.start   <-- only now
    2 of her sentences still unspoken ***      INVARIANT HELD
```

Note the detector tests **"segments remain unplayed"**, not "a clip is audible right now" —
the first version of it missed the bug entirely, because the recorder was opening in the
*gap between two sentences*, with four still to come.

**Barge-in is not an exception.** When the candidate talks over her she is *stopped* first —
the remaining clips are **abandoned, not postponed** — and only then does the mic open. By
the time capture is armed she genuinely has nothing left to say, so barge-in passes the same
gate honestly rather than going around it. Tapping the mic mid-question is now treated as
exactly what it is: an interruption. She stops; the floor is theirs; she does not re-say the
rest.

Two more bugs fell out of this work:

- **The re-ask and the mute-fork were each playing their clip twice** — once explicitly, and
  once via the autoplay sequencer — so the second start tore the first out mid-word. There is
  now one player and one owner.
- **Unmuting while a turn was still generating** would open the mic into the thinking gap.
  That gap belongs to her, not to their answer.

---

## Bugs found and fixed along the way

1. **`restart()` threw a `ReferenceError`.** It called `setGreetingAudioUrl`, which has not existed
   since the whole-reply clip was removed in the last sprint. **"Start fresh" did nothing at all.**
2. **The greeting never rendered in dev (found in a real browser, not by any test).** React
   StrictMode double-invokes mount effects; my ref guard correctly blocked the second fetch, but the
   first fetch's own cleanup then marked it cancelled and threw its result away. The room sat on
   "Connecting…" forever. A build and a unit test both sail straight past this — only a browser
   catches it.
3. **The mic opened before the interviewer had spoken.** FAST START renders the room on the session
   row, which already says `next_action: "answer"` — so for the 3s before the greeting landed, every
   "is it their turn?" check said yes: the mic would open, the question clock would start, and the
   90-second abandonment timer would arm. It is not their turn until somebody has asked them
   something (`canAnswer` now excludes `connecting`).
4. **Hands-free never armed on question one.** The lobby is the consent moment and already records a
   `voice_recording` grant on join — but the room still started with `voiceConsented = false`, so
   auto-listen was dead until the candidate clicked the mic once. Which is precisely the manual tap
   the voice stage exists to remove.
5. **Migrations 004 and 006 had never been applied to the dev database.** `delivery_metrics`,
   `early_wrap_reason`, `camera_at_join` and `interviewer_name` were all missing — meaning the
   founder's UAT session ran *without* roster-name persistence and *without* the camera policy, and
   the defensive `try/except` around each was silently swallowing it. **Applied (additive only, with
   your go-ahead).** See the schema check below — this can no longer happen unnoticed.

---

## 6. SCHEMA DRIFT CHECK (added mid-sprint, after the above)

Every optional column in this codebase is written defensively — `try / except / log a warning /
carry on` — so that a missing column can never break a live interview. That is the right call at
the point of use. It is **catastrophic as a deployment story**: the app runs perfectly happily on a
database two migrations behind, quietly doing less than it says it does. Which is precisely what
had been happening, through an entire founder UAT session, with the only trace being one warning
line per request in a log nobody was reading.

`app/schema_check.py` now probes the live schema **once at boot** against a flat manifest of every
expected table and column, and shouts if the database is behind:

```
==============================================================================
SCHEMA DRIFT — THE DATABASE IS BEHIND THE CODE. 7 expected object(s) missing.

    MISSING  vyom_messages.delivery_metrics              needs migration 004_delivery_metrics
    MISSING  vyom_focus_events  (TABLE)                  needs migration 006_interview_room
    MISSING  vyom_messages.presence_metrics              needs migration 006_interview_room
    MISSING  vyom_sessions.interviewer_name              needs migration 006_interview_room
    MISSING  vyom_sessions.early_wrap_reason             needs migration 006_interview_room
    MISSING  vyom_sessions.early_wrap_stage              needs migration 006_interview_room
    MISSING  vyom_sessions.camera_at_join                needs migration 006_interview_room

The app WILL still serve: every one of these is written defensively and
degrades to a no-op. That is the danger — the features above are silently
NOT HAPPENING, and the only other trace is a warning per request.

Run, in order:
    mysql ... < db/migration_004_delivery_metrics.sql
    mysql ... < db/migration_006_interview_room.sql
==============================================================================
```

On a healthy database it is one quiet line: `schema: up to date (through migration 006_interview_room)`.

- **It never applies anything.** Not a column, not a table, not "just this one, it's additive". A
  process that mutates a shared schema on boot is how two app instances race each other into a
  half-migrated database at 3am. It reports; a human runs the migration. (A test greps the module
  for `ALTER`/`CREATE`/`DROP`/`INSERT`/`UPDATE`/`DELETE` and fails if any appear.)
- **It never blocks boot.** A drifted database still serves. An *unreachable* one is a database
  problem, not a drift finding — it says "could not check" and gets out of the way.
- **It rides on `/health`** as `schema_status: "ok" | "drift"` + `pending_migrations: [...]`, so a
  deploy can see drift without anyone reading a log. It deliberately does **not** mark the service
  degraded: the service is up, it is just quietly doing less than it claims.
- **The contract is one line in a flat list**: add a row to `EXPECTED` in the same commit that adds
  a column. A test asserts every migration named there actually exists on disk.

13 tests (`tests/test_schema_check.py`), including the exact drift that prompted it.

### Confirmed to run in the Hugging Face Space, not just locally

The Space is a Docker Space whose `CMD` is `uvicorn app.main:app --host 0.0.0.0 --port 7860`.
Verified by running **that exact command**, on that port, and reading the boot log:

```
INFO:     Waiting for application startup.
INFO  app.schema_check  schema: up to date (through migration 006_interview_room)   <-- HERE
INFO  app.main          clip pack: 8 lines x 2 voices -> warmed=0 cached=16 ...
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:7860
```

...and, with a drifted schema, the full banner appears in the same place, `/health` returns
`schema_status: "drift"` with the pending migration list, and **the app still comes up and
serves**. Both were run end-to-end, not reasoned about.

Why it holds there specifically:

- It is an `@app.on_event("startup")` hook, so it runs inside the **ASGI lifespan** — before
  the server accepts its first request. Uvicorn runs the lifespan whether it is invoked by
  the Dockerfile's `CMD`, by `render.yaml`'s `startCommand`, or by hand. There is no
  entrypoint in this repo that starts the app and skips it.
- It logs through `logging` to **stderr**, which is exactly what an HF Space captures and
  shows in its container logs. (`logging.basicConfig` in `main.py` configures the root
  logger; uvicorn does not disable it — the lines above are the proof.)
- HF injects config as **environment variables** rather than a `.env` file, which is the same
  code path: `config.py` reads `os.getenv` either way, and `validate_settings()` already
  refuses to boot without `DATABASE_URL`.
- **It cannot hang the Space.** The probe opens a DB connection during the lifespan, so an
  unreachable database would otherwise sit on a TCP connect while HF waits for the container
  to become healthy. The engine now sets an **explicit `connect_timeout: 10`** rather than
  relying on the driver's default, so the worst case is a bounded 10s, after which the check
  logs "skipped" and the app boots anyway. An unreachable database is a database problem —
  `/health` reports `db: down` — and the schema check gets out of the way rather than making
  it worse.

**Not verified:** the image was not built and run under Docker (no Docker daemon on this
machine). What was verified is the command, the port, the lifespan ordering, the log
destination and both outcomes. The remaining risk is Docker-image-specific rather than
app-specific.

---

## Deliberately NOT done

- **Barge-in during the confidence rating.** It arms only when the floor is genuinely about to be
  theirs. Interrupting the *rating ask* helps nobody, and the branch (is this speech an answer, or a
  spoken rating?) is ambiguous enough that guessing wrong would be worse than not offering it.
- **Echo is mitigated, not eliminated.** Backchannels play into a room with a live mic. Every capture
  now requests `echoCancellation`, and the barge-in threshold is 3x the silence floor and requires
  300ms of sustain — but on a laptop with speakers at high volume and no headset, a backchannel could
  in principle nudge the trailing-silence detector and delay an auto-stop by a second or two. It
  cannot cause a false barge-in (wrong threshold, wrong duration). Worth one real-world listen.
- **The barge-in mic is genuinely open while she speaks.** That is inherent to the feature, not a
  leak — it is torn down and the track *stopped* on mute (the browser's mic indicator goes out), on
  unmount, and when the recorder takes it over. A mute button that leaves the mic open would be a
  lie, and this one does not.
- **`/session/turn` still awaits the full LLM reply** before returning (only its *audio* streams).
  The thinking gap there is covered by the acknowledgment clip, which is what the gap needed. The
  same streaming lever could be pulled for turns if the reply latency ever becomes the complaint.
- **The 4s target is a median, not a guarantee.** The spread (2.7s–7.8s) is Anthropic's generation
  latency. If the tail matters more than the median, the next lever is returning the first sentence
  *before* the model has finished writing the rest — which needs the greeting text to arrive in two
  parts, and is a bigger change than this sprint wanted.
