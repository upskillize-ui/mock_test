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

import asyncio
import base64
import hashlib
import logging
import re
import time
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger(__name__)

# v3 synthesis of a full sentence routinely takes several seconds; the old 5s read
# ceiling timed out on essentially every call (RequestError -> None -> "silent TTS").
# Give the vendor room; the caller still degrades to text-only if it genuinely stalls.
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
# Boot-time clip-pack warming must be HARD-bounded: a dead or hanging TTS account can never
# be allowed to delay the Space becoming healthy or to leave a multi-minute zombie task
# behind. Each warm call gets a short hard ceiling (a one-word clip synthesises in ~1s), and
# the whole pass gets an overall budget after which the remaining clips are simply left to
# synthesise on first use. These are separate from the generous mid-session _TIMEOUT above,
# which is deliberately long because a full-sentence v3 synth genuinely takes several seconds.
_WARM_CALL_TIMEOUT = 8.0
_WARM_BUDGET_SECONDS = 45.0
_SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
# Sarvam Bulbul caps request text length; keep a safe margin under the limit.
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

# ── The cost meter (E2 sentence-splitting is billed per SECOND, not per call) ──
# Splitting a reply into one clip per sentence is what buys human pacing, and it costs
# roughly 2-3x the vendor calls of a single-shot synth. Calls are the wrong unit to argue
# about, though: Sarvam bills AUDIO. So we measure the SECONDS we actually had
# synthesised, per session, split into what we PAID for and what the content-addressed
# cache gave us free. That number is the input to the Sarvam credits application and to
# the decision on whether to fall back to the 2-call lever.
#
# In-process, like the cap above: a restart mid-session under-counts that session, which
# is acceptable for a measurement (and honest — it is never used for billing).
_session_seconds: dict[str, dict] = {}


def _cost_row(session_id: str) -> dict:
    return _session_seconds.setdefault(session_id, {
        "vendor_calls": 0,        # clips we actually paid Sarvam for
        "vendor_seconds": 0.0,    # audio we paid for — THE number
        "cache_hits": 0,          # clips the cache served free
        "cached_seconds": 0.0,    # audio we would have paid for without the cache
        "unmeasured_clips": 0,    # clips whose duration we could not parse
    })


def _note_clip(session_id: str, audio: bytes, *, billed: bool) -> None:
    """Record one synthesised clip against this session's cost meter."""
    row = _cost_row(session_id)
    seconds = mp3_duration_seconds(audio)
    if seconds is None:
        row["unmeasured_clips"] += 1
    if billed:
        row["vendor_calls"] += 1
        row["vendor_seconds"] += seconds or 0.0
    else:
        row["cache_hits"] += 1
        row["cached_seconds"] += seconds or 0.0


def session_cost(session_id: str) -> dict:
    """This session's synthesised-seconds meter. Zeroed shape when nothing was synthesised,
    so a caller can always read the keys."""
    row = dict(_cost_row(session_id))
    row["vendor_seconds"] = round(row["vendor_seconds"], 1)
    row["cached_seconds"] = round(row["cached_seconds"], 1)
    row["total_seconds"] = round(row["vendor_seconds"] + row["cached_seconds"], 1)
    # What the cache saved us, as a share of the audio we'd otherwise have bought.
    row["cache_saved_pct"] = (
        round(100.0 * row["cached_seconds"] / row["total_seconds"])
        if row["total_seconds"] else 0
    )
    return row


# MPEG audio frame header tables (Layer III only — that is all Bulbul returns).
_L3_BITRATES = {
    3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],  # MPEG 1
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],      # MPEG 2
    0: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],      # MPEG 2.5
}


def mp3_duration_seconds(data: bytes) -> float | None:
    """Duration of an MP3 clip, from its first frame header. None if it isn't parseable.

    Assumes CBR — which is what Bulbul returns, and what makes bytes/bitrate exact. A VBR
    clip would make this an estimate, so the number is reported as MEASURED SECONDS, never
    as a bill: we are sizing a credits application, not invoicing anybody.
    """
    if not data or len(data) < 4:
        return None
    i = 0
    # Skip an ID3v2 tag if the encoder wrote one (its size is syncsafe: 7 bits per byte).
    if data[:3] == b"ID3" and len(data) > 10:
        i = 10 + ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
                  | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
    n = len(data)
    while i + 4 <= n:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            b1, b2 = data[i + 1], data[i + 2]
            version = (b1 >> 3) & 0x03      # 3=MPEG1, 2=MPEG2, 0=MPEG2.5 (1 is reserved)
            layer = (b1 >> 1) & 0x03        # 1 = Layer III
            br_idx = (b2 >> 4) & 0x0F       # 0 = free, 15 = bad
            if version != 1 and layer == 1 and 0 < br_idx < 15:
                bitrate = _L3_BITRATES[version][br_idx] * 1000
                if bitrate:
                    return round(((n - i) * 8) / bitrate, 2)
        i += 1
    return None


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


