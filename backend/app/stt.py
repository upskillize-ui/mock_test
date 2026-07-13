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

import logging

import httpx

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


def stt_calls_used(session_id: str) -> int:
    return _session_stt_counts.get(session_id, 0)


def stt_cap_reached(session_id: str, cap: int) -> bool:
    """True when this session has already used up its STT allowance."""
    return stt_calls_used(session_id) >= cap


async def _request(audio_bytes: bytes, mime: str | None, want_timestamps: bool) -> dict | None:
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
    if settings.STT_LANGUAGE:
        data["language_code"] = settings.STT_LANGUAGE
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
        return r.json()
    except Exception as e:
        log.warning("STT decode failed: %s", type(e).__name__)
        return None


def _extract_transcript(body: dict) -> str | None:
    """Pull the transcript text out of a Saarika response body (defensive on key)."""
    transcript = body.get("transcript")
    if transcript is None:
        transcript = body.get("text")
    if not isinstance(transcript, str):
        return None
    transcript = transcript.strip()
    return transcript or None


async def transcribe(audio_bytes: bytes, mime: str | None) -> str | None:
    """Transcript text only, or None on any failure (backward-compatible)."""
    body = await _request(audio_bytes, mime, want_timestamps=False)
    if body is None:
        return None
    return _extract_transcript(body)


async def transcribe_full(
    audio_bytes: bytes, mime: str | None, want_timestamps: bool = True
) -> dict | None:
    """Phase 3 Part C: transcript PLUS the raw signals delivery scoring needs.

    Returns {"transcript": str, "timestamps": dict|None, "confidence": float|None}
    or None if there is no usable transcript. `timestamps` is Saarika's
    {words, start_time_seconds, end_time_seconds} block when present; `confidence`
    is the vendor articulation score if the model returns one (Saarika currently
    does not, so it is typically None). Audio is not retained beyond this call.
    """
    body = await _request(audio_bytes, mime, want_timestamps=want_timestamps)
    if body is None:
        return None
    transcript = _extract_transcript(body)
    if transcript is None:
        return None
    ts = body.get("timestamps")
    if not isinstance(ts, dict):
        ts = None
    conf = body.get("confidence")
    if not isinstance(conf, (int, float)):
        conf = None
    return {"transcript": transcript, "timestamps": ts, "confidence": conf}
