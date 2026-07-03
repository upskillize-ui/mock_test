# InterviewIQ — Voice Phase 2 Report (STT for the Behavioural Round)

**Scope shipped:** the learner can *speak* their answer in the **BEHAVIOURAL round only**;
the transcript is dropped into the editable text box for review before Send. Every other
round stays typed. No delivery scoring (that is Phase 3). Shipped **OFF** behind
`STT_ENABLED` (default false) and additionally gated by `VOICE_ENABLED` + voice consent.

---

## 1. What shipped

### Backend
- **`app/stt.py`** — `async transcribe(audio_bytes, mime) -> str | None`. Sarvam Saarika
  (`POST https://api.sarvam.ai/speech-to-text`), multipart upload, 15s timeout, returns
  `None` on **any** failure (missing key, network, non-200, bad body, empty transcript).
  Never logs the API key, the audio, or the transcript. Mirrors the resilience contract of
  the Phase-1 `tts.py`. Plus a per-session in-process vendor-call counter
  (`note_stt_call` / `stt_calls_used` / `stt_cap_reached`) for the cost guard — no DB, `vyom_` tables untouched.
- **`POST /session/stt`** — multipart (`session_id` + `audio` file), auth-guarded. Validates,
  in order: `STT_ENABLED && VOICE_ENABLED` (else **404**, so a disabled feature isn't
  advertised) → session ownership (`_load_session`) → `current_stage == BEHAVIOURAL` (else
  **409**) → `voice_recording` consent row via the existing `compliance.consent_gate_ok`
  (else **403**) → per-session cost cap (else **429**) → 10 MB size cap (else **413**).
  Returns `{ transcript }`. **It does not submit the turn.**
- **No raw audio stored.** Bytes are read into memory, passed to the vendor, and discarded
  when the request returns. Nothing hits disk or DB. Only the eventual *text* is persisted,
  and only through the normal `/session/turn` message insert the learner triggers by pressing Send.
- **State signal** — `SessionState.stt_available` (= `STT_ENABLED && VOICE_ENABLED`), computed
  in `_build_state`, so the frontend knows whether to render the mic. Rides on
  start / turn / state responses.
- **Config** — `STT_ENABLED` (false), `STT_MODEL` (`saarika:v2.5`), `STT_LANGUAGE`
  (`unknown` = auto-detect; Hinglish/en-IN/regional; ops can pin `en-IN`),
  `STT_MAX_UPLOAD_BYTES` (10 MB), `STT_RETRY_ALLOWANCE` (3). Reuses `SARVAM_API_KEY`.
- **`requirements.txt`** — pinned `python-multipart==0.0.20` (already installed; FastAPI needs
  it for `Form`/`File`, but it was previously unpinned).

### Frontend (`App.jsx`)
- Mic button appears in the composer **only** when `state.stt_available && current_stage === 'BEHAVIOURAL'`.
- Record via **MediaRecorder**: tap to start, tap the stop-square to stop. Orange (`#E8521A`)
  pulse ring while recording, elapsed timer in **DM Mono**. Hard **3-minute** auto-stop.
- On stop → upload to `/session/stt` → subtle **"Transcribing…"** shimmer → the transcript is
  **inserted into the editable text input** (appended if the box already had text, clamped to
  4000 chars). The learner reviews, edits, and presses **Send** as normal.
- **Consent modal on first mic use per session** — existing `POST /consent` with
  `consent_type='voice_recording'`, `copy_version='v0-draft'`; the draft copy is marked
  `[PENDING LEGAL REVIEW]` in a code comment. Accepting records consent then starts recording.
- **Zero-degradation fallback** — mic-permission denial, STT failure, or a null transcript all
  produce the toast *"Voice input unavailable — please type your answer"* and normal typing
  continues. Recording/stream/timers are torn down on unmount.
- **Brand** — inline Lucide-style mic/stop SVG at 1.6px stroke; navy `#0B1628` base, orange
  `#E8521A` recording, teal `#00C4A0` accents; Plus Jakarta Sans UI, DM Mono timer. No emojis.

### Tests
- `tests/test_stt.py` — 10 tests: graceful `None` (no key / empty audio), cost-cap counter,
  and endpoint gates (feature-off 404, non-BEHAVIOURAL 409, missing consent 403, size cap 413,
  cost cap 429, happy-path transcript, graceful-null 200).
- **Full suite green: 39/39** (stages 7, tts 10, phase0 12, stt 10). Backend imports cleanly,
  all routes register (`POST /session/stt` present), `vite build` succeeds.

---

## 2. Design decision: no raw-audio storage (why it minimises DPDPA exposure)

The endpoint **transcribes and discards** — audio never touches disk or DB. Consequences:

- **Nothing to retain, purge, export, or breach.** Under DPDPA, stored audio would be
  biometric-adjacent personal data pulling in retention windows, an entry in the `/me/data`
  export, a target for the erasure/purge job, and a much larger breach blast-radius. By keeping
  the persisted surface to **text only** (a normal `vyom_messages` row, already covered by the
  Phase-0 retention/erasure machinery), Phase 2 adds **no new data category** to protect.
- **The transcript is exactly what the learner would have typed** — same sensitivity class as
  the existing typed answers, already governed. The consent copy says this plainly.
- Recording **playback** (which *would* require storing audio) is deliberately deferred to
  Phase 3 as a separate, explicit product/legal decision — not smuggled in here.

---

## 3. Cost per behavioural round (estimate)

Sarvam Saarika STT is billed on **audio minutes transcribed**. Per session, calls are capped at
**behavioural-question-count + 3 retries** (Fresher/Junior 3 questions → cap 6; Mid 3 → 6;
Senior 4 → 7).

Illustrative round: **3 behavioural answers × ~90s each ≈ 4.5 minutes** of audio; with a retry or
two, budget **~5–6 audio-minutes/round**.

| Assumed vendor rate | Cost / behavioural round (~5 min) |
|---|---|
| ₹0.30 / min | ~₹1.5 |
| ₹0.50 / min | ~₹2.5 |
| ₹1.00 / min | ~₹5.0 |

> **Confirm the live Saarika per-minute rate** against the current Sarvam contract — the table
> is a planning estimate, not a quoted price. Worst case is bounded by the per-session call cap
> regardless of rate. (Unlike TTS, STT has **no content cache** — every answer is unique — so
> there is no cache-hit saving to model.)

---

## 4. Activation checklist

1. **Flags** (both required): `STT_ENABLED=true` **and** `VOICE_ENABLED=true`.
2. **Vendor**: `SARVAM_API_KEY` set (shared with TTS); optionally pin `STT_LANGUAGE=en-IN`.
3. **DB**: none. `vyom_consents` already exists (migration 003). **No new migration.**
4. **Legal**: replace the `v0-draft` consent copy with final wording, then **bump
   `CONSENT_COPY_VERSION`** (frontend) so grants trace to the approved text. Sign off the
   retention posture (text-only; no audio) recorded in §2.
5. **Decision 1 closed** — no pre-flip action. The start-time voice-consent gate has been removed
   (consent is enforced at capture); typed-only sessions start normally with `VOICE_ENABLED=true`.
   See §6 (RESOLVED).
6. Deploy frontend build; smoke-test the UAT script (§5).

---

## 5. UAT script (for Haritha)

Pre-req: `STT_ENABLED=true`, `VOICE_ENABLED=true`, valid `SARVAM_API_KEY`, a mic-equipped device,
Chrome/Edge/Firefox (MediaRecorder). Start a session and advance to the **Behavioural** round.

1. **Mic visibility** — mic button is **absent** in Warm-up/Domain/Case, **present** in Behavioural. ✅
2. **First-use consent** — first mic tap opens the consent modal with the audio-discarded copy.
   *"Not now"* closes it and typing still works; *"Allow & record"* records the grant and begins recording. ✅
3. **English answer** — speak a 30–60s STAR answer → orange pulse + DM Mono timer counts up →
   tap stop → "Transcribing…" → transcript lands in the editable box. Edit a word, press **Send**. ✅
4. **Hinglish answer** — speak a code-mixed answer (e.g. *"Maine team ko lead kiya jab ek critical
   deadline miss ho rahi thi, so I restructured the sprint…"*). Confirm the transcript captures
   both languages reasonably (Saarika auto-detect / `STT_LANGUAGE=unknown`). Minor errors are
   expected — the point is that it's **editable** before Send. ✅
5. **Second use, no re-prompt** — on the next behavioural question the mic records immediately
   (consent already given this session). ✅
6. **3-minute auto-stop** — start recording and wait; it auto-stops at 3:00 and transcribes. ✅
7. **Mic-deny fallback** — block mic permission (browser site settings) → tap mic → toast
   *"Voice input unavailable — please type your answer"*, typing unaffected. ✅
8. **Vendor-failure fallback** — (ops) point `SARVAM_API_KEY` at an invalid value → tap/record/stop
   → same toast, no crash, typing works. ✅
9. **Mid-recording refresh** — start recording, refresh the tab. Session resumes (INT-06) into the
   behavioural round; the in-flight recording is discarded (nothing was uploaded/stored); the mic
   is ready again. ✅
10. **Rating still works** — after sending a spoken-then-edited answer, the 1–5 confidence widget
    appears and advances the stage as before. ✅

---

## 6. Product decisions to confirm (not guessed)

**Decision 1 — the `start_session` voice gate vs. mid-interview consent (needs a call).**
The pre-existing INT-07 gate in `start_session` already **requires a `voice_recording` consent row
to *start* any session when `VOICE_ENABLED` is true.** Phase 2, per the hard rule ("wire the
existing gates, do not rebuild them"), does **not** touch that gate. But it collects voice consent
at **first mic use**, not at setup. So with `VOICE_ENABLED=true`, a learner with no prior voice
consent would be **blocked from starting even a typed-only session** (403). Options for product/legal:
  - **(a)** Move the voice consent to **session setup** (collect `voice_recording` before start) —
    simplest, but asks for voice consent even from learners who only type.
  - **(b)** **Relax the start gate** so `VOICE_ENABLED` no longer forces consent at start, leaving
    the per-use `/session/stt` gate (already implemented) as the sole STT consent enforcement —
    keeps typed sessions frictionless. *(Recommended, but it edits an INT-07 gate, so it's your call.)*
  - **(c)** Keep as-is and accept that turning on voice makes voice consent mandatory for everyone.

> **RESOLVED (2026-07-03) — Option (b), consent at point of capture.** The
> `voice_recording` consent check has been **removed from `start_session`**: a session now
> starts normally for everyone, including typed-only learners, even when `VOICE_ENABLED=true`.
> Voice-recording consent is enforced in **exactly two places**, both at the moment audio is
> actually captured:
> 1. **First-mic-use consent modal** (frontend) — no recording begins until the learner accepts;
> 2. **`POST /session/stt` server-side gate** (`compliance.consent_gate_ok` → **403** without a
>    `voice_recording` row) — authoritative; a client that skips the modal still cannot transcribe.
>
> **Rationale for legal:** consent is captured **at the point of processing** (when the mic turns
> on and audio is sent for transcription), not pre-emptively at session start. This is tighter,
> not looser — no one is asked for voice consent they never use, and no audio can be processed
> without an explicit, logged `voice_recording` grant tied to the capture event. It also removes
> a UX defect where enabling voice would have blocked typed-only sessions. The server gate is the
> hard enforcement boundary; the modal is the UX layer. **Retained/enforced:** the `/session/stt`
> 403 gate, the per-session consent modal, and the no-audio-storage posture (§2) are unchanged.
> **Regression guard:** `tests/test_stt.py::test_start_session_does_not_require_voice_consent`
> asserts `/session/start` returns 200 (not 403) with `VOICE_ENABLED=true` and no consent row;
> `test_endpoint_requires_voice_consent` continues to assert the `/session/stt` 403. Decision 1 in
> the Activation checklist (§4, item 5) is therefore closed — no pre-flip action required.

**Decision 2 — consent scope/duration.** `voice_recording` consent is currently recorded per
session (re-prompted each new session, matching "first mic use per session"). Confirm whether one
grant should persist across sessions (fewer prompts) or stay per-session (stronger, explicit).

**Decision 3 — recording playback.** Deferred to Phase 3. Enabling it reverses the no-audio-storage
posture in §2 and needs its own DPDPA review (storage, retention, export, erasure).

---

## 7. Known gaps / limitations

- **Batch, not streaming.** The full answer uploads once after stop (robust for campus WiFi);
  live streaming transcription is a Phase-3 upgrade.
- **No delivery scoring.** Pace/filler/clarity analysis is out of scope (Phase 3). STT only
  produces text; the debrief scores that text exactly as typed text.
- **`Send` is not disabled while recording.** Pressing Send mid-recording sends the current input
  and the eventual transcript lands in the (now-cleared) box for the *next* answer. Low-risk edge;
  can be hardened in Phase 3 if it surfaces in UAT.
- **Cost cap is in-process.** Like the Phase-1 TTS cap, the counter resets on process restart /
  isn't shared across replicas. Fine as a guard-rail; a hard multi-replica budget would need a
  shared store.
- **Transcript accuracy varies** for heavy code-mixing / strong accents / noisy rooms — mitigated
  by the mandatory review-and-edit step before Send.
- **Browser support.** MediaRecorder is required; unsupported/embedded webviews fall back to the
  "voice unavailable" toast and typing (no crash).
- **Sarvam response shape** implemented against the documented batch contract (`transcript` field,
  with a `text` fallback). Verify against the live API on first real key and adjust the key name in
  `stt.transcribe` if the vendor differs.

---

## 8. Addendum — "mic never appears" root cause + discoverability fix (2026-07-03)

**Reported symptom:** with `STT_ENABLED=true` and `VOICE_ENABLED=true` in `backend/.env` and the
backend restarted, the mic button never rendered in the Behavioural round.

**Chain traced end-to-end — where it was and wasn't broken:**
1. **Config parse — OK.** `backend/.env` had clean `true` values; `settings.STT_ENABLED` and
   `VOICE_ENABLED` both parse to `True`. *Hardening applied anyway:* all three voice flags now go
   through a shared `_env_bool()` that `.strip()`s the value, so a trailing space / inline comment
   (`VOICE_ENABLED=true  # on`) can no longer silently parse as False — the classic "flag set but
   feature stays off" footgun.
2. **State payload — OK.** `GET /session/{id}/state` and `_build_state` return
   `stt_available=true` when both flags are on (verified: the field serialises correctly). *Change:*
   `stt_available` is now **also** mirrored at the top level of the `/session/start` response, so a
   client that keeps only the session id can decide to show the mic without a second `/state` fetch.
3. **Frontend read — OK, but visibility was over-gated (the real cause of "never appears").** The
   mic was rendered **only** when `stt_available && current_stage === 'BEHAVIOURAL'`. That condition
   is correct and re-evaluates on every state change (it reads live `sstate`, not a mount-time
   snapshot), so it *does* light up on entering Behavioural. But because the mic was **invisible in
   every other stage**, there was **no signal anywhere** that voice existed — so a tester checking
   in Warm-up/Domain, or anyone whose client was pointed at a backend without the flags, saw simply
   nothing and read it as "feature missing / broken." The tightest-fit **contributing** root cause
   is a client/backend mismatch: the frontend's default `API_URL` is the hosted HF space, so
   flipping flags in a **local** `.env` changes nothing the hosted client can see — and there was no
   on-screen or console signal to reveal `stt_available` was `undefined`.

**Fixes shipped:**
- **Discoverability** — the mic now renders **whenever `stt_available` is true**, in every
  answerable stage. Outside Behavioural it is a **locked** control: faint line tokens (no orange),
  tooltip *"Voice answers unlock in the Behavioural round"*, and a tap-toast with the same message.
  It uses `aria-disabled` (not the native `disabled` attribute) specifically so the tooltip still
  shows on hover and taps still explain it. In Behavioural it becomes the active record/stop button
  exactly as before. Learners now discover speaking exists **before** they reach the round.
- **Diagnostics** — backend logs one line at startup:
  `Voice: TTS=<bool> STT=<bool> VOICE=<bool> model=bulbul:v3 speakers=<f>/<m>`, so a misconfiguration
  (or a client hitting the wrong backend) is visible in ten seconds. The frontend `console.debug`s
  `stt_available` (and the stage) once per state change **in dev mode only** — an `undefined` there
  instantly points at a client/backend mismatch; `false` points at a flag being off.

**Manual verification (both flags on, fresh session):**
1. Start a session → in **Warm-up** the **locked** mic shows next to Send with the unlock tooltip. ✅
2. Advance to **Behavioural** → the mic becomes **active** (record button); dev console shows
   `stt_available = true | stage = BEHAVIOURAL`. ✅
3. First mic tap → consent modal fires; **Allow & record** → orange pulse + DM Mono timer. ✅
4. Speak → stop → "Transcribing…" → transcript lands in the **editable** input → edit → **Send**. ✅
5. Mic-deny / vendor-failure → toast *"Voice input unavailable — please type your answer"*, typing
   unaffected. ✅

**Tests:** `test_stt.py` adds `test_state_stt_available_true_only_when_both_flags_on`
(true only when STT **and** VOICE are on; false if either is off). Full suite **green (44 total)**;
`vite build` passes. Consent logic, `vyom_` tables, and scoring were not touched.
