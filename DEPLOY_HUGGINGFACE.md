# Deploying Vyom on Hugging Face Spaces

Single-deployment approach: one Space serves both the React frontend and the FastAPI backend. No separate Netlify + Render needed.

## Prerequisites

- A Hugging Face account (you already have one — you have other agents there)
- Your Aiven MySQL already has the `vyom_*` tables from `db/schema.sql` (run this first if you haven't)
- Your Anthropic API key

## Step 1 — Create the Space

1. Go to https://huggingface.co/new-space
2. **Owner:** your username or an org
3. **Space name:** `vyom` (or `upskillize-vyom`)
4. **License:** MIT (or your choice)
5. **SDK:** pick **Docker** → **Blank template**
6. **Hardware:** CPU basic (free) is fine to start
7. **Visibility:** Public or Private (Private if you want a gated pilot)
8. Click Create Space

## Step 2 — Push the code

You have two options.

### Option A: Git push (what you're used to)

```bash
# Clone your empty Space
git clone https://huggingface.co/spaces/YOUR_USERNAME/vyom
cd vyom

# Copy the Vyom files from the unzipped build
cp /path/to/vyom_build/Dockerfile .
cp /path/to/vyom_build/README_HF.md ./README.md    # HF needs it named README.md
cp -r /path/to/vyom_build/backend .
cp -r /path/to/vyom_build/frontend .

# HF free tier has a ~5GB repo limit, and node_modules is huge — exclude it
cat > .gitignore << 'EOF'
node_modules/
frontend/dist/
__pycache__/
*.pyc
.env
venv/
EOF

# Commit and push
git add .
git commit -m "Initial Vyom deployment"
git push
```

### Option B: Upload via web UI

1. Space → Files → Add file → Upload files
2. Drag the `Dockerfile`, `README.md` (renamed from `README_HF.md`), and the `backend/` and `frontend/` folders
3. Commit from the web UI

## Step 3 — Add environment variables as Space Secrets

Space → Settings → **Variables and secrets** → New secret (these are encrypted, not visible in logs):

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your key from console.anthropic.com |
| `DATABASE_URL` | `mysql+pymysql://avnadmin:PASSWORD@HOST.aivencloud.com:PORT/defaultdb?ssl_verify_cert=false` |
| `JWT_SECRET` | Same as your LMS JWT secret |
| `ALLOWED_ORIGINS` | `https://YOUR_USERNAME-vyom.hf.space,https://upskillize.com,https://lms.upskillize.com` |
| `MAX_SESSIONS_PER_DAY` | `10` |
| `MODEL_INTERVIEW` | `claude-haiku-4-5-20251001` |
| `MODEL_DEBRIEF` | `claude-sonnet-4-6` |

**Aiven SSL shortcut:** `?ssl_verify_cert=false` gets you live fast. For production-grade SSL, upload Aiven's CA cert to the Space and reference it in DATABASE_URL as `?ssl_ca=/app/ca.pem`.

## Step 4 — Build

Once you push or save secrets, HF automatically rebuilds. Watch the **Logs** tab:

- Stage 1: node builds the React frontend (~2 min)
- Stage 2: Python installs dependencies (~1 min)
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 7860`

When you see `Application startup complete.`, your Space is live at:

```
https://YOUR_USERNAME-vyom.hf.space
```

Open it in a browser — you should see the Vyom setup screen.

## Step 5 — Test

```bash
# Health check
curl https://YOUR_USERNAME-vyom.hf.space/health

# Expected response:
# {"status":"ok","model_interview":"claude-haiku-4-5-20251001","model_debrief":"claude-sonnet-4-6"}
```

Then open the Space URL in your browser, fill the setup screen, and run a mock interview end to end.

## Step 6 — Custom domain (optional, requires paid Space)

Free Spaces give you `YOUR_USERNAME-vyom.hf.space`. To point `vyom.upskillize.com` at it:

1. Upgrade Space to paid CPU tier ($9/month) — free tier does not support custom domains.
2. Space Settings → Custom domain → add `vyom.upskillize.com`.
3. Update DNS: CNAME `vyom` → `YOUR_USERNAME-vyom.hf.space`.
4. HF auto-provisions SSL via Let's Encrypt.

## Trade-offs to know before you commit to HF for production

| Issue | Impact | Fix |
|---|---|---|
| Sleeps after ~48h idle | First user of the day waits 30–60s | Upgrade to persistent hardware ($9+/mo) OR ping `/health` every 12h from an external cron |
| One instance for all users | ~20–30 concurrent learners OK on free tier | Upgrade to CPU Upgrade or move to Render when you outgrow it |
| MySQL latency Aiven ↔ HF | +50–150ms per query | Accept it for pilot; for scale, keep backend close to DB |
| No background workers | Can't run cron, email queues, etc. | Add a tiny separate worker later when you need it |
| Free tier logs are public | Don't log secrets or raw student PII | The backend already doesn't — just confirming |

## When to migrate off HF

Move to Render + Netlify (the setup in the main README) when:

- You consistently see queueing during placement season
- You need cron jobs (nightly intel-network digests, weekly progress emails)
- You have 500+ daily active learners
- You want separate scaling for API and frontend

The code is identical — same backend, same frontend — so migration is just redeploying to different hosts.

## You're done

Single URL. One platform. Same agent. Use HF to ship the MVP this week, validate with 50–100 learners, then decide whether to stay or migrate based on real usage. The Dockerfile and same-origin API client mean the exact same codebase works on both — zero rewrite needed.
