"""InterviewIQ speech-to-text (Voice Phase 2 — the learner speaks their answer).

Vendor: Sarvam AI Saarika (POST https://api.sarvam.ai/speech-to-text).

Scope: BEHAVIOURAL round only. Batch (not streaming) — the browser records the
full answer, uploads once, we transcribe and hand back text. The learner reviews
and edits the transcript before sending; STT assists typing, it never bypasses
review.

Hard rules honoured here:
  - DO NOT STORE RAW AUDIO. Audio bytes are transcribed in-memory and discarded
    the instant this function returns; they never touch disk or DB. Only the text
    transcript is persisted, and that happens elsewhere (a normal message insert).
  - STT failure must NEVER be a dead end: every path returns None on any error, and
    the caller falls back to the learner typing.
  - The API key, the audio, and the transcript are NEVER logged.

Cost control:
  - Per-session vendor-call cap (in-process) so a single session can't run up cost.
    The cap is the behavioural question count + a few retries (set by the caller).
"""

import asyncio
import json
import logging
import shutil

import httpx

from . import compliance
from .config import settings

log = logging.getLogger(__name__)

# 15s ceiling on the whole vendor round-trip (spec). A campus-WiFi upload of a
# short answer plus Saarika transcription fits comfortably; anything slower is a
# failure and the learner types instead.
_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_SARVAM_URL = "https://api.sarvam.ai/speech-to-text"

# In-process per-session vendor-call counter (successful OR attempted calls that
# reach the vendor). Resets on process restart, which is fine for a cost guard —
# no DB, vyom_ tables untouched.
_session_stt_counts: dict[str, int] = {}


def note_stt_call(session_id: str) -> None:
    """Record that a vendor STT call was made for this session (cost accounting)."""
    _session_stt_counts[session_id] = _session_stt_counts.get(session_id, 0) + 1


# ── STT SECONDS meter (Capacity/Cost phase, item 2) ──────────────────────────
# Sarvam bills AUDIO, so the cost ledger needs SECONDS, not just calls. Saarika is billed on
# the length of the audio we upload, which the client reports as `duration_seconds` on every
# /session/stt (and which we can also derive from the vendor's word timestamps). In-process
# and no-DB, exactly like the call counter above and the TTS seconds meter in tts.py: a
# restart under-counts that session, which is fine for a measurement and never a bill.
_session_stt_seconds: dict[str, dict] = {}


def note_stt_seconds(session_id: str, seconds: float, *, estimated: bool = False) -> None:
    """Add `seconds` of transcribed audio to this session's STT meter. `estimated` marks a
    duration we inferred (e.g. from word timestamps) rather than one the client measured, so
    the ledger can flag it. Never raises."""
    try:
        row = _session_stt_seconds.setdefault(session_id, {"seconds": 0.0, "calls": 0, "estimated": False})
        row["seconds"] += max(0.0, float(seconds or 0.0))
        row["calls"] += 1
        if estimated:
            row["estimated"] = True
    except Exception:
        pass


def session_seconds(session_id: str) -> dict:
    """This session's transcribed-seconds meter. Zeroed shape when nothing was transcribed,
    so a caller can always read the keys."""
    row = dict(_session_stt_seconds.get(session_id, {"seconds": 0.0, "calls": 0, "estimated": False}))
    row["seconds"] = round(row.get("seconds", 0.0), 1)
    return row


# ── Measurement health (in-process, like the cost meters) ────────────────────
# The assessment gate's evidence: how many spoken answers actually became text. A
# restart forgets a session's record, which errs LENIENT — the gate can only fail to
# withhold a band, never withhold one unfairly. No audio, no transcripts — counts only.
_session_stt_health: dict[str, dict] = {}


def note_stt_health(session_id: str, status: str) -> None:
    """Count an answer-STT attempt's final outcome ('ok' heard / anything else missed)."""
    try:
        row = _session_stt_health.setdefault(session_id, {"ok": 0, "missed": 0})
        row["ok" if status == "ok" else "missed"] += 1
    except Exception:
        pass


def session_health(session_id: str) -> dict:
    """This session's measurement-health record: {ok, missed, attempts, healthy}.

    Unhealthy = at least 3 attempts and >=40% of them never became text. Below 3
    attempts there is not enough evidence to blame the pipeline, so it stays healthy
    (typed sessions, with zero attempts, are always healthy)."""
    row = dict(_session_stt_health.get(session_id, {"ok": 0, "missed": 0}))
    attempts = row["ok"] + row["missed"]
    row["attempts"] = attempts
    row["healthy"] = not (attempts >= 3 and row["missed"] * 5 >= attempts * 2)
    return row


def stt_calls_used(session_id: str) -> int:
    return _session_stt_counts.get(session_id, 0)


def stt_cap_reached(session_id: str, cap: int) -> bool:
    """True when this session has already used up its STT allowance."""
    return stt_calls_used(session_id) >= cap


# Item 6: live-caption partial transcriptions are counted SEPARATELY from answer STT, so a
# caption can never spend an answer's allowance (and vice versa). Same in-process, no-DB shape.
_session_stt_partial_counts: dict[str, int] = {}


def note_stt_partial_call(session_id: str) -> None:
    """Record a live-caption partial STT call for this session (cost accounting)."""
    _session_stt_partial_counts[session_id] = _session_stt_partial_counts.get(session_id, 0) + 1


def stt_partial_cap_reached(session_id: str, cap: int) -> bool:
    """True when this session has used up its live-caption partial allowance."""
    return _session_stt_partial_counts.get(session_id, 0) >= cap


# Voice-reliability fix: browser MediaRecorder ships opus in a webm/ogg container,
# and Saarika intermittently answers 200-OK-with-blank-transcript on those exact
# uploads (see docs/VOICE_RELIABILITY_DIAGNOSTIC.md — failures at 4.2s AND 15s,
# byte counts overlapping with successes). WAV/PCM removes the vendor's opus
# decode from the equation. ffmpeg runs bytes-in/bytes-out over pipes, so the
# no-audio-on-disk rule holds.
_FFMPEG = shutil.which("ffmpeg")
_OPUS_CONTAINER_MIMES = {"audio/webm", "video/webm", "audio/ogg"}
_TRANSCODE_TIMEOUT_S = 8.0


async def _transcode_to_wav(audio_bytes: bytes) -> bytes | None:
    """Transcode an opus-container recording to 16 kHz mono PCM WAV via ffmpeg
    pipes. Returns the WAV bytes, or None on ANY failure so the caller falls back
    to uploading the original bytes. Audio never touches disk and is never logged.
    """
    if not _FFMPEG:
        return None
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            _FFMPEG, "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-ac", "1", "-ar", "16000", "-codec:a", "pcm_s16le", "-bitexact",
            "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(
            proc.communicate(audio_bytes), timeout=_TRANSCODE_TIMEOUT_S
        )
        if proc.returncode == 0 and out and len(out) > 44:   # > bare WAV header
            return out
        log.warning("stt_transcode failed rc=%s out_bytes=%d", proc.returncode, len(out or b""))
    except asyncio.TimeoutError:
        log.warning("stt_transcode timeout after %.1fs", _TRANSCODE_TIMEOUT_S)
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception as e:
        log.warning("stt_transcode error: %s", type(e).__name__)
    return None


async def _request(
    audio_bytes: bytes,
    mime: str | None,
    want_timestamps: bool,
    *,
    use_transcode: bool = True,
    language_override: str | None = None,
) -> dict | None:
    """POST audio to Saarika and return the parsed JSON body, or None on ANY
    failure. Never raises, never logs the key/audio/transcript.

    The audio bytes are used only for this request and are not retained here.
    `want_timestamps` asks the vendor for word/segment timestamps (Phase 3 Part C —
    same call, no extra cost); older models may return a single whole-utterance
    segment, which the delivery layer treats as "no usable pauses".
    """
    if not settings.SARVAM_API_KEY:
        log.warning("STT requested but SARVAM_API_KEY is not set")
        return None
    if not audio_bytes:
        return None

    # Chrome/Firefox MediaRecorder report the content-type WITH a codec parameter
    # (e.g. "audio/webm;codecs=opus"). Sarvam's allowed-types check is an EXACT string
    # match and rejects the parameterized form with 400 "Invalid file type", even
    # though it accepts the bare "audio/webm". Strip to the base MIME type; the bytes
    # are unchanged. (Firefox "audio/ogg;codecs=opus" -> "audio/ogg", also accepted.)
    base_mime = (mime or "").split(";")[0].strip().lower() or "application/octet-stream"
    # Voice-reliability fix: hand Saarika 16 kHz mono WAV instead of the raw opus
    # container whenever we can. On any transcode failure the original bytes go up
    # unchanged — this path must never turn a working upload into a dead end.
    if use_transcode and settings.STT_TRANSCODE_WAV and base_mime in _OPUS_CONTAINER_MIMES:
        wav = await _transcode_to_wav(audio_bytes)
        if wav is not None:
            log.info("stt_transcode ok in_bytes=%d wav_bytes=%d", len(audio_bytes), len(wav))
            audio_bytes = wav
            base_mime = "audio/wav"
    ext = {
        "audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg",
        "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
        "audio/mp4": "mp4", "audio/x-m4a": "m4a", "audio/mpeg": "mp3",
        "audio/aac": "aac", "audio/flac": "flac",
    }.get(base_mime, "webm")
    # Sarvam accepts a multipart upload. Language "unknown" asks Saarika to
    # auto-detect (Hinglish / en-IN / regional); ops can pin en-IN via config.
    files = {"file": (f"answer.{ext}", audio_bytes, base_mime)}
    data = {"model": settings.STT_MODEL}
    language = settings.STT_LANGUAGE if language_override is None else language_override
    if language:
        data["language_code"] = language
    if want_timestamps:
        data["with_timestamps"] = "true"
    headers = {"api-subscription-key": settings.SARVAM_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(_SARVAM_URL, headers=headers, files=files, data=data)
    except httpx.RequestError as e:
        log.warning("STT request failed: %s: %s", type(e).__name__, e)
        return None

    if r.status_code != 200:
        # Log the vendor's ERROR body (truncated) — an error body is a diagnostic
        # message (e.g. "Invalid file type: …"), not a transcript, so it's safe and
        # is exactly what pins format/field problems. The API key is never in it.
        body = ""
        try:
            body = r.text[:500]
        except Exception:
            pass
        log.warning("STT vendor error status=%s body=%s", r.status_code, body)
        return None

    try:
        body = r.json()
    except Exception as e:
        log.warning("STT decode failed: %s", type(e).__name__)
        return None
    _log_response_shape(body)
    return body


def _log_response_shape(body) -> None:
    """Log the SHAPE of a Saarika 200 body — its keys and each value's type/length,
    never the transcript TEXT — plus the non-PII diagnostic fields (language_code,
    request_id). This is the line that tells a genuinely-blank response
    (`transcript:str[0]`) apart from a parser-shape miss (the text sitting under a
    key `_extract_transcript` doesn't read). Always on; never raises.

    When settings.STT_DEBUG_BODY is set, ALSO dump a redacted, truncated raw body —
    an operator-controlled diagnostic only (redact() scrubs emails/phones but not
    speech), so it stays off by default.
    """
    try:
        if not isinstance(body, dict):
            log.info("stt_body_shape non_dict type=%s", type(body).__name__)
            return
        parts = []
        for k, v in body.items():
            if isinstance(v, str):
                parts.append(f"{k}:str[{len(v)}]")
            elif isinstance(v, (list, tuple)):
                parts.append(f"{k}:list[{len(v)}]")
            elif isinstance(v, dict):
                parts.append(f"{k}:dict{{{len(v)}}}")
            elif v is None:
                parts.append(f"{k}:null")
            else:
                parts.append(f"{k}:{type(v).__name__}")
        log.info(
            "stt_body_shape keys=%s language_code=%s request_id=%s",
            ",".join(parts), body.get("language_code"), body.get("request_id"),
        )
        if settings.STT_DEBUG_BODY:
            log.info("stt_body_debug %s", compliance.redact(json.dumps(body))[:600])
    except Exception:
        pass


def _extract_transcript(body: dict) -> str | None:
    """Pull the transcript text out of a Saarika response body (defensive on shape).

    Primary keys are `transcript`/`text` (the documented Saarika contract). The
    remaining fallbacks are hardening against response-shape drift seen in the wild:
    a diarized/segmented body that carries the text in a list of segments rather
    than a flat string. Returns None only when there is genuinely no text anywhere.
    """
    if not isinstance(body, dict):
        return None
    # 1) Flat string under the documented keys.
    for key in ("transcript", "text"):
        v = body.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # 2) Segmented / diarized shapes: join the per-segment transcript strings.
    for key in ("diarized_transcript", "segments", "output", "results"):
        v = body.get(key)
        if isinstance(v, dict):
            v = v.get("entries") or v.get("segments") or v.get("transcript")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            chunks = []
            for seg in v:
                if isinstance(seg, str):
                    chunks.append(seg)
                elif isinstance(seg, dict):
                    t = seg.get("transcript") or seg.get("text")
                    if isinstance(t, str):
                        chunks.append(t)
            joined = " ".join(c.strip() for c in chunks if c and c.strip()).strip()
            if joined:
                return joined
    return None


# ── Long answers: Sarvam's real-time API hard-rejects clips over 30 seconds ──
# ("Audio duration exceeds the maximum limit of 30 seconds", observed live on a 37.6s
# answer). Interview answers routinely run 30-90s, so a long capture is sliced into
# independent ≤25s WAV clips — pure byte math on the 16 kHz mono PCM we already produce,
# no disk, no extra tools — transcribed clip by clip, and joined. Word timestamps are
# dropped for chunked answers (their offsets would be wrong); delivery metrics already
# tolerate their absence.
_SARVAM_MAX_CLIP_S = 30.0
_CHUNK_S = 25.0
_WAV_BYTES_PER_S = 16000 * 2   # 16 kHz, mono, s16
# Hard ceiling on clips per answer (8 x 25s = 200s, comfortably past the client's 180s
# recording cap). Without it, a crafted 10 MB upload with a lying duration_seconds could
# fan one counted call out into ~100 billed vendor calls — the cost cap exists precisely
# to make that impossible. Dropped clips are LOGGED, never silently discarded.
_MAX_CHUNKS = 8


def _wav_pcm(wav: bytes) -> bytes | None:
    """The raw PCM payload of a WAV buffer — found by locating the 'data' chunk, not by
    assuming a 44-byte header (ffmpeg pipes write placeholder sizes and may add LIST
    chunks). Returns None if there is no data chunk."""
    i = wav.find(b"data", 12)
    if i < 0 or i + 8 >= len(wav):
        return None
    return wav[i + 8:]


def _slice_wav_pcm(pcm: bytes, chunk_s: float = _CHUNK_S) -> list[bytes]:
    """Split raw 16 kHz mono s16 PCM into standalone WAV clips of ≤ chunk_s seconds."""
    import struct
    step = int(chunk_s * _WAV_BYTES_PER_S)
    step -= step % 2   # sample alignment
    clips = []
    for off in range(0, len(pcm), step):
        seg = pcm[off:off + step]
        if len(seg) < _WAV_BYTES_PER_S // 4:   # a <0.25s tail carries no words
            continue
        hdr = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + len(seg), b"WAVE", b"fmt ", 16, 1, 1,
            16000, _WAV_BYTES_PER_S, 2, 16, b"data", len(seg),
        )
        clips.append(hdr + seg)
    return clips


async def _transcribe_chunked(
    audio_bytes: bytes, mime: str | None, session_id: str | None = None
) -> dict | None:
    """Transcribe an answer longer than Sarvam's 30s clip limit, in ≤25s slices.

    Every vendor call beyond the first is counted against the session's cost cap via
    note_stt_call — the caller counted ONE call for this upload, and the cap's whole
    promise ("a single session can't run up cost") dies if chunking multiplies calls
    invisibly.
    """
    wav = await _transcode_to_wav(audio_bytes)
    pcm = _wav_pcm(wav) if wav else None
    if not pcm:
        # No ffmpeg / transcode failed: one raw attempt is still better than giving up
        # (it will be rejected over 30s, but this path must never be a dead end).
        body = await _request(audio_bytes, mime, want_timestamps=False, use_transcode=False)
        if body is None:
            return None
        return {"transcript": _extract_transcript(body), "timestamps": None, "confidence": None}
    clips = _slice_wav_pcm(pcm)
    if len(clips) > _MAX_CHUNKS:
        log.warning("stt_chunked capped: %d clips sliced, %d dropped (answer tail not transcribed)",
                    len(clips), len(clips) - _MAX_CHUNKS)
        clips = clips[:_MAX_CHUNKS]
    parts: list[str] = []
    any_body = False
    for i, clip in enumerate(clips):
        if i > 0 and session_id:
            note_stt_call(session_id)   # cost-cap honesty: each clip is a real vendor call
        body = await _request(clip, "audio/wav", want_timestamps=False, use_transcode=False)
        if body is None:
            continue
        any_body = True
        t = _extract_transcript(body)
        if t:
            parts.append(t)
    if not any_body:
        return None
    joined = " ".join(parts).strip() or None
    log.info("stt_chunked clips=%d transcript_len=%d", len(clips), len(joined or ""))
    return {"transcript": joined, "timestamps": None, "confidence": None}


async def transcribe(audio_bytes: bytes, mime: str | None) -> str | None:
    """Transcript text only, or None on any failure (backward-compatible)."""
    body = await _request(audio_bytes, mime, want_timestamps=False)
    if body is None:
        return None
    return _extract_transcript(body)


async def transcribe_full(
    audio_bytes: bytes,
    mime: str | None,
    want_timestamps: bool = True,
    duration_seconds: float = 0.0,
    session_id: str | None = None,
) -> dict | None:
    """Phase 3 Part C: transcript PLUS the raw signals delivery scoring needs.

    Returns {"transcript": str, "timestamps": dict|None, "confidence": float|None}
    or None if there is no usable transcript. `timestamps` is Saarika's
    {words, start_time_seconds, end_time_seconds} block when present; `confidence`
    is the vendor articulation score if the model returns one (Saarika currently
    does not, so it is typically None). Audio is not retained beyond this call.
    """
    # A capture longer than Sarvam's 30s clip limit is transcribed in slices — sending
    # it whole is a guaranteed 400 ("Audio duration exceeds the maximum limit").
    if (duration_seconds or 0.0) > _SARVAM_MAX_CLIP_S - 2.0:
        return await _transcribe_chunked(audio_bytes, mime, session_id=session_id)

    body = await _request(audio_bytes, mime, want_timestamps=want_timestamps,
                          use_transcode=False)
    # None means the vendor call itself FAILED (transport/non-200/decode) — the
    # caller logs status=fail. A dict with transcript=None means the vendor
    # answered 200 but we got no usable text (silence, noise, or a shape we can't
    # read) — a distinct outcome the caller logs as status=empty. Collapsing the
    # two into None (the old behaviour) is what made every 200-but-blank turn look
    # like a hard failure in the logs.
    transcript = _extract_transcript(body) if body is not None else None
    # Voice-reliability retry ladder. Attempt 1 is the RAW browser container with the
    # pinned language — live evidence (22 Jul) showed the raw upload succeeding while the
    # WAV path drew 402s, and it is also the cheaper call (no ffmpeg run, half the upload
    # bytes). If it produced NO words on real captured audio, spend one more vendor call
    # the OTHER way — 16 kHz WAV with language auto-detect — which covers the original
    # opus-decode blanks and a language pin rejecting a Hinglish/regional answer. Only
    # fires on a failed first attempt, so a healthy pipeline pays nothing extra.
    if not transcript:
        log.info("stt_retry wav+autodetect (first attempt %s)",
                 "failed" if body is None else "empty")
        if session_id:
            note_stt_call(session_id)   # the retry is a second real vendor call
        body2 = await _request(
            audio_bytes, mime, want_timestamps=want_timestamps,
            use_transcode=True, language_override="unknown",
        )
        if body2 is not None:
            t2 = _extract_transcript(body2)
            if t2:
                log.info("stt_retry recovered transcript_len=%d", len(t2))
                body, transcript = body2, t2
            elif body is None:
                body = body2   # at least a 200 body -> report empty, not fail
    if body is None:
        return None
    ts = body.get("timestamps")
    if not isinstance(ts, dict):
        ts = None
    conf = body.get("confidence")
    if not isinstance(conf, (int, float)):
        conf = None
    return {"transcript": transcript, "timestamps": ts, "confidence": conf}
