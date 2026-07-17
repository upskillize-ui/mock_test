import httpx
import io
import json
import logging
from urllib.parse import urlparse
from fastapi import HTTPException
from .config import settings
from . import ledger

log = logging.getLogger(__name__)


_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
# The turn calls are short and latency-critical; 60s of read is generous for them. The
# DEBRIEF is neither: it is one long non-streaming generation at the end of the session,
# and the read clock covers the model's entire writing time, not just the network. Sixty
# seconds was already marginal for it (measured ~50s at the old 2500-token cap), and
# raising that cap to fit a complete readout (QA-01) pushed straight through it — trading
# a truncated readout for a timed-out one, which is the same 502 wearing a different hat.
# This is the ceiling for how long a student's readout may take to write, so it is set for
# the worst case, not the typical one.
_DEBRIEF_TIMEOUT = httpx.Timeout(connect=5.0, read=240.0, write=10.0, pool=5.0)
_RESUME_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
_MAX_RESUME_BYTES = 5_000_000


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": settings.ANTHROPIC_VERSION,
    }


def _system_block(system: str, system_suffix: str = "") -> list[dict]:
    # The big prompt stays cached; the per-turn stage directive is a small,
    # un-cached second block so it can change every turn without a cache miss.
    block = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if system_suffix:
        block.append({"type": "text", "text": system_suffix})
    return block


async def stream_claude(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 600,
    system_suffix: str = "",
    on_delta=None,
    session_id: str | None = None,
) -> str:
    """call_claude, but STREAMED — and the streaming is not decoration.

    `on_delta(text_so_far)` is invoked on every chunk, so the caller can start work while
    the model is still writing. That is what puts the interviewer's first spoken word
    inside four seconds: her opening SENTENCE exists about a second into a six-second
    generation, and we send it to the voice vendor there and then, rather than waiting for
    her to finish composing a paragraph we have not begun to synthesise.

    Returns the complete text, exactly as call_claude would. on_delta must not raise and
    must not block — spawn a task and return.
    """
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": _system_block(system, system_suffix),
        "messages": messages,
        "stream": True,
    }

    chunks: list[str] = []
    # Cost ledger (item 2): the streaming API carries usage across TWO events — input +
    # cache tokens on `message_start`, output tokens on `message_delta` — so we accumulate
    # both and record once at the end. Without this the streamed greeting/kickoff would be
    # invisible to the ledger. Recording never affects the returned text.
    usage: dict = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", settings.ANTHROPIC_URL,
                                     headers=_headers(), json=payload) as r:
                if r.status_code != 200:
                    await r.aread()
                    # INT-07: status only. An error body can echo request content.
                    log.error("Claude API error status=%s", r.status_code)
                    raise HTTPException(status_code=502, detail="Upstream model error")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if not body or body == "[DONE]":
                        continue
                    try:
                        event = json.loads(body)
                    except ValueError:
                        continue
                    etype = event.get("type")
                    if etype == "message_start":
                        u = (event.get("message") or {}).get("usage") or {}
                        for k in ("input_tokens", "cache_read_input_tokens",
                                  "cache_creation_input_tokens", "output_tokens"):
                            if u.get(k) is not None:
                                usage[k] = u[k]
                        continue
                    if etype == "message_delta":
                        u = event.get("usage") or {}
                        if u.get("output_tokens") is not None:
                            usage["output_tokens"] = u["output_tokens"]
                        continue
                    if etype != "content_block_delta":
                        continue
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        chunks.append(delta["text"])
                        if on_delta:
                            try:
                                on_delta("".join(chunks))
                            except Exception as e:
                                # A greedy optimisation must never be able to break the
                                # thing it was optimising.
                                log.warning("stream on_delta failed: %s", type(e).__name__)
    except httpx.RequestError as e:
        log.exception("Claude stream failed: %s", e)
        raise HTTPException(status_code=502, detail="Upstream model unreachable")

    if session_id and usage:
        ledger.record_llm(session_id, model, usage)
    return "".join(chunks).strip()


async def call_claude(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 600,
    system_suffix: str = "",
    timeout: httpx.Timeout | None = None,
    session_id: str | None = None,
) -> str:
    headers = _headers()

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": _system_block(system, system_suffix),
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout or _TIMEOUT) as client:
            r = await client.post(settings.ANTHROPIC_URL, headers=headers, json=payload)
    except httpx.RequestError as e:
        log.exception("Claude request failed: %s", e)
        raise HTTPException(status_code=502, detail="Upstream model unreachable")

    if r.status_code != 200:
        # INT-07: log status only. The response body can echo request content
        # (learner answers) on some error classes — keep it out of logs.
        log.error("Claude API error status=%s", r.status_code)
        raise HTTPException(status_code=502, detail="Upstream model error")

    data = r.json()
    # Cost ledger (item 2): record token usage for this call. Best-effort and never
    # affects the returned text.
    if session_id:
        ledger.record_llm(session_id, model, data.get("usage"))
    # A truncated generation is a 200 with stop_reason="max_tokens" — the caller
    # only sees a string, so without this line an output cap reads downstream as
    # "the model returned garbage". It cost a sprint to find that once (QA-01).
    if data.get("stop_reason") == "max_tokens":
        log.warning(
            "Claude output hit max_tokens: model=%s cap=%d output_tokens=%s — "
            "the reply is TRUNCATED, not malformed",
            model, max_tokens, (data.get("usage") or {}).get("output_tokens"),
        )
    parts = [
        block["text"]
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    return "\n".join(parts).strip()


def _is_resume_url_safe(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme != "https":
        return False
    host = (u.hostname or "").lower()
    if not host:
        return False
    if host.replace(".", "").isdigit() or ":" in host:
        return False
    for allowed in settings.RESUME_HOST_ALLOWLIST:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


async def extract_resume_text(url: str) -> str:
    if not url or not _is_resume_url_safe(url):
        return ""

    try:
        async with httpx.AsyncClient(
            timeout=_RESUME_TIMEOUT,
            follow_redirects=False,
            max_redirects=0,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            content_length = int(resp.headers.get("content-length") or 0)
            if content_length > _MAX_RESUME_BYTES:
                return ""
            content = resp.content
            if len(content) > _MAX_RESUME_BYTES:
                return ""
    except Exception as e:
        log.warning("extract_resume_text fetch failed: %s", type(e).__name__)
        return ""

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text.strip())
        result = "\n".join(pages).strip()
        if result:
            return result[:3000]
    except Exception:
        pass

    try:
        return content.decode("utf-8", errors="ignore")[:3000]
    except Exception:
        return ""