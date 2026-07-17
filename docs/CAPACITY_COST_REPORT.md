# CAPACITY_COST_REPORT.md — cost per student, safe concurrency, and the safety valve

**Phase:** Capacity/Cost (synthetic sessions, cost ledger, load knee). See
`docs/CAPACITY_COST_PHASE_PROMPT.md`.
**Context:** 2,000–2,500 students onboard next week. Before that we need measured cost per
student per session per mode, measured max safe concurrency, and a safety valve.

## TL;DR — status of the six items

| # | Item | Status |
|---|------|--------|
| 1 | Synthetic student driver | **Built & unit-verified.** Live end-to-end run is itself the item-3 spend (gated). |
| 2 | Per-session cost ledger | **Shipped.** Instrumented, stored on the session row (migration 011), 7 unit tests. |
| 3 | The cost matrix | **Harness built; go-ahead GIVEN (full, over-caps); BLOCKED on deploy + migration.** See Execution status. |
| 4 | Capacity ramp | **Harness built; go-ahead GIVEN (deployed Space); BLOCKED on deploy + test-window env.** See Execution status. |
| 5 | Safety valve | **Shipped.** Server gate + in-brand hold UI + 14 tests. Ships dark (cap defaults to 0). |
| 6 | DB pool + connection audit | **Analysed & pool made configurable.** Live Aiven numbers pending an allowlisted run. |

**Total spend of the test itself so far: $0.00 / 0 Sarvam credits.** No money-spending run has
executed.

### Execution status — go-ahead received, runs blocked on environment (as of 2026-07-18)

Go-ahead was given to run the **full cost matrix (over-caps)** and the **capacity ramp against
the deployed Space**. Both are held because the deployed Space is running **pre-phase code**, so
spending now would capture nothing:

- The Space (`https://upskill25-mock-test.hf.space`) is **up and healthy** (`db: ok`) but its
  `/health` reports `pending_migrations: ["010_presence_metrics"]` and no knowledge of
  migration 011 — i.e. **the ledger instrumentation, the `cost_ledger` column write, and the
  safety valve from this phase are NOT deployed there.** Driving it would spend real LLM/Sarvam
  money and store **zero** ledger data → no Amit table.
- The deployed `model_interview` is `claude-sonnet-4-6` (not the Haiku default), so the *real*
  per-turn LLM cost will be **higher** than the Haiku-based projection — the ledger will capture
  the actual figure once it's live.
- The ramp would additionally hit the Space's `MAX_SESSIONS_PER_DAY` cap (10 per user) after 10
  synthetic sessions from the single dev user, and the locally-minted token must match the
  Space's `JWT_SECRET`.

**Unblock checklist (then both runs execute immediately):**

1. **Deploy this branch to the Space.** The code is pushed to `origin/capacity-cost-phase`.
   Deploying to the hf Space is a push to the `hf` remote — **not done, and I will not do it
   without your explicit confirmation** (per the phase rules). Confirm and I'll push `hf`, or
   have ops deploy the branch.
2. **Apply migrations** `010_presence_metrics` **and** `011_cost_ledger` to the shared Aiven DB
   (010 is currently drifted; 011 is new). Additive/nullable — safe.
3. **For the test window only:** raise `MAX_SESSIONS_PER_DAY` (or set `APP_ENV=development`) so
   the synthetic user isn't daily-capped mid-ramp, and set `MAX_CONCURRENT_SESSIONS=0` so the
   ramp measures the hardware knee, not the valve.
4. **Confirm** the local `backend/.env` `JWT_SECRET` matches the Space's, and confirm the Sarvam
   credit quota covers the over-caps matrix (~1,760 credits at the placeholder rate).
5. (Optional but needed for item-6 live numbers) fix DB access from a runner host, or run
   `scripts/db_pool_audit.py` from an allowlisted host.

A local run is not a fallback: this host **cannot reach the Aiven DB** (`Access denied for user
'avnadmin'`), so a locally-run backend can't start sessions and the harness can't read ledgers.

---

## The rates (state them plainly — every ₹ below rests on these)

The ledger converts vendor units to ₹ with four env-configurable rates (`app/config.py`), and
every stored ledger echoes back the exact rates it used, so an old ledger is self-describing.

| Rate | Config key | Default used here | Confidence |
|------|-----------|-------------------|-----------|
| USD → INR | `USD_TO_INR` | **₹88.0 / $1** | Approximate — set to the finance forex rate. |
| Anthropic LLM price | (in `app/ledger.py`) | Haiku 4.5 **$1/$5** per Mtok; Sonnet 4.6 **$3/$15** per Mtok; cache-read ×0.10, cache-write ×1.25 | **From the Anthropic price list** (current). |
| Sarvam credit → INR | `SARVAM_CREDIT_TO_INR` | **₹1.0 / credit** *(placeholder)* | ⚠️ **Confirm on the Sarvam dashboard.** |
| Sarvam TTS credits/sec | `SARVAM_TTS_CREDITS_PER_SEC` | **0.5 /s** *(placeholder)* | ⚠️ **Confirm on the Sarvam dashboard.** |
| Sarvam STT credits/sec | `SARVAM_STT_CREDITS_PER_SEC` | **0.5 /s** *(placeholder)* | ⚠️ **Confirm on the Sarvam dashboard.** |

> The LLM $ side is trustworthy today (real prices, real measured tokens). The **Sarvam credit
> side is only as good as the three placeholder rates** — the ledger measures the *seconds*
> exactly (from the same meters the product already keeps), so once the real credit/sec rate is
> entered the ₹ numbers become exact with no re-run.

---

## Item 2 — the cost ledger (shipped, permanent telemetry)

Every completed **and** abandoned session — real student or synthetic — now writes a
`cost_ledger` JSON blob to `vyom_sessions` at close (the single `_finalize_session` funnel).
It is product telemetry, not test scaffolding: the synthetic matrix is just its first heavy
reader.

What it captures, per session:

- **LLM**, per model: calls, uncached-input / output / cache-read / cache-write tokens, and $.
  Captured by instrumenting `claude_client.call_claude` **and** `stream_claude` (the streamed
  greeting/kickoff carries usage across `message_start` + `message_delta`, both now parsed).
- **TTS**: billed audio seconds (from `tts.session_cost`, already measured) → credits → ₹.
- **STT**: transcribed audio seconds (new meter in `stt.py`, fed by the client-reported
  recording length, falling back to the vendor's word timestamps) → credits → ₹.
- **total_inr** and the **rates** used.

Design notes: in-process meters (like the TTS/STT meters they sit beside — a restart
mid-session under-counts that one session, which is honest for a measurement and never a bill);
fully defensive (a DB without migration 011 still closes sessions normally, just without a
stored ledger); recording never affects a turn or a debrief.

Files: `app/ledger.py` (new), `app/claude_client.py`, `app/stt.py`, `app/main.py`
(`_write_cost_ledger`), `db/migration_011_cost_ledger.sql` (+ rollback),
`app/schema_check.py`, `tests/test_cost_ledger.py`.

**Action required:** apply `db/migration_011_cost_ledger.sql` to the shared Aiven DB (additive,
nullable JSON column — safe, no backfill).

---

## Item 3 — the cost matrix (harness ready; run gated on go-ahead)

`scripts/cost_matrix.py` drives **2 sessions per cell of {TEXT, AUDIO, VIDEO} × {10, 20, 45
min}**, Realistic / Interview (18 sessions), reads each session's stored ledger, and prints the
Amit table + the 2,500-student projection. It is **dry-run by default** — it prints the
projection and spends nothing; `--confirm` runs it; it **aborts if the projection exceeds a
cap** unless `--over-caps` (the explicit go-ahead) is passed; and it hard-stops on actual spend
crossing a cap mid-run.

### Projected vendor spend (printed before any spend)

```
LLM (Anthropic)  : ~$1.8    (cap $15)      ✅ within cap
Sarvam credits   : ~1760    (cap 500)      ❌ EXCEEDS cap  (at the 0.5/s placeholder rate)
    TTS ~760  +  STT ~1000
```

- **LLM is comfortably within the $15 cap** — the whole matrix is projected at under $2.
- **Sarvam is the constraint.** At the *placeholder* 0.5 credit/sec rate, the 12 voice sessions
  project to ~1,760 credits — **3.5× over the 500-credit cap.** Two things follow:
  1. The real credit/sec rate may be much lower — enter it before trusting this. If the true
     rate is ≤ ~0.14/s, the matrix fits under 500 credits as-is.
  2. If the real rate keeps the voice cells over 500, run the **TEXT column now** (0 Sarvam
     credits, ~$0.5 LLM) and run the voice cells with `--over-caps` and your explicit sign-off,
     or reduce to 1 session per voice cell.

### ESTIMATED cost per student — NOT MEASURED (money runs held at your instruction)

Computed from **the ledger's own price book + rates** (`app/ledger.py`, `app/config.py`) applied
to a documented per-session token/second model, **not** from a live run. Realistic / Interview,
Fresher (13 answerable questions + greeting = 14 interviewer calls + 1 debrief). The question
*count* is level-driven, so 20 vs 45 min differ only in answer richness (bigger transcript, more
spoken seconds). Two configs shown because the model choice for turns is the single biggest LLM
lever — the **deployed** Space currently runs Sonnet for turns; the code default is Haiku.

**Read the two halves differently:** the **LLM ₹ is reliable** (real Anthropic prices × modelled
tokens). The **Sarvam ₹ is placeholder-driven and almost certainly overstated** — it uses the
config stand-in of 0.5 credit/sec × ₹1/credit = ₹0.5 per second of audio, which is far above real
Sarvam pricing. What's reliable on the voice side is the **seconds** (the volume), not the ₹.

**₹ per student per session — DEPLOYED config (Sonnet turns + Sonnet debrief):**

| mode | 20 min | 45 min | reliable? |
|------|-------:|-------:|-----------|
| TEXT  | **₹18.5** | **₹24.2** | ✅ LLM-only, trustworthy |
| AUDIO | ₹148.5 | ₹254.2 | ⚠️ ₹130 / ₹230 of this is Sarvam at the **placeholder** rate |
| VIDEO | ₹148.5 | ₹254.2 | ⚠️ same as AUDIO (camera presence is on-device / free) |

**Same table with the Haiku-turns lever (turns→Haiku, debrief stays Sonnet):**

| mode | 20 min | 45 min |
|------|-------:|-------:|
| TEXT  | **₹8.9** | **₹11.3** |
| AUDIO | ₹138.9 | ₹241.3 |
| VIDEO | ₹138.9 | ₹241.3 |

Voice volume (reliable): **~110 s TTS + 150 s STT** at 20 min; **~200 s TTS + 260 s STT** at 45
min. Once the real Sarvam credit/sec rate is entered, multiply those seconds by it for the true
voice ₹ — no re-estimate needed.

**2,500 students × 1 session (deployed Sonnet config, TEXT is the reliable line):**

| | 20 min | 45 min |
|--|-------:|-------:|
| TEXT  | ₹46,300 | ₹60,500 |
| AUDIO/VIDEO | ₹371,000* | ₹635,000* |

\* Sarvam-dominated and placeholder-inflated — **do not budget from these** until the real rate
is set; the TEXT row and the LLM component are the trustworthy figures.

**Takeaways:** (1) the interview is cheap in text — **₹9–₹24 per student** depending on model and
length; (2) **switching turns to Haiku roughly halves LLM cost** (₹18.5→₹8.9 at 20 min) with the
debrief still on Sonnet; (3) the *entire* mode-cost story is Sarvam seconds, so the voice budget
hinges on one unknown rate — get it from the dashboard before quoting AUDIO/VIDEO.

### Launch recommendation (one paragraph)

Do **not** try to serve 2,500 students concurrently on the current single-worker `cpu-basic`
Space: the real wall is the **~15-connection DB pool** (5 + 10, one worker), because each
LLM-bearing request pins its connection across the multi-second model call — so ~12–15 concurrent
interviews is the ceiling regardless of CPU. For next week, **keep the single instance but set
`MAX_CONCURRENT_SESSIONS=12`** (just under the pool wall) so the new safety valve holds the 13th+
student with the polite in-brand message instead of erroring, and **stagger onboarding into
cohorts** so peak concurrency stays under 12; **default the cohort to TEXT** (≈₹9–₹24/student, zero
Sarvam, no voice latency) with AUDIO/VIDEO opt-in once the Sarvam rate is confirmed. To actually
raise the ceiling rather than queue, first **raise Aiven's connection cap**, then add uvicorn
workers (each worker = its own 15-connection pool, so N workers × 15 must still fit under the
Aiven cap minus the LMS's peak) — and the durable fix is to release the DB connection *before* the
LLM await so concurrency stops being bound by the pool at all.

---

## Item 4 — capacity ramp & the knee (harness ready; run gated on go-ahead)

`scripts/capacity_ramp.py` ramps concurrent synthetic **TEXT** sessions **5 → 10 → 20 → 40**
against the deployed Space, measuring median/p95 per-turn latency and error rate at each step,
stopping at the knee (median latency ≥ 2× baseline, or errors). Then a mixed wave (3 AUDIO + 7
TEXT) measures the voice path's extra weight. **Dry-run by default; `--confirm` to run.**
Projected LLM spend for the full ramp: **~$7.74** (TEXT is cheap, no Sarvam), less if the knee
is early.

> **Run it with `MAX_CONCURRENT_SESSIONS` unset (0) on the Space**, or the safety valve will
> hold sessions and you'll measure the *cap*, not the hardware knee. The script warns about this.

### Predicted bottleneck (to be confirmed by the run): the DB connection pool

The single most likely wall on `cpu-basic` is **not CPU — it's the DB pool**, for a specific
structural reason:

- The Space runs a **single uvicorn worker** (Dockerfile/render.yaml, no `--workers`), so there
  is **one** SQLAlchemy pool: `pool_size + max_overflow` = **5 + 10 = 15** connections.
- A request **pins its pooled connection across the entire multi-second LLM `await`**: the read
  transaction opens on the first `SELECT` in the handler and isn't released until the turn's
  final `commit()`, which lands *after* the Anthropic call returns. So each in-flight
  `/session/turn`, `/session/greeting`, `/session/end` holds one DB connection for ~1–3 s of
  otherwise-idle wait.
- That makes **~15 the ceiling on concurrent LLM-bearing requests**, regardless of CPU
  headroom. The 16th concurrent turn waits for a pool slot up to `pool_timeout` (now 15 s), then
  errors — which is exactly the "errors appear" knee the ramp watches for.

If the measured knee lands at/near ~15 concurrent, the DB pool is confirmed as the bottleneck.
If it lands well below 15, CPU (LLM-response JSON handling, TTS/STT proxying) or a vendor rate
limit is the wall — the ramp's latency curve and error samples will say which.

**Max safe concurrent sessions and the named bottleneck will be filled in here from the run.**

---

## Item 5 — the safety valve (shipped)

**Config:** `MAX_CONCURRENT_SESSIONS` (default **0 = unlimited**, i.e. ships dark until ops
sets item 4's measured number). `CONCURRENCY_ACTIVE_WINDOW_MINUTES` (default 75) bounds what
counts as "live" so a tab closed without `/session/end` can't wedge the cap forever.

**Behaviour:** `/session/start` calls `_check_capacity` **first — before the daily cap, before
intake, before any spend** — so a held student never pays an LLM call to be told to wait. It
counts `active`, non-deleted sessions started inside the window; at/over the cap it returns
**503** with a structured detail `{capacity_full: true, message: <copy>}` and a `Retry-After`.
**Sessions already running are never touched** — this only gates new entries.

**The hold copy (exact, one line, never styled as an error):**

> Every panel is in session right now. Give us a few minutes — your seat is coming.

**UI:** the lobby renders it as a **gold** hold panel (mirroring the existing "voice vendor
down" seatbelt — gold, not red, because a full house is not the student's fault and nothing has
broken), with the Join button still live so a retry the instant a seat frees just works.
(`frontend/src/App.jsx` — `capacityHold` state + panel; the frontend build passes.)

**Tests (`tests/test_capacity.py`, 7):** ships dark at cap 0 (doesn't even query); at/over the
cap → 503 + structured detail + Retry-After; the copy is the approved one-liner, single line,
never the word "error"; a freed slot (under cap) and an empty house both admit. Plus the ledger
suite (7) and the existing 402 → **all 416 backend tests pass.**

Files: `app/config.py`, `app/main.py` (`_live_session_count`, `_check_capacity`),
`frontend/src/App.jsx`, `tests/test_capacity.py`.

---

## Item 6 — DB pool + connection audit

**Space side (known now):** single worker → one pool → **15 max connections** (5 + 10). As
argued in item 4, that ceiling is also the concurrency ceiling for LLM-bearing endpoints, and
every one of those 15 is a connection the **LMS cannot** have (both share one Aiven instance).

**Fix applied:** the pool is no longer hard-coded. `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` are now env-configurable (`app/config.py` + `app/db.py`),
defaulting to the historical 5 / 10 / (timeout lowered 30→15) / 280. This lets ops right-size
the pool against Aiven's real cap **minus the LMS's headroom** with no code change — the correct
move, since blindly raising the pool could starve the LMS.

**Aiven side (pending):** I could not read Aiven's `max_connections` / live usage from this host
— the credentials in `backend/.env` returned `Access denied for user 'avnadmin'` (rotated key or
this IP isn't allowlisted). `scripts/db_pool_audit.py` (read-only) prints
`max_connections`, `max_user_connections`, `Threads_connected`, the peak high-water mark, and
per-user connection counts (Space vs LMS), then does the fit arithmetic. **Run it from an
allowlisted host with current creds and paste the numbers here.**

The number that matters: **Aiven cap  ≥  (Space pool ceiling) + (LMS peak usage) + headroom.**
On small Aiven MySQL plans the cap is often ~20–25 total — if so, the current 15-connection
Space pool + the LMS is already close to the edge, and the launch recommendation below sizes
around it.

---

## Recommendation — launching 2,500 students safely next week

These are the levers; the two starred numbers get pinned by the gated ramp (item 4) and the
allowlisted DB audit (item 6).

1. **Hardware tier.** `cpu-basic` with a **single worker** caps LLM-bearing concurrency at the
   ~15-connection pool wall regardless of CPU. Two independent moves raise the ceiling:
   - **Scale the DB path, not just CPU.** Either add uvicorn workers (each worker = its own
     pool, so 2 workers × 15 = 30 connections — *only if Aiven's cap allows it*), or upgrade the
     hardware tier so more workers fit. **Do not add workers without first raising the Aiven
     connection cap** (item 6) — otherwise you multiply the starvation risk.
   - Higher-leverage, lower-risk follow-up (post-launch): release the DB connection **before**
     the LLM await (commit/close the read transaction, reopen after) so a turn doesn't pin a
     connection for its idle seconds. That decouples concurrency from the pool size and is the
     real fix if the ramp confirms the pool as the wall.
2. **Vendor quotas.**
   - **Anthropic:** cost is a non-issue (whole matrix < $2; per session ~₹5–₹13). Confirm the
     **rate limits** (requests/min, tokens/min) on the account tier cover the peak concurrent
     turn rate at launch — that, not cost, is the Anthropic risk under a spike.
   - **Sarvam:** the real budget lever. **Confirm the credit/sec rate and the monthly credit
     quota**, then size against measured seconds. If voice modes are expensive, default the
     onboarding cohort to **TEXT** (zero Sarvam spend, full interview) and make AUDIO/VIDEO
     opt-in — the ledger already prices every mode so this is a data-driven toggle.
3. **`MAX_CONCURRENT_SESSIONS` = ★** — set it to the **measured safe knee from item 4 minus a
   margin** (e.g. if the knee is 15, set 12). Its whole job is to keep the Space *below* the
   point where the shared DB saturates, so it protects the LMS too. Until the ramp runs, a
   conservative interim value of **12** (just under the 15-connection pool wall) is the safe
   default to ship with — the valve is already built and tested; only the number is pending.
4. **Apply migration 011** so every launch-week session carries a cost ledger — that's how the
   projections above become measured actuals over the first real cohort.

### What's needed to close items 3, 4, 6 (the go-ahead gate)

- **Item 3:** your go-ahead to spend. Cheapest safe first step: run the **TEXT column** (~$0.5,
  0 Sarvam). Voice cells need either the confirmed-lower Sarvam rate to fit under 500 credits, or
  your explicit `--over-caps` sign-off.
- **Item 4:** your go-ahead + `MAX_CONCURRENT_SESSIONS` unset on the Space (~$7.74 LLM, 0 Sarvam).
- **Item 6:** run `scripts/db_pool_audit.py` from an allowlisted host with current Aiven creds.

---

## Files delivered this phase

**Backend:** `app/ledger.py` (new), `app/config.py`, `app/db.py`, `app/claude_client.py`,
`app/stt.py`, `app/main.py`, `app/schema_check.py`.
**DB:** `db/migration_011_cost_ledger.sql`, `db/migration_011_cost_ledger_rollback.sql`.
**Frontend:** `frontend/src/App.jsx` (capacity hold panel).
**Scripts:** `scripts/synthetic_student.py` (driver, importable), `scripts/cost_matrix.py`,
`scripts/capacity_ramp.py`, `scripts/db_pool_audit.py`.
**Tests:** `tests/test_cost_ledger.py`, `tests/test_capacity.py`, `tests/test_schema_check.py`
(updated). All 416 pass.
**Docs:** `docs/CAPACITY_COST_PHASE_PROMPT.md`, this report.
