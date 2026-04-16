# Vyom — Deployment Guide

Complete AI mock interview agent for Upskillize. FastAPI backend on Render, React frontend on Netlify, MySQL on Aiven — same stack as your existing LMS.

---

## What's in this repo

```
vyom_build/
├── db/
│   └── schema.sql              # Run once against Aiven
├── backend/                    # Deploy to Render
│   ├── app/
│   │   ├── main.py             # All endpoints
│   │   ├── config.py           # Env loader
│   │   ├── db.py               # SQLAlchemy + Aiven pooling
│   │   ├── auth.py             # JWT (reuses LMS secret)
│   │   ├── schemas.py          # Pydantic types
│   │   ├── claude_client.py    # Anthropic API + prompt caching
│   │   └── prompts.py          # System prompt + alumni intel
│   ├── requirements.txt
│   ├── render.yaml
│   └── .env.example
└── frontend/                   # Deploy to Netlify
    ├── src/
    │   ├── App.jsx             # 3-screen flow
    │   ├── main.jsx
    │   └── index.css
    ├── index.html
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── netlify.toml
    └── .env.example
```

---

## Step 1 — Aiven MySQL (5 minutes)

All new tables are prefixed `vyom_` so they won't collide with LMS tables.

```bash
# Connect to your existing Aiven MySQL (same one as LMS)
mysql -h HOST.aivencloud.com -P PORT -u avnadmin -p --ssl-ca=ca.pem defaultdb < db/schema.sql
```

You can also paste `schema.sql` into the Aiven web console SQL editor.

This creates:
- `vyom_sessions` — one row per mock
- `vyom_messages` — full chat history
- `vyom_debriefs` — final scored report (JSON columns)
- `vyom_rate_limits` — per-user daily cap
- `vyom_alumni_questions` — **the Golden Point** — where real alumni submit real questions
- `vyom_user_progress` — view for "you scored better than X%" feature

---

## Step 2 — Render backend (10 minutes)

1. Push `backend/` to a new GitHub repo (e.g. `upskillize/vyom-api`).
2. On Render → New → Web Service → connect the repo.
3. Render will detect `render.yaml` — click Apply. Build and start commands are preset.
4. Set these env vars in the Render dashboard:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your key from console.anthropic.com |
| `DATABASE_URL` | `mysql+pymysql://avnadmin:PASSWORD@HOST.aivencloud.com:PORT/defaultdb?ssl_ca=/etc/ssl/certs/ca.pem` |
| `JWT_SECRET` | Same secret your LMS uses (so SSO just works) |
| `ALLOWED_ORIGINS` | `https://vyom.upskillize.com,https://lms.upskillize.com` |
| `MAX_SESSIONS_PER_DAY` | `10` |
| `MODEL_INTERVIEW` | `claude-haiku-4-5-20251001` |
| `MODEL_DEBRIEF` | `claude-sonnet-4-6` |

5. Deploy. When green, test: `curl https://your-api.onrender.com/health`

**Aiven SSL note:** if you use Aiven's CA cert, upload it to Render via the "Secret Files" feature at `/etc/ssl/certs/ca.pem`, or append `?ssl_verify_cert=false` to the DATABASE_URL if you just want it working first (not recommended long-term).

---

## Step 3 — Netlify frontend (5 minutes)

1. Push `frontend/` to a new GitHub repo (e.g. `upskillize/vyom-web`).
2. On Netlify → Add new site → Import from Git → pick the repo.
3. Build settings autodetected via `netlify.toml`. Click Deploy.
4. In Site settings → Environment variables:
   - `VITE_API_URL` = `https://your-vyom-api.onrender.com` (from Step 2)
5. Trigger a redeploy.
6. In Domain settings, add custom domain `vyom.upskillize.com` and point DNS.

---

## Step 4 — SSO from LMS (optional but recommended)

When a learner logs into `lms.upskillize.com`, write the JWT to localStorage on a domain both apps share (e.g. `.upskillize.com`). The frontend reads it on start:

```js
// In your LMS, after login:
localStorage.setItem("upskillize_token", jwt);

// Vyom's App.jsx already reads this automatically in authHeaders()
```

If the LMS and Vyom are on different subdomains, set the cookie/token via a shared parent domain or pass it via a URL param on the link to Vyom.

---

## Cost at scale

With Haiku for interview turns + Sonnet for debrief + prompt caching:

- **Per session cost:** ~₹2–4 (~$0.03–0.05)
- **1,000 sessions/month:** ~₹3,000
- **10,000 sessions/month:** ~₹30,000
- **Render Starter:** $7/month, handles ~100 concurrent sessions
- **Netlify Free tier:** 100 GB bandwidth, covers 50k+ visits/month
- **Aiven:** whatever your existing tier is — Vyom adds tiny load

Prompt caching (already on) saves ~70% of input tokens per session after the first turn.

---

## Step 5 — Golden Point activation (Day 1 after launch)

This is what makes Vyom un-copyable. Start now, in parallel with launch.

### Bootstrap the alumni question intel network

1. **Email your last 200 placed alumni:**

   > Hi [name],
   >
   > You graduated from Upskillize and interviewed at [company] earlier this year. We're launching Vyom — an AI coach that uses real interview questions from our alumni to prep current Upskillize students.
   >
   > Would you submit 3–5 questions you were actually asked in your interview? We'll credit ₹200 per verified question to your Upskillize account (usable for any future course).
   >
   > Link: https://vyom.upskillize.com/alumni/submit
   >
   > Thank you — this directly helps the next batch of students.

2. **After submission, verify manually** (for now — review the `vyom_alumni_questions` table and flip `verified = 1` for good ones).

3. **Automate verification later** — once you have volume, a reviewer dashboard at `/admin/alumni` takes <1 day to build.

4. **Target: 250 verified questions by Day 30.** Once you hit this, every Vyom session for a matching company+role automatically pulls from real questions (see `fetch_alumni_intel()` in `prompts.py`). Students see the count on setup screen. Moat activated.

---

## Endpoints reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/session/start` | Begin a new mock; returns session_id + greeting |
| POST | `/session/turn` | Send a learner message; returns Vyom's reply |
| POST | `/session/end` | Generate debrief (Sonnet) and persist |
| GET | `/session/{id}` | Full session + messages + debrief |
| GET | `/user/history` | Last 20 sessions for this user |
| POST | `/alumni/submit` | Alumni submits a real interview question |
| GET | `/alumni/preview?company=X&role=Y` | Count of verified questions for setup UI |

---

## Local development

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your values
uvicorn app.main:app --reload
# → http://localhost:8000
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.example .env  # point at http://localhost:8000 for local
npm run dev
# → http://localhost:5173
```

---

## What's deliberately NOT in this MVP (add in Phase 2)

- Voice / webcam analysis (audio ML — build after product-market fit)
- Negotiation simulator (separate mode — worth shipping in month 4)
- Real interviewer personas (after 20+ partner engineers signed)
- Admin dashboard for alumni question verification (build after 50+ submissions)
- Progress graph / "you scored better than X%" — easy to add once you have 100+ completed sessions (data exists in `vyom_user_progress` view)

---

## You're done

Once Steps 1–3 are complete, you have:

- A working Vyom at `https://vyom.upskillize.com`
- Real Claude API running at ₹3–5 per session
- All session data persisted in Aiven
- Rate-limited and auth-gated
- Ready for the alumni intel network to start feeding it real interview questions

Every session from Day 1 gets better as the alumni question bank grows.
