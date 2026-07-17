# CAPACITY_COST_PHASE_PROMPT.md — synthetic sessions, cost ledger, load knee
# Context: 2,000–2,500 students onboard NEXT WEEK. Before that: measured cost
# per student per session per mode, measured max safe concurrency, and a
# safety valve. Rules: commit to origin as you go; NEVER push hf without
# explicit confirmation; the load test spends REAL vendor money — every test
# run must print its projected spend BEFORE starting and stay under the
# budget caps below.

1. SYNTHETIC STUDENT DRIVER: a script that runs a full interview end-to-end
   with no human — scripted realistic answers. TEXT mode: typed answers via
   the API. AUDIO/VIDEO: pre-synthesized answer audio files fed to the STT
   path (generate a small reusable bank of spoken-answer WAVs once). Driver
   completes sessions through /session/end so debriefs + benchmarks write.

2. COST LEDGER PER SESSION: instrument (or extract from existing logs) a
   per-session ledger: LLM calls × model × input/output tokens → $ cost;
   Sarvam TTS seconds → credits; STT seconds → credits; total per session.
   Store it on the session record. This is permanent product telemetry,
   not test scaffolding — every real student session gets a ledger too.

3. THE COST MATRIX: run 2 complete sessions per cell: {TEXT, AUDIO, VIDEO}
   × {10, 20, 45 min}, Realistic difficulty, Interview feedback. Deliver
   the table: cost per student per session per mode in ₹ (state the $/₹
   and credit/₹ rates used). Then project: 2,500 students × 1 session each
   at 20 min and at 45 min, per mode. BUDGET CAP for this matrix: print
   projected vendor spend first; abort any run that would exceed 500 Sarvam
   credits or $15 LLM total without my go-ahead.

4. CAPACITY RAMP: against the deployed Space, ramp concurrent synthetic
   TEXT sessions (cheapest): 5 → 10 → 20 → 40, measuring per-turn latency
   and error rate at each step; stop at the knee (latency doubling or
   errors). Then a small mixed run (3 AUDIO + spread TEXT) to measure the
   voice path's extra weight. Deliver: max safe concurrent sessions on
   current cpu-basic hardware, and the observed bottleneck (CPU, DB pool,
   vendor rate limits — name it with evidence).

5. SAFETY VALVE: MAX_CONCURRENT_SESSIONS env (default from item 4's
   measured number). Beyond the cap, the lobby shows an honest, in-brand
   hold state — exact copy, one line, never styled as an error:
   "Every panel is in session right now. Give us a few minutes — your
   seat is coming." Sessions already running are never affected.
   Tests: cap reached → polite hold; slot frees → entry works.

6. DB POOL + CONNECTION AUDIT: the Space shares Aiven with the LMS — check
   pool sizing vs the concurrency target and vs Aiven's connection limit;
   fix pool config if it's the bottleneck; report the numbers.

Report to docs/CAPACITY_COST_REPORT.md: the cost matrix (the Amit table),
capacity knee + bottleneck evidence, safety valve config, total spend of the
test itself, and a stated recommendation: what hardware tier + vendor quotas
+ MAX_CONCURRENT_SESSIONS value to launch 2,500 students safely next week.