_SENTENCE_RX = re.compile(r"[^.!?…]+[.!?…]*")


def split_sentences(text: str) -> list[str]:
    """E2: split a reply into sentences so each can be synthesised as its OWN clip.

    That is what buys human pacing: the client can hold a 300-450ms beat between
    sentences and ~700ms before the question lands, and captions advance in exact
    lockstep with the audio instead of being interpolated from a progress bar.
    """
    cleaned = strip_markdown(text or "")
    parts = [s.strip() for s in _SENTENCE_RX.findall(cleaned)]
    return [p for p in parts if p]


def cache_key(text: str, speaker: str) -> str:
    """Stable content address for a synthesised clip.

    Hashes the PREPROCESSED text plus every parameter that changes the audio the
    vendor returns — **model, speaker, and sample rate** — so a model/voice upgrade
    can NEVER serve stale audio from a previous version (e.g. legacy Bulbul v2 clips
    can't leak through after the v3 upgrade). The key is independent of surrounding
    markdown noise because the text is preprocessed first.
    """
    payload = (
        f"{preprocess(text)}|model={settings.TTS_MODEL}|spk={speaker}"
        f"|sr={settings.TTS_SAMPLE_RATE}|temp={settings.TTS_TEMPERATURE}|pace={settings.TTS_PACE}"
    ).encode("utf-8")
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


def build_payload(text: str, speaker: str) -> dict:
    """Assemble the Bulbul v3 request body for `text`.

    v3 notes baked in here:
      - NO pitch/loudness (unsupported on v3 — sending them errors the request).
      - temperature + pace tune delivery; speech_sample_rate up to 48000.
      - dict_id is attached only when a pronunciation dictionary is configured.
    """
    payload = {
        "text": preprocess(text),
        "target_language_code": settings.TTS_LANG,
        "model": settings.TTS_MODEL,
        "speaker": speaker,
        "output_audio_codec": "mp3",
        "speech_sample_rate": settings.TTS_SAMPLE_RATE,
        "temperature": settings.TTS_TEMPERATURE,
        "pace": settings.TTS_PACE,
    }
    if settings.TTS_DICT_ID:
        payload["dict_id"] = settings.TTS_DICT_ID
    return payload


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

    # Evaluation aid: v3 auto-preprocesses English/numerics, so the acronym dict may
    # become redundant. Log raw vs preprocessed (DEBUG only) so we can measure how
    # often the dict actually changes anything before deciding to drop it. This is
    # interviewer question text (model-generated), not learner content; the global
    # PII filter still scrubs any stray contact detail.
    if spoken != text:
        log.debug("tts preprocess changed text: raw=%r preprocessed=%r", text, spoken)
    else:
        log.debug("tts preprocess no-op (v3 may handle it natively): %r", text)

    payload = build_payload(text, speaker)
    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(_SARVAM_URL, headers=headers, json=payload)
    except httpx.RequestError as e:
        # Phase 3 Part A: surface the concrete failure (name + message) so a
        # deterministic all-calls-fail (e.g. read timeout) is diagnosable. The
        # exception text never contains the API key.
        log.warning("TTS request failed: %s: %s", type(e).__name__, e)
        return None

    if r.status_code != 200:
        # Phase 3 Part A: log the vendor's error BODY (truncated), not just the
        # status — a 4xx from Sarvam explains exactly what v3 rejected (bad speaker,
        # unknown field, quota). The body is our own model-generated question text +
        # the vendor's error message, never the API key; the global PII filter still
        # scrubs any stray contact detail from the log line.
        body = ""
        try:
            body = r.text[:800]
        except Exception:
            pass
        log.warning("TTS vendor error status=%s body=%s", r.status_code, body)
        return None

    try:
        audios = r.json().get("audios") or []
        if not audios:
            return None
        return base64.b64decode(audios[0])
    except Exception as e:
        log.warning("TTS decode failed: %s", type(e).__name__)
        return None


# ── The clip pack: acknowledgments + listening backchannels ──────────────────
# The thinking gap is the moment the illusion dies. An answer is submitted, and then the
# room goes silent for two or three seconds while an LLM writes a reply and a vendor reads
# it — and what the candidate hears in that gap is a MACHINE LOADING. A person doesn't do
# that. A person says "Hmm." and then thinks.
#
# So: a tiny fixed vocabulary, synthesised ONCE per voice, ever, and played instantly on
# submit while the real reply is generated. There are 8 of them + 2 backchannels, they are
# content-addressed on disk like every other clip, and after the first run they cost
# exactly nothing — 20 clips total across both voices, for the life of the product.
ACK_LINES = [
    "Hmm.",
    "Okay.",
    "Right.",
    "Accha.",
    "Got it.",
    "Interesting.",
    "Let me think about that.",
    "Mm-hmm.",
]

