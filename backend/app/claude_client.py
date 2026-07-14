import httpx
import io
import json
import logging
from urllib.parse import urlparse
from fastapi import HTTPException
from .config import settings

log = logging.getLogger(__name__)


_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
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
                    if event.get("type") != "content_block_delta":
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

    return "".join(chunks).strip()


async def call_claude(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 600,
    system_suffix: str = "",
) -> str:
    headers = _headers()

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": _system_block(system, system_suffix),
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
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