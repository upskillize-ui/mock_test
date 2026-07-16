# SCORING_CONTEXT_PHASE_PROMPT.md — context-weighted scoring + ONE readout
# Problem: Easy/10min/100-raw currently reads stronger than Critical/45min/
# 75-raw, and the readout renders as two stacked designs with the band
# shown twice. Rules header: same as VOICE_CAPTURE (origin commits, hf only
# on explicit confirmation, suites green, brand, copy + layout rules).

1. SESSION PROFILE STRIP: every readout opens with role, level, difficulty,
   duration, mode, feedback style, rounds covered vs skipped. Every section
   carries a small context chip. No score anywhere without context.
2. BENCHMARK SCORE: benchmark = raw × difficulty × evidence × feedback ×
   coverage, display-capped at 100 (uncapped stored). Constants in ONE
   tunable table: difficulty Easy .60 / Realistic 1.00 / Stretch 1.15 /
   Critical 1.25; evidence 10min .70 / 20min 1.00 / 30min 1.10 / 45min
   1.20; feedback Interview 1.00 / Coach .90; reserved mode rows TEXT .90 /
   AUDIO 1.00 / VIDEO 1.00 (dormant until Intake sprint). Coverage =
   rounds_attempted/offered — tempers the benchmark only; skipped ≠ failed
   stays true for raw.
3. BAND GATES (outrank arithmetic): Easy caps band at Building regardless
   of score. 10-min sessions cap one band below earned. Offer-Ready needs
   Stretch or Critical, 20+ min, case attempted. Gate copy is a ladder:
   "Perfect run — Easy caps at Building. Step up to Realistic to unlock
   Interview-Ready."
4. MINIMUM EVIDENCE: <3 substantive answers → no band, no benchmark, no
   tiles — "Insufficient evidence" card only (+ Presence if data exists).
   Substantive includes auto-submitted partials; empty skips don't count.
5. PERSIST, NEVER RECOMPUTE: store per attempt: raw, benchmark, factor
   values, weights_version. Old attempts never change when constants are
   tuned. DB migration (next number) + boot schema-check update → backend:
   hf push pending confirmation.
6. EARLY EXITS VISIBLE: below-threshold sessions appear in history as
   "Ended early — not scored" (navy, neutral). Quitting can't hide a run;
   it's never framed as failure.
7. TREND OVER TROPHY: history shows benchmark trend, newest flagged; any
   placement view reads latest-3 average, never best-ever.
8. SHOW THE MATH: expandable "How this score is calculated" listing this
   attempt's factors in plain words. Raw rubric is level-anchored — level
   is NOT a benchmark factor (no double-count).
9. BAND APPEARS EXACTLY ONCE: remove the band pill from the Presence card
   (presence is report-only) and anywhere else; the only band lives in the
   Readiness block.
10. ONE READOUT, ONE DESIGN LANGUAGE, THIS ORDER: (1) Session Profile strip
    (navy, DM Mono) → (2) verdict, one sentence quoting the candidate where
    possible → (3) what went well → (4) Delivery Profile → (5) Presence
    Profile (no pill) → (6) the fixes that matter, with "try this next
    time" → (7) READINESS block LAST major section — band (Playfair) +
    per-round pills + calibration delta + competency bars (DM Mono) +
    benchmark + show-the-math, all in ONE navy block → (8) answer-by-answer
    STAR, collapsed behind "View answer-by-answer" → (9) re-attempt window
    + one closing line (funny-but-sharp allowed, never quirky).
    One card system: same width, radius, padding rhythm, header treatment.
    Exactly two surfaces: light cards for coaching prose; navy ONLY for the
    Session Profile strip and the Readiness block. Band colours: Offer-
    Ready gold / Interview-Ready teal / Building navy / Not Ready orange.
    Missing data = honest one-line card, never silently absent.
11. ECOPRO HOOKS: session close exports {band, benchmark, top-3 fixes,
    re-attempt window} in a stable shape for NudgeAI now, CareerIQ later.
    Presence, calibration, focus events stay OUT of the benchmark.
12. CALIBRATION UNTOUCHED: keeps its own place in the Readiness block;
    confidence never enters the benchmark formula.

Acceptance: (a) Easy/10min raw 100 → benchmark ≈42, Building cap, ladder
copy. (b) Critical/45min/Coach raw 75 → benchmark 100. (c) 2 answers →
insufficient-evidence card, history "ended early". (d) constants change →
stored benchmarks unchanged. (e) full-page screenshot reads as ONE designed
document; band appears exactly once. Report to docs/SCORING_CONTEXT_REPORT.md.