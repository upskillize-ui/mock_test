# InterviewIQ — Voice Phase 3 Report (Full Voice Mode)

Everything speaks (TTS repaired), everything listens (mic in all rounds), and delivery
gets scored (compute-and-discard metrics → a readout Delivery Profile). Builds on Phase 1
(TTS) and Phase 2 (STT). All feature-flagged; **no audio is ever stored**; consent stays
enforced at point of capture; `vyom_` tables are untouched except one additive column.

Backend suite **green: 64/64** (stages, tts, stt, phase0, delivery). `vite build` passes.
The live TTS diagnostic returns real audio bytes.

---

## 1. What shipped

### Part A — TTS repaired (was silent on every call)
- **Root cause:** the v3 request contract was already correct; the failure was the **5-second
  read timeout**. Bulbul v3 takes several seconds per sentence, so every call raised
  `ReadTimeout` → `None` → silent interviewer. Timeout raised to **connect 10s / read 30s**.
- **Diagnosability:** `synthesize()` now logs the vendor **status + response body** (truncated,
  never the key) on a non-200, and the concrete exception text on transport errors.
- **`scripts/test_tts.py`** — loads `backend/.env`, does a raw probe (prints status + body +
  `audios[]`) and exercises the real `synthesize("Hello, welcome to your interview.", "ritu")`,
  reporting byte count or the full error. **Verified live: HTTP 200, ~30 KB of MP3 bytes.**
- Cache key already binds **model + speaker + sample-rate** (+ temperature/pace), so v2 clips
  can't leak post-upgrade; **5 stale cache files were cleared**.

### Part B — Mic in all answering rounds
- `/session/stt`: the **BEHAVIOURAL-only 409 is gone**. All other gates kept — `STT_ENABLED`
  + `VOICE_ENABLED` (404 when off), ownership, `voice_recording` consent (403), 10 MB size cap.
  Cost cap raised to **`MAX_ANSWERS_PER_SESSION + 5`** (mirrors the TTS cap).
- Frontend: the mic is **active in every answering round** (Warm-up, Domain, Behavioural, Case,
  **Reverse**) whenever STT is available and the learner can answer. The "unlocks in the
  Behavioural round" locked-mic + tooltip is removed. Consent modal unchanged. Each sent answer
  now carries a **Spoken / Typed** caption under the bubble.

### Part C — Delivery metrics (compute-and-discard)
- `stt.py`: new `transcribe_full()` requests Saarika **word/segment timestamps** (`with_timestamps`,
  same call, no extra cost) and returns `{transcript, timestamps, confidence}`. `transcribe()`
  kept as a thin wrapper. Recording **duration** is sent by the client on the upload.
- New **`app/delivery.py`** (pure, unit-tested) computes per spoken answer: **wpm** (+ pace flag:
  <110 slow / >180 rushed vs the **130–160** sweet spot), **filler density/min** (um, uh, like,
  basically, actually, you know, **matlab, woh**), **long mid-answer pauses** (>2 s gaps *between*
  segments — the pre-answer thinking pause is excluded) when timestamps are usable, and an
  **articulation proxy = STT confidence** if the vendor returns one.
- **Storage:** only the metrics JSON, on **`vyom_messages.delivery_metrics`** (migration 004,
  additive, nullable). **Audio is discarded immediately** as in Phase 2; **typed answers store
  no metrics**. Metrics never block the turn — any failure yields null and the learner proceeds.

### Part D — Delivery Profile in the readout
- The debrief aggregates spoken-answer metrics into a **Delivery Profile**: avg WPM + sweet-spot
  verdict, filler density with the **top 2 offenders named**, a pause-pattern note, and a
  **delivery band** (the standard four bands). **< 3 spoken answers →** "Not enough voice data —
  try answering aloud next session." (no band).
- Colors follow the locked semantics (gold Offer-Ready, teal Interview-Ready, navy Building,
  orange Not Ready). Copy is direct, never punitive.
- **Delivery does NOT affect the overall readiness band in v1** — it is shown alongside and the
  card says so explicitly ("Shown separately, not counted in your readiness band yet").

### Part E — Live voice state chip
- A plain-text chip in the session header driven by **actual events**: **Listening** while
  recording, **Thinking** while transcribing/scoring, **Speaking** while TTS audio plays, else
  nothing. Existing tokens only — the orb/waveform treatment is deferred to the dual-theme redesign.

### Part F — Migration + tests
- `db/migration_004_delivery_metrics.sql` (additive `JSON NULL` column) **+ its rollback file**.
- Tests: TTS script green; STT **accepted in all answering rounds** (was a 409 test, now asserts
  200 in Warm-up/Domain/Case/Reverse); **`test_delivery.py`** (17 assertions: wpm/pace, fillers
  incl. Hinglish + substring safety, pauses, sanitize, aggregation band + <3 guard); cost-cap and
  graceful-null tests updated. Full suite green; `vite build` passes.

---

## 2. Privacy rationale — compute-and-discard (metrics ≠ recordings)

The recording is transcribed **in memory and discarded** the instant the STT request returns —
exactly as in Phase 2. Phase 3 adds only **derived numbers** (wpm, filler counts, a pause count,
an optional confidence value) on the answer's message row. Consequences:

- **What lands in the DB is not a recording and not biometric** — it's a handful of integers/floats
  describing *how* an answer was delivered, in the same sensitivity class as the transcript text we
  already store. There is no new category of personal data to protect, retain, export, or breach.
- **The additive column rides the existing DPDPA machinery:** `delivery_metrics` is included in the
  `/me/data` export, is purged with the message row by the retention job, and is dropped on erasure —
  no new retention/erasure surface.
- **Legal review scope is unchanged.** Because no audio is stored, the Phase 2 consent posture (voice
  consent captured at point of capture; `v0-draft` copy pending legal) covers Phase 3 as-is. The
  consent copy did not need to change and was not changed.

---

## 3. Activation checklist

1. **Apply migration 004** (`db/migration_004_delivery_metrics.sql`) **before** enabling delivery —
   the turn INSERT writes the new column. Rollback file is alongside.
2. **Flags:** `TTS_ENABLED=true`, `STT_ENABLED=true`, `VOICE_ENABLED=true`, and
   **`DELIVERY_METRICS_ENABLED=true`** for the Delivery Profile. `STT_WITH_TIMESTAMPS=true` (default)
   enables pause detection. `SARVAM_API_KEY` set (shared by TTS + STT).
3. **Verify TTS live:** run `python scripts/test_tts.py` — it must print `SUCCESS … audio bytes`.
4. **Legal:** finalize the `v0-draft` voice-consent copy and bump `CONSENT_COPY_VERSION`; sign off the
   compute-and-discard posture in §2 and the provisional delivery scoring in §6.
5. Deploy the frontend build; run the UAT script (§5).

---

## 4. Cost note

- **Timestamps add nothing.** Requesting `with_timestamps` is the **same single STT call** at the
  same price — it only enriches the response. No extra vendor round-trips for delivery metrics.
- **TTS** billing is unchanged from Phase 1 (content-addressed cache; per-session cap = answers + 5).
- **STT** per-session cap raised to answers + 5; worst-case vendor calls per session are bounded by
  that cap regardless of how often the learner re-records.

---

## 5. UAT script (for Haritha)

Pre-req: migration 004 applied; `TTS_ENABLED`, `STT_ENABLED`, `VOICE_ENABLED`,
`DELIVERY_METRICS_ENABLED` all true; valid `SARVAM_API_KEY`; a mic-equipped device on
Chrome/Edge/Firefox.

1. **Hear the v3 greeting** — start a session; the interviewer's greeting **plays aloud** in the v3
   voice (no longer silent). The header chip shows **Speaking** while it plays. ✅
2. **Speak in Warm-up** — the mic is active immediately (not locked). First tap → consent modal →
   Allow → header shows **Listening**, orange timer counts up → stop → **Thinking** → transcript lands
   in the editable box → edit → **Send**. The bubble shows a **Spoken** caption. ✅
3. **Speak in Domain** — mic still active in the Domain round; repeat the record→edit→send flow. ✅
4. **Speak in Reverse** — in the reverse round (you interview them) the mic is **also active**; ask
   your question aloud. ✅
5. **Hinglish answer** — speak a code-mixed answer (e.g. *"Basically maine team ko lead kiya, um, jab
   deadline miss ho rahi thi, so I restructured the sprint, you know."*). Confirm the transcript is
   reasonable and editable; fillers like "um / you know / basically" are what the Delivery Profile
   will count. ✅
6. **Type one answer** — answer one question by typing; its bubble shows **Typed** and it contributes
   **no** delivery metrics. ✅
7. **Readout shows the Delivery Profile** — end the session; the report shows a **Delivery Profile**
   card with avg WPM + verdict, fillers/min + top 2 offenders, a pause note, and a delivery **band** —
   with the line that it's *shown separately, not counted in your readiness band yet*. ✅
8. **Too few spoken answers** — in a session where you spoke fewer than 3 answers, the card instead
   says **"Not enough voice data — try answering aloud next session."** ✅
9. **Fallbacks** — deny mic permission or point the key at an invalid value → toast *"Voice input
   unavailable — please type your answer"*, typing unaffected, no crash. ✅

---

## 6. Product decisions to confirm (not guessed)

- **D1 — the delivery 0-100 score formula is provisional.** `delivery._delivery_score` is a
  transparent, hand-tuned heuristic (pace-band + filler-rate + pause penalties). The thresholds and
  weights are **not calibrated against real sessions**. Product/data should validate them before this
  band is shown as authoritative. (It does **not** affect the readiness band, limiting the blast radius.)
- **D2 — delivery band thresholds.** The delivery band reuses the **same 50/70/85** cutoffs as
  readiness. Confirm those are appropriate for *delivery* specifically, or set delivery-specific bands.
- **D3 — the filler list is blunt.** "like" and "actually" are counted as fillers even when used
  legitimately, so filler counts skew high. Confirm the list (and whether to weight/contextualize).
- **D4 — word-level pauses are unreliable with `saarika:v2.5`.** In probing, v2.5 returned the whole
  utterance as a **single timestamp segment**, so mid-answer pause detection is usually null. Reliable
  pause metrics would need a model/endpoint that returns true word-level timings. Decide whether pauses
  are worth pursuing now or deferring.
- **D5 — SPOKEN/TYPED meta and delivery metrics are client-reported.** The Spoken/Typed caption is
  client-tracked (not server-persisted), and delivery metrics are echoed by the client from
  `/session/stt` back to `/session/turn` (server re-validates the shape but trusts the values).
  Informational-only in v1. If either must be tamper-proof/authoritative, that needs a server-side
  association (e.g. a short-lived STT token) — flag if required.
- **D6 — consent copy is still `v0-draft`** (unchanged from Phase 2). Legal sign-off + a
  `CONSENT_COPY_VERSION` bump are still outstanding.

---

## 7. Known gaps / limitations

- **Batch, not streaming** STT (unchanged) — robust for campus WiFi; live streaming is a later upgrade.
- **Pauses often null** (see D4) — the profile degrades gracefully to "pause timing wasn't available".
- **No articulation score** — Saarika returned no confidence field in probing, so the articulation
  proxy is null until the vendor exposes one.
- **History screen doesn't show the Delivery Profile** — it's computed live at `/session/end` from the
  message metrics, so it appears in the end-of-session readout, not the historical detail view.
- **Delivery metrics depend on retained messages** — after the transcript retention window purges a
  session's messages, re-opening its readout shows "not enough voice data" (metrics went with the rows).
- **Send-while-recording** edge from Phase 2 still applies (low risk).
- **`delivery_metrics` client-echo** (D5) — informational, so client tampering only affects that
  learner's own non-scoring readout.
