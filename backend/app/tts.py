"""InterviewIQ text-to-speech (Voice Phase 1 — TTS only, the interviewer speaks).

Vendor: Sarvam AI Bulbul (POST https://api.sarvam.ai/text-to-speech).

Hard rules honoured here:
  - TTS failure must NEVER block the interview: every synth path returns None on
    any error, and the caller always sends the question text regardless.
  - The API key and learner content are NEVER logged.
  - No STT / mic / recording — this module only turns text into audio bytes.

Cost control:
  - Content-addressed disk cache (hash of preprocessed text + speaker). Greetings
    and common warm-ups repeat constantly, so repeats are served from cache and
    never re-billed (~30% vendor spend saved).
  - Per-session vendor-call cap (in-process) so a single session can't run up cost.
"""

import base64
import hashlib
import logging
import re
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0)
_SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
# Sarvam bulbul:v2 caps at 1500 chars/request; keep a safe margin.
_MAX_TTS_CHARS = 1400

# BFSI acronyms that a generic TTS voice mispronounces. Expanded to a phonetic or
# spelled-out form before synthesis. Maintainable single source of truth.
# Values are what we want SPOKEN, not the written form shown to the learner.
ACRONYMS = {
    "CIBIL": "sibil",
    "NPA": "N P A",
    "FOIR": "F O I R",
    "EMI": "E M I",
    "KYC": "K Y C",
    "CAGR": "C A G R",
    "DSCR": "D S C R",
}

# In-process per-session vendor-call counter (cache hits do NOT count). Resets on
# process restart, which is fine for a cost guard. No DB — vyom_ tables untouched.
_session_synth_counts: dict[str, int] = {}


def _tts_cap() -> int:
    return settings.MAX_ANSWERS_PER_SESSION + 5


def strip_markdown(text: str) -> str:
    """Remove markdown so the voice doesn't read asterisks, backticks, links, etc."""
    if not text:
        return ""
    t = text
    t = re.sub(r"```.*?```", " ", t, flags=re.DOTALL)        # code fences
    t = re.sub(r"`([^`]*)`", r"\1", t)                         # inline code
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)             # links -> text
    t = re.sub(r"(\*\*|__)(.*?)\1", r"\2", t)                  # bold
    t = re.sub(r"(\*|_)(.*?)\1", r"\2", t)                     # italic
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)  # headers
    t = re.sub(r"^\s{0,3}([-*_])\s*\1\s*\1[\s\1]*$", " ", t, flags=re.MULTILINE)  # hr
    t = re.sub(r"^\s{0,3}[-*+]\s+", "", t, flags=re.MULTILINE)  # bullet markers
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _expand_acronyms(text: str) -> str:
    """Replace whole-word BFSI acronyms with their spoken form (case-sensitive on
    the uppercase token so we don't mangle ordinary lowercase words)."""
    def repl(m):
        return ACRONYMS[m.group(0)]
    pattern = r"\b(" + "|".join(re.escape(k) for k in ACRONYMS) + r")\b"
    return re.sub(pattern, repl, text)


def preprocess(text: str) -> str:
    """Full pipeline: strip markdown, expand acronyms, clamp length for the vendor."""
    cleaned = _expand_acronyms(strip_markdown(text))
    return cleaned[:_MAX_TTS_CHARS]


def cache_key(text: str, speaker: str) -> str:
    """Stable content address for a (preprocessed text, speaker) pair.

    Hashes the PREPROCESSED text so two inputs that synthesize identically share a
    cache entry, and the key is independent of surrounding markdown noise.
    """
    payload = f"{preprocess(text)}|{speaker}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_dir() -> Path:
    d = Path(settings.TTS_CACHE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.mp3"


def read_cache(key: str) -> bytes | None:
    p = cache_path(key)
    try:
        if p.exists() and p.stat().st_size > 0:
            return p.read_bytes()
    except OSError:
        return None
    return None


def _write_cache(key: str, data: bytes) -> None:
    try:
        # Write-then-rename so a crashed write never leaves a truncated cache file.
        tmp = cache_path(key).with_suffix(".mp3.part")
        tmp.write_bytes(data)
        tmp.replace(cache_path(key))
    except OSError as e:
        log.warning("tts cache write failed: %s", type(e).__name__)


async def synthesize(text: str, speaker: str) -> bytes | None:
    """Call Sarvam and return decoded audio bytes, or None on ANY failure.

    Never raises, never logs the API key or the text being synthesized.
    """
    if not settings.SARVAM_API_KEY:
        log.warning("TTS requested but SARVAM_API_KEY is not set")
        return None

    spoken = preprocess(text)
    if not spoken:
        return None

    payload = {
        "text": spoken,
        "target_language_code": settings.TTS_LANG,
        "model": settings.TTS_MODEL,
        "speaker": speaker,
        "output_audio_codec": "mp3",
    }
    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(_SARVAM_URL, headers=headers, json=payload)
    except httpx.RequestError as e:
        log.warning("TTS request failed: %s", type(e).__name__)
        return None

    if r.status_code != 200:
        # Status only — the body can echo request text; never log it.
        log.warning("TTS vendor error status=%s", r.status_code)
        return None

    try:
        audios = r.json().get("audios") or []
        if not audios:
            return None
        return base64.b64decode(audios[0])
    except Exception as e:
        log.warning("TTS decode failed: %s", type(e).__name__)
        return None


async def get_audio_hash(session_id: str, text: str, speaker: str) -> str | None:
    """Return a cache hash the client can fetch audio by, or None if unavailable.

    Order: cache hit (free) -> per-session cost guard -> vendor synth. Any failure
    yields None so the caller falls back to text-only with zero degradation.
    """
    if not text or not text.strip():
        return None

    key = cache_key(text, speaker)

    # 1) Cache hit — no vendor call, no counter increment.
    if read_cache(key) is not None:
        return key

    # 2) Cost guard — cap actual vendor calls per session.
    used = _session_synth_counts.get(session_id, 0)
    if used >= _tts_cap():
        log.info("TTS cap reached for session; serving text only")
        return None

    # 3) Vendor synth.
    audio = await synthesize(text, speaker)
    if audio is None:
        return None

    _write_cache(key, audio)
    _session_synth_counts[session_id] = used + 1
    return key
