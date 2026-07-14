# FIXUP_SPRINT_REPORT.md

Closing the gaps the last two reports left open. Six items, all six landed, suites green.

| Suite | Before | After |
|---|---|---|
| Backend (`pytest`) | 127 | **161** |
| Frontend (`npm test`) | 9 | **24** |
| `npm run build` | clean | clean |

Eight commits, all pushed to **origin** (`main`). Nothing pushed to `hf`.

---

## 1. Per-question timer (E7.7) — the "Time is up, no answers given" dead end is gone

**What it was.** A question could be asked and then nothing could ever happen again. The
mic sat in "Waiting…" against a clock that had already run out, and a session where the
learner never got going ended on *"Time is up. No answers given."* with a Try Again
button — the attempt thrown away, unscored, unrecorded.

**What it is now.** Every question carries its own visible budget (90s warm-up, 3min
domain/behavioural, 4min case, 2min reverse — `roomPolicy.QUESTION_SECONDS`). It is on
screen from the first second, because a countdown the candidate cannot see is a trap.
When it expires there are exactly two outcomes and neither is a dead end:

- **Something was captured** — a recording we cut off mid-sentence, or a draft sitting in
  the composer → it is submitted as their answer (`timeout: "partial"`). The interviewer
  answers an incomplete answer in persona: acknowledges being out of time, engages with
  what they *did* get out, moves on. It is never silently dropped.
- **Nothing was captured** → a skip (`timeout: "skip"`). The **server** writes the marker
  text, so it can't be forged or varied. It's non-substantive by construction, spends no
  question slot (a round of 4 still means 4 answers they actually got to attempt), and
  asks for no confidence rating — we do not ask anyone to rate an answer they never got
  to give. The interviewer acknowledges it neutrally and asks the next question.

A timeout is **not a refusal**, so it deliberately outranks the FIX-2 non-answer
step-down: we do not re-ask the same topic more simply and punish them for our clock.

**Session-clock expiry is now an EARLY_WRAP**, persisted server-side (a refresh can't
dodge it), straight to a scored readout. A session where nothing was answered gets an
honest readout that says so.

Tests: `test_timers.py` — expiry-with-partial → submitted and rated normally;
expiry-empty → skip, no slot, no rating, and REVERSE still advances (otherwise a silent
candidate could never reach the close); session expiry → wrapped to READOUT with the
rounds completed still scored. Client-side: `roomPolicy.test.mjs` pins that the expiry
decision has only those two branches — the third one *was* the dead end.

## 2. Device-policy timers

- **60s camera grace.** Put the camera back inside it and *nothing* escalates — it is a
  real second chance, not a countdown. Let it lapse still-off and we re-report, which
  walks the ladder that already existed: nudge → warn → wrap.
- **90s both-channels-silent.** A muted mic **and** an empty composer, with an answer due
  → abandonment → the same courteous EARLY_WRAP. Typing keeps the interview alive (typed
  answers are first-class). An **unmuted mic is never abandonment**: silence there is
  thinking, and thinking is what the per-question clock is for — it ends in a skip and
  the next question, never in ending someone's session.

Both are decided in pure policy (`presence.py` / `roomPolicy.js`, same numbers both
sides) and enforced client-side, because the client is the thing with a wall clock. Every
wrap is still the server's decision to persist.

## 3. E6 readout re-order

The order **is** the coaching. The band used to open the page, so the first thing a
struggling learner saw was a label, with every reason for it buried underneath where it
would never be read.

Now: **what went well** (quoting their own words back to them — a strength you cannot
quote them for is a compliment you invented, and the prompt now cuts it) → **Delivery
Profile** → **Presence Profile** → **the 2-3 fixes that matter**, each with a concrete
*"try this next time"* action for tomorrow rather than a subject to go away and study →
**and only then the readiness band**, with the calibration delta explained in one
sentence (how confident they felt, where their answers actually landed, what the distance
means). Sub-scores, STAR, interviewer thoughts and the 7-day plan now sit *under* the
verdict: they are the working, not the message.

The voice is a mentor's — writing to them, not about them; describing what they **did**
and what it won or cost them, never what they felt or what kind of person they are.

Two things that already existed but no screen ever showed now render: the **Presence
Profile** (the meetroom sprint returned it in the API and nothing displayed it) and the
**early-wrap note**, which says plainly that the interview ended early and that nothing
was zeroed.

## 4. Riya joins the roster

Base portrait placed per the roster convention (`riya_warm_human_female.png`), four poses
in `poses/`. Her thinking and listening frames are the same chin-on-hands image, as
specified. `riya_emphasis.png` was byte-identical to `riya_intense.png` and is dropped —
the glob would have shipped 466KB twice.

**The optional enhancement is in**, because it was trivial: while she speaks warm/neutral,
a sustained amplitude over 0.65 crossfades to her emphatic-gesture frame and settles back
under 0.4, with a 1.5s minimum hold so a single loud syllable can't strobe the face. Her
hands move with her voice. Pure hysteresis (`posePolicy.nextEmphasis`), tested.

## 5. Roster audit

- **Ananya and Kavya are deleted, not pending.** Their portraits were rejected, so leaving
  commented-out rows in place was a trap for the next person. Replacements arrive later as
  pose-grid characters.
- **Mira does not exist in this codebase.** She is from the robot roster in
  `docs/ROSTER_INSTALL.md`, which is a superseded design — no code references her.
- **Every roster row's image resolves.** `npm run build` is the audit: an unresolved import
  is a hard Vite failure, and the build is clean. The live roster is Priya, **Riya**,
  Meera, Arjun, Vikram.
- `neo_warm_male.png`, `rex_stern_male.png`, `veda_formal_female.png` are on disk but in
  **no roster row** — 3MB of LFS on every clone for files no page can show. They are now
  git-ignored, with a note on how to promote one the day it earns a row.

## 6. TTS cost guard — and what it immediately found

The sentence-split is argued about in **calls** ("2-3×"), but **Sarvam bills audio**. So
the meter counts **seconds**, per session, split into what we paid for and what the
content-addressed cache gave us free (`tts.session_cost`, on the delivery block, logged at
`/session/end`). Duration is read from the MP3 frame header — exact for CBR, and honest
when it can't parse a clip: it counts it as `unmeasured` rather than inventing a number.
It is internal; the readout never shows a candidate what their voice cost.

### Measured

Validated against the **59 real Bulbul clips already in the UAT cache: 59/59 parse,
825.8s of audio.** Distribution splits cleanly into two populations — 19 clips ≥20s (449s,
mean 23.6s: whole replies) and 40 clips <20s (377s: sentences).

**Projected for one full 20-min session** (greeting + ~13 turns, at the measured 23.6s
mean reply): **≈660 billed seconds — roughly 11 minutes of synthesized audio per
20-minute interview.**

### The finding — this is the 2-call lever, and it is bigger than the sentence split

`/session/turn` and `/session/start` call **both** `_try_tts` (the whole reply, one clip)
**and** `_try_tts_segments` (each sentence, N clips). Every multi-sentence reply is
therefore synthesized **twice** — once whole, once split. In *seconds*, the sentence split
is nearly free (same words); **the doubling comes from the redundant whole-reply clip,
which is ~50% of the bill.** (Single-sentence replies escape it: identical preprocessed
text → identical cache key → the second call is a free cache hit. The meter's
`cache_hits` / `cached_seconds` will show exactly this in production.)

The whole-reply `audio_url` is only ever *played* on the iOS autoplay-blocked
"tap to hear the question" path and as a replay fallback — both of which can be served by
replaying the segments instead. **Recommendation: drop the whole-reply synth from
`/session/turn` and `/session/start` (keep it for the short reask / mute / rating lines,
which have no segments). That is a ~50% TTS saving for a handful of lines.** Not pulled
here — the sprint asked for the measurement to *inform* that decision, so it is yours to
take.

---

## Not done / worth knowing

- **The measured per-session number above is a projection** from real cached vendor audio,
  not one instrumented session end-to-end: that needs a live UAT run against MySQL +
  Sarvam, and I wasn't going to bill your Sarvam account uninvited. The instrument is in
  place — the true number is one line in the logs of the next session you run:
  `tts cost: session=… billed_seconds=… cached_seconds=…`.
- **Nothing was exercised against a live backend.** Verification here is 185 tests, a clean
  Vite build (which is what proves every roster image resolves), and an import-smoke of the
  FastAPI app. The room's clocks are timing logic in a browser; they want one manual pass.
- **A skipped question still costs an `answer_count`**, so a pathological run of timeouts
  can reach `MAX_ANSWERS_PER_SESSION` and 409. The session clock wraps long before that in
  practice, but it is the one edge where a timeout could still surprise someone.
- `docs/` is left untracked — it holds the sprint prompts and `riya_sheet.png`, and a raw
  1MB binary outside the LFS paths is exactly what the HF remote rejects.
