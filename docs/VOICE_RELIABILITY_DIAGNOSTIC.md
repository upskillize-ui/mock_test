# VOICE_RELIABILITY_DIAGNOSTIC — why voice breaks, with per-turn evidence

Post-launch quality investigation into two production symptoms in VOICE mode:

1. Saarika STT often returns nothing on real, captured speech — the student gives a
   full spoken answer and gets "Didn't catch that."
2. The interviewer's backchannel clips fire during/around the student's turn instead
   of only between turns.

TEXT mode is not touched anywhere in this work.

---

## 1. Per-turn evidence (real sessions 93e09b81 and 2eeeb5f3)

Every `stt_attempt` below was immediately preceded in the Space logs by:
`httpx POST https://api.sarvam.ai/speech-to-text "HTTP/1.1 200 OK"`.

| status | bytes   | mime                    | dur_s | transcript_len | stt_ms |
|--------|---------|-------------------------|-------|----------------|--------|
| fail   | 136502  | audio/webm;codecs=opus  | 8.5   | 0              | 2137   |
| ok     | 109454  | audio/webm;codecs=opus  | 6.8   | 58             | 2187   |
| ok     | 213782  | audio/webm;codecs=opus  | 13.3  | 112            | 2530   |
| fail   | 240830  | audio/webm;codecs=opus  | 15.0  | 0              | 2383   |
| ok     | 246626  | audio/webm;codecs=opus  | 15.3  | 90             | 2547   |
| fail   | 67916   | audio/webm;codecs=opus  | 4.2   | 0              | 1883   |
| fail   | 89168   | audio/webm;codecs=opus  | 5.5   | 0              | 2073   |
| ok     | 152924  | audio/webm;codecs=opus  | 9.5   | 83             | 2264   |
| ok     | 230204  | audio/webm;codecs=opus  | 14.3  | 124            | 2612   |

**What the evidence rules OUT:**

- **Not a timeout.** Every failing turn returned in ~1.9–2.4 s, nowhere near the 15 s
  read budget (`stt.py` `_TIMEOUT` `read=15.0`). The earlier read-timeout hypothesis is
  dead.
- **Not length-based.** Failures at 4.2 s AND 15.0 s; successes at 6.8 s AND 15.3 s.
  Byte counts overlap between fail and ok. Audio *was* captured (67–240 KB).
- **Not a quiet/noisy-mic verdict (client-side).** These turns reached the vendor and
  came back 200; the client's own RMS gate had already let them through.
- **Not the MIME `;codecs=opus` 400 rejection.** That path returns non-200 → would log
  `status=fail` with an adjacent `STT vendor error status=400 body=...`. Here Sarvam
  returned **200 OK** and there is no vendor-error line. The base-MIME strip
  (`stt.py:118-129`) is working.

**What the evidence points TO:** Sarvam answers **200 OK, fast, with no usable
transcript** for certain turns — regardless of length or byte count.

---

## 2. Root cause of the "undiagnosable status=fail"

`status` is computed in `main.py` from the result of `stt.transcribe_full()`:

```python
_status = "ok" if transcript else ("fail" if result is None else "empty")
```

This is a correct three-way split — `ok` / `empty` (200 but blank) / `fail` (vendor call
failed). **But the `empty` branch was dead code**, because `transcribe_full()` collapsed
both outcomes into `None`:

```python
transcript = _extract_transcript(body)
if transcript is None:
    return None          # ← a 200-but-blank body returned None, identical to a real failure
```

So every 200-OK-with-blank-transcript logged `status=fail` — exactly matching the
production lines (HTTP 200, `stt_ms`~2 s, `transcript_len=0`). The instrumentation could
not tell "the vendor genuinely heard nothing" apart from "the vendor call failed," which
is why the logs looked like a hard failure when Sarvam had actually answered.

**The failure point is named: Sarvam returns HTTP 200 with no usable transcript on those
turns, and our parsing collapses that into an indistinguishable `fail`.** Two sub-causes
remain to be separated with one more piece of evidence (below):

- (a) **genuinely blank** — Sarvam decoded the webm/opus but transcribed nothing
  (audio content Saarika couldn't resolve; the `language_code="unknown"` auto-detect is a
  suspect lever here), or
