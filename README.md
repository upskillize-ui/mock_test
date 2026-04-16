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

Set secrets in Space Settings → Variables and secrets:
- ANTHROPIC_API_KEY
- DATABASE_URL
- JWT_SECRET
- ALLOWED_ORIGINS
- MODEL_INTERVIEW = claude-haiku-4-5-20251001
- MODEL_DEBRIEF = claude-sonnet-4-6
- MAX_SESSIONS_PER_DAY = 10