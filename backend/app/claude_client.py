import httpx
import io
from fastapi import HTTPException
from .config import settings


async def call_claude(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 600,
) -> str:
    """Call Anthropic messages API. Returns the text reply.

    Uses prompt caching on the system prompt — saves ~70% on input tokens
    for subsequent turns in the same session.
    """
    headers = {
        "Content-Type": "application/json",
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": settings.ANTHROPIC_VERSION,
    }

    system_block = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_block,
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(settings.ANTHROPIC_URL, headers=headers, json=payload)

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Claude API error {r.status_code}: {r.text[:300]}",
        )

    data = r.json()
    parts = [
        block["text"]
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    return "\n".join(parts).strip()


async def extract_resume_text(url: str) -> str:
    """Download resume PDF from Cloudinary and extract text.
    
    Returns up to 3000 chars of clean text.
    Returns empty string silently on any failure — never blocks the interview.
    """
    if not url:
        return ""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            content = resp.content

        # Try pdfplumber (best quality)
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text.strip())
            result = "\n".join(pages).strip()
            if result:
                return result[:3000]
        except Exception:
            pass

        # Fallback: raw UTF-8 decode (works for .txt resumes)
        try:
            return content.decode("utf-8", errors="ignore")[:3000]
        except Exception:
            pass

    except Exception:
        pass

    return ""