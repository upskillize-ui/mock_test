# VOICE_CAPTURE_REPORT.md — voice input, turn-taking, lobby fixes

The product's ears. This sprint made capture reliable, made every answer diagnosable
from logs, made turn-taking feel like a conversation, and tidied the lobby.

All suites are green: **backend 247 passed**, **frontend 61 passed** (incl. the 22 Critical
guardrails in `test_critical.py` and the capture-gate mutation/structure test in
`captureInvariant.test.mjs` — nothing may reach the recorder except through `armCapture()`).
Frontend `npm run build` is clean.

Backend changes below are marked **[HF PUSH PENDING]** — they are committed to origin but
NOT deployed to Hugging Face without explicit confirmation.

---

## 1. UNMUTE MUST ARM CAPTURE — LISTENING is now level-triggered

**The bug:** arming was *edge-triggered*. The mic opened only on discrete events — "she
finished" (`onAudioEnded → maybeAutoListen`) or "they tapped unmute" (`toggleMic`). Unmuting
mid-question and then having her finish could fall *between* those events and strand the mic
on READY, recorder never armed.

**The fix** (`App.jsx`): a new level-triggered effect is now the guarantee. Whenever ALL of
*question open · student unmuted · interviewer finished* hold — regardless of the order they
became true — it starts the same auto-listen grace beat:

```js
useEffect(() => {
  if (!voiceMode || awaitingRating) return;   // rating has its own capture path
  if (graceMs > 0) return;                     // a grace beat is already counting
  if (!canArmCapture(captureState())) return;  // THE INVARIANT + "is it their turn?"
  startGrace();
}, [voiceMode, micOn, canAnswer, audioPlaying, connecting, recording, transcribing,
    loading, awaitingRating, ratingPills, typeOpen, ended, voiceConsented, graceMs]);
```

`canArmCapture()` remains the single authority — the effect only decides *when to ask it* —
so the capture invariant is untouched: `connecting / speaking / speechQueued` still hold the
mic shut here exactly as at every other arming site. The recorder still has **exactly one
caller** (`armCapture → openMicUnsafe`); the structural test confirms it.

**Muted-during-open-question UI** (`App.jsx` + CSS): the muted chip stops being a passive
label when an answer is genuinely due and points at the fix — **"You're muted — tap the mic
to answer"** — pulsing (`iqMutedCue`) to send the eye down to the mic button.

**Tests exercised:** unmute-before-question (PATH 1), unmute-mid-question, and
unmute-during-reask (PATH 4) all reach LISTENING via the gate — covered by the existing
`captureInvariant.test.mjs` path walks plus the new level-trigger, which cannot bypass the
gate.

## 2. NO AUDIO BEFORE JOIN

Verified and preserved — this was already the architecture and remains so:

- `startSession` (`/session/start`, the session row) is called **only** in `App.handleJoin`,
  after Join is pressed. Nothing before it.
- The session *brain* (kickoff LLM), question generation and the greeting's TTS live in
  `/session/greeting`, fetched **from inside the room** (`InterviewScreen`), i.e. strictly
  after Join.
- The pre-join `Lobby` opens a mic **only** for a local level meter and the new 5-second
  mic-test (§5), which runs entirely in the browser — **no session, no backend call, no
  audio output, nothing stored**. The one pre-Join audio touch is `unlockAudioPlayback()`,
  which plays a **silent** iOS-unlock WAV (inaudible; not the interviewer).
- **Warm-up** is silent and stateless: a fire-and-forget `GET /health` on lobby mount
  (§10c) — connections only, nothing audible or stateful.

## 3. INSTRUMENT EVERY ANSWER

**Client** (`App.jsx`): one line per answer via `emitTurnLog()`, accumulated across the flow
(`finishRecording → send → playSegments`) and emitted once — on playback start (success), on
TTS-off, or on any failure. It carries **no transcript text and no audio**, only shapes and
timings. Log shape (`console.info("[answer] …")`):

```json
{
  "capture_ms": 7300,
  "bytes": 61340,
  "mime": "audio/webm;codecs=opus",
  "peak_rms": 0.214,
  "mean_rms": 0.052,
  "mic_flags_dropped": "none",          // or e.g. ["echoCancellation"]
  "sample_rate": 48000,
  "channels": 1,
  "stt": "ok",                          // ok | empty | fail
  "transcript_len": 512,
  "confidence": null,                   // Saarika articulation score when present
  "latency_ms": { "capture": 7300, "stt": 940, "llm_tts": 2130, "playback": 180 }
}
```

Per-hop latency = `capture → STT → LLM/TTS → playback`:
`stt` = STT round trip, `llm_tts` = `/session/turn` round trip (LLM + first-sentence TTS),
`playback` = gap from reply-arrived to her voice going out.

**Server** [HF PUSH PENDING] (`main.py /session/stt`): one privacy-safe line per attempt —
no transcript text, no audio:

```
stt_attempt session=<id> status=ok bytes=61340 mime=audio/webm;codecs=opus
            dur_s=7.3 transcript_len=512 confidence=None stt_ms=940
```

## 4. CAPTURE QUALITY + QUIET-MIC RE-ASK

**Constraints** (`App.jsx MIC_CONSTRAINTS`): `echoCancellation / noiseSuppression /
autoGainControl: true` (unchanged) **plus** `sampleRate: { ideal: 16000 }, channelCount:
{ ideal: 1 }` to match Saarika's preferred 16 kHz mono — `ideal`, never `exact`, so a device
that can't hit it still yields a working mic.

**Refused-flags logging** (`micSettingsShortfall`): granted `MediaTrackSettings` are read
from the live track once per answer; any processing flag the browser silently dropped shows
in `mic_flags_dropped` on the answer log line.

**Quiet-mic re-ask** (item 4): the meter now tracks per-answer **peak/mean RMS**. A full
attempt (≥2.5 s) that comes through near-silent (peak < 0.05) triggers a persona re-ask that
says **why** — `reaskTurn(kind:"quiet")` → *"Your mic seems very quiet — come closer to it,
or type your answer and we'll carry on."* [HF PUSH PENDING for the backend line]. Environmental
re-asks don't count toward the two-strikes-then-type rule; the invisible per-question timer
is the ultimate backstop.

## 5. PRE-FLIGHT MIC CHECK (`Lobby.jsx`)

- **Live input level bar** (kept) + a **"Test my mic (5s)"** button.
- The 5-second test runs **in the browser** (platform `SpeechRecognition`, `lang=en-IN`,
  interim results) — no session, no backend (respects §2). It shows the running words, then
  **"We heard: '&lt;transcript&gt;'. Sound right?"** with **[Sounds right / Try again /
  Switch to typing]**.
- **Noise floor:** the quietest frame between words is measured; a high floor over a real
  attempt shows *"Your surroundings are quite noisy — a quieter spot will help the
  interviewer hear you."*
- **Text mode:** the whole check is skipped when the mic is off.
- Where `SpeechRecognition` is absent, the level meter still confirms the mic works (no
  transcript line).

## 6. LIVE SELF-CAPTIONS — now from our OWN Saarika STT (`App.jsx`, `main.py`, `stt.py`, `config.py`)

While the student speaks, a **"You:"** line shows their running transcript — DM Mono, a teal
`YOU` tag, left-aligned, in a teal-tinted band **visually distinct** from the interviewer's
navy caption. Verbatim — window transcripts are joined as-is, never beautified.

**Source (permanent fix — the browser recognizer is gone):** the caption is built from
**short rolling windows of the SAME mic recording**, transcribed through **our own Saarika
STT**. A separate short-lived `MediaRecorder` on the same stream produces a ~3.5 s clip; it
is POSTed to the new **`/session/stt/partial`** endpoint; the returned text is appended to the
running line; repeat while recording. **There is ONE audio path (the mic) and ONE vendor
(Saarika) — no browser speech service, no second capture of a third party.** The platform
`SpeechRecognition` path has been **removed entirely** from the in-session self-captions.

**Display-only, and isolated from capture:** the window recorder is independent of the
authoritative recorder, so a partial that fails — or the whole caption path — can never
disturb the recording it describes. The endpoint is side-effect-free: **no turn, no delivery
metrics, no storage, no stage change**; audio is transcribed in-memory and discarded.

**Cost, bounded on both sides:**
- Client: at most **30 windows/answer** (`SELFCAP_MAX_WINDOWS`); after that the caption
  freezes and the final authoritative transcript still lands on stop.
- Server [HF PUSH PENDING]: a **separate** per-session cap `STT_PARTIAL_MAX_PER_SESSION`
  (default 400) counted apart from answer STT, so a caption can never spend an answer's
  allowance. When hit, the endpoint returns a null transcript (never an error) and the
  caption simply stops growing. Set the cap to 0 to disable partials.

**Default OFF — a cost choice, not a privacy one.** With the third-party path removed, there
is no new data flow (the audio already goes to our Saarika for the answer). Self-captions stay
**OFF by default** only because the rolling-window partials cost extra STT calls; a dedicated
"Live captions of me" toggle (sub-label *"Transcribes your speech as you talk"*) lets the
student switch them on. **This is now a pure cost/product decision — the team can safely
default it ON.** The interviewer's own captions remain a separate, local, default-ON toggle.

> **Remaining browser-recognizer use — the PRE-FLIGHT test only (§5), by necessity.** The
> 5-second "We heard: '…'" mic test in `Lobby.jsx` runs **before Join, when no session
> exists**, so it cannot call the session-scoped `/session/stt/partial`; forcing a session
> there would violate §2 (no session/brain before Join). It therefore still uses the browser
> recognizer for that one local, pre-Join check. If zero browser-recognizer usage is wanted,
> the follow-up is a session-less STT ping for the pre-flight — flagged, not silently left.

## 7. TURN-TAKING BY SILENCE + INVISIBLE TIMER

- **End-of-answer** (`App.jsx` meter): auto-submit fires after **≥2 s of speech** (new
  `MIN_SPEECH_MS` guard) followed by **~2.2 s trailing silence** (`SILENCE_HOLD_MS` 2500 →
  2200, mid the 1.8–2.5 s target). A thinking pause before an answer, and a half-second cough,
  can no longer be read as "finished".
- **Latency targets:** LISTENING arms instantly (level-triggered, §1); the ack clip ("Hmm/
  Accha", pre-warmed) plays on submit; fast-start streams sentence one. All hops are now on
  the answer log line (§3) so the targets are measurable rather than asserted.
- **Invisible failsafe timer:** the per-question clock still runs and the expiry ladder
  (auto-submit partial / skip empty / EARLY_WRAP) is **unchanged**. Its chip now surfaces on
  the stage **only** in the final 30 s (`QUESTION_WARN_SECONDS`) **or** when no speech has
  been detected at all for the question (dead air). Classic typed mode keeps the clock
  visible (no speech signal there). Barge-in and typing are unchanged.

## 8. NOISE COACHING IN-SESSION

When speech is clearly present (strong peak RMS) but transcription keeps failing, the second
such attempt triggers a one-time persona line — `reaskTurn(kind:"noise")` → *"There's a lot
of noise on your end — move somewhere quieter if you can, or type your answers."* [HF PUSH
PENDING]. Said **once** per session (`noiseCoachedRef`); the streak resets on any clean
transcript. **Environment never affects scores** — enforced by the directive and by §9.

## 9. STT-NOISE-PROOF SCORING [HF PUSH PENDING] (`prompts.py DEBRIEF_INSTRUCTION`)

A new "THESE ANSWERS ARE SPEECH" block, ahead of the scoring rules, binds the scorer:
never penalise spelling / capitalisation / punctuation / dropped words / homophones / garble
plausibly from STT; resolve every such doubt in the candidate's favour; **Indian English is
the standard, never a deviation** (do-the-needful, prepone, revert back, Hinglish — never
flagged, never scored). Quotes may be **lightly cleaned for readability, meaning never
altered**; if the intent is unclear, quote as-is. Applies to the standard and the pressure-
panel readouts (both build on `DEBRIEF_INSTRUCTION`).

## 10. LOBBY FIXES (`App.jsx SetupScreen` + CSS)

- **(a) Difficulty = one row of four equal chips** (`.iq-diff4`, `repeat(4,1fr)`, wrapping to
  2×2 under 700px). Critical is now a chip in the row — a **red dot + "Pressure panel"**
  subtext set it apart — and its **full warning appears below the row only when selected**.
  The old two-tap arm/confirm panel is gone (single-tap select, warning-below), matching the
  spec.
- **(b) "Mode" heading → "Feedback".** Heading text only; the Interview / Coach options and
  their behaviour are byte-for-byte unchanged.
- **(c) Instant render + warm-up.** The lobby renders off local state with no blocking
  backend wait (unchanged; the alumni preview was already non-blocking). Added a
  fire-and-forget `GET /health` on mount. *"Connecting you with your interviewer…"* is shown
  only during the genuine `connecting` window (greeting in flight) — unchanged and correct.

## 11. RANGE GUIDANCE COPY (`Lobby.jsx`)

Added under the mic check (mic on): **"Best within arm's reach of your mic, in a quiet room."**

---

## Granted mic settings — Chrome / Windows

The new instrumentation reads `track.getSettings()` per answer, so exact grants are now
observable in the `[answer]` log line during UAT. **Expected** on Chrome/Windows (to be
confirmed against the log line in UAT, not fabricated here):

| Requested                | Typical grant on Chrome/Windows |
|--------------------------|---------------------------------|
| echoCancellation: true   | true                            |
| noiseSuppression: true   | true                            |
| autoGainControl: true    | true                            |
| sampleRate ideal 16000   | often forced to **48000** (device native) — harmless; Saarika resamples |
| channelCount ideal 1     | 1                               |

Any deviation (e.g. a Bluetooth headset dropping echoCancellation) now surfaces in
`mic_flags_dropped` rather than being invisible.

## Measured turn latency per hop

The hops are now emitted on every answer (§3). **Live values require a browser session**
against a warm backend and will be captured in UAT from the `latency_ms` object; they are not
fabricated here. Design targets the instrumentation now lets us verify:

| Hop                 | Target                         |
|---------------------|--------------------------------|
| LISTENING arm       | instant (level-triggered)      |
| Ack clip            | ~1 s of end-of-speech (pre-warmed) |
| capture → STT       | STT round trip (≤15 s ceiling) |
| LLM + first-clip TTS| fast-start; full response ~2–3 s |
| playback start      | small (reply-arrived → voice out) |

## Backend changes — [HF PUSH PENDING] (committed to origin, NOT deployed to HF)

- `prompts.py` — item 9 scoring block; `QUIET_MIC_DIRECTIVE` / `NOISE_DIRECTIVE` + fallback
  line banks (`quiet_mic_line`, `noise_line`).
- `schemas.py` — `ReaskRequest.kind` gains `"quiet"` and `"noise"`.
- `main.py` — `/session/reask` routes the two new kinds; `/session/stt` emits the per-attempt
  instrumentation line and imports the new prompt symbols; `import time`. **New endpoint
  `POST /session/stt/partial`** (item 6) — display-only rolling-window transcription for the
  live self-caption: same gates, separate cost cap, no metrics/storage/state.
- `stt.py` — separate partial cost counter (`note_stt_partial_call`, `stt_partial_cap_reached`).
- `config.py` — `STT_PARTIAL_MAX_PER_SESSION` (default 400; 0 disables partials).
- `tests/test_realism.py` — quiet/noise lines & directives, item-9 scoring rule.
- `tests/test_stt.py` — the `/session/stt/partial` endpoint (transcribes, no metrics, gated by
  feature+consent, separate cap that stops without erroring).

Frontend changes (`App.jsx`, `Lobby.jsx`) are static assets, deployed with the frontend.

## UAT checklist (browser, Chrome/Windows, inside the LMS embed)

1. Unmute mid-question → mic arms the instant she finishes (LISTENING). Repeat unmute-before
   and unmute-during-reask.
2. Muted with an answer due → chip reads "You're muted — tap the mic to answer" and pulses.
3. Speak an answer → on stop, "Heard:" flashes; check the `[answer]` console line for granted
   settings, RMS, and per-hop latency. Enable "Live captions of me" in the settings menu →
   the "You:" self-caption grows every ~3.5 s from our own Saarika STT (`/session/stt/partial`
   in the network tab — no call to any browser/Google speech service). Confirm it is OFF by
   default and that toggling it never disturbs the authoritative answer transcript.
4. Very quiet mic on a full answer → quiet-mic re-ask ("come closer…").
5. Noisy room, two garbled attempts → one in-persona noise line; scores unaffected.
6. Timer chip hidden while answering, appears in the final 30 s / on dead air.
7. Lobby: four difficulty chips in one row (2×2 under 700px); Critical shows the warning only
   when selected; "Feedback" heading; 5-second mic test with "We heard: …"; noisy-room and
   arm's-reach copy; type-mode skips the check.
