# syntax=docker/dockerfile:1
# ==========================================================================
# Vyom — Hugging Face Space Dockerfile
# Builds the React frontend, then runs FastAPI which serves both API and UI.
# ==========================================================================

# --- Stage 1: build the React frontend ---
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
# Point the frontend at relative /api paths (same-origin deploy)
RUN echo "VITE_API_URL=" > .env.production
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.11-slim AS runtime
WORKDIR /app

# System deps (pymysql needs nothing extra; ssl certs just in case).
# ffmpeg: voice-reliability fix — transcodes browser opus recordings to 16 kHz
# WAV in-memory before Saarika STT (app/stt.py falls back gracefully without it).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/app ./app

# Static frontend from stage 1
COPY --from=frontend-build /build/dist ./static

# HF Spaces require port 7860
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