- (b) **parser-shape miss** — the text is present in the 200 body under a key/shape
  `_extract_transcript` didn't read (e.g. a diarized/segmented body).

---

## 3. What was fixed (shipped to origin)

### 3a. Make `empty` real, and log the body SHAPE — `stt.py`, `main.py`, `config.py`
- `transcribe_full()` now returns `{"transcript": None, ...}` on a 200-but-blank body
  (→ `status=empty`) and returns `None` **only** for a genuine transport/non-200/decode
  failure (→ `status=fail`). The two are finally distinct in the logs.
- New always-on **`stt_body_shape`** log line records the 200 body's keys and each
  value's type/length — **never the transcript words** — plus the non-PII `language_code`
  and `request_id`. This single line separates sub-cause (a) from (b) at a glance:
  `transcript:str[0]` = genuinely blank; text under another key = parser-shape miss.
- `STT_DEBUG_BODY` config flag (default **off**): when an operator turns it on for a
  controlled window, it dumps a redacted, truncated raw body. Off by default because
  `compliance.redact()` scrubs emails/phones but not speech.
- `_extract_transcript` hardened to also read segmented/diarized shapes, so if it IS a
  shape drift we both see it (shape line) and recover the text.
- Regression tests: `test_transcribe_full_empty_vs_fail`, `test_extract_transcript_flat_and_segmented`.

Honors the hard rule (`stt.py` docstring): the key, the audio, and the transcript are
never logged. The always-on line is shape-only; the full-body dump is opt-in and off.

### 3b. Interviewer listens in silence — `App.jsx` (symptom 2)
- Removed the mid-answer backchannel trigger from the recording meter loop. It fired a
  soft "mm-hmm" at an RMS-detected pause, but with `SILENCE_RMS=0.018` and
  `autoGainControl` on, ordinary between-sentence dips tripped a false pause and the clip
  landed as an interruption during the student's turn.
- The single between-turns acknowledgment (`playAck`, on answer submit) is unchanged.
- End-of-speech remains the trailing-silence VAD (`SILENCE_HOLD_MS=2200`,
  `MIN_SPEECH_MS=2000`), not a fixed timer — already the intended behavior for item 2.
- `shouldBackchannel` and its constants remain in `roomPolicy.js` (still unit-tested);
  only the app wiring was removed. 123 frontend tests + production build green.

---

## 4. Still pending (needs the deployed diagnostic + a go on `hf`)

The `stt_body_shape` line only produces evidence once it runs against real failing
sessions in the Space. The final root-cause fix depends on what it shows:

- **If `transcript:str[0]` on fails (genuinely blank):** the fix is upstream of the
  parser — most likely pin `STT_LANGUAGE=en-IN` (a one-line config lever; today it's
  `"unknown"` auto-detect), and/or stop sending raw MediaRecorder webm/opus to a batch
  STT (convert to WAV/PCM) if opus decoding is the culprit.
- **If the text is under a different key (shape miss):** the hardened `_extract_transcript`
  should already recover it; confirm and tighten.

Then close out the two remaining requirements, which build on the same evidence:

- **Item 3 (browser noise suppression):** `noiseSuppression`/`echoCancellation`/
  `autoGainControl` are already all `true` (`App.jsx` `MIC_DESIRED`); what's missing is
  the "room too noisy → tell the student to move somewhere quieter" surfacing (the RMS
  aggregates and a `noise` re-ask path already exist to build on).
- **Item 4 (empty-transcript handling):** now that `empty` is distinct from `fail`, wire
  the client to say "we couldn't hear you" (mic/noise/format) vs "you were silent"
  differently, and never count either as an answer (the `isSubstantiveAnswer` gate
  already blocks counting).

**Deploy step:** these changes are committed to `origin` only. The `hf` push (which is
what makes `stt_body_shape` run in production and capture the real bodies) is held pending
explicit confirmation. To capture bodies without leaking words, the always-on shape line
is enough; `STT_DEBUG_BODY=true` can be set in Space secrets for a short window if the
shape line proves ambiguous.
