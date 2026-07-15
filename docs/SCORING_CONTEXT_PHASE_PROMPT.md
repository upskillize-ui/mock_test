# SCORING_CONTEXT_PHASE_PROMPT.md — context-weighted scoring + readout formatting
# Problem: scores are not comparable across session configs. Easy/10min/100 raw
# currently reads stronger than Critical/45min/75 raw. Fix: every score carries
# its context, and weak-evidence sessions cannot earn strong claims.
# Commit to origin as you go. NEVER push hf without explicit confirmation.

1. SESSION PROFILE STRIP: every readout opens with the session's parameters —
   role, experience level, difficulty, duration chosen, mode (Interview/Coach),
   rounds covered vs skipped. Every section of the readout renders a small
   context chip (e.g. "Realistic · 20 min"). No score anywhere without context.

2. BENCHMARK SCORE: alongside raw score, compute
   benchmark = raw × difficulty × evidence × mode × coverage, capped at 100.
   Defaults (single tunable constants table, not scattered literals):
   difficulty: Easy 0.60, Realistic 1.00, Stretch 1.15, Critical 1.25
   evidence (duration): 10min 0.70, 20min 1.00, 30min 1.10, 45min 1.20
   mode: Interview 1.00, Coach 0.90
   coverage: rounds_attempted / rounds_offered (skipped ≠ failed stays true for
   the RAW score; coverage only tempers the BENCHMARK claim).
   Readout shows both numbers with a one-line explanation of the weighting.

3. BAND GATES (these outrank arithmetic): Easy difficulty caps the readiness
   band at Building regardless of score. 10-min sessions cap one band below
   earned. Offer-Ready requires Stretch or Critical at 20+ min with the case
   round attempted. Gate copy is a ladder, never a slap — e.g. "Perfect run —
   Easy caps at Building. Step up to Realistic to unlock Interview-Ready."
   Band pill colours unchanged (gold/teal/navy/orange).

4. HISTORY COMPARABILITY: the attempts/history view lists benchmark score +
   session profile per attempt, so a student (and later a placement officer)
   can compare attempts fairly. Raw score visible on drill-in.

5. CALIBRATION UNTOUCHED: the calibration delta and profile keep their own
   block; confidence weighting does NOT enter the benchmark formula.

Acceptance tests: (a) Easy/10min/comm-only, raw 100 → benchmark ≈ 42, band
capped Building, ladder copy shown. (b) Critical/45min/Coach, raw 75 →
benchmark 100, band per earned score. (c) benchmark never exceeds 100; empty
session → no scores at all (existing rule). Report to
docs/SCORING_CONTEXT_REPORT.md with before/after readout screenshots list.

# STRENGTHENING ADDENDUM — items 6–12

6. MINIMUM EVIDENCE RULE: fewer than 3 substantive answers → no band, no
   benchmark — readout says "Insufficient evidence — complete at least 3
   answers for a scored readout." Substantive = captured content, including
   auto-submitted partials; empty skips don't count. Extends the existing
   empty-session rule.

7. PERSIST, NEVER RECOMPUTE: at session close, store per attempt: raw,
   benchmark (capped for display, uncapped internally), the exact factor
   values applied, and a weights_version. Historical attempts NEVER change
   when the constants table is tuned. This adds columns/table → DB migration
   (next number in sequence) + boot schema-check update → backend change:
   list in report, hf push only on explicit confirmation.

8. EARLY EXITS ARE VISIBLE: sessions ended before the evidence threshold
   appear in history as "Ended early — not scored" (navy, neutral copy).
   Quitting can't hide a bad run, but it's never framed as failure.

9. TREND OVER TROPHY: history shows the benchmark trend across attempts,
   newest flagged. Any future placement/officer view reads the latest-3
   average, never best-ever — one lucky run is not readiness. Improvement
   across attempts is itself called out in readout copy.

10. RESERVE MODE ROWS NOW: constants table includes TEXT 0.90 and HYBRID 1.00
    rows (dormant until the Intake & Modes sprint) so mode weights live in
    ONE place. Text sessions will score typed-communication metrics only —
    never voice Delivery metrics.

11. SHOW THE MATH: an expandable "How this score is calculated" on the
    readout lists the factors applied to this attempt, in plain words.
    State explicitly: the raw rubric is already anchored to the declared
    experience level, so level is NOT a benchmark factor (no double-count).

12. ECOPRO HOOKS: session close exports {band, benchmark, top-3 fixes,
    suggested re-attempt window} in a stable shape for NudgeAI follow-ups
    now and the CareerIQ readiness gate later. Presence metrics, calibration
    profile, and focus events stay OUT of the benchmark — report-only.

Additional acceptance tests: (d) 2 answered questions → "Insufficient
evidence", no band, attempt visible in history as ended early; (e) change a
constant in the weights table → all previously stored benchmarks unchanged,
new attempts use new weights_version; (f) uncapped benchmark stored (Critical
45min raw 90 vs raw 75 distinguishable internally even though both display
100).