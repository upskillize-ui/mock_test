import httpx
import io
import logging
from urllib.parse import urlparse
from fastapi import HTTPException
from .config import settings

log = logging.getLogger(__name__)


_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_RESUME_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
_MAX_RESUME_BYTES = 5_000_000


async def call_claude(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 600,
    system_suffix: str = "",
) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": settings.ANTHROPIC_VERSION,
    }

    # The big prompt stays cached; the per-turn stage directive is a small,
    # un-cached second block so it can change every turn without a cache miss.
    system_block = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if system_suffix:
        system_block.append({"type": "text", "text": system_suffix})

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_block,
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