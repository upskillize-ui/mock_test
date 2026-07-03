# InterviewIQ — Voice Phase 1 Report (TTS only)

**Audience:** business / product (plain English).
**Scope:** Phase 1 of the voice roadmap — **the interviewer speaks, the learner still types.** No speech-to-text, no microphone, no recording, no delivery scoring. Those are later phases.
**Status:** built, unit-tested (10/10 new TTS tests; 28/28 across the whole backend suite), backend imports cleanly, frontend `vite build` succeeds. **Shipped OFF by default** behind a feature flag.

---

## 1. What shipped

InterviewIQ can now read each interviewer question aloud using **Sarvam AI's Bulbul** voice. The learner reads and types exactly as before; the audio is an addition on top, never a replacement.

- The greeting and every interviewer question can be spoken. Audio **auto-plays** as each new question appears.
- **Mute toggle** in the interview header — session-sticky and remembered across visits.
- **Replay button** to hear the latest question again.
- The interviewer avatar shows a subtle **teal pulse** while it is speaking.
- **Voice picker** (Female / Male) on the setup screen; the choice is remembered.
- **Mobile Safari safety net:** iPhones block audio that starts on its own. We "unlock" sound the moment the learner taps **Start Interview**, and if a play is still blocked we show a small **"Tap to hear the question"** button instead of failing.
- **Zero degradation:** if the voice is turned off, fails, or the vendor is slow, the question text appears exactly as it does today. Voice never blocks or delays the interview — the text always goes out.

---

## 2. Under the hood (for the technical reader)

- New backend module `app/tts.py`: cleans the text (strips markdown, expands finance acronyms for pronunciation), calls Sarvam with a **5-second timeout**, and returns audio — or **nothing** on any error, so a voice failure can never stall an interview.
- **Acronym pronunciation:** a maintainable dictionary fixes the ones a generic voice mangles — CIBIL → "sibil", NPA → "N P A", FOIR → "F O I R", EMI → "E M I", KYC → "K Y C", CAGR → "C A G R", DSCR → "D S C R".
- **Audio delivery:** responses now include a nullable `audio_url`; the browser fetches the clip from `GET /session/audio/{hash}` (login required). Audio is **not** inlined into JSON (that would bloat every response).
- **No database changes.** The `vyom_` tables are untouched. Voice preference lives in the browser (same pattern as the existing mute/consent settings) and is sent with each request.

New environment settings (all optional, safe defaults):
`SARVAM_API_KEY`, `TTS_ENABLED` (default **false**), `TTS_MODEL` (default `bulbul:v2`), `TTS_LANG` (default `en-IN`), `TTS_VOICE_FEMALE` (default `anushka`), `TTS_VOICE_MALE` (default `abhilash`), `TTS_CACHE_DIR` (default `tts_cache`).

---

## 3. Cost notes

Voice is a metered vendor cost, so spend is controlled two ways:

1. **Caching (~30% saving expected).** Every clip is stored by a fingerprint of its exact text + voice. Greetings and common warm-up questions repeat across learners and sessions, so those are served from cache and **never re-billed**. The report's `test_cache_hit_does_not_recall_vendor` proves a repeat is not re-synthesized. Expect the hit rate to climb as the question bank stabilises.
2. **Per-session cap.** Each session can trigger at most `MAX_ANSWERS_PER_SESSION + 5` actual vendor calls (cache hits don't count). Beyond that, the interview simply continues in text — no error to the learner.

**Rough cost model:** vendor cost ≈ (unique questions across all sessions) × per-clip price, not (total questions). Because so much repeats, real spend tracks the *variety* of questions, not the *volume*.

---

## 4. Feature-flag rollout plan

Ship dark, ramp deliberately:

1. **Deploy with `TTS_ENABLED=false`** (current default). Nothing changes for learners. Confirm the app is healthy.
2. **Set `SARVAM_API_KEY`** and do an internal smoke test with `TTS_ENABLED=true` on a staging/one-team basis. Verify voice quality, acronym pronunciation, and the mobile-Safari path.
3. **10% rollout.** Enable for ~10% of traffic first (e.g. a canary deploy / a percentage cohort at the proxy or a per-user flag if available). Watch vendor spend, error rates, and the cache-hit ratio for a few days.
4. **Ramp to 100%** once cost-per-session and quality look right. The mute toggle means anyone who dislikes it can silence it instantly.
5. **Rollback is one setting:** flip `TTS_ENABLED=false` — the product falls back to today's text-only experience with no redeploy of logic.

---

## 5. UAT checklist (for Haritha)

Run with `TTS_ENABLED=true` and a valid `SARVAM_API_KEY`.

**Core**
- [ ] Start an interview → the greeting is spoken automatically, and the interviewer avatar pulses teal while it talks.
- [ ] Answer a question → the next question is spoken automatically.
- [ ] **Mute** → no further questions are spoken; refresh/return later → still muted (sticky).
- [ ] **Unmute** → new questions speak again.
- [ ] **Replay** the latest question → it plays again on demand.
- [ ] Pick **Male** voice in setup → the interviewer voice is male; pick **Female** → female.

**Acronym pronunciation** (ask a BFSI-flavoured mock so these come up, or check the greeting/warm-ups)
- [ ] "CIBIL" sounds like **"sibil"**, not "kibble/C-I-B-I-L".
- [ ] "NPA", "KYC", "FOIR", "EMI", "CAGR", "DSCR" are **spelled out clearly**, letter by letter.

**Mobile Safari (iPhone) — important**
- [ ] On an iPhone, tap **Start Interview** → the greeting audio plays (unlocked by that tap).
- [ ] If a question ever doesn't auto-play, a **"Tap to hear the question"** button appears and works.
- [ ] At no point does a broken/silent audio stop you from reading and typing.

**Graceful degradation**
- [ ] With `TTS_ENABLED=false`, the interview looks and works exactly like today (no voice controls, no errors).

---

## 6. Known gaps / decisions for product

- **Voice IDs need a quick QA.** Defaults are `anushka` (female) / `abhilash` (male) on `bulbul:v2`. Confirm these exist on our Sarvam plan and that we like them; they're env-overridable, so swapping is a config change, not code.
- **Audio access is "any logged-in user" by design.** Clips are addressed by a non-guessable content hash and shared across sessions (that's what makes caching work). A greeting clip contains the learner's first name; the non-enumerable hash mitigates exposure, but if product wants strict per-user gating we can add it in a follow-up.
- **Cache has no auto-eviction yet.** Clips accumulate on disk. For Phase 1 volumes this is fine; a later cleanup (or reusing the nightly purge) should cap it. On HuggingFace, point `TTS_CACHE_DIR` at a writable/persistent path.
- **Cost counter is per-process.** The per-session cap lives in memory and resets on restart / isn't shared across multiple workers. It's a spend guardrail, not an exact meter.
- **English (en-IN) only** this phase. Other languages are a config/roadmap item.
- **No STT / mic / recording / delivery scoring** — intentionally out of scope; those are later voice phases and are still gated by the separate `VOICE_ENABLED` consent flag built in Phase 0.

---

## 7. Guardrails honoured
Feature-flagged **off** by default. **No STT/mic code** whatsoever. The **API key and learner content are never logged** (vendor errors log status codes only). **`vyom_` tables untouched.** Inline Lucide-style SVG icons (no emojis); brand palette (teal `#00C4A0`) for the voice cues.

---

## 8. Addendum — Bulbul v3 upgrade (2026-07-03)

The v2 voices were legacy/low quality; TTS is upgraded to **Bulbul v3**.

- **Model** `bulbul:v3` (was `bulbul:v2`). **temperature=0.4** (stable, professional read),
  **pace=1.0**. **`pitch`/`loudness` removed** — v3 rejects them.
- **`speech_sample_rate=44100`** (v3 REST supports up to 48000); mp3 output retained.
- **Speakers** now the v3 catalog, lowercase, env-overridable: `TTS_VOICE_FEMALE=ritu`,
  `TTS_VOICE_MALE=shubh`. The v2-only `anushka`/`abhilash` are removed (they fail on v3).
- **Cache invalidation** — `cache_key` now hashes **model + speaker + sample_rate** (plus
  temperature/pace) alongside the preprocessed text, so a v2 clip can never be served after the
  upgrade. Existing `tts_cache/` contents were cleared as part of this change.
- **Acronym dict kept as a fallback.** v3 auto-preprocesses English/numerics, so the BFSI acronym
  map may be redundant; `synthesize` now logs raw-vs-preprocessed at DEBUG so we can measure how
  often it changes anything before dropping it. New optional `TTS_DICT_ID` is passed as `dict_id`
  when set — a hook for a future Sarvam pronunciation dictionary of BFSI terms.
- **Config additions:** `TTS_TEMPERATURE` (0.4), `TTS_PACE` (1.0), `TTS_SAMPLE_RATE` (44100),
  `TTS_DICT_ID` ("").  **Tests:** `test_tts.py` updated for the new cache key + v3 params
  (payload asserts model/temperature/sample-rate and *no* pitch/loudness; cache-key versioning);
  **13/13 green**. Verify the exact v3 speaker ids (`ritu`/`shubh`) against the live Sarvam v3
  catalog on first real key and override via env if they differ.
