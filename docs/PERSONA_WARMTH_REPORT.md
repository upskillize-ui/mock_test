# PERSONA_WARMTH_REPORT.md — senior Nia, warmth, variety, de-escalation

All five items are built. `339 backend + 100 frontend tests pass` (37 of the backend ones
are new, in `tests/test_persona_warmth.py`). Migration 008 is **applied and verified**
against Aiven; the HF push is **pending your confirmation**, as always.

Three things to know before anything else in this report:

1. **There is no `NIA_PITCH`, and there cannot be one** — `pitch` is a `bulbul:v2`
   parameter that v3 ignores. You approved shipping `NIA_SPEAKER` + `NIA_PACE` instead.
2. **Item 3 inverts a rule a previous phase deliberately installed** — the opening no
   longer ends on a role-shaped question. Raised and **approved by the owner**; the
   inversion stands. Recorded in §4 because the reasoning matters to whoever reads this
   next.
3. **The abuse lexicon is approved as tuned for go-live** — the only new thing here that can
   end a student's session. Two conditions recorded with it (§3): Indic-script abuse is a
   known gap for a future addition, and session-ending stays the ladder's last rung, after
   de-escalation and rebuild. Both are now pinned by tests.

**No open design decisions remain.** What's left in §9 is yours to trigger: the HF push,
your Sarvam audition, and LEGAL on the retention window.

---

## 1. Voice config (item 1)

| Env var | Default | What it does |
|---|---|---|
| `NIA_SPEAKER` | `ritu` (falls back to `TTS_VOICE_FEMALE`) | Nia's Sarvam v3 speaker |
| `NIA_PACE` | `0.93` | Nia's read speed (Nova stays on `TTS_PACE`, 1.0) |

Tune both from the Space settings; no code change, exactly as you asked. The boot log now
prints the **resolved** bundles so an audition can be confirmed in one line:

```
INFO app.main: Voice: TTS=True STT=True VOICE=True model=bulbul:v3 nia=ritu@pace0.93 nova=shubh@pace1.00
```

### Why pitch isn't there

Sarvam's docs are explicit that `pitch` is supported only on `bulbul:v2` and is **ignored
on v3**, and your own code already said so (`tts.py:257`, plus a tripwire test at
`test_tts.py:280` asserting `pitch` never enters the payload). A `NIA_PITCH` var would
have been a dial wired to nothing: you'd audition a pitch, set it, restart, and hear
identical audio with no error to explain why. Since **"lower pitch" on v3 is a speaker
choice**, that is what `NIA_SPEAKER` is for — v3 ships ~14 female voices, and your
audition picks one.

### A latent bug this surfaced — please note, it would have bitten you personally

`cache_key()` and `build_payload()` each reached into `settings` independently, and nothing
forced them to agree. Pace was global, so they agreed *by coincidence*. The moment pace
became per-interviewer, they would have stopped: the payload would ask for 0.93 while the
key still hashed the global 1.0. **You would have retuned `NIA_PACE`, restarted, and been
served the old read from disk cache — forever, silently.** The exact failure the knob
exists to avoid, on the exact workflow you described.

Fixed at the root: a frozen `tts.Voice(speaker, pace)` is now passed to *both*, so there is
no longer a way to synthesise under parameters the key did not hash. `Voice` is threaded
through `cache_key` / `build_payload` / `synthesize` / `get_audio_hash` /
`get_shared_audio_hash` / `warm_clip_pack`, and `test_cache_key_covers_every_voice_field`
enforces the invariant structurally — add a field to `Voice` and forget `cache_fields()`,
and it fails rather than shipping a stale cache.

**One expectation genuinely moved:** `test_v3_payload_params` asserted `pace == 1.0` for
speaker `ritu`; it now asserts `0.93`, because that is Nia's payload. The `pitch` tripwire
is untouched and still passing.

## 2. Persona diffs

### Nia's register (`prompts.SENIOR_ADDENDUM`, Nia only)

Appended to the persona when `interviewer_name` is `Nia`: 40+, **calm authority**, **short
declarative sentences**, **no hedging** (an explicit kill-list: "I think", "maybe", "sort
of", "just"…), **decisive follow-ups**. It closes with `AUTHORITY IS NOT COLDNESS`, because
"be authoritative" is one bad reading from "be cold", and cold would quietly undo the whole
warm-openings ritual.

**Nova is untouched** — proven, not asserted: I rendered `HEAD`'s component against the new
one across all **16 tone × state combinations** and the markup is byte-identical, while
Nia's differs. Same for the prompt: `SENIORITY` and `40+` appear in no Nova persona in any
of the four modes.

**Keying on the name** is the only option available — the roster lives in the frontend and
only `interviewer_name` crosses the wire. It's reliable (`"Nia"` is not in `_NAMES_F`, so
the classic-mode fallback draw can never produce it) and it is not a security boundary: the
worst a crafted name does is select one of the two registers we ship. Centralised in
`prompts.is_senior_character` / `SENIOR_ROSTER_NAMES`.

**Dials:** only `brisk` is removed from Nia's pace pool (it contradicts a 0.93 read and
reads as someone with something to prove). All five warmth values, all four registers,
every opening move and habit stay in play — narrowing the dials to protect a trait would
buy the trait by paying with the exact thing the anti-convergence dials exist for.

### Looks (`RobotInterviewer.jsx`) — see `docs/screenshots/persona-warmth/`

Five changes, all `fem`-gated: squarer cranium, **angular set brows** (`rx` 1.6 → 0.3, +4°
permanent converge, sat 1px lower — her neutral is already level-eyed), **silver streak**
through the bob crown (in `C.headA`, on-palette), **higher sharper peak-lapel collar**, and
**no jewelry** (the teal pendant is gone; the header comment claiming hoop earrings and a
gold chain was describing things that never existed in the file).

Three of those live in markup that was **shared with Nova**, so they became new `fem`
branches rather than in-place edits.

**This is where rendering earned its keep.** There are no renderer tests in this project, so
I stood up a headless-Chrome render harness. My first collar attempt put the lapel peaks
*above* the shoulder line: two navy spikes stabbed up through the white shirt and Nia was
wearing **a bow tie**. The code looked fine. Fixed by tucking the collar apexes behind the
neck joint (so the collar rises from behind it rather than as wings pinned beside the jaw)
and keeping all lapel geometry at or below `y=292`.

## 3. Never abusive, always de-escalating (item 2)

The old handling was one canned line ("I hear you — interviews can feel stressful…") that
every frustrated student heard identically. It is now a two-beat rule binding **all four
modes**, with `This rule does not soften in Critical` stated in the prompt:

1. **Take the heat out of it** — calm, unbothered, no judgement.
2. **Rebuild their footing** — an easier entry onto the same ground, *or* a callback to
   something they genuinely did well. **A callback must be TRUE**; inventing a compliment to
   comfort someone is flattery and is forbidden here exactly as everywhere else.

Plus `YOU DO NOT MIRROR`, and a named ban on the tone-policing register ("let's keep this
professional", "watch your language", "calm down", asking them to apologise…). Those
phrases are named explicitly because they are what an affronted interviewer actually
reaches for — a guardrail test caught that two of them weren't banned, and I fixed the
prompt rather than the test.

### The abuse floor (`stages.abuse_action`) — **your decision needed**

Repeated abuse → courteous wrap, in the engagement-floor family (same derivation from the
transcript, same two-strike shape, same `early_wrap_reason` persistence, new `WRAP_ABUSIVE`
sentinel so the readout can be honest about why a session was short).

The line it draws:

| Message | Verdict |
|---|---|
| "This is fucking hard." | frustration — never counts, never wraps |
| "You're a fucking idiot." | person-directed abuse — counts |

The discriminator is whether profanity is aimed **at a person** — deliberate symmetry with
the rule binding us in Critical (pressure lands on the answer, never the person). One hit
de-escalates; only a **second consecutive** one wraps; **any** real answer resets the count
to zero.

It is tuned to **under-fire on purpose**: a false positive ends a student's interview, a
false negative means we were too patient with someone. Those costs aren't close.

A real false positive I found and fixed: a **STAR story quoting an insult** —
*"the tech lead told me you are an idiot for shipping on a Friday. I waited until after the
call, asked what specifically broke, and we agreed a rollback"* — tripped the
second-person test. That is a *good* answer to a behavioural question, and de-escalating at
someone calmly describing how they handled being insulted would be absurd. Fixed with a
25-word ceiling: abuse aimed at the interviewer is short and hot; a 40-word story is an
answer.

### Status: **approved as tuned, for go-live** (owner sign-off)

Two things recorded with that approval:

**1. Script coverage is a known gap, accepted.** The lexicon is English + Hinglish **in
Latin script only**. Abuse typed in Devanagari or another Indic script does not trip it —
a future addition.

It fails in the safe direction, and it is worth being precise about what the gap actually
costs, because it is less than it sounds:

| | Latin-script abuse | Devanagari / Indic abuse |
|---|---|---|
| Prompt-level de-escalation + rebuild | ✅ | ✅ — **unaffected** |
| Server-side wrap on repetition | ✅ | ❌ (the gap) |

The de-escalation is the **model** reading the message, and the model is not limited to any
script — so a student who swears at Nia in Hindi still gets the calm response and the way
back in. The only thing the gap costs is the *wrap*: the rung nobody is in a hurry to reach.
The failure mode is "we were too patient with someone", never "we ended an interview we
shouldn't have". Verified:

```
Devanagari / Indic-script abuse — the known gap. Must fail SAFE (no wrap):
   is_abuse_at_person=False action=''             | तुम चूतिया हो
   is_abuse_at_person=False action=''             | बेवकूफ
   is_abuse_at_person=False action=''             | तू पागल है
Latin-script Hinglish — covered:
   is_abuse_at_person=True  action='deescalate'   | tum chutiya ho
```

Pinned by `test_indic_script_abuse_is_a_known_gap_that_fails_safe`, which asserts the
*direction* of the failure, not that the gap is fine. **When Indic-script support lands,
that test should start failing** — it is the marker for the future addition, not a blessing
of the status quo.

**2. Session-ending is the last rung of the ladder** — after de-escalation and rebuild, per
the phase prompt. This is now an enforced invariant, not a property that happens to hold:

```
  0 abusive turns  -> ''            (nothing)
  1 abusive turn   -> 'deescalate'  <- de-escalate + rebuild
  2 consecutive    -> 'wrap'        <- LAST rung
  reset by answer  -> ''
=> a wrap is UNREACHABLE without a prior de-escalation turn: True
```

`test_ending_the_session_is_the_last_rung_and_unreachable_without_the_earlier_ones` asserts
this across the whole domain rather than at the threshold value, because the property that
matters isn't "2 wraps" — it's that **no input ends a candidate's interview on their first
swing**. `ABUSE_TURNS_BEFORE_WRAP = 2` carries a comment saying that dropping it to 1 would
not tighten the floor but delete the de-escalation and the rebuild entirely, leaving a
product that hangs up on people: *if you change this number, change it upward.*

**Readout:** already behaviour-only (`prompts.py:1302`); I added that a heated session is
**not a topic** for the readout — no mention of tone, language or conduct, no moralising,
no hinting. Someone who lost their temper in a mock interview is precisely who this product
exists for, and a lecture is the one thing guaranteed to stop them coming back.

## 4. Warm openings (item 3) — **a deliberate contract inversion, owner-approved**

The opening is now three beats, 20–40s (3–4 short sentences, not a paragraph): **greet by
name → one safe ice-breaker → the intent question**, ending on the intent question.

**This directly overturns `prompts.py:594-609`**, which forbade rapport openers and demanded
the opening *end* on a role-shaped question, and it inverts `test_realism.py::
test_kickoff_opening_constraints_not_a_template`, which asserted exactly that. The first
role question now lands on the **next** turn, once they've answered the intent question. I
rewrote the test with the reasoning recorded in its docstring rather than silently flipping
the assertion.

**Status: raised with the owner and approved — the inversion stands.** It is written up
here anyway because the earlier rule was installed on purpose, with measurements behind it
(openings were running to five sentences; the 2-3 cap was also worth ~0.6s of start
latency). Anyone who later finds the old rule's rationale and assumes this was an oversight
should find this paragraph first. The latency cost of the third beat is real but small, and
the ritual is what item 3 bought with it.

### The ice-breaker has thin real data, and I did not paper over it

`get_student_context` returns **no city, no interests field, and there is no weather
source**. The spec's "weather/city/interest from profile" is therefore only partly
supportable. Rather than invent a data source, the prompt draws the ice-breaker **only**
from what's actually in the candidate background (course, field of study, current work, a
listed skill) and is told, in these words, to skip the beat entirely when there is nothing
concrete and safe:

> NEVER INVENT A FACT ABOUT THEM TO BE FRIENDLY WITH. You do not know their city, you do not
> know their weather… Asking "how's the weather in Bangalore?" of someone whose city you are
> guessing is not warmth — it is a stranger pretending to know them, and it lands exactly
> that way. […] A skipped ice-breaker costs nothing. An invented one costs the whole illusion.

Sensitive ground (scores, past attempts, psychometrics, age, money, family, health, caste,
religion, appearance) is banned outright, with "if you're weighing whether it's safe, it
isn't — skip it".

**If you want real ice-breakers, the fix is upstream:** add city/interests to
`student_profiles` and surface them in `get_student_context`. Say the word and it's a small
follow-up.

## 5. Closing ritual (item 4)

A **new `FEEDBACK` stage** sits between REVERSE and READOUT:
`… → CASE → REVERSE → FEEDBACK → READOUT → DONE`.

1. *"Any questions for me?"* — already existed as the REVERSE round.
2. **NEW:** one question asking how the session was **for them**, stored for product review.
3. Then the readout.

Order is the point: asking after the readout would be asking someone to review the exam
that just graded them. The close then **calls back to the intent they stated at the start**
— "you said you wanted X" — and is told that *"today didn't get going, here's exactly how
the next one will"* is a better goodbye than a comfortable lie.

The beat is **not scored and not rated** — deliberately absent from `SCORED_STAGES` and
`RATING_STAGES`. What they think of us must never touch what we think of them, in either
direction. It also forbids fishing for compliments and any out-of-ten rating (one question,
not a survey).

**Two traps I closed while building it:** FEEDBACK is exempt from the engagement floor
(chasing someone who won't tell us how it went would be the most self-regarding thing this
product does), and a timed-out FEEDBACK turn *must* still advance — otherwise the one turn
where nothing is asked *of* them becomes the only one they cannot leave, re-asking "so how
was that for you?" forever. Both are pinned by tests.

Storage: `vyom_sessions.experience_feedback` (queryable, and survives the transcript purge —
"what did students say about the product in Q3" must not be answerable only for 90 days).

## 6. Memory schema (item 5)

`vyom_student_memory` — designed as the **first slice of Flagship longitudinal memory**, to
extend rather than throw away:

```sql
id BIGINT PK · user_id VARCHAR(36) NOT NULL · session_id VARCHAR(36) NULL (FK CASCADE)
kind VARCHAR(32) NOT NULL · content TEXT NOT NULL · content_digest CHAR(64) NOT NULL
meta JSON NULL · created_at DATETIME
INDEX (user_id, kind, created_at) · (user_id, content_digest) · (created_at)
```

Four decisions worth knowing:

- **`kind` is an open vocabulary, not an ENUM** — enforced in `db.MEMORY_KINDS`. Flagship
  adding `recurring_gap` or `stated_goal` must not need a migration.
- **`session_id` is nullable on purpose** — durable cross-session memory belongs to the
  *student*, not to one attempt, and needs a home.
- **`content_digest`** makes "heard this exact line before?" a point lookup; MySQL can't
  index TEXT without a prefix, and a prefix index on prose collides on every line sharing an
  opening clause — which, for greetings, is most of them. Normalised (casefold, punctuation
  and whitespace collapsed) so *"Good morning, Asha!"* and *"good morning asha"* are one
  memory.
- **`meta` JSON** is the extension point; promote to a real column when something earns an
  index.

**Reads and writes are fully defensive.** A missing table means the do-not-repeat list is
empty and we improvise blind, exactly as before — the cost of failing is repeating ourselves
in six months; the cost of raising is a candidate's session.

### The variety engine

Openings and closings get the spec's guarantee ("no repeat student ever hears the same
opening/closing again"): the last 5 are handed back to the persona as a do-not-repeat list,
which is the half the model **cannot** supply for itself — it has no recollection of the
session it ran for them last month, so "say something fresh" is an instruction with no
referent. The block also bans *variations* (reordering, synonym-swapping, same shape with
new nouns), and forbids revealing that we remember them at all: the interviewer is a
different person who has never met them; the memory is **ours**.

Stored where a kind is **cleanly isolable** — i.e. where the whole reply *is* that thing:
`opening` (greeting), `closing` (FEEDBACK turn / either wrap), `checkin` (engagement
check-in turn), `encouragement` (de-escalation turn), `reask` (improvised re-asks only).
**I did not fabricate an "encouragement" record for encouragements buried mid-reply** —
isolating one would need a second model call, so we don't pretend to store it. Re-asks and
check-ins were already model-improvised per session (the canned pools are failure-only
fallbacks), so item 5's "improvised fresh" already held for them.

### DPDPA

This table is personal data (keyed by `user_id`), so it is wired into retention **and**
erasure:
- **Its own window**, `MEMORY_RETENTION_DAYS` (default 365) — deliberately *longer* than the
  90-day transcript window, because purging it on the transcript clock would defeat the
  feature while still holding the data. **Needs the same LEGAL sign-off as the other two.**
- **Erasure**: the session FK cascades, *and* `/admin/purge` deletes user-scoped rows
  explicitly (like `vyom_consents`) — otherwise a NULL-session row would survive the account
  it belongs to. `PurgeResponse.memory_purged` reports it.

## 7. Migration 008 — applied and verified

No `mysql` client on this box, so I drove it through SQLAlchemy/pymysql using
`backend/.env`. Pre-flight showed the database exactly at 007 with only 008's two objects
missing. **`app/schema_check.py` still never applies anything** — this was a human running a
migration, which is its supported path.

```
migration_008_student_memory.sql -> 2 statement(s)
[1] APPLY  table vyom_student_memory          OK
[2] APPLY  column vyom_sessions.experience_feedback   OK
```

### Verification output

```
==============================================================================
1. THE BOOT SCHEMA CHECK — app.schema_check.check(), the exact call main.py makes
==============================================================================
    INFO app.schema_check: schema: up to date (through migration 008_student_memory)

    check() returned: []
    VERDICT: UP TO DATE — no drift
    LATEST_MIGRATION the code expects: 008_student_memory

==============================================================================
2. THE NEW TABLE'S SHAPE, as the database actually built it
==============================================================================
    column           type           null  default
    id               bigint         NO    None
    user_id          varchar(36)    NO    None
    session_id       varchar(36)    YES   None
    kind             varchar(32)    NO    None
    content          text           NO    None
    content_digest   char(64)       NO    None
    meta             json           YES   None
    created_at       datetime       NO    CURRENT_TIMESTAMP

    indexes:
      fk_memory_session                (session_id)
      idx_memory_created               (created_at)
      idx_memory_user_digest           (user_id,content_digest)
      idx_memory_user_kind_recent      (user_id,kind,created_at)
      PRIMARY                          (id)

    foreign keys (erasure path):
      fk_memory_session -> vyom_sessions  ON DELETE CASCADE

    vyom_sessions.experience_feedback: text, nullable=YES

==============================================================================
3. LIVE ROUND-TRIP — the variety engine actually writing and reading
==============================================================================
    remember_line x2 -> True, True
    recent_lines     -> ['Good to see you. Shall we start?', "Morning, Asha! How's the week?"]
    unknown kind refused -> True
    digest normalises punctuation/case -> True
    first-timer reads empty -> True
    test rows cleaned up -> 0 remaining

==============================================================================
ALL VERIFICATION PASSED
==============================================================================
```

Rollback exists (`migration_008_student_memory_rollback.sql`) and is honest that it loses
real data — the heard-lines history and every feedback answer. Re-running 008 brings the
table back empty.

## 8. Guardrail test results

`tests/test_persona_warmth.py` — **37 new tests**, same contract as the 22 Critical ones:
pure prompt-string and pure-logic assertions, offline, nothing mocked, no API call.

A provocation transcript can't be fed to a live model in a unit test. What these do instead:
prove the instruction the model receives says the right thing **in every mode**, that the
server-side floor is tuned to under-fire, and that the one path which ends a session early
cannot be reached by a candidate who is merely having a hard time.

Coverage: de-escalation binds all 4 modes · the rebuild beat exists and can't be invented
flattery · tone-policing named and banned · spoken fallbacks never reference what the
candidate did · abuse floor under-fires (6 frustration + 3 STAR-quote cases must not fire;
6 person-directed cases must) · first hit never wraps · any answer resets · Nia senior /
Nova clean across all modes · authority ≠ coldness · no pitch knob · opening ritual + the
ice-breaker honesty rules · feedback beat never scored/rated, never fishes, never traps a
silent candidate · variety engine (variations count, never reveals the memory, first-timer
gets a byte-identical prompt, injection sanitised).

**Full suite: 339 backend, 100 frontend, all passing.** Six pre-existing tests needed
updating; five were mechanical (FEEDBACK in the chain, `LATEST_MIGRATION`, `Voice`
signatures) and **two encoded expectations that genuinely moved** — the opening contract
(§4) and Nia's payload pace (§1). Both are called out above rather than quietly flipped.

## 9. Pending

- [ ] **HF push — pending your explicit confirmation.** Nothing pushed. When you're ready,
      the Space needs `NIA_SPEAKER` / `NIA_PACE` set (or it uses `ritu` @ 0.93), and note
      **`MEMORY_RETENTION_DAYS`** is new.
- [ ] **Your Sarvam audition** → set `NIA_SPEAKER` to the v3 female voice you pick. Confirm
      it took via the boot log's `nia=<speaker>@pace<n>`.
- [x] ~~The abuse lexicon + threshold (§3)~~ — **approved as tuned for go-live.** Indic-script
      coverage logged below as a future addition.
- [ ] **LEGAL sign-off on `MEMORY_RETENTION_DAYS`** (365), alongside the existing transcript
      and debrief windows.
- [ ] **Future addition: Indic-script abuse coverage** (§3). Fails safe today (no wrap;
      de-escalation still works in every script). `test_indic_script_abuse_is_a_known_gap_that_fails_safe`
      is the marker — it should start failing when this is picked up.
- [x] ~~Decide on the opening contract inversion (§4)~~ — **approved by the owner; the
      inversion stands.**
- [ ] **Optional:** city/interests in `student_profiles` would make the ice-breaker real
      rather than usually-skipped.
- [ ] Frontend has no renderer, so Nia's art is verified by screenshot + a byte-identical
      Nova check, not by a test. A snapshot test would need a jsdom/vitest dependency —
      say the word.
