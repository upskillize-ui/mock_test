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

import json
import logging

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
    # None means the vendor call itself FAILED (transport/non-200/decode) — the
    # caller logs status=fail. A dict with transcript=None means the vendor
    # answered 200 but we got no usable text (silence, noise, or a shape we can't
    # read) — a distinct outcome the caller logs as status=empty. Collapsing the
    # two into None (the old behaviour) is what made every 200-but-blank turn look
    # like a hard failure in the logs.
    if body is None:
        return None
    transcript = _extract_transcript(body)
    ts = body.get("timestamps")
    if not isinstance(ts, dict):
        ts = None
    conf = body.get("confidence")
    if not isinstance(conf, (int, float)):
        conf = None
    return {"transcript": transcript, "timestamps": ts, "confidence": conf}
