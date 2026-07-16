# SCORING_CONTEXT_REPORT.md — context-weighted scoring + ONE readout

**Sprint:** context-weighted scoring, band gates, evidence floor, one readout.
**Status:** complete. All suites green — **298 backend** (was 250; +48), **71 frontend**
(was 61; +10), including the 22 Critical guardrails and the capture-gate mutation test.
**Backend changes are NOT pushed to hf — pending explicit confirmation** (see §Deploy).

---

## The bug, and the fix in one line

Easy / 10 min / raw **100** used to read stronger than Critical / 45 min / raw **75**.
It now reads **42 · Building** against **100 · Interview-Ready**. Both were rendered from
the real `/session/end` payload and screenshotted (see §Verification).

The reason it was possible: the readout printed a score with no context attached, and a
score with no context is not a verdict, it is a compliment. Two numbers now exist, and
they answer different questions:

| | what it answers | who touches it |
|---|---|---|
| **raw** (`overall`) | "how good were these answers, for someone at this level?" | the debrief rubric. Never re-weighted. Coverage never touches it — that is what keeps *skipped ≠ failed* true. |
| **benchmark** | "against a real bar, where is this person?" | `raw × difficulty × evidence × feedback × coverage`. This is what history trends and what NudgeAI reads. |

Level is deliberately **not** a benchmark factor: the raw rubric is already level-anchored,
so weighting by it again would count the same fact twice (item 8).

---

## Per-item

**1. Session profile strip** — `SessionProfileStrip` (navy, DM Mono) opens every readout,
scored or not: role, level, difficulty, duration, mode, feedback, and rounds covered vs.
skipped as pills. Every section carries a `.rd-chip` context chip. `mode` (TEXT/VOICE/HYBRID)
does not exist until the Intake sprint, so it renders an em-dash rather than a guess —
this strip is the one place on the page that must never be wrong.

**2. Benchmark** — `app/scoring.py`. Every constant lives in ONE dict (`scoring.WEIGHTS`)
with a `WEIGHTS_VERSION`; nothing else in the codebase holds a weight. Difficulty
.60/1.00/1.15/1.25, evidence 10→.70 / 20→1.00 / 30→1.10 / 45→1.20, feedback
Interview 1.00 / Coach .90. Display-capped at 100; the uncapped value is stored (it is the
only way to tell a 101 from a 140 when these weights are next tuned).

The **mode rows are present and dormant**: `MODE_FACTOR_ACTIVE = False`, `mode_factor()`
returns 1.00 for everyone. Nothing may be weighted by a mode nobody can choose yet.
*Vocabulary note:* this prompt says TEXT/AUDIO/VIDEO; INTAKE_AND_MODES says TEXT/VOICE/HYBRID.
I implemented this prompt's rows as authoritative and added `MODE_ALIASES` (VOICE→AUDIO,
HYBRID→VIDEO) so the Intake sprint resolves. **Reconciling the two names is that sprint's
call** — inert either way while the factor is dormant.

Coverage = `rounds_attempted/offered` over the four scored rounds, read from the existing
answer-id join (`stages.substantive_stages`). REVERSE is excluded — the candidate's own
questions are not a scored round. It tempers the benchmark only.

**3. Band gates** — the band is earned from **raw** (the rubric's verdict on the answers)
and then capped by context. Gates can only ever cap **downward**; no factor in the file can
promote anyone. Where several bind, the most restrictive sets the ceiling and its copy is
the headline. Easy → Building; 10-min → one band below earned; Offer-Ready needs
Stretch/Critical + 20 min + case attempted (and "case attempted" reads the answer join, not
the stage plan — a case that was offered but never answered does not count).

**4. Minimum evidence** — under 3 substantive answers: no band, no benchmark, no tiles;
the "Insufficient evidence" card plus Presence is the whole render. The debrief LLM is now
**skipped entirely** on these sessions (nobody may be shown its output, so paying Sonnet for
it was waste). Auto-submitted partials count; empty skips do not — both calls are made
upstream by `stages.is_non_substantive`, which already treats `TIMEOUT_SKIP_TEXT` as a
non-answer. `scoring.py` only counts.

**5. Persist, never recompute** — migration **007** adds `benchmark`, `benchmark_uncapped`,
`score_factors` (the full result + gates + coverage), `weights_version`, `gated_band`,
`substantive_answers`, `scored`. `/session/end`'s idempotent replay path re-reads the stored
factors and **never** re-runs `compute_benchmark`. Retuning the table tomorrow cannot change
a score a learner has already read. `overall` stays the raw score; `overall_band` stays what
the raw answers earned, so the gap between earned and gated is inspectable rather than lost.

**6. Early exits visible** — a below-the-floor attempt still writes a row (`scored=0`) and
shows in history as "Ended early — not scored", navy and neutral, via
`readoutPolicy.historyStatus`. Quitting cannot hide a run, and a run nobody scored is not a
run somebody failed.

**7. Trend over trophy** — `/user/history` returns a `trend` (benchmarks, newest first,
newest flagged `latest: true`) and `latest_average`. **`best_score` is gone from
`/user/stats`**, deliberately: it was an average of raw scores across different difficulties
and durations, held up as who the person is. The History header now leads with "Latest 3 —
average" and "Where you are now". `by_role`/`by_round` average the benchmark, not the raw.

**8. Show the math** — `scoring.math_lines()` renders an expandable
"How this score is calculated" listing this attempt's real factors in plain words, read from
the **stored** factors. It states in-page that level is already in the first line and is not
weighted again.

**9. Band appears exactly once** — `presence_band()` and `PRESENCE_BANDS` are **deleted**,
not merely unrendered (`presence_readout` now returns `measured: true` and the card gates on
that). The Delivery card's pill is gone from the UI too. Verified on the rendered DOM: the
only element whose entire text is a band name, outside the per-round pills, is the one in
the Readiness block.
*Left alone:* `delivery.delivery_band` still exists server-side (three assertions in
`test_delivery.py` pin it, and it is that sprint's contract). Nothing renders it. Worth
removing when Delivery is next touched.

**10. One readout, one design language** — order implemented exactly as specified:
profile strip → verdict → what went well → Delivery → Presence → fixes → **Readiness (last
major section)** → answer-by-answer (collapsed `<details>`) → re-attempt + closing line.
Exactly two surfaces (`.rd-card` light, `.rd-navy` for the strip and Readiness — verified on
the DOM: `["Session profile", "Readiness"]` and nothing else). One card system: one width,
radius, padding rhythm, header treatment. Missing data is an honest one-line card
(`RdMissing`), never a silently absent section.
*One insertion:* the **7-day plan** sits between the fixes and Readiness. It is not in the
prompt's nine slots but it already existed, it is coaching prose, and it is what the
re-attempt window's copy assumes ("give the plan a full week"). Flagging it as a judgement
call.

**11. EcoPro hooks** — `scoring.ecopro_export()` → `{session_id, scored, band, benchmark,
top_fixes[3], reattempt_window, weights_version}` on every `/session/end`. Presence,
calibration and focus are **excluded and tested for their absence** — an agent that
schedules study time off a camera signal is exactly the product this is not.

**12. Calibration untouched** — same place in the Readiness block, same maths. Confidence
never enters the benchmark formula.

---

## Files touched

| file | what |
|---|---|
| `backend/app/scoring.py` | **new** — the weights table, benchmark, gates, evidence floor, show-the-math, re-attempt window, EcoPro export, `latest_average`. Pure, no I/O. |
| `backend/app/main.py` | `/session/end` wiring (compute → persist → respond, and a replay path that never recomputes); evidence-floor short-circuit; history trend; stats rewrite; `_grouped_averages`. |
| `backend/app/presence.py` | `presence_band`/`PRESENCE_BANDS` deleted; `measured` flag added. |
| `backend/app/schemas.py` | `SessionProfile`, `ScoreContext`; `DebriefResponse` +profile/scored/evidence/score/reattempt_window/ecopro; `HistoryListItem` +benchmark/band/scored; `HistoryListResponse` +trend/latest_average. |
| `backend/app/schema_check.py` | 007 rows (the boot drift banner). |
| `db/migration_007_scoring_context.sql` (+rollback) | **new** — additive only. |
| `frontend/src/readoutPolicy.js` | `hasMinimumEvidence`, `canRenderBand`, `historyStatus`, `trendDirection`; `isEmptyReadout` now honours the server's `scored:false`. |
| `frontend/src/App.jsx` | the readout rebuilt as one document; `.rd-*` card system; history trend + neutral early-exit rows; early-wrap copy fix. |
| `backend/tests/test_scoring.py` | **new**, 48 tests. |
| `backend/tests/test_room.py`, `test_schema_check.py` | updated to pin the new rules (presence has no band; 007 is newest). |
| `frontend/src/readoutPolicy.test.mjs` | +10 tests. |

---

## Verification

Beyond the suites, I rendered the **real `DebriefScreen`** against **real `/session/end`
payloads** (generated by calling `main._score_context` / `main._debrief_response`) in a
throwaway Vite+Playwright harness, and screenshotted each full page. The harness was
deleted afterwards — it needed a browser dep, and this repo's test philosophy is
pure-logic and zero-dep. What it proved:

- **(a)** Easy/10min/raw 100 → **benchmark 42**, band **Building**, ladder copy
  *"Perfect run — Easy caps at Building. Step up to Realistic to unlock Interview-Ready."*
- **(b)** Critical/45min/Coach/raw 75 → **benchmark 100** (uncapped 101.2, stored), math
  row: *"The maths came to 101.2. 100 is the top of the scale — you cleared it with room to
  spare."*
- **(c)** 2 answers → insufficient-evidence card only. Band pills on page: **zero**. Navy
  surfaces: **one** (the strip — no Readiness block at all).
- **(d)** covered by `test_changing_a_constant_cannot_change_a_stored_benchmark`: retuning
  Easy .60→.90 leaves the stored 42 and its explanation untouched; a new attempt reads 63.
- **(e)** full page reads as one document; two navy surfaces; band exactly once; no
  horizontal overflow at 1180px (the LMS embed width) or 640px.

**Two real bugs the render caught that the tests did not:**
1. The early-wrap note promised *"what you covered is scored below"* on the
   insufficient-evidence readout — where nothing is scored below. Reason and reassurance are
   now composed separately (`earlyWrapNote(reason, scored)`).
2. "How this score is calculated" printed *"Rounds you didn't reach…"* under **4 of 4
   rounds**. Now conditional, with a test.

---

## Deploy — action needed

**Backend changes are pending your explicit confirmation before any hf push.** Nothing has
been pushed.

1. **Run migration 007 before deploying the backend.**
   `mysql ... < db/migration_007_scoring_context.sql`
   Rollback: `migration_007_scoring_context_rollback.sql` (lossy — it discards which weights
   scored each attempt, and there is no backfill).
2. Every 007 read/write is **defensive**: a drifted database still serves a readout, just
   without a benchmark, and `schema_check` says so loudly at boot. That is the safety net,
   not the plan — **006 and 004 had never been applied to dev**, which is why that banner
   exists at all. Check the boot log says `schema: up to date (through migration
   007_scoring_context)`.
3. Pre-007 rows render fine: they keep their raw score and band, and show no benchmark
   rather than having one invented for them at today's weights.

**One call worth your eye:** the evidence floor now **skips the billed Sonnet debrief**
entirely under 3 substantive answers. It saves the call and matches item 4 (the card is the
whole render) — but it does mean a below-floor session produces no stored prose at all. Say
the word if you want the debrief to still run and simply not be shown.
