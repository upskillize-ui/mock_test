# InterviewIQ — Spec Alignment Report

Running log of product/spec decisions and how they were implemented. Newest last.

---

## UAT fixes (2026-07-03) — substantive-answer discipline + domain depth

Two product fixes from UAT, both **generalising the earlier WARMUP rating exemption**
(INT-01: warm-up answers advance without a confidence rating) into a general rule:
*we only rate, and only "spend a question" on, answers the learner actually attempts;
and once past warm-up every question must be deep and role-specific.*

Shipped OFF-risk: **none** — these tighten existing flow logic and prompt guidance. No
schema/migration change, no consent/TTS/STT change, `vyom_` tables untouched (only the
normal message insert). Full backend suite **green: 49/49** (was 44; +5 unit tests).

### FIX 1 — Rate only substantive answers

**Decision.** A learner is asked to rate their confidence only on a *substantive* answer.
A non-answer — an "I don't know" / "skip" / "no idea" variant, a reply under 15 meaningful
characters, or a pure clarification request ("what do you mean?") — or an answer to a turn
that was itself a clarifier/rapport turn rather than a scored question, is **not rated**,
and is **excluded from calibration and round-band scoring**.

**Why.** UAT showed the confidence widget firing after "I don't know", which is meaningless
to calibrate and quietly dragged round scores down. This is the same principle that already
exempts WARMUP from rating — now applied wherever an answer isn't real.

**How it was implemented (two-tier, cheap-guard-before-LLM).**
- **Cheap deterministic guard, at turn time** — `stages.is_non_substantive(text)` runs in
  `POST /session/turn` *before* any model judgement. It flags the obvious non-answers
  (length floor of 15 meaningful chars incl. Devanagari for Hinglish; anchored "don't
  know / skip / pass / next / idk / no idea" patterns; anchored bare-clarification
  patterns). Deliberately conservative — it only fires on clear non-answers, so genuine
  terse answers still rate. When it fires in a rating-gated stage, the server does **not**
  set `awaiting_rating`, so `next_action` stays `"answer"` and the frontend (which renders
  the rating widget solely off `next_action === "rating"`) shows no widget. **No frontend
  change was required.**
- **LLM flag, at debrief time** — the debrief scoring call's JSON contract
  (`perAnswerScores`) gains `"substantive": <true|false>`, defined to cover both the
  non-answer case and the "responding to a clarifier/rapport turn" case the heuristic
  can't see. This is the authoritative signal for scoring exclusion, and it catches the
  subtler non-answers the cheap guard lets through. The guard "runs before the LLM flag"
  precisely so we never burn a rating prompt on an obvious non-answer even if the model
  would later misjudge it as substantive.
- **Exclusion from scoring.** Calibration in `end_session` now pairs a rating with the
  model's per-answer score only over **substantive, rating-gated-stage** entries — which
  also fixes a latent alignment bug: the old positional `zip` counted WARMUP `perAnswerScores`
  (WARMUP is never rated), so calibration pairs were off by the WARMUP count whenever a
  warm-up answer existed. `roundScores` is instructed to be computed over substantive answers
  only, so a "don't know" no longer pulls a round down.

**Files.** `app/stages.py` (`is_non_substantive`, `should_await_rating`,
`consumes_question_slot`), `app/main.py` (`session_turn` gating + `end_session` calibration
filter), `app/prompts.py` (`perAnswerScores` contract), `tests/test_stages.py` (+5).

### FIX 2 — Domain depth discipline

**Decision.** Once past warm-up, DOMAIN and CASE questions must be **deep, role-specific and
scenario-based** — never biographical or generic rapport. On a non-answer, the interviewer
**steps difficulty DOWN on the same topic** (a more fundamental question on the same theme),
**never** pivoting to biography or small-talk. **At most one clarifier per question**; after
that, move on to the next planned question. Clarifier turns **do not consume a question slot** —
a round of 4 still means 4 substantive questions.

**Why.** UAT showed the interviewer, when stuck on a non-answer, retreating to easy
biographical small-talk (which also wasted a question slot), so a "round of N" delivered
fewer than N real questions.

**How it was implemented.**
- **Prompt guidance** — `_ask_line` for DOMAIN/CASE now demands concrete, scenario-based,
  role-specific questions and explicitly forbids biographical/generic ones; the system
  prompt's non-answer rule now says step-down-on-same-topic, never pivot to biography,
  one clarifier max.
- **Non-answer recovery directive** — `stage_turn_directive(..., substantive=False)`
  emits a dedicated step-down directive for rating-gated rounds: encourage briefly, ask one
  more fundamental question on the *same* topic, never pivot to biography, move on after the
  single allowed clarifier.
- **Counter discipline** — `stages.consumes_question_slot(stage, is_substantive)` returns
  False for a non-substantive answer in a rating-gated stage, so `session_turn` holds
  `round_index` (the slot isn't spent) while the interviewer re-asks. WARMUP/REVERSE always
  advance (never rating-gated). The per-session answer cap remains the backstop against a
  learner stalling indefinitely.

**Files.** `app/prompts.py` (`_ask_line`, system prompt, `stage_turn_directive`),
`app/main.py` (`session_turn` slot logic), `tests/test_stages.py`.

**Not touched (per constraints):** consent machinery, TTS/STT, and `vyom_` tables (beyond the
normal message insert).

---

## INT-11 (2026-07-03) — answer_id as a join key through the scoring pipeline

**Decision.** The scoring pipeline joins the model's per-answer scores to a learner's
confidence ratings (and to round-band gating) on the **`answer_id`**, not a positional zip.
`perAnswerScores` now echoes an `answerId` per entry; calibration and band math key off it.
**Migration-free** — the id is the existing `vyom_messages.id` (already the `answer_id` in
`vyom_answer_ratings`).

**Why.** FIX 1 left an honest gap: calibration paired two independently-produced lists
(DB ratings vs. the model's `perAnswerScores`) by position. If the model dropped, added, or
reordered an entry — e.g. flagged a *rated* answer non-substantive — the positional zip could
shift every later pair onto the wrong answer. A shared join key removes the failure mode
entirely: the pairing is by id, so a mid-list drop is just a missing lookup, never a shift.

**How it was implemented.**
- **Expose the id to the scoring call.** `_load_debrief_messages` builds the debrief transcript
  with each learner turn prefixed by a stable `[answer #<id>]` tag and returns the set of real
  answer ids. The scoring contract (`DEBRIEF_INSTRUCTION`) instructs the model to copy that
  exact integer into each `perAnswerScores` entry's `answerId`.
- **Join, don't zip.** `stages.calibration_pairs(ratings, perAnswerScores, valid_answer_ids)`
  indexes scores by `answerId` (coercing string/float ids, rejecting any id that isn't a real
  answer to defend against hallucination), then for each `(answer_id, rating)` looks up that
  answer's score and keeps the pair only if the answer is substantive. Order-independent.
- **Band math on the join too.** `stages.substantive_stages(...)` derives, via the id join,
  which scored rounds actually contain a substantive answer; `stages.gate_round_scores(...)`
  zeroes any scored round (warmup/domain/behavioural/case) with none, so a round of pure
  non-answers can't surface a positive band. REVERSE is untouched — it has no per-answer scores
  and is scored separately.
- **Graceful degradation.** If the model echoes no usable `answerId` at all, the join yields no
  pairs and calibration reports `insufficient_data` (with a content-free warning log) rather
  than mispairing — strictly safer than the old positional behaviour.
- **Also fixes the earlier WARMUP misalignment** noted under FIX 1: because pairing is now by id,
  WARMUP scores (never rated) simply don't match any rating and drop out naturally.

**Files.** `app/stages.py` (`calibration_pairs`, `substantive_stages`, `gate_round_scores`,
`_scores_by_answer_id`, `_coerce_int`), `app/main.py` (`_load_debrief_messages`; `end_session`
join + round-score gating; ratings query now selects `answer_id`), `app/prompts.py`
(`perAnswerScores` gains `answerId` + the copy-the-tag instruction), `tests/test_stages.py`
(+4, incl. the mid-list-drop-without-misalignment case). Suite **green: 53/53**.