# Played SOFTLY, mid-answer, at a natural pause in a long answer — the sound a person makes
# to tell you they are still listening and you should keep going. Never more than twice in
# one answer, and never in the first ten seconds: a backchannel that arrives too early
# reads as an interruption, which is the exact opposite of what it is for.
BACKCHANNEL_LINES = [
    "Mm-hmm.",
    "Right.",
]


def ack_line(seed: int) -> str:
    """Seeded rotation, so the same answer always draws the same acknowledgment (stable
    across a retry) but the session never repeats itself in a loop."""
    return ACK_LINES[abs(int(seed)) % len(ACK_LINES)]


async def get_shared_audio_hash(text: str, speaker: str) -> str | None:
    """Cache-first synth for a SHARED, session-independent clip (the ack pack, the
    backchannels).

    Deliberately NOT metered and NOT capped, unlike get_audio_hash: these clips belong to
    the product, not to a session. There are twenty of them in total, they are synthesised
    once in the life of the cache, and billing them against whichever candidate happened to
    warm them would make the per-session cost meter lie.
    """
    if not text or not text.strip():
        return None
    key = cache_key(text, speaker)
    if read_cache(key) is not None:
        return key
    audio = await synthesize(text, speaker)
    if audio is None:
        return None
    _write_cache(key, audio)
    return key


def clip_pack_lines() -> list[str]:
    """Every shared line, de-duplicated ("Mm-hmm." and "Right." are in both lists, and
    are ONE clip on disk — the cache is content-addressed, so they already were)."""
    seen, out = set(), []
    for line in ACK_LINES + BACKCHANNEL_LINES:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


async def warm_clip_pack(
    speakers: list[str],
    *,
    per_call_timeout: float = _WARM_CALL_TIMEOUT,
    budget_seconds: float = _WARM_BUDGET_SECONDS,
) -> dict:
    """Synthesise the whole shared clip pack for these voices, at startup.

    HARD-bounded and best-effort by construction: a dead or hanging TTS account at boot must
    never stop the app serving, never delay it becoming healthy, and never leave a zombie
    task running for minutes. Every synth gets a hard per-call ceiling (via asyncio.wait_for,
    so it holds even if the HTTP client's own timeout somehow does not); the whole pass gets
    an overall budget, after which the remaining clips are LEFT to synthesise on first use.
    A clip that fails or times out is skipped — the interview never depends on an ack.

    Returns a one-line boot-log summary. Never raises.
    """
    summary = {"warmed": 0, "cached": 0, "failed": 0, "skipped": 0, "bytes": 0}
    if not settings.TTS_ENABLED:
        return summary

    deadline = (time.monotonic() + budget_seconds) if budget_seconds else None
    for speaker in speakers:
        for line in clip_pack_lines():
            key = cache_key(line, speaker)
            hit = read_cache(key)
            if hit is not None:
                summary["cached"] += 1
                summary["bytes"] += len(hit)
                continue
            if deadline is not None and time.monotonic() >= deadline:
                # Out of budget — leave the rest to first-use synth rather than block boot.
                summary["skipped"] += 1
                continue
            try:
                # HARD per-call ceiling: wait_for cancels a hung synth (and closes its HTTP
                # client) even if the client's own timeout somehow does not fire.
                got = await asyncio.wait_for(
                    get_shared_audio_hash(line, speaker),
                    timeout=per_call_timeout,
                )
            except Exception as e:  # incl. asyncio.TimeoutError — warming NEVER raises
                summary["failed"] += 1
                log.warning("clip pack warm failed: %s", type(e).__name__)
                continue
            if got:
                summary["warmed"] += 1
                blob = read_cache(key)
                summary["bytes"] += len(blob or b"")
            else:
                summary["failed"] += 1
    return summary


async def get_audio_hash(session_id: str, text: str, speaker: str) -> str | None:
    """Return a cache hash the client can fetch audio by, or None if unavailable.

    Order: cache hit (free) -> per-session cost guard -> vendor synth. Any failure
    yields None so the caller falls back to text-only with zero degradation.
    """
    if not text or not text.strip():
        return None

    key = cache_key(text, speaker)

    # 1) Cache hit — no vendor call, nothing billed. Still METERED: the seconds it saved
    #    us are exactly what the cache is worth, and that is worth knowing.
    cached = read_cache(key)
    if cached is not None:
        _note_clip(session_id, cached, billed=False)
        return key

    # 2) Cost guard — cap actual vendor calls per session.
    used = _session_synth_counts.get(session_id, 0)
    if used >= _tts_cap():
        log.info("TTS cap reached for session; serving text only")
        return None

    # 3) Vendor synth — billed, and metered in seconds.
    audio = await synthesize(text, speaker)
    if audio is None:
        return None

    _write_cache(key, audio)
    _session_synth_counts[session_id] = used + 1
    _note_clip(session_id, audio, billed=True)
    return key
