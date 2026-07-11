# InterviewIQ — Voice Phase 3 Plan (Discovery)

> **Status: PLAN ONLY — no product code written.** This document scopes Phase 3,
> grounds each option in the code that exists today, and surfaces the product/legal
> decisions that must be made *before* implementation. Nothing here has been built.
> Generated 2026-07-03 while continuing from the completed, committed Phase 2.

---

## 0. Where we are (verified)

- Phase 1 (TTS) and Phase 2 (STT for the Behavioural round) are **shipped, committed, OFF by flag**.
- Backend suite **green: 44/44** (re-run 2026-07-03, not just quoted from the report).
- STT today is **batch** (`app/stt.py`): record full answer → one upload → transcript → learner
  edits → Send. Audio is transcribed in-memory and discarded; **only text is persisted**.
- Per-session vendor-call cap is **in-process** (`_session_stt_counts`), no DB.
- Debrief scores the **text** of an answer exactly as if typed — there is **no delivery signal**
  (pace, fillers, clarity) anywhere in the pipeline yet.

Phase 2's report (§6) left three things explicitly undecided. Phase 3 is where they land.

---

## 1. Candidate scope for Phase 3 (three independent tracks)

These are **separable**; we do not have to do all three, and they carry very different risk.

### Track A — Delivery scoring (pace / fillers / clarity)  · *lowest legal risk*
Analyse *how* the behavioural answer was delivered, not just *what* was said, and fold a
**delivery sub-score** into the debrief.

- **Pace** — words ÷ speaking-seconds (WPM). We already have the recording duration client-side
  and the transcript word count server-side; no new vendor call needed for a first cut.
- **Fillers** — count "um / uh / like / you know / matlab / actually" against transcript length.
  Cheap, transparent, tunable; language-mixed filler list for Hinglish.
- **Clarity** — reuse the existing Claude debrief pass; add a rubric line scoring structure/signposting.
- **Where it plugs in:** `stages.py` is pure scoring math — a `delivery_profile(...)` helper fits
  the existing `calibration_profile` / `band_for` pattern exactly. The debrief assembly in `main.py`
  gains one more section. **`vyom_` tables:** a delivery sub-score is a new field on the existing
  debrief/session summary — confirm whether it needs a column (migration 004) or rides in the JSON
  summary blob (no migration). *Decision D1 below.*
- **DPDPA:** neutral. Derived metrics over text we already store; **no audio retained**. Same posture as §2 of Phase 2.

### Track B — Streaming STT (live transcription while speaking)  · *medium risk, high cost*
Replace batch upload with a WebSocket to Sarvam so text appears as the learner talks.

- **Robustness cost:** Phase 2 deliberately chose batch "for campus WiFi." Streaming reintroduces
  the fragility batch was chosen to avoid. Recommend **keeping batch as the fallback** and treating
  streaming as a progressive enhancement only where the socket holds.
- **Cost guard:** the in-process per-session cap counts discrete calls; a stream needs a
  **minutes/duration** cap instead. New accounting in `stt.py`.
- **DPDPA:** still no storage if we transcribe-and-discard frames, but the audio now transits a
  long-lived socket — worth a line in the retention note.
- **Assessment:** highest effort, least user-visible benefit for a review-before-send flow (the
  learner still edits before Send). **Recommend deferring** unless UAT specifically demands it.

### Track C — Recording playback  · *highest risk — reverses a shipped posture*
Let the learner (or a reviewer) replay their spoken answer.

- **This requires STORING AUDIO** — which Phase 2 explicitly refused (Report §2). Enabling it turns
  audio into retained, biometric-adjacent personal data and pulls in **retention windows, `/me/data`
  export, the erasure/purge job, and a larger breach blast-radius**.
- **Cannot be built without a fresh DPDPA sign-off** (storage location, encryption, retention TTL,
  export format, erasure wiring into the existing Phase-0 purge job).
- **Recommend: do not build in Phase 3** unless product+legal explicitly reverse the no-storage
  decision in writing. If approved, it is its own mini-phase with its own migration and consent copy.

---

## 2. Recommended Phase 3 = **Track A only**

Rationale: Track A is the piece that actually advances the *product thesis* (better interview
feedback), carries **no new DPDPA surface**, needs at most a trivial migration, and reuses the
`stages.py` pure-logic pattern that is already well-tested. Tracks B and C are cost/risk-heavy and
gated on decisions that aren't ours to make. Ship A, leave B/C as documented, decision-gated options.

### Proposed build (Track A), mirroring the Phase 1/2 discipline
1. `stages.py`: add `delivery_profile(word_count, speaking_seconds, transcript) -> dict` returning
   `{ wpm, pace_band, filler_count, filler_rate, delivery_note }`. Pure, unit-tested in isolation.
2. `main.py`: capture `speaking_seconds` from the `/session/stt` request (client sends elapsed
   recording time as a form field; **not** stored audio), thread it to the debrief assembly, add a
   **Delivery** section to the readout. Gate the whole thing behind a new `DELIVERY_SCORING_ENABLED`
   flag (default false), consistent with shipping OFF.
3. Frontend: a small Delivery card in the debrief (navy/orange/teal, Plus Jakarta Sans, DM Mono for
   the WPM number). No new capture UI — it reuses the Phase 2 mic.
4. Tests: pace bands at boundaries, filler counting incl. Hinglish tokens, zero-speech guard,
   flag-off path omits the section. Keep the full suite green.
5. `VOICE_PHASE3_REPORT.md` in the established format.

---

## 3. Decisions to confirm BEFORE coding (not guessed)

- **D1 — storage shape for the delivery sub-score.** New column (migration 004) vs. ride in the
  existing session-summary JSON. *Recommendation: JSON blob first (no migration), promote to a
  column only if we need to query/aggregate it.*
- **D2 — is Track A the right/only scope?** Or does product want streaming (B) and/or playback (C)
  in this phase? B is deferrable; **C cannot ship without reversing the no-audio-storage posture and
  a new DPDPA sign-off.**
- **D3 (carried from Phase 2 §6) — consent scope/duration.** Per-session vs. persistent
  `voice_recording` grant. Independent of Track A but still open.
- **D4 — does delivery scoring affect the headline readiness band,** or is it a *separate, advisory*
  card? *Recommendation: advisory only in v1 — don't let WPM move the offer-readiness number until
  it's calibrated against real sessions.*

---

## 4. What I did NOT do

- No code changed. No migration written. No flags added. Tree is still clean at plan time.
- No product/legal decision assumed — Track C in particular is left explicitly gated.

**Next step on approval:** confirm D1–D4 (or just "Track A, recommendations as written"), and I'll
implement Track A behind `DELIVERY_SCORING_ENABLED` with the report, exactly as Phases 1–2 were shipped.
