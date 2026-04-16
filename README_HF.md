---
title: Vyom
emoji: 🎯
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: AI mock interview coach for Upskillize learners
---

# Vyom — by Upskillize

AI mock interview agent that uses real alumni interview questions to prepare Upskillize learners for their dream roles.

## Environment variables (set these in Space Settings → Secrets)

- `ANTHROPIC_API_KEY` — your Anthropic console key
- `DATABASE_URL` — Aiven MySQL connection string
- `JWT_SECRET` — same as LMS
- `ALLOWED_ORIGINS` — e.g. `https://huggingface.co,https://upskillize.com`
- `MODEL_INTERVIEW` — `claude-haiku-4-5-20251001`
- `MODEL_DEBRIEF` — `claude-sonnet-4-6`
- `MAX_SESSIONS_PER_DAY` — `10`

Once running, the app is available at the Space URL. Frontend and API served from the same origin.
