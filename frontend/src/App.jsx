import { useState, useRef, useEffect } from "react";

// ── API plumbing ───────────────────────────────────────────────────────────
// Accept either env var name; an explicitly-set empty string means same-origin (Docker/HF build).
const _API_ENV = import.meta.env.VITE_INTERVIEWIQ_API_URL ?? import.meta.env.VITE_API_URL;
const API_URL = _API_ENV === undefined ? "https://upskill25-mock-test.hf.space" : _API_ENV;
const TOKEN_KEY = "upskillize_token";

const getToken = () => localStorage.getItem(TOKEN_KEY) || localStorage.getItem("token") || "";
const authHeaders = () => {
  const t = getToken();
  return t ? { Authorization: "Bearer " + t } : {};
};

async function api(path, opts = {}) {
  const res = await fetch(API_URL + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(opts.headers || {}) },
  });
  if (!res.ok) {
    let serverMsg = "";
    try { const j = await res.json(); serverMsg = j.detail || j.message || ""; }
    catch { try { serverMsg = (await res.text()).slice(0, 200); } catch { /* noop */ } }
    // In dev, append the backend's specific reason (auth.py exposes it in `detail`)
    // so "Please log in again" becomes e.g. "Please log in again (token expired)".
    if (res.status === 401) throw new Error("Please log in again to continue." + (import.meta.env?.DEV && serverMsg ? ` (${serverMsg})` : ""));
    if (res.status === 429) throw new Error(serverMsg || "Daily limit reached. Try again tomorrow.");
    if (res.status >= 500) throw new Error("InterviewIQ is having a hiccup. Please try again.");
    throw new Error(serverMsg || `Request failed (${res.status}).`);
  }
  return res.json();
}

// Voice Phase 1 fix: native <audio> requests don't carry our Authorization header
// (and bypass the CORS fetch path), so the auth-guarded /session/audio/{hash}
// endpoint rejects them. Fetch the audio ourselves with auth, then hand the
// <audio> element a local blob URL. `path` is relative; API_URL makes it absolute
// against the backend (not the vite dev server).
async function fetchAudioObjectUrl(path) {
  const res = await fetch(API_URL + path, { headers: { ...authHeaders() } });
  if (!res.ok) throw new Error(`audio request failed (${res.status})`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

const startSession = (c) => api("/session/start", { method: "POST", body: JSON.stringify(c) });
const sendTurn = (sid, msg, stage, voice, deliveryMetrics) => api("/session/turn", { method: "POST", body: JSON.stringify({ session_id: sid, message: msg, stage, voice, delivery_metrics: deliveryMetrics || null }) });
const submitRating = (sid, answerId, rating) => api("/session/turn/rating", { method: "POST", body: JSON.stringify({ session_id: sid, answer_id: answerId, rating }) });
const fetchSessionState = (sid) => api(`/session/${encodeURIComponent(sid)}/state`);
const fetchSessionMessages = (sid) => api(`/session/${encodeURIComponent(sid)}/messages`);
const endSession = (sid) => api("/session/end", { method: "POST", body: JSON.stringify({ session_id: sid }) });
const abandonSession = (sid) => api("/session/abandon", { method: "POST", body: JSON.stringify({ session_id: sid }) }).catch(() => {});
const fetchAlumniPreview = (co, ro) => api("/alumni/preview?company=" + encodeURIComponent(co) + "&role=" + encodeURIComponent(ro));
const fetchHistory = (limit = 50, offset = 0) => api(`/user/history?limit=${limit}&offset=${offset}`);
const fetchHistoryDetail = (sid) => api(`/user/history/${encodeURIComponent(sid)}`);
const fetchStats = () => api("/user/stats");
// Voice Phase 2: STT — upload a recorded behavioural answer, get back { transcript }.
// Multipart: we must NOT set Content-Type ourselves (the browser adds the boundary),
// and we send only the auth header. On any non-OK we throw so the caller falls back
// to typing. The endpoint transcribes-and-discards; raw audio is never stored.
async function sttTranscribe(sessionId, blob, filename = "answer.webm", durationSeconds = 0) {
  const fd = new FormData();
  fd.append("session_id", sessionId);
  fd.append("audio", blob, filename);
  // Voice Phase 3: recording duration drives wpm; the audio itself is still discarded.
  fd.append("duration_seconds", String(Math.max(0, Math.round(durationSeconds * 10) / 10)));
  const res = await fetch(API_URL + "/session/stt", { method: "POST", headers: { ...authHeaders() }, body: fd });
  if (!res.ok) {
    let msg = "";
    try { const j = await res.json(); msg = j.detail || ""; } catch { /* noop */ }
    throw new Error(msg || `stt failed (${res.status})`);
  }
  return res.json();   // { transcript: string | null, delivery_metrics: object | null }
}
// INT-07 DPDPA data rights + consent.
const recordConsent = (payload) => api("/consent", { method: "POST", body: JSON.stringify(payload) });
const fetchMyData = () => api("/me/data");
const requestDataDeletion = () => api("/me/data/delete-request", { method: "POST", body: JSON.stringify({}) });
const confirmDataDeletion = (token) => api("/me/data", { method: "DELETE", body: JSON.stringify({ confirmation_token: token }) });

// ── INT-06: active-session persistence (survives page refresh) ───────────────
const ACTIVE_KEY = "interviewiq_active_session";
// INT-07: remembers that the current learner already saw+accepted the consent copy.
const CONSENT_KEY = "interviewiq_consent_v0-draft";
const CONSENT_COPY_VERSION = "v0-draft";

function saveActiveSession(sessionId, config, startedAt) {
  try { localStorage.setItem(ACTIVE_KEY, JSON.stringify({ session_id: sessionId, config, started_at: startedAt })); }
  catch { /* storage full / disabled — resume simply won't be available */ }
}
function loadActiveSession() {
  try { const raw = localStorage.getItem(ACTIVE_KEY); return raw ? JSON.parse(raw) : null; }
  catch { return null; }
}
function clearActiveSession() {
  try { localStorage.removeItem(ACTIVE_KEY); } catch { /* noop */ }
}

// ── Voice Phase 1: TTS playback (interviewer speaks; learner still types) ─────
const MUTE_KEY = "interviewiq_muted";
const VOICE_KEY = "interviewiq_voice";   // "female" | "male"
const getVoicePref = () => { try { return localStorage.getItem(VOICE_KEY) === "male" ? "male" : "female"; } catch { return "female"; } };
const getMutePref = () => { try { return localStorage.getItem(MUTE_KEY) === "1"; } catch { return false; } };

// One shared <audio> element across screens so the iOS unlock (done on the Start
// button gesture) carries over to programmatic playback in the interview.
let _player = null;
function player() {
  if (!_player && typeof Audio !== "undefined") { _player = new Audio(); _player.preload = "auto"; }
  return _player;
}
// Minimal silent WAV — played inside the Start-button gesture to unlock autoplay
// on iOS Safari, which otherwise blocks programmatic .play().
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";
async function unlockAudioPlayback() {
  const p = player(); if (!p) return;
  try { p.src = SILENT_WAV; await p.play(); p.pause(); p.currentTime = 0; }
  catch { /* still blocked — the UI will offer a tap-to-play affordance */ }
}

// Inline Lucide-style line icons (1.6px stroke). No emojis.
const IconSpeaker = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M19 5a9 9 0 0 1 0 14" /></svg>
);
const IconSpeakerOff = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5z" /><line x1="22" y1="9" x2="16" y2="15" /><line x1="16" y1="9" x2="22" y2="15" /></svg>
);
const IconReplay = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M3 2v6h6" /><path d="M3 8a9 9 0 1 0 3-5.7L3 8" /></svg>
);
// Voice Phase 2: mic / stop icons (learner speaks their behavioural answer).
const IconMic = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0" /><line x1="12" y1="17" x2="12" y2="22" /><line x1="8" y1="22" x2="16" y2="22" /></svg>
);
const IconStop = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
);

// ── Theme ─────────────────────────────────────────────────────────────────
const T = {
  navy: "#1a2744", navyLight: "#2c3e6b", navyDeep: "#0f1a2e", gold: "#b8960b", goldSoft: "#fdf8ed", goldBorder: "#e8d89a",
  white: "#ffffff", bg: "#f7f8fc", border: "#e8e9f0", text: "#1a1a1a", muted: "#72706b", subtle: "#a8a49f",
  green: "#2d6a2d", greenSoft: "#edf7ed", red: "#c0392b", redSoft: "#fdf1f0", blue: "#1e3a6b", blueSoft: "#eef2fb",
  font: "'Plus Jakarta Sans', sans-serif",
};

// ── InterviewIQ brand tokens for spec-aligned components (rating, bands, calibration)
const IQ = {
  navy: "#0B1628", gold: "#C8992A", teal: "#00C4A0", orange: "#E8521A",
  buildingNavy: "#1a2744", cream: "#FBF7EF",
  mono: "'DM Mono', 'SFMono-Regular', Menlo, monospace",
  display: "'Playfair Display', Georgia, serif",
  sans: "'Plus Jakarta Sans', sans-serif",
};

// INT-03: readiness band pill colours (cream text on each).
const BAND_STYLE = {
  "Offer-Ready": { bg: IQ.gold, fg: IQ.cream },
  "Interview-Ready": { bg: IQ.teal, fg: IQ.cream },
  "Building": { bg: IQ.buildingNavy, fg: IQ.cream },
  "Not Ready": { bg: IQ.orange, fg: IQ.cream },
};

// INT-02: calibration profile pill colour + coaching copy (never punitive).
const CALIBRATION_COPY = {
  well_calibrated: { bg: IQ.teal, label: "Well-calibrated", copy: "Your confidence matches your quality. Keep it." },
  over_confident: { bg: IQ.orange, label: "Over-confident", copy: "This is the pattern panels reject. Your confidence outran your answers." },
  under_confident: { bg: IQ.gold, label: "Under-confident", copy: "Your answers were stronger than you thought. This is coachable." },
};

const ROUND_BAND_LABELS = { warmup: "Warm-up", domain: "Domain", behavioural: "Behavioural", case: "Case", reverse: "Your Questions" };

// ── Markdown rendering ─────────────────────────────────────────────────────
function fmt(text) {
  const parts = [];
  const rx = /(\[([^\]]+)\]\(([^)]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let last = 0, m, k = 0;
  while ((m = rx.exec(text)) !== null) {
    if (m.index > last) parts.push(<span key={k++}>{text.slice(last, m.index)}</span>);
    if (m[2] && m[3]) {
      const safeUrl = /^https?:\/\//.test(m[3]) ? m[3] : "#";
      parts.push(<a key={k++} href={safeUrl} target="_blank" rel="noopener noreferrer" style={{ color: T.navy, textDecoration: "underline" }}>{m[2]}</a>);
    } else if (m[4]) parts.push(<strong key={k++}>{m[4]}</strong>);
    else if (m[5]) parts.push(<em key={k++}>{m[5]}</em>);
    else if (m[6]) parts.push(<code key={k++} style={{ background: "rgba(0,0,0,0.06)", padding: "1px 5px", borderRadius: 4, fontSize: "0.9em" }}>{m[6]}</code>);
    last = rx.lastIndex;
  }
  if (last < text.length) parts.push(<span key={k++}>{text.slice(last)}</span>);
  return parts.length > 0 ? parts : text;
}
function renderMd(text) {
  if (!text) return null;
  return text.split("\n").map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={i} style={{ height: 6 }} />;
    if (/^[-*]\s/.test(t)) return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4, paddingLeft: 4 }}><span style={{ color: T.gold, fontWeight: 700 }}>•</span><span>{fmt(t.replace(/^[-*]\s+/, ""))}</span></div>;
    const nm = t.match(/^(\d+)[.)]\s+(.*)/);
    if (nm) return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4, paddingLeft: 4 }}><span style={{ color: T.subtle, fontWeight: 600, minWidth: 18 }}>{nm[1]}.</span><span>{fmt(nm[2])}</span></div>;
    return <p key={i} style={{ margin: "0 0 6px" }}>{fmt(t)}</p>;
  });
}

const ROLES = ["Software Engineer (SDE)", "Frontend Developer", "Backend Developer", "Full-stack Developer", "Data Analyst", "Data Scientist", "Machine Learning Engineer", "Product Manager", "Business Analyst", "Finance Analyst", "Digital Marketing", "UX / UI Designer", "HR / Recruiter", "Other"];
const LEVELS = ["Fresher", "1-3 years", "3-10 years", "10-20 years", "20+ years", "Career switcher"];
const COMPANIES = [{ value: "", label: "General (mid-tier product)" }, { value: "TCS", label: "TCS / Infosys / Wipro" }, { value: "Amazon", label: "Amazon" }, { value: "Google", label: "Google / Meta / Microsoft" }, { value: "Startup", label: "Startups" }, { value: "Consulting", label: "Consulting / Banking / KPMG" }, { value: "Other", label: "Other (specify below)" }];
const DURATIONS = [{ v: 10, l: "10 min" }, { v: 20, l: "20 min" }, { v: 30, l: "30 min" }, { v: 45, l: "45 min" }];
const DIFFICULTIES = [{ v: "Easy", l: "Easy", d: "Warm-up pace" }, { v: "Realistic", l: "Realistic", d: "Matches real bar" }, { v: "Stretch", l: "Stretch", d: "Tough + curveball" }];
const MODES = [{ v: "interview", l: "Interview mode", d: "Feedback at end only" }, { v: "coach", l: "Coach mode", d: "Feedback after each answer" }];
const ROUNDS = [
  { v: "screening", l: "Screening Round", d: "Motivation, fitment & communication", badge: "SCREEN", detail: "Covers: Why this role? Why this company? Career goals, salary expectations, notice period. Short answers, rapid-fire pace. No technical depth." },
  { v: "technical", l: "Technical Round 1 / 2", d: "Domain knowledge, case analysis, problem solving", badge: "TECH", detail: "Covers: Role-specific concepts, case studies, data/finance/engineering problems, trade-offs, system/process design. Deep follow-up questioning." },
  { v: "leadership", l: "Leadership Round", d: "Strategy, ownership & decision-making", badge: "LEAD", detail: "Covers: Leadership in ambiguity, cross-team conflict, stakeholder management, big decisions you drove, failure stories with recovery." },
  { v: "hr", l: "HR / Behavioral", d: "Culture fit, values & strengths", badge: "HR", detail: "Covers: STAR-format behavioral questions, strengths/weaknesses, team conflict, diversity & inclusion, why you left previous role." },
  { v: "full", l: "Full Interview", d: "All rounds — progressive difficulty", badge: "FULL", detail: "Covers: All stages in sequence — Warm-up → Screening → Technical → Leadership → HR → Pressure round → Wrap-up. Difficulty escalates across stages." },
];
const FOCUS_OPTIONS = ["Communication", "Technical depth", "Confidence", "Structure", "Project storytelling", "Salary negotiation", "Other"];
const LOADING_TIPS = [
  "Tip: Start your answers with a headline, then expand.",
  "Tip: Use the STAR method — Situation, Task, Action, Result.",
  "Tip: Numbers make answers memorable. Quantify your impact.",
  "Tip: It's okay to pause and think. Silence beats rambling.",
  "Preparing your personalized interview questions...",
  "Analyzing your profile for targeted questions...",
];

const CSS = `
  @keyframes iqPulse { 0%,100%{opacity:.3;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}
  @keyframes iqLoad { 0%{width:0%}50%{width:70%}100%{width:100%}}
  @keyframes iqFade { from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
  @keyframes iqSpin { to { transform: rotate(360deg); } }
  @keyframes iqTealPulse { 0%,100%{box-shadow:0 0 0 0 rgba(0,196,160,.55)}50%{box-shadow:0 0 0 6px rgba(0,196,160,0)}}
  .iq-avatar-speaking{animation:iqTealPulse 1.2s ease-in-out infinite}
  /* Voice Phase 2: mic button + recording pulse + transcribing shimmer */
  @keyframes iqMicPulse { 0%,100%{box-shadow:0 0 0 0 rgba(232,82,26,.5)}50%{box-shadow:0 0 0 8px rgba(232,82,26,0)}}
  @keyframes iqRecDot { 0%,100%{opacity:.35}50%{opacity:1}}
  @keyframes iqShimmer { 0%{background-position:-220px 0}100%{background-position:220px 0}}
  .iq-mic-btn{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;min-height:44px;border-radius:10px;border:1.5px solid #e8e9f0;background:#fff;color:#0B1628;cursor:pointer;transition:all .15s;flex-shrink:0}
  .iq-mic-btn:hover{border-color:#c0c1c8;background:#fafbfe}
  .iq-mic-btn:disabled{opacity:.4;cursor:not-allowed}
  .iq-mic-btn:focus-visible{outline:2px solid #0B1628;outline-offset:2px}
  .iq-mic-recording{background:#E8521A;border-color:#E8521A;color:#fff;animation:iqMicPulse 1.2s ease-in-out infinite}
  .iq-mic-recording:hover{background:#cf460f;border-color:#cf460f}
  /* Locked (STT available but not yet the behavioural round): faint, line-only,
     no orange. Uses aria-disabled, so it stays hoverable for the tooltip. */
  .iq-mic-locked{opacity:.45;cursor:help;background:#fff;border-color:#e8e9f0;color:#0B1628}
  .iq-mic-locked:hover{opacity:.6;background:#fafbfe;border-color:#e8e9f0}
  .iq-shimmer-text{background:linear-gradient(90deg,#a8a49f 0%,#e8e9f0 40%,#a8a49f 80%);background-size:220px 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:iqShimmer 1.1s linear infinite}
  /* Interview HUD — responsive header. No fixed heights (min-height:auto); wraps
     and truncates so title/stage text never clips, safe down to 360px. */
  .iq-hud{background:#1a2744;flex-shrink:0;display:flex;flex-direction:column;gap:8px;padding:12px 20px;min-height:auto}
  .iq-hud-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 12px}
  .iq-hud-brand{min-width:0;flex:1 1 auto}
  .iq-hud-title{color:#fff;font-weight:800;font-size:15px;line-height:1.2;white-space:nowrap}
  .iq-hud-sub{color:rgba(255,255,255,.4);font-size:11px;line-height:1.35;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
  .iq-hud-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
  .iq-hud-audio{display:flex;align-items:center;gap:6px}
  .iq-hud-timer{font-size:18px;font-weight:800;color:#fff;font-variant-numeric:tabular-nums;line-height:1.1;flex-shrink:0}
  .iq-hud-end{padding:6px 16px;border-radius:8px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);color:#fff;font-size:13px;font-weight:600;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif;flex-shrink:0}
  .iq-hud-end:hover{background:rgba(255,255,255,.12)}
  .iq-hud-stage-row{display:flex;min-width:0}
  .iq-hud-stage{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:5px 12px;border-radius:16px;background:rgba(184,150,11,.2);border:1px solid rgba(184,150,11,.4)}
  .iq-hud-stage-dot{width:7px;height:7px;border-radius:50%;background:#b8960b;flex-shrink:0}
  .iq-hud-stage-label{font-size:12px;font-weight:700;color:#b8960b;line-height:1.35;word-break:break-word}
  @media(max-width:480px){.iq-hud{padding:10px 14px}.iq-hud-timer{font-size:16px}.iq-hud-end{padding:6px 12px}}
  @media(max-width:360px){.iq-hud{padding:10px 12px;gap:6px}}
  .iq-audio-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:8px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.06);color:#fff;cursor:pointer;transition:all .15s}
  .iq-audio-btn:hover{background:rgba(255,255,255,.14)}
  .iq-audio-btn:disabled{opacity:.4;cursor:not-allowed}
  .iq-audio-btn:focus-visible{outline:2px solid #00C4A0;outline-offset:2px}
  .iq-stat{position:relative;cursor:default;transition:all .25s}
  .iq-stat:hover{background:rgba(255,255,255,.12)!important}
  .iq-stat .iq-tip{visibility:hidden;opacity:0;position:absolute;top:calc(100% + 12px);left:50%;transform:translateX(-50%);min-width:220px;z-index:200;transition:opacity .2s,visibility .2s}
  .iq-stat:hover .iq-tip{visibility:visible;opacity:1}
  .vc{background:#fff;border:1.5px solid #e8e9f0;border-radius:12px;transition:all .2s}
  .vc:hover{border-color:#d0d1d8;box-shadow:0 2px 12px rgba(26,39,68,.06)}
  .vc-h{padding:14px 20px 0}
  .vc-t{font-size:14px;font-weight:800;color:#1a2744;letter-spacing:-.01em}
  .vc-b{padding:12px 20px 20px}
  .vl{display:block;font-size:12px;font-weight:700;color:#72706b;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
  .vi{width:100%;padding:10px 14px;border:1.5px solid #e8e9f0;border-radius:8px;font-size:14px;outline:none;box-sizing:border-box;font-family:'Plus Jakarta Sans',sans-serif;transition:all .2s;background:#fff}
  .vi:focus,.vi:focus-visible{border-color:#1a2744;box-shadow:0 0 0 3px rgba(26,39,68,.07)}
  .vchip{padding:8px 18px;border-radius:8px;font-size:13px;border:1.5px solid #e8e9f0;cursor:pointer;background:#fff;color:#1a1a1a;transition:all .18s;font-family:'Plus Jakarta Sans',sans-serif;font-weight:500}
  .vchip:hover{border-color:#c0c1c8;background:#fafafa}
  .vchip:focus-visible{outline:2px solid #1a2744;outline-offset:2px}
  .vchip-on{border-color:#1a2744;background:#1a2744;color:#fff;font-weight:700}
  .vopt{text-align:left;padding:12px 16px;border-radius:10px;cursor:pointer;border:1.5px solid #e8e9f0;background:#fff;font-family:'Plus Jakarta Sans',sans-serif;transition:all .2s;width:100%}
  .vopt:hover{border-color:#c0c1c8;background:#fafbfe}
  .vopt:focus-visible{outline:2px solid #1a2744;outline-offset:2px}
  .vopt-on{border:2px solid #1a2744;background:#eef2fb}
  .vbtn{width:100%;padding:14px 24px;background:#1a2744;color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:8px}
  .vbtn:hover{background:#2c3e6b}
  .vbtn:disabled{opacity:.5;cursor:not-allowed}
  .vg2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .vg3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
  @media(max-width:800px){.vg2{grid-template-columns:1fr!important}}
  .iq-hero:hover .iq-hero-desc{opacity:1!important;max-height:60px!important;margin-top:6px!important}
  .round-detail{display:none;font-size:11px;color:#72706b;margin-top:6px;line-height:1.5;padding:8px 12px;background:#f7f8fc;border-radius:6px;border-left:2px solid #1a2744}
  .vopt-on .round-detail{display:block}
  .iq-tabs{display:flex;gap:6px;border-bottom:1px solid #e8e9f0;margin-bottom:18px}
  .iq-tab{padding:10px 18px;background:none;border:none;font-family:'Plus Jakarta Sans',sans-serif;font-size:13px;font-weight:700;color:#72706b;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
  .iq-tab:hover{color:#1a2744}
  .iq-tab-on{color:#1a2744;border-bottom-color:#1a2744}
  .iq-hist-row{display:grid;grid-template-columns:1fr auto;gap:14px;padding:14px 16px;border:1px solid #e8e9f0;border-radius:10px;background:#fff;cursor:pointer;transition:all .15s;margin-bottom:10px}
  .iq-hist-row:hover{border-color:#c0c1c8;background:#fafbfe;transform:translateY(-1px);box-shadow:0 4px 14px rgba(26,39,68,.06)}
  .iq-pill{display:inline-block;padding:2px 9px;border-radius:10px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
  .mba-spinner{width:32px;height:32px;border:3px solid #e8e9f0;border-top-color:#1a2744;border-radius:50%;animation:iqSpin .8s linear infinite}
  .mba-btn-primary{padding:10px 22px;background:#1a2744;color:#fff;border:none;border-radius:8px;font-weight:700;font-family:'Plus Jakarta Sans',sans-serif;cursor:pointer;font-size:14px}
  .mba-btn-primary:hover{background:#2c3e6b}
  .mba-grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .mba-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:800px){.mba-grid-3{grid-template-columns:1fr 1fr}.mba-grid-2{grid-template-columns:1fr}}
  .mba-metric{padding:14px 16px;background:#fff;border:1.5px solid #e8e9f0;border-radius:10px}
  .mba-metric-green{border-left:3px solid #2d6a2d}
  .mba-metric-gold{border-left:3px solid #b8960b}
  .mba-metric-red{border-left:3px solid #c0392b}
  .mba-metric-label{font-size:11px;font-weight:700;color:#72706b;text-transform:uppercase;letter-spacing:.05em}
  .mba-metric-value{font-size:26px;font-weight:800;color:#1a2744;margin-top:4px}
  .mba-bar-track{height:4px;background:#e8e9f0;border-radius:2px;margin-top:8px;overflow:hidden}
  .mba-bar-fill{height:100%;border-radius:2px}
  .mba-pill{padding:3px 9px;border-radius:6px;font-size:11px;font-weight:700}
  .mba-pill-pass{background:#edf7ed;color:#2d6a2d}
  .mba-pill-warn{background:#fdf8ed;color:#7a5e00}
  .mba-pill-fail{background:#fdf1f0;color:#c0392b}
`;

function Tip({ children, style = {} }) {
  return <div className="iq-tip" style={{ background: "#fff", borderRadius: 10, padding: "14px 18px", color: T.text, fontSize: 12, lineHeight: 1.6, boxShadow: "0 8px 30px rgba(26,39,68,.18)", border: "1px solid " + T.border, ...style }}>{children}</div>;
}

const fmtDate = (s) => { if (!s) return "—"; try { return new Date(s).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return s; } };
const fmtDuration = (sec) => { if (sec == null) return "—"; const m = Math.floor(sec / 60), s = sec % 60; return `${m}m ${String(s).padStart(2, "0")}s`; };
const scoreColor = (s) => (s == null) ? T.subtle : s >= 70 ? T.green : s >= 50 ? T.gold : T.red;
const completionLabel = (status, ct) => {
  if (status === "active") return { label: "IN PROGRESS", bg: T.blueSoft, fg: T.blue };
  if (ct === "abandoned") return { label: "ABANDONED", bg: T.redSoft, fg: T.red };
  if (ct === "timeout") return { label: "TIMED OUT", bg: T.goldSoft, fg: "#7a5e00" };
  if (status === "completed") return { label: "COMPLETED", bg: T.greenSoft, fg: T.green };
  return { label: status?.toUpperCase() || "—", bg: T.bg, fg: T.muted };
};

function SetupScreen({ onStart, userName }) {
  const [role, setRole] = useState(ROLES[0]);
  const [customRole, setCustomRole] = useState("");
  const [level, setLevel] = useState(LEVELS[0]);
  const [company, setCompany] = useState("");
  const [customCompany, setCustomCompany] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [duration, setDuration] = useState(20);
  const [difficulty, setDifficulty] = useState("Realistic");
  const [mode, setMode] = useState("interview");
  const [round, setRound] = useState("full");
  const [focus, setFocus] = useState([]);
  const [customFocus, setCustomFocus] = useState("");
  const [intro, setIntro] = useState("");
  const [jd, setJd] = useState("");
  const [alumniCount, setAlumniCount] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const [tipIdx, setTipIdx] = useState(0);
  // INT-07: consent gate. Once accepted (this browser), we don't re-prompt.
  const [consented, setConsented] = useState(() => { try { return localStorage.getItem(CONSENT_KEY) === "1"; } catch { return false; } });
  // Voice Phase 1: interviewer TTS voice preference (default female).
  const [voice, setVoice] = useState(getVoicePref());

  const toggleFocus = (f) => {
    if (f === "Other") { setFocus(c => c.includes("Other") ? c.filter(x => x !== "Other") : [...c, "Other"]); return; }
    setFocus(c => c.includes(f) ? c.filter(x => x !== f) : [...c, f]);
  };

  const finalRole = role === "Other" ? (customRole || "General") : role;
  const finalCompany = companyName.trim() || (company === "Other" ? (customCompany || "") : company);

  useEffect(() => {
    if (!finalCompany || !finalRole) { setAlumniCount(null); return; }
    let cancelled = false;
    fetchAlumniPreview(finalCompany, finalRole).then(r => !cancelled && setAlumniCount(r.count)).catch(() => {});
    return () => { cancelled = true; };
  }, [finalCompany, finalRole]);

  useEffect(() => { if (!starting) return; const t = setInterval(() => setTipIdx(i => (i + 1) % LOADING_TIPS.length), 2500); return () => clearInterval(t); }, [starting]);

  const handleStart = async () => {
    // Voice Phase 1: unlock audio inside this user gesture so iOS Safari will
    // allow the interviewer's voice to autoplay later.
    unlockAudioPlayback();
    try { localStorage.setItem(VOICE_KEY, voice); } catch { /* noop */ }
    setStarting(true); setError(null); setTipIdx(0);
    const allFocus = [...focus.filter(f => f !== "Other")];
    if (focus.includes("Other") && customFocus.trim()) allFocus.push(customFocus.trim());
    const selectedRound = ROUNDS.find(r => r.v === round);
    try {
      const payload = {
        name: userName || "Candidate",
        role: finalRole,
        level,
        company: finalCompany,
        duration_min: duration,
        difficulty,
        mode,
        round,
        round_label: selectedRound?.l || "Full Interview",
        round_detail: selectedRound?.detail || "",
        focus: allFocus,
        intro: [intro, jd ? "\n\n--- JOB DESCRIPTION ---\n" + jd : ""].filter(Boolean).join(""),
        voice,
      };
      const r = await startSession(payload);
      // INT-07: record the consent grant against this session (non-blocking).
      try { await recordConsent({ consent_type: "data_processing", copy_version: CONSENT_COPY_VERSION, session_id: r.session_id }); } catch { /* non-blocking */ }
      try { localStorage.setItem(CONSENT_KEY, "1"); } catch { /* noop */ }
      onStart({ ...payload, focus: allFocus }, r.session_id, r.greeting, r.state, r.audio_url);
    } catch (e) { setError(e.message); setStarting(false); }
  };

  if (starting) return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "100px 28px", textAlign: "center" }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: T.navy, marginBottom: 8 }}>Preparing your interview...</div>
      <div style={{ fontSize: 13, color: T.muted, marginBottom: 28 }}>Setting up personalized questions for {userName || "you"}</div>
      <div style={{ width: 200, height: 3, borderRadius: 2, background: T.border, overflow: "hidden", margin: "0 auto 32px" }}>
        <div style={{ height: "100%", background: T.navy, borderRadius: 2, animation: "iqLoad 2s ease-in-out infinite" }} />
      </div>
      <div style={{ padding: "14px 24px", borderRadius: 10, background: T.bg, border: "1px solid " + T.border, display: "inline-block", fontSize: 13, color: T.muted, maxWidth: 400, lineHeight: 1.6, animation: "iqFade .5s ease" }} key={tipIdx}>{LOADING_TIPS[tipIdx]}</div>
    </div>
  );

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "24px 28px" }}>
      <div style={{ background: T.navy, borderRadius: 12, padding: "22px 28px", marginBottom: 14, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div className="iq-hero">
          <div style={{ color: "#fff", fontWeight: 800, fontSize: 22, letterSpacing: "-.02em" }}>InterviewIQ</div>
          <div style={{ color: "rgba(255,255,255,.35)", fontSize: 12, marginTop: 2 }}>by Upskillize</div>
          <p className="iq-hero-desc" style={{ color: "rgba(255,255,255,.5)", fontSize: 13, lineHeight: 1.6, maxWidth: 400, opacity: 0, maxHeight: 0, overflow: "hidden", transition: "opacity .3s, max-height .3s", margin: 0 }}>Practice with real interview questions. Get scored. Know your selection chances.</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {[
            { label: "7", sub: "Stages", tip: (
              <Tip style={{ width: 270, padding: 0 }}>
                <div style={{ padding: "10px 16px", borderBottom: "1px solid #e8e9f0" }}>
                  <div style={{ fontWeight: 800, color: T.navy, fontSize: 11, textTransform: "uppercase", letterSpacing: ".08em" }}>Interview Flow</div>
                  <div style={{ fontSize: 10, color: T.subtle, marginTop: 2 }}>7 progressive stages · every session</div>
                </div>
                <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 4 }}>
                  {[
                    ["01", "Warm-up", "Ice-breaker & rapport building", "#2c3e6b"],
                    ["02", "About You", "Tell me about yourself", "#1a2744"],
                    ["03", "Deep-dive", "Resume cross-questioning", "#1a2744"],
                    ["04", "Role Q&A", "Domain & company-specific questions", "#1a2744"],
                    ["05", "Pressure", "Curveball & stress test", "#c0392b"],
                    ["06", "Your Turn", "Your questions to the interviewer", "#2d6a2d"],
                    ["07", "Wrap-up", "Close & scoring begins", "#b8960b"],
                  ].map(([num, title, sub, color], i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 4px", borderRadius: 6, background: i === 4 ? "#fdf1f0" : "transparent" }}>
                      <div style={{ width: 26, height: 26, borderRadius: 6, background: color, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        <span style={{ fontSize: 9, fontWeight: 900, color: "#fff", letterSpacing: ".02em" }}>{num}</span>
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: T.navy, lineHeight: 1.2 }}>{title}</div>
                        <div style={{ fontSize: 10, color: T.subtle, marginTop: 1 }}>{sub}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </Tip>
            )},
            { label: "AI", sub: "Powered", tip: (
              <Tip style={{ width: 240 }}>
                <div style={{ fontWeight: 700, marginBottom: 6, color: T.navy, fontSize: 11, textTransform: "uppercase" }}>Upskillize Solutions</div>
                <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.5 }}>Adaptive AI that simulates real interviewer behavior. Questions adjust to your answers, role, and target company.</div>
              </Tip>
            )},
            { label: "STAR", sub: "Scored", tip: (
              <Tip style={{ width: 230, left: "auto", right: 0, transform: "none" }}>
                <div style={{ fontWeight: 700, marginBottom: 8, color: T.navy, fontSize: 11, textTransform: "uppercase" }}>STAR Framework</div>
                {[["S","Situation — Set the context"],["T","Task — Your specific role"],["A","Action — What you did"],["R","Result — Quantified outcome"]].map(([l,d],i) => <div key={i} style={{ display:"flex",gap:8,marginBottom:5 }}><span style={{ fontWeight:800,color:T.navy,minWidth:14 }}>{l}</span><span style={{ fontSize:12,color:T.muted }}>{d}</span></div>)}
              </Tip>
            )},
          ].map((s, i) => (
            <div key={i} className="iq-stat" style={{ textAlign: "center", padding: "10px 16px", background: "rgba(255,255,255,.06)", borderRadius: 8, minWidth: 70 }}>
              <div style={{ fontSize: 18, fontWeight: 800, color: "#fff" }}>{s.label}</div>
              <div style={{ fontSize: 10, color: "rgba(255,255,255,.4)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".04em" }}>{s.sub}</div>
              {s.tip}
            </div>
          ))}
        </div>
      </div>

      <div className="vg2">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="vc">
            <div className="vc-h"><span className="vc-t">Your Profile</span></div>
            <div className="vc-b">
              <label className="vl">Paste Job Description <span style={{ fontWeight: 400, color: T.subtle, textTransform: "none" }}>(optional)</span></label>
              <textarea value={jd} onChange={e => setJd(e.target.value.slice(0, 2000))} rows={3} maxLength={2000} placeholder="Paste the JD — questions will be tailored to match requirements..." className="vi" style={{ resize: "none", minHeight: 70 }} />
              <label className="vl" style={{ marginTop: 14 }}>Quick Self-introduction <span style={{ fontWeight: 400, color: T.subtle, textTransform: "none" }}>(optional)</span></label>
              <textarea value={intro} onChange={e => setIntro(e.target.value.slice(0, 4000))} rows={2} maxLength={4000} placeholder="e.g. MBA graduate with 3 years in BFSI, led a credit risk project at ICICI..." className="vi" style={{ resize: "none", minHeight: 56 }} />
            </div>
          </div>

          <div className="vc">
            <div className="vc-h"><span className="vc-t">Target Role</span></div>
            <div className="vc-b">
              <label className="vl">Job Role</label>
              <select value={role} onChange={e => setRole(e.target.value)} className="vi" style={{ cursor: "pointer" }}>
                {ROLES.map(r => <option key={r}>{r}</option>)}
              </select>
              {role === "Other" && <input value={customRole} onChange={e => setCustomRole(e.target.value.slice(0, 120))} placeholder="Type your role..." className="vi" style={{ marginTop: 8 }} />}

              <label className="vl" style={{ marginTop: 14 }}>Experience Level</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {LEVELS.map(l => <button key={l} className={"vchip" + (level === l ? " vchip-on" : "")} onClick={() => setLevel(l)}>{l}</button>)}
              </div>

              <label className="vl" style={{ marginTop: 14 }}>Company Style</label>
              <select value={company} onChange={e => setCompany(e.target.value)} className="vi" style={{ cursor: "pointer" }}>
                {COMPANIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
              {company === "Other" && <input value={customCompany} onChange={e => setCustomCompany(e.target.value.slice(0, 120))} placeholder="Company style / sector..." className="vi" style={{ marginTop: 8 }} />}

              <label className="vl" style={{ marginTop: 14 }}>Specific Company Name <span style={{ fontWeight: 400, color: T.subtle, textTransform: "none" }}>(optional)</span></label>
              <input value={companyName} onChange={e => setCompanyName(e.target.value.slice(0, 120))} placeholder="e.g. KPMG, Razorpay, Zerodha, Deloitte..." className="vi" />
              <div style={{ fontSize: 11, color: T.subtle, marginTop: 4 }}>Questions will be tailored to this company's interview style.</div>

              {alumniCount > 0 && (
                <div style={{ marginTop: 10, padding: "10px 14px", borderRadius: 8, background: T.goldSoft, border: "1px solid " + T.goldBorder, fontSize: 13, color: "#5a4500" }}>
                  <strong>{alumniCount} real questions</strong> from alumni at {finalCompany} for {finalRole}.
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="vc">
            <div className="vc-h"><span className="vc-t">Session Settings</span></div>
            <div className="vc-b">
              <label className="vl">Duration</label>
              <div style={{ display: "flex", gap: 6 }}>
                {DURATIONS.map(d => <button key={d.v} className={"vchip" + (duration === d.v ? " vchip-on" : "")} onClick={() => setDuration(d.v)}>{d.l}</button>)}
              </div>

              <label className="vl" style={{ marginTop: 14 }}>Difficulty</label>
              <div className="vg3">
                {DIFFICULTIES.map(d => (
                  <button key={d.v} className={"vopt" + (difficulty === d.v ? " vopt-on" : "")} onClick={() => setDifficulty(d.v)} style={{ textAlign: "center", padding: "12px 10px" }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: T.navy }}>{d.l}</div>
                    <div style={{ fontSize: 11, color: T.subtle, marginTop: 2 }}>{d.d}</div>
                  </button>
                ))}
              </div>

              <label className="vl" style={{ marginTop: 14 }}>Mode</label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {MODES.map(m => (
                  <button key={m.v} className={"vopt" + (mode === m.v ? " vopt-on" : "")} onClick={() => setMode(m.v)}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: T.navy }}>{m.l}</div>
                    <div style={{ fontSize: 11, color: T.subtle, marginTop: 2 }}>{m.d}</div>
                  </button>
                ))}
              </div>

              {/* Voice Phase 1: interviewer voice picker. */}
              <label className="vl" style={{ marginTop: 14 }}>Interviewer Voice</label>
              <div style={{ display: "flex", gap: 6 }}>
                {[{ v: "female", l: "Female" }, { v: "male", l: "Male" }].map(o => (
                  <button key={o.v} className={"vchip" + (voice === o.v ? " vchip-on" : "")} onClick={() => setVoice(o.v)}>{o.l}</button>
                ))}
              </div>
            </div>
          </div>

          <div className="vc">
            <div className="vc-h"><span className="vc-t">Interview Round</span></div>
            <div className="vc-b">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {ROUNDS.map((r) => (
                  <button key={r.v} className={"vopt" + (round === r.v ? " vopt-on" : "")} onClick={() => setRound(r.v)}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span style={{ width: 28, height: 28, borderRadius: 6, background: round === r.v ? T.navy : T.bg, color: round === r.v ? "#fff" : T.subtle, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, flexShrink: 0, letterSpacing: "-.02em" }}>{r.badge}</span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 700, fontSize: 13, color: T.navy }}>{r.l}</div>
                        <div style={{ fontSize: 11, color: T.subtle, marginTop: 1 }}>{r.d}</div>
                      </div>
                    </div>
                    <div className="round-detail">{r.detail}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="vc" style={{ marginTop: 14 }}>
        <div className="vc-h"><span className="vc-t">Focus Areas <span style={{ fontWeight: 400, color: T.subtle }}>(optional)</span></span></div>
        <div className="vc-b">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {FOCUS_OPTIONS.map(f => <button key={f} className={"vchip" + (focus.includes(f) ? " vchip-on" : "")} onClick={() => toggleFocus(f)}>{f}</button>)}
          </div>
          {focus.includes("Other") && <input value={customFocus} onChange={e => setCustomFocus(e.target.value.slice(0, 80))} placeholder="Type your focus area..." className="vi" style={{ marginTop: 8 }} />}
        </div>
      </div>

      {/* INT-07: consent notice shown at (first) session start.
          [PENDING LEGAL REVIEW] — placeholder copy only; final wording and the
          retention windows are signed off by Legal outside this sprint. Recorded
          with copy_version="v0-draft" so we can trace exactly what was shown. */}
      {!consented && (
        <div className="vc" style={{ marginTop: 14, borderLeft: "3px solid " + T.gold }}>
          <div className="vc-h"><span className="vc-t">Before you begin</span></div>
          <div className="vc-b">
            <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
              <input type="checkbox" checked={consented} onChange={e => setConsented(e.target.checked)} style={{ marginTop: 3, width: 16, height: 16, flexShrink: 0, accentColor: T.navy }} />
              <span style={{ fontSize: 13, color: T.muted, lineHeight: 1.6 }}>
                {/* [PENDING LEGAL REVIEW] */}
                I agree that InterviewIQ may process my interview responses to generate my
                practice feedback and scorecard. My transcript and report are retained for a
                limited period and I can download or delete my data any time from Settings.
                <span style={{ color: T.subtle }}> (Draft notice — pending legal review.)</span>
              </span>
            </label>
          </div>
        </div>
      )}

      {error && <div style={{ marginTop: 14, padding: "12px 16px", borderRadius: 10, background: T.redSoft, border: "1px solid #f5c6c2", color: T.red, fontSize: 13 }}>{error}</div>}
      <button className="vbtn" style={{ marginTop: 16 }} onClick={handleStart} disabled={!consented}>Start Interview</button>
      {!consented && <p style={{ textAlign: "center", fontSize: 12, color: T.subtle, marginTop: 8 }}>Please accept the notice above to begin.</p>}
      <p style={{ textAlign: "center", fontSize: 12, color: T.subtle, marginTop: 10 }}>No judgement. No abuse. No matter how you answer.</p>
    </div>
  );
}
// INT-01: confidence rating widget shown after every scored answer.
function RatingWidget({ busy, onRate }) {
  const [picked, setPicked] = useState(undefined);
  const choose = (n) => { if (busy) return; setPicked(n); onRate(n); };
  const pillStyle = (n) => {
    const isPicked = picked === n;
    return {
      width: 46, height: 46, borderRadius: 10, fontFamily: IQ.mono, fontSize: 18, fontWeight: 500,
      cursor: busy ? "not-allowed" : "pointer", transition: "all .15s",
      border: "1.5px solid " + (isPicked ? IQ.teal : T.border),
      background: isPicked ? IQ.teal : "#fff", color: isPicked ? IQ.cream : IQ.navy,
    };
  };
  return (
    <div style={{ background: "#fff", border: "1px solid " + T.border, borderRadius: 12, padding: "16px 18px", fontFamily: IQ.sans, animation: "iqFade .3s ease" }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: IQ.navy, marginBottom: 4 }}>How confident are you in that answer?</div>
      <div style={{ fontSize: 12, color: T.muted, marginBottom: 12 }}>1 = not confident, 5 = very confident</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {[1, 2, 3, 4, 5].map(n => (
          <button key={n} disabled={busy} onClick={() => choose(n)} style={pillStyle(n)}
            onMouseEnter={e => { if (!busy && picked !== n) { e.currentTarget.style.background = IQ.gold; e.currentTarget.style.color = IQ.cream; e.currentTarget.style.borderColor = IQ.gold; } }}
            onMouseLeave={e => { if (picked !== n) { e.currentTarget.style.background = "#fff"; e.currentTarget.style.color = IQ.navy; e.currentTarget.style.borderColor = T.border; } }}>
            {n}
          </button>
        ))}
        <button disabled={busy} onClick={() => choose(null)} style={{ marginLeft: 6, padding: "0 16px", height: 46, borderRadius: 10, border: "1.5px dashed " + (picked === null ? IQ.teal : T.border), background: picked === null ? IQ.teal : "#fff", color: picked === null ? IQ.cream : T.muted, fontSize: 13, fontWeight: 600, cursor: busy ? "not-allowed" : "pointer", fontFamily: IQ.sans }}>
          Prefer not to say
        </button>
      </div>
    </div>
  );
}

// Voice Phase 2: consent modal shown on first mic use per session. Recorded as
// consent_type="voice_recording", copy_version="v0-draft".
// [PENDING LEGAL REVIEW] — the copy below is a draft only. Final wording is signed
// off by Legal outside this sprint; copy_version pins exactly what was shown.
function VoiceConsentModal({ onAccept, onDecline, busy }) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(11,22,40,.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onDecline}>
      <div onClick={e => e.stopPropagation()} style={{ background: "#fff", borderRadius: 14, maxWidth: 440, width: "100%", overflow: "hidden", fontFamily: IQ.sans, boxShadow: "0 20px 60px rgba(11,22,40,.35)", animation: "iqFade .25s ease" }}>
        <div style={{ background: IQ.navy, padding: "18px 24px", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: IQ.teal, display: "inline-flex" }}><IconMic size={20} /></span>
          <div style={{ color: "#fff", fontWeight: 800, fontSize: 16 }}>Use your voice to answer</div>
        </div>
        <div style={{ padding: "20px 24px" }}>
          {/* [PENDING LEGAL REVIEW] — draft consent copy, do not ship without legal sign-off. */}
          <p style={{ fontSize: 14, color: T.text, lineHeight: 1.65, margin: 0 }}>
            InterviewIQ will convert your spoken answer to text. Your audio is transcribed and
            immediately discarded — it is never stored. Only the text of your answer is saved,
            exactly as if you had typed it.
          </p>
          <div style={{ fontSize: 12, color: T.subtle, marginTop: 10 }}>You can still type instead at any time. (Draft notice — pending legal review.)</div>
          <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
            <button onClick={onAccept} disabled={busy} className="vbtn" style={{ opacity: busy ? 0.6 : 1 }}>Allow & record</button>
            <button onClick={onDecline} disabled={busy} className="vbtn" style={{ background: "#fff", color: IQ.navy, border: "1.5px solid " + T.border }}>Not now</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function InterviewScreen({ config, sessionId, greeting, greetingAudioUrl, initialState, initialMessages, startedAt, onEnd, onRestart }) {
  // INT-06: on resume we hydrate from server history; on a fresh start we seed with the greeting.
  const [messages, setMessages] = useState(
    initialMessages && initialMessages.length ? initialMessages : [{ role: "assistant", content: greeting, audio_url: greetingAudioUrl }]
  );
  // Voice Phase 1: playback state.
  const [muted, setMuted] = useState(getMutePref);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);   // autoplay blocked (iOS) → tap-to-play
  const playedIdxRef = useRef(-1);                    // last message index auto-played
  const audioBlobCache = useRef(new Map());           // audio_url -> object URL (so Replay reuses, no re-fetch)
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // Voice Phase 2: spoken-answer (STT) state — BEHAVIOURAL round only.
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [recSeconds, setRecSeconds] = useState(0);
  const [voiceConsented, setVoiceConsented] = useState(false);   // per session
  const [showVoiceConsent, setShowVoiceConsent] = useState(false);
  const [consentBusy, setConsentBusy] = useState(false);
  const [sttToast, setSttToast] = useState(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const recTimerRef = useRef(null);
  const recChunksRef = useRef([]);
  const recStartRef = useRef(0);                 // Phase 3: precise recording duration
  const pendingDeliveryRef = useRef(null);       // Phase 3: metrics awaiting the next Send
  const answeredByVoiceRef = useRef(false);      // Phase 3: TYPED vs SPOKEN meta
  const toastTimerRef = useRef(null);
  const MAX_REC_SECONDS = 180;   // 3 min hard cap, auto-stop
  // INT-06: timer remaining is derived from the persisted start time so a refresh
  // resumes the same countdown instead of restarting it.
  const [secondsLeft, setSecondsLeft] = useState(() => {
    const total = config.duration_min * 60;
    if (!startedAt) return total;
    return Math.max(0, total - Math.floor((Date.now() - startedAt) / 1000));
  });
  const [sstate, setSstate] = useState(initialState || null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  const nextAction = sstate?.next_action || "answer";
  const awaitingRating = nextAction === "rating";
  const reverseMode = nextAction === "reverse_question";
  const uc = messages.filter(m => m.role === "user").length;

  useEffect(() => { if (secondsLeft <= 0 || ended) return; const t = setInterval(() => setSecondsLeft(s => s - 1), 1000); return () => clearInterval(t); }, [secondsLeft, ended]);
  useEffect(() => { if (secondsLeft <= 0 && !ended && !loading) { setEnded(true); if (uc > 0) onEnd(); } }, [secondsLeft, ended, loading, uc, onEnd]);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages, loading, awaitingRating]);

  // Backend is the source of truth: when it reports the interview is done, move to the readout.
  useEffect(() => {
    if (ended) return;
    if (nextAction === "readout" || nextAction === "done") { setEnded(true); onEnd(); }
  }, [nextAction, ended, onEnd]);

  // Voice Phase 1: track playback so the avatar can pulse and errors fall back to text.
  useEffect(() => {
    const p = player(); if (!p) return;
    const onPlay = () => { setAudioPlaying(true); setNeedsTap(false); };
    const onStop = () => setAudioPlaying(false);
    p.addEventListener("play", onPlay);
    p.addEventListener("playing", onPlay);
    p.addEventListener("ended", onStop);
    p.addEventListener("pause", onStop);
    p.addEventListener("error", onStop);
    return () => {
      p.removeEventListener("play", onPlay);
      p.removeEventListener("playing", onPlay);
      p.removeEventListener("ended", onStop);
      p.removeEventListener("pause", onStop);
      p.removeEventListener("error", onStop);
      try { p.pause(); } catch { /* noop */ }   // stop audio when leaving the interview
      // Revoke cached blob URLs so audio buffers are freed when the session ends.
      audioBlobCache.current.forEach(u => { try { URL.revokeObjectURL(u); } catch { /* noop */ } });
      audioBlobCache.current.clear();
    };
  }, []);

  // force=true is used by the explicit replay/tap controls (a user gesture), so it
  // plays even when muted; autoplay respects the mute toggle.
  // The audio is fetched with our auth headers and played from a blob URL cached
  // per message, so Replay never re-fetches and the endpoint stays auth-guarded.
  const playAudio = async (url, force = false) => {
    const p = player();
    if (!p || !url || (muted && !force)) return;
    try {
      let objUrl = audioBlobCache.current.get(url);
      if (!objUrl) {
        objUrl = await fetchAudioObjectUrl(url);
        audioBlobCache.current.set(url, objUrl);
      }
      p.src = objUrl;
      const pr = p.play();
      if (pr && pr.then) pr.then(() => setNeedsTap(false)).catch(() => setNeedsTap(true));
    } catch { setNeedsTap(true); }
  };

  // Autoplay the newest interviewer message when its audio arrives (once per message).
  useEffect(() => {
    const idx = messages.length - 1;
    const last = messages[idx];
    if (!last || last.role !== "assistant" || !last.audio_url) return;
    if (idx === playedIdxRef.current) return;
    playedIdxRef.current = idx;
    if (!muted) playAudio(last.audio_url);
  }, [messages]); // eslint-disable-line react-hooks/exhaustive-deps

  const latestAudioUrl = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant" && messages[i].audio_url) return messages[i].audio_url;
    return null;
  })();
  const lastAssistantIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
    return -1;
  })();

  const toggleMute = () => {
    setMuted(m => {
      const next = !m;
      try { localStorage.setItem(MUTE_KEY, next ? "1" : "0"); } catch { /* noop */ }
      if (next) { try { player()?.pause(); } catch { /* noop */ } }
      return next;
    });
  };
  const replay = () => { if (latestAudioUrl) playAudio(latestAudioUrl, true); };

  // ── Voice Phase 2/3: record → transcribe → drop editable text into the input ──
  const sttAvailable = !!sstate?.stt_available;
  // Phase 3 Part B: voice works in EVERY answering round (Warm-up, Domain,
  // Behavioural, Case, Reverse) — i.e. whenever the learner can submit an answer.
  const canAnswer = !ended && !awaitingRating && (nextAction === "answer" || nextAction === "reverse_question");

  const showToast = (msg) => {
    setSttToast(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setSttToast(null), 4000);
  };

  const stopMediaStream = () => {
    const s = mediaStreamRef.current;
    if (s) { try { s.getTracks().forEach(t => t.stop()); } catch { /* noop */ } mediaStreamRef.current = null; }
  };

  const clearRecTimer = () => { if (recTimerRef.current) { clearInterval(recTimerRef.current); recTimerRef.current = null; } };

  // Actually acquire the mic and start capturing (consent already handled).
  const beginRecording = async () => {
    if (recording || transcribing) return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      showToast("Voice input unavailable — please type your answer"); return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      // Permission denied or no device → fall back to typing, zero degradation.
      showToast("Voice input unavailable — please type your answer"); return;
    }
    mediaStreamRef.current = stream;
    let mr;
    try { mr = new MediaRecorder(stream); }
    catch { stopMediaStream(); showToast("Voice input unavailable — please type your answer"); return; }
    recChunksRef.current = [];
    mr.ondataavailable = (e) => { if (e.data && e.data.size) recChunksRef.current.push(e.data); };
    mr.onstop = () => finishRecording(mr.mimeType);
    mediaRecorderRef.current = mr;
    try { mr.start(); }
    catch { stopMediaStream(); showToast("Voice input unavailable — please type your answer"); return; }
    recStartRef.current = Date.now();
    setRecording(true); setRecSeconds(0);
    recTimerRef.current = setInterval(() => setRecSeconds(s => {
      const next = s + 1;
      if (next >= MAX_REC_SECONDS) stopRecording();   // auto-stop at the cap
      return next;
    }), 1000);
  };

  const stopRecording = () => {
    clearRecTimer();
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") { try { mr.stop(); } catch { /* noop */ } }   // fires onstop → finishRecording
    setRecording(false);
  };

  // Called from MediaRecorder.onstop: bundle chunks, upload, insert transcript.
  const finishRecording = async (mimeType) => {
    stopMediaStream();
    const chunks = recChunksRef.current; recChunksRef.current = [];
    if (!chunks.length) { showToast("Voice input unavailable — please type your answer"); return; }
    const type = mimeType || "audio/webm";
    const blob = new Blob(chunks, { type });
    const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : type.includes("wav") ? "wav" : "webm";
    const durationSeconds = recStartRef.current ? (Date.now() - recStartRef.current) / 1000 : 0;
    setTranscribing(true);
    try {
      const res = await sttTranscribe(sessionId, blob, `answer.${ext}`, durationSeconds);
      if (res && res.transcript) {
        // Insert into the editable input — the learner reviews and presses Send.
        setInput(prev => ((prev ? prev.trimEnd() + " " : "") + res.transcript).slice(0, 4000));
        // Phase 3: mark this answer as SPOKEN and stash its delivery metrics for Send.
        answeredByVoiceRef.current = true;
        pendingDeliveryRef.current = res.delivery_metrics || null;
        setTimeout(() => inputRef.current?.focus(), 50);
      } else {
        showToast("Voice input unavailable — please type your answer");
      }
    } catch {
      showToast("Voice input unavailable — please type your answer");
    } finally { setTranscribing(false); }
  };

  // Mic button: toggle stop while recording; otherwise gate on consent then record.
  const onMicClick = () => {
    if (recording) { stopRecording(); return; }
    if (transcribing) return;
    if (!voiceConsented) { setShowVoiceConsent(true); return; }
    beginRecording();
  };

  const acceptVoiceConsent = async () => {
    setConsentBusy(true);
    try { await recordConsent({ consent_type: "voice_recording", copy_version: CONSENT_COPY_VERSION, session_id: sessionId }); }
    catch { /* non-blocking: the server-side gate is authoritative */ }
    setConsentBusy(false);
    setVoiceConsented(true);
    setShowVoiceConsent(false);
    beginRecording();
  };

  const declineVoiceConsent = () => { setShowVoiceConsent(false); };

  // Cleanup: stop any in-flight recording/stream/timers when leaving the interview.
  useEffect(() => () => {
    clearRecTimer();
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") { try { mr.stop(); } catch { /* noop */ } }
    stopMediaStream();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Diagnostics (dev only): surface stt_available once per state change so a
  // missing mic is instantly attributable — e.g. `undefined` means the client is
  // talking to a backend without the flags, `false` means a flag is off.
  useEffect(() => {
    if (import.meta.env?.DEV && sstate) {
      console.debug("[voice] stt_available =", sstate.stt_available, "| stage =", sstate.current_stage);
    }
  }, [sstate]);

  const send = async () => {
    const textVal = input.trim(); if (!textVal || loading || ended || awaitingRating) return;
    // Phase 3: this answer is SPOKEN if it came from the mic, else TYPED. Consume the
    // pending metrics/flag so a later typed answer doesn't inherit them.
    const spoken = answeredByVoiceRef.current;
    const metrics = pendingDeliveryRef.current;
    answeredByVoiceRef.current = false; pendingDeliveryRef.current = null;
    setMessages(m => [...m, { role: "user", content: textVal, meta: spoken ? "SPOKEN" : "TYPED" }]); setInput(""); setLoading(true); setError(null);
    try {
      const res = await sendTurn(sessionId, textVal, sstate?.current_stage, config.voice || "female", spoken ? metrics : null);
      setMessages(m => [...m, { role: "assistant", content: res.reply, audio_url: res.audio_url }]);
      setSstate(res.state);
    } catch (e) {
      setError(e.message);
      try { setSstate(await fetchSessionState(sessionId)); } catch { /* noop */ }
    } finally { setLoading(false); setTimeout(() => inputRef.current?.focus(), 50); }
  };

  const rate = async (val) => {
    if (ratingBusy || !awaitingRating || !sstate?.last_answer_id) return;
    setRatingBusy(true); setError(null);
    try {
      const res = await submitRating(sessionId, sstate.last_answer_id, val);
      setSstate(res.state);
    } catch (e) {
      setError(e.message);
      try { setSstate(await fetchSessionState(sessionId)); } catch { /* noop */ }
    } finally { setRatingBusy(false); }
  };

  // Keyboard 1-5 submits the confidence rating on desktop.
  useEffect(() => {
    if (!awaitingRating) return;
    const onKey = (e) => { if (["1", "2", "3", "4", "5"].includes(e.key) && e.target.tagName !== "TEXTAREA") { e.preventDefault(); rate(Number(e.key)); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [awaitingRating, ratingBusy, sstate]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  const mmss = (s) => Math.floor(Math.max(0, s) / 60) + ":" + String(Math.max(0, s) % 60).padStart(2, "0");
  const stageLabel = sstate?.stage_label || "Warm-up";

  // Phase 3 Part E: minimal live voice-state chip driven by ACTUAL events.
  // LISTENING while recording, THINKING while transcribing/scoring, SPEAKING while
  // the interviewer's audio plays, otherwise nothing. (The full orb/waveform lands
  // in the dual-theme redesign — this is the plain-text placeholder.)
  const voiceChip = recording ? { label: "Listening", color: IQ.orange }
    : (transcribing || loading) ? { label: "Thinking", color: IQ.navy }
    : audioPlaying ? { label: "Speaking", color: IQ.teal }
    : null;

  const handleEndClick = async () => {
    setEnded(true);
    if (uc > 0) { onEnd(); }
    else { await abandonSession(sessionId); onRestart(); }
  };

  const inputDisabled = loading || ended || awaitingRating;

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", display: "flex", flexDirection: "column", height: "calc(100vh - 70px)", minHeight: 500 }}>
      {/* Interview HUD — responsive header (replaces the legacy fixed-row header
          that clipped its title on narrow viewports). Wraps and truncates; no
          fixed heights; safe padding down to 360px. */}
      <div className="iq-hud">
        <div className="iq-hud-bar">
          <div className="iq-hud-brand">
            <div className="iq-hud-title">InterviewIQ</div>
            <div className="iq-hud-sub">{config.role}{config.company ? ` — ${config.company}` : " — General"}</div>
          </div>
          <div className="iq-hud-right">
            {latestAudioUrl && (
              <div className="iq-hud-audio">
                <button className="iq-audio-btn" onClick={toggleMute} title={muted ? "Unmute interviewer voice" : "Mute interviewer voice"} aria-label={muted ? "Unmute interviewer voice" : "Mute interviewer voice"} style={muted ? {} : { color: IQ.teal }}>
                  {muted ? <IconSpeakerOff /> : <IconSpeaker />}
                </button>
                <button className="iq-audio-btn" onClick={replay} disabled={!latestAudioUrl} title="Replay question" aria-label="Replay question">
                  <IconReplay />
                </button>
              </div>
            )}
            <span className="iq-hud-timer" style={{ color: secondsLeft <= 60 ? "#ff6b6b" : secondsLeft <= 180 ? T.gold : "#fff" }}>{mmss(secondsLeft)}</span>
            <button className="iq-hud-end" onClick={handleEndClick}>End</button>
          </div>
        </div>
        <div className="iq-hud-stage-row">
          <span className="iq-hud-stage">
            <span className="iq-hud-stage-dot" />
            <span className="iq-hud-stage-label">{stageLabel}</span>
          </span>
          {voiceChip && (
            <span aria-live="polite" style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: 10, padding: "2px 10px", borderRadius: 999, background: "rgba(255,255,255,0.10)", fontFamily: IQ.mono, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "#fff" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: voiceChip.color, animation: "iqRecDot 1.1s ease-in-out infinite", flexShrink: 0 }} />
              {voiceChip.label}
            </span>
          )}
        </div>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "20px 28px", background: T.bg }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {messages.map((m, i) => { const isV = m.role === "assistant"; const speaking = isV && i === lastAssistantIdx && audioPlaying; return (
            <div key={i} style={{ display: "flex", gap: 10, flexDirection: isV ? "row" : "row-reverse", alignItems: "flex-start", animation: "iqFade .3s ease" }}>
              <div className={speaking ? "iq-avatar-speaking" : ""} style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: isV ? T.navy : T.border, color: isV ? "#fff" : T.navy, fontWeight: 800, fontSize: 11 }}>{isV ? "IQ" : (config.name?.[0]?.toUpperCase() || "Y")}</div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: isV ? "flex-start" : "flex-end", maxWidth: "78%" }}>
                <div style={{ padding: "12px 16px", borderRadius: isV ? "2px 12px 12px 12px" : "12px 2px 12px 12px", fontSize: 14, lineHeight: 1.65, background: isV ? T.white : T.navy, color: isV ? T.text : "#fff", border: isV ? "1px solid " + T.border : "none", fontFamily: T.font }}>{isV ? renderMd(m.content) : m.content}</div>
                {!isV && m.meta && <span style={{ fontSize: 10, color: T.subtle, marginTop: 3, fontFamily: IQ.mono, letterSpacing: "0.05em" }}>{m.meta === "SPOKEN" ? "Spoken" : "Typed"}</span>}
              </div>
            </div>); })}
          {loading && <div style={{ display: "flex", gap: 10 }}><div style={{ width: 32, height: 32, borderRadius: "50%", background: T.navy, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ color: "#fff", fontWeight: 800, fontSize: 11 }}>IQ</span></div><div style={{ padding: "14px 18px", borderRadius: "2px 12px 12px 12px", background: T.white, border: "1px solid " + T.border }}><div style={{ display: "flex", gap: 5 }}>{[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: T.subtle, animation: "iqPulse 1.2s ease-in-out infinite", animationDelay: i * 0.15 + "s" }} />)}</div></div></div>}
          {needsTap && latestAudioUrl && !muted && (
            <button onClick={() => playAudio(latestAudioUrl, true)} style={{ alignSelf: "flex-start", display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 20, border: "1px solid " + IQ.teal, background: "#fff", color: IQ.navy, fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: T.font }}>
              <span style={{ color: IQ.teal, display: "inline-flex" }}><IconSpeaker size={16} /></span> Tap to hear the question
            </button>
          )}
          {awaitingRating && !loading && <RatingWidget busy={ratingBusy} onRate={rate} />}
          {reverseMode && !loading && <div style={{ padding: "12px 16px", borderRadius: 10, background: IQ.cream, border: "1px solid " + IQ.gold, color: "#5a4500", fontSize: 13, fontWeight: 600, fontFamily: IQ.sans }}>Your turn to interview us. Ask us two questions.</div>}
          {error && <div style={{ padding: "10px 14px", borderRadius: 8, background: T.redSoft, color: T.red, fontSize: 13 }}>{error}</div>}
          {secondsLeft <= 0 && <div style={{ padding: "14px 18px", borderRadius: 8, background: T.bg, border: "1px solid " + T.border, textAlign: "center", fontSize: 14, color: T.muted }}>{uc > 0 ? <span style={{ fontWeight: 700 }}>Time is up. Generating your report...</span> : <div><div style={{ fontWeight: 700, marginBottom: 8 }}>Time is up. No answers given.</div><button onClick={onRestart} className="vbtn" style={{ width: "auto", display: "inline-flex", fontSize: 13, padding: "8px 20px" }}>Try Again</button></div>}</div>}
          {ended && uc === 0 && secondsLeft > 0 && <div style={{ padding: "14px 18px", borderRadius: 8, background: T.bg, border: "1px solid " + T.border, textAlign: "center" }}><div style={{ fontWeight: 700, marginBottom: 8, color: T.muted }}>Session ended.</div><button onClick={onRestart} className="vbtn" style={{ width: "auto", display: "inline-flex", fontSize: 13, padding: "8px 20px" }}>Start New Session</button></div>}
        </div>
      </div>

      <div style={{ background: T.white, borderTop: "1px solid " + T.border, padding: "14px 28px", flexShrink: 0 }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", gap: 10, alignItems: "flex-end" }}>
          <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value.slice(0, 4000))} onKeyDown={handleKey} rows={1} maxLength={4000} placeholder={awaitingRating ? "Rate your confidence above to continue" : ended ? "Interview ended" : reverseMode ? "Ask your question…" : transcribing ? "Transcribing your answer…" : recording ? "Listening… tap the square to stop" : "Type your answer…"} disabled={inputDisabled} className="vi" style={{ flex: 1, resize: "none", minHeight: 44, maxHeight: 140, borderRadius: 10 }} />
          {/* Voice Phase 3 Part B: mic is ACTIVE in every answering round (Warm-up,
              Domain, Behavioural, Case, and Reverse) whenever STT is available and
              the learner can answer. No more Behavioural-only lock. */}
          {sttAvailable && canAnswer && (
            <button
              onClick={onMicClick}
              disabled={(inputDisabled || transcribing) && !recording}
              className={"iq-mic-btn" + (recording ? " iq-mic-recording" : "")}
              title={recording ? "Stop recording" : "Record your answer"}
              aria-label={recording ? "Stop recording" : "Record your answer"}
            >
              {recording ? <IconStop /> : <IconMic />}
            </button>
          )}
          <button onClick={send} disabled={inputDisabled || !input.trim()} className="mba-btn-primary" style={{ padding: "10px 22px", fontSize: 14, opacity: inputDisabled || !input.trim() ? 0.5 : 1 }}>Send</button>
        </div>
        {/* Voice Phase 2: live recording timer (DM Mono) / transcribing shimmer / fallback toast. */}
        {(recording || transcribing || sttToast) ? (
          <div style={{ maxWidth: 700, margin: "8px auto 0", display: "flex", alignItems: "center", gap: 10, minHeight: 18 }}>
            {recording && (
              <>
                <span style={{ width: 9, height: 9, borderRadius: "50%", background: IQ.orange, animation: "iqRecDot 1.1s ease-in-out infinite", flexShrink: 0 }} />
                <span style={{ fontFamily: IQ.mono, fontSize: 13, color: IQ.orange, fontVariantNumeric: "tabular-nums" }}>{mmss(recSeconds)}</span>
                <span style={{ fontSize: 12, color: T.muted }}>Recording — tap the square to stop (auto-stops at 3:00)</span>
              </>
            )}
            {transcribing && !recording && <span className="iq-shimmer-text" style={{ fontSize: 13, fontWeight: 700 }}>Transcribing…</span>}
            {sttToast && !recording && !transcribing && <span style={{ fontSize: 12, color: IQ.orange, fontWeight: 600 }}>{sttToast}</span>}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: T.subtle, marginTop: 6, maxWidth: 700, margin: "6px auto 0" }}>{awaitingRating ? "Tap 1–5 or press a number key to rate your confidence." : sttAvailable && canAnswer ? "Type your answer, or tap the mic to speak it." : "Enter to send — Shift+Enter for new line"}</div>
        )}
      </div>

      {showVoiceConsent && <VoiceConsentModal onAccept={acceptVoiceConsent} onDecline={declineVoiceConsent} busy={consentBusy} />}
    </div>
  );
}

// INT-02: calibration profile — three summary tiles + a coaching pill (never punitive).
function CalibrationBlock({ cal }) {
  const profile = cal?.profile;
  const hasData = profile && profile !== "insufficient_data" && cal.avg_confidence != null;
  const copy = CALIBRATION_COPY[profile];
  const delta = cal?.calibration_delta;
  return (
    <div className="vc" style={{ marginBottom: 16 }}>
      <div className="vc-h"><span className="vc-t">Calibration Profile</span></div>
      <div className="vc-b">
        {!hasData ? (
          <div style={{ fontSize: 13, color: T.muted, fontFamily: IQ.sans }}>Not enough data — rate your confidence on a few answers next time to see how your self-assessment compares with your performance.</div>
        ) : (
          <>
            <div className="mba-grid-3" style={{ marginBottom: 14 }}>
              {[
                ["Your Average Confidence", cal.avg_confidence, "/5"],
                ["Your Average Score", cal.avg_score, "/5"],
                ["Your Calibration Delta", (delta > 0 ? "+" : "") + delta, ""],
              ].map(([label, val, suffix], i) => (
                <div key={i} className="mba-metric">
                  <div className="mba-metric-label">{label}</div>
                  <div className="mba-metric-value" style={{ fontFamily: IQ.mono }}>{val}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>{suffix}</span></div>
                </div>
              ))}
            </div>
            {copy && (
              <div style={{ display: "inline-block", padding: "12px 18px", borderRadius: 10, background: copy.bg, color: IQ.cream, fontFamily: IQ.sans, maxWidth: 580 }}>
                <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 3 }}>{copy.label}</div>
                <div style={{ fontSize: 13, lineHeight: 1.5 }}>{copy.copy}</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// Voice Phase 3 Part D: Delivery Profile — informational, NOT counted in the band.
// Colors follow the locked band semantics via BAND_STYLE (gold Offer-Ready, teal
// Interview-Ready, navy Building, orange Not Ready). < 3 spoken answers → a nudge.
function DeliveryBlock({ delivery }) {
  if (!delivery || Object.keys(delivery).length === 0) return null;
  if (!delivery.enough_data) {
    return (
      <div className="vc" style={{ marginBottom: 16 }}>
        <div className="vc-h"><span className="vc-t">Delivery Profile</span></div>
        <div className="vc-b"><div style={{ fontSize: 13, color: T.muted, fontFamily: IQ.sans }}>{delivery.message || "Not enough voice data — try answering aloud next session."}</div></div>
      </div>
    );
  }
  const bs = BAND_STYLE[delivery.delivery_band] || BAND_STYLE["Not Ready"];
  const metric = (label, val, suffix) => (
    <div className="mba-metric"><div className="mba-metric-label">{label}</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono }}>{val ?? "—"}{suffix ? <span style={{ fontSize: 12, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>{suffix}</span> : null}</div></div>
  );
  return (
    <div className="vc" style={{ marginBottom: 16 }}>
      <div className="vc-h" style={{ display: "flex", alignItems: "center" }}>
        <span className="vc-t">Delivery Profile</span>
        <span style={{ marginLeft: "auto", padding: "3px 12px", borderRadius: 8, background: bs.bg, color: bs.fg, fontFamily: IQ.display, fontWeight: 700, fontSize: 13 }}>{delivery.delivery_band}</span>
      </div>
      <div className="vc-b">
        <div className="mba-grid-3" style={{ marginBottom: 14 }}>
          {metric("Avg Pace", delivery.avg_wpm, " wpm")}
          {metric("Fillers / min", delivery.filler_per_min, "")}
          {metric("Spoken Answers", delivery.spoken_answers, "")}
        </div>
        <div style={{ fontSize: 13, lineHeight: 1.6, color: T.text, fontFamily: IQ.sans, marginBottom: 6 }}>{delivery.pace_verdict}</div>
        <div style={{ fontSize: 13, lineHeight: 1.6, color: T.text, fontFamily: IQ.sans, marginBottom: 6 }}>{delivery.filler_note}</div>
        <div style={{ fontSize: 13, lineHeight: 1.6, color: T.text, fontFamily: IQ.sans, marginBottom: 10 }}>{delivery.pause_note}</div>
        <div style={{ fontSize: 11, color: T.subtle, fontStyle: "italic" }}>{delivery.note}</div>
      </div>
    </div>
  );
}

function DebriefScreen({ config, sessionId, onRestart, onViewHistory }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { (async () => { try {
    const r = await endSession(sessionId);
    if (!(r.strengths?.length) && !(r.star_breakdown?.length)) {
      r.one_line = r.one_line || "Session ended before answering. Start another when ready.";
      r.next_focus = r.next_focus || "Prepare your introduction, pick a role, and try again.";
    }
    setD(r);
  } catch (e) { setError(e.message); } })(); }, [sessionId]);

  if (error) return <div className="vc" style={{ padding: 28, textAlign: "center" }}><div style={{ fontSize: 16, fontWeight: 700, color: T.navy, marginBottom: 8 }}>Could not generate report</div><div style={{ fontSize: 13, color: T.muted, marginBottom: 20 }}>{error}</div><button onClick={onRestart} className="mba-btn-primary">Start new session</button></div>;
  if (!d) return <div style={{ textAlign: "center", padding: "80px 20px" }}><div className="mba-spinner" style={{ margin: "0 auto 16px" }} /><div style={{ fontSize: 16, fontWeight: 700, color: T.navy }}>Analyzing your interview...</div><div style={{ fontSize: 13, color: T.subtle, marginTop: 4 }}>Scoring each response against the STAR framework.</div></div>;

  const band = d.overall_band || "Not Ready";
  const bandStyle = BAND_STYLE[band] || BAND_STYLE["Not Ready"];
  const roundBands = d.round_bands || {};
  const cal = d.calibration || {};
  const ss = d.sub_scores || {};
  const pk = (k) => ({ communication:"Communication",roleKnowledge:"Role Knowledge",clarity:"Clarity",confidence:"Confidence",structure:"Structure",problemSolving:"Problem Solving" })[k] || k;
  const currentRound = ROUNDS.find(r => r.v === config.round) || ROUNDS[ROUNDS.length - 1];

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "24px 28px" }}>
      <div style={{ background: T.navy, borderRadius: 12, padding: "28px 32px", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "rgba(255,255,255,.3)" }}>Readiness</div>
          <div style={{ padding: "3px 10px", borderRadius: 10, background: "rgba(184,150,11,.2)", border: "1px solid rgba(184,150,11,.3)", fontSize: 10, fontWeight: 700, color: T.gold }}>{currentRound.l}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
          <div style={{ display: "inline-flex", alignItems: "center", padding: "10px 24px", borderRadius: 10, background: bandStyle.bg, color: bandStyle.fg, fontFamily: IQ.display, fontWeight: 700, letterSpacing: "-0.01em", fontSize: 26 }}>{band}</div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", lineHeight: 1.4 }}>{d.one_line}</div>
            <div style={{ fontSize: 12, color: "rgba(255,255,255,.3)", marginTop: 8 }}>{config.role} — {config.level} — {config.company || "General"} — {currentRound.l} — {config.duration_min} min</div>
          </div>
        </div>
        {Object.keys(roundBands).length > 0 && (
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 18 }}>
            {Object.entries(roundBands).map(([k, v]) => { const bs = BAND_STYLE[v] || BAND_STYLE["Not Ready"]; return (
              <div key={k} style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                <span style={{ fontSize: 10, color: "rgba(255,255,255,.4)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".04em" }}>{ROUND_BAND_LABELS[k] || k}</span>
                <span style={{ padding: "3px 12px", borderRadius: 8, background: bs.bg, color: bs.fg, fontFamily: IQ.display, fontWeight: 700, fontSize: 13 }}>{v}</span>
              </div>
            ); })}
          </div>
        )}
      </div>

      <CalibrationBlock cal={cal} />

      <DeliveryBlock delivery={d.delivery || {}} />

      <div className="mba-grid-3" style={{ marginBottom: 16 }}>{Object.entries(ss).map(([k, v]) => {
        const co = v >= 7 ? T.green : v >= 5 ? T.gold : T.red;
        return <div key={k} className={"mba-metric " + (v >= 7 ? "mba-metric-green" : v >= 5 ? "mba-metric-gold" : "mba-metric-red")}><div className="mba-metric-label">{pk(k)}</div><div className="mba-metric-value">{v}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/10</span></div><div className="mba-bar-track"><div className="mba-bar-fill" style={{ width: (v * 10) + "%", background: co }} /></div></div>;
      })}</div>

      <div className="mba-grid-2" style={{ marginBottom: 16 }}>
        <div className="vc" style={{ borderLeft: "3px solid " + T.green }}><div className="vc-h"><span className="vc-t" style={{ color: T.green }}>What went well</span></div><div className="vc-b">{(d.strengths || []).map((s, i) => <div key={i} style={{ fontSize: 13, lineHeight: 1.65, marginBottom: 8, paddingLeft: 14, borderLeft: "2px solid " + T.green }}>{s}</div>)}</div></div>
        <div className="vc" style={{ borderLeft: "3px solid " + T.gold }}><div className="vc-h"><span className="vc-t" style={{ color: "#7a5e00" }}>Where to improve</span></div><div className="vc-b">{(d.gaps || []).map((g, i) => <div key={i} style={{ marginBottom: 12 }}><div style={{ fontSize: 13, lineHeight: 1.65, paddingLeft: 14, borderLeft: "2px solid " + T.gold }}>{g.gap}</div><div style={{ fontSize: 12, color: T.navy, fontWeight: 700, marginTop: 4, paddingLeft: 14 }}>Study: {g.upskillizeCourse}</div></div>)}</div></div>
      </div>

      {d.star_breakdown?.length > 0 && <div className="vc" style={{ marginBottom: 16 }}><div className="vc-h"><span className="vc-t">Answer-by-answer analysis (STAR)</span></div><div className="vc-b">{d.star_breakdown.map((q, i) => <div key={i} style={{ marginBottom: 16, paddingBottom: 14, borderBottom: i < d.star_breakdown.length - 1 ? "1px solid " + T.border : "none" }}><div style={{ fontSize: 13, fontWeight: 700, color: T.navy, marginBottom: 8 }}>{q.question}</div><div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>{["situation","task","action","result"].map(key => { const val = q[key] || 0; return <span key={key} className={"mba-pill " + (val >= 2 ? "mba-pill-pass" : val === 1 ? "mba-pill-warn" : "mba-pill-fail")}>{key[0].toUpperCase()} {val}/2</span>; })}</div><div style={{ fontSize: 12, color: T.muted, fontStyle: "italic" }}>{q.note}</div></div>)}</div></div>}

      {d.interviewer_thoughts?.length > 0 && <div className="vc" style={{ marginBottom: 16, borderLeft: "3px solid " + T.navy }}><div className="vc-h"><span className="vc-t">What the interviewer was thinking</span></div><div className="vc-b">{d.interviewer_thoughts.map((t, i) => <div key={i} style={{ marginBottom: 12 }}><div style={{ fontSize: 11, color: T.subtle, textTransform: "uppercase" }}>Re: {t.answer}</div><div style={{ fontSize: 13, fontStyle: "italic", marginTop: 2, paddingLeft: 12, borderLeft: "2px solid " + T.navy }}>"{t.thought}"</div></div>)}</div></div>}

      <div className="vc" style={{ marginBottom: 16 }}><div className="vc-h"><span className="vc-t">Your 7-day action plan</span></div><div className="vc-b">{(d.plan || []).map((p, i) => <div key={i} style={{ display: "flex", gap: 12, marginBottom: 10 }}><div style={{ width: 26, height: 26, borderRadius: 6, flexShrink: 0, background: T.bg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, color: T.navy, border: "1px solid " + T.border }}>{i + 1}</div><div style={{ fontSize: 13, lineHeight: 1.6, paddingTop: 3 }}>{p.replace(/^Day \d:\s*/, "")}</div></div>)}</div></div>

      <div style={{ background: T.navy, borderRadius: 10, padding: "18px 24px", marginBottom: 20 }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "rgba(255,255,255,.4)", marginBottom: 6 }}>Before your next mock</div>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#fff", lineHeight: 1.5 }}>{d.next_focus}</div>
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <button onClick={onRestart} className="vbtn">Start Another Mock</button>
        <button onClick={onViewHistory} className="vbtn" style={{ background: T.white, color: T.navy, border: "1.5px solid " + T.border }}>View History</button>
      </div>
    </div>
  );
}

function HistoryScreen({ onPickSession, onStartNew }) {
  const [items, setItems] = useState(null);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("all");

  useEffect(() => {
    (async () => {
      try {
        const [h, s] = await Promise.all([fetchHistory(100, 0), fetchStats()]);
        setItems(h.sessions); setStats(s);
      } catch (e) { setError(e.message); }
    })();
  }, []);

  if (error) return <div style={{ padding: 40, textAlign: "center", fontFamily: T.font }}><div style={{ color: T.red, marginBottom: 12 }}>{error}</div><button onClick={onStartNew} className="mba-btn-primary">Back to setup</button></div>;
  if (!items) return <div style={{ textAlign: "center", padding: 80, fontFamily: T.font }}><div className="mba-spinner" style={{ margin: "0 auto 14px" }} /><div style={{ color: T.muted }}>Loading your history...</div></div>;

  const filtered = tab === "all" ? items
    : tab === "completed" ? items.filter(i => i.status === "completed")
    : tab === "in_progress" ? items.filter(i => i.status === "active")
    : items.filter(i => i.completion_type === "abandoned");

  const summary = stats?.summary || {};
  const totalMinutes = Math.round((summary.total_seconds || 0) / 60);

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "24px 28px" }}>
      <div style={{ background: T.navy, borderRadius: 12, padding: "22px 28px", marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ color: "#fff", fontWeight: 800, fontSize: 22, letterSpacing: "-.02em" }}>InterviewIQ History</div>
          <div style={{ color: "rgba(255,255,255,.4)", fontSize: 12, marginTop: 2 }}>Every mock interview, scored and stored.</div>
        </div>
        <button onClick={onStartNew} className="mba-btn-primary" style={{ background: T.gold }}>+ New Mock</button>
      </div>

      <div className="mba-grid-3" style={{ marginBottom: 18 }}>
        <div className="mba-metric mba-metric-green"><div className="mba-metric-label">Total Sessions</div><div className="mba-metric-value">{summary.total_sessions || 0}</div></div>
        <div className="mba-metric mba-metric-gold"><div className="mba-metric-label">Average Score</div><div className="mba-metric-value">{summary.avg_score != null ? Math.round(summary.avg_score) : "—"}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/100</span></div></div>
        <div className="mba-metric mba-metric-green"><div className="mba-metric-label">Best Score</div><div className="mba-metric-value">{summary.best_score ?? "—"}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/100</span></div></div>
        <div className="mba-metric"><div className="mba-metric-label">Completed</div><div className="mba-metric-value" style={{ color: T.green }}>{summary.completed || 0}</div></div>
        <div className="mba-metric"><div className="mba-metric-label">Abandoned</div><div className="mba-metric-value" style={{ color: T.red }}>{summary.abandoned || 0}</div></div>
        <div className="mba-metric"><div className="mba-metric-label">Total Practice Time</div><div className="mba-metric-value">{totalMinutes}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}> min</span></div></div>
      </div>

      {stats?.by_role?.length > 0 && (
        <div className="vc" style={{ marginBottom: 16 }}>
          <div className="vc-h"><span className="vc-t">Average score by role</span></div>
          <div className="vc-b">
            {stats.by_role.map((r, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: i < stats.by_role.length - 1 ? "1px solid " + T.border : "none" }}>
                <div style={{ flex: 1, fontSize: 13, color: T.navy, fontWeight: 600 }}>{r.role}</div>
                <div style={{ fontSize: 11, color: T.subtle }}>{r.n} session{r.n === 1 ? "" : "s"}</div>
                <div style={{ width: 60, textAlign: "right", fontSize: 13, fontWeight: 700, color: scoreColor(r.avg_score) }}>{r.avg_score != null ? Math.round(r.avg_score) : "—"}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="iq-tabs">
        <button className={"iq-tab" + (tab === "all" ? " iq-tab-on" : "")} onClick={() => setTab("all")}>All ({items.length})</button>
        <button className={"iq-tab" + (tab === "completed" ? " iq-tab-on" : "")} onClick={() => setTab("completed")}>Completed</button>
        <button className={"iq-tab" + (tab === "in_progress" ? " iq-tab-on" : "")} onClick={() => setTab("in_progress")}>In progress</button>
        <button className={"iq-tab" + (tab === "abandoned" ? " iq-tab-on" : "")} onClick={() => setTab("abandoned")}>Abandoned</button>
      </div>

      {filtered.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40, color: T.muted, fontSize: 14 }}>No sessions in this category yet.</div>
      ) : filtered.map(s => {
        const tag = completionLabel(s.status, s.completion_type);
        return (
          <div key={s.session_id} className="iq-hist-row" onClick={() => onPickSession(s.session_id)}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span className="iq-pill" style={{ background: T.bg, color: T.navy }}>{s.round_label || s.round || "Full"}</span>
                <span className="iq-pill" style={{ background: tag.bg, color: tag.fg }}>{tag.label}</span>
                <span style={{ fontSize: 11, color: T.subtle }}>{fmtDate(s.started_at)}</span>
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: T.navy }}>{s.role} {s.company ? `— ${s.company}` : ""}</div>
              <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>
                {s.level} · {s.difficulty} · {s.mode === "coach" ? "Coach" : "Interview"} · planned {s.planned_duration_min} min · actual {fmtDuration(s.actual_duration_seconds)} · {s.user_message_count} answer{s.user_message_count === 1 ? "" : "s"}
              </div>
              {s.one_line && <div style={{ fontSize: 12, color: T.muted, marginTop: 6, fontStyle: "italic" }}>"{s.one_line}"</div>}
            </div>
            <div style={{ textAlign: "right", minWidth: 80 }}>
              {s.overall != null
                ? <><div style={{ fontSize: 28, fontWeight: 800, color: scoreColor(s.overall) }}>{s.overall}</div><div style={{ fontSize: 10, color: T.subtle, fontWeight: 600 }}>/ 100</div></>
                : <div style={{ fontSize: 12, color: T.subtle }}>Not scored</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function HistoryDetail({ sessionId, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => { (async () => { try { setData(await fetchHistoryDetail(sessionId)); } catch (e) { setError(e.message); } })(); }, [sessionId]);

  if (error) return <div style={{ padding: 40, fontFamily: T.font }}><button onClick={onBack} className="mba-btn-primary" style={{ marginBottom: 16 }}>← Back</button><div style={{ color: T.red }}>{error}</div></div>;
  if (!data) return <div style={{ textAlign: "center", padding: 80, fontFamily: T.font }}><div className="mba-spinner" style={{ margin: "0 auto 14px" }} /><div style={{ color: T.muted }}>Loading session...</div></div>;

  const s = data.session;
  const d = data.debrief || {};
  const tag = completionLabel(s.status, s.completion_type);
  const ss = d.subScores || {};

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "24px 28px" }}>
      <button onClick={onBack} style={{ background: "none", border: "none", color: T.navy, fontWeight: 700, fontSize: 13, cursor: "pointer", padding: 0, marginBottom: 14, fontFamily: T.font }}>← Back to history</button>

      <div style={{ background: T.navy, borderRadius: 12, padding: "22px 28px", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <span className="iq-pill" style={{ background: "rgba(184,150,11,.2)", color: T.gold }}>{s.round_label || s.round || "Full"}</span>
          <span className="iq-pill" style={{ background: tag.bg, color: tag.fg }}>{tag.label}</span>
        </div>
        <div style={{ color: "#fff", fontSize: 20, fontWeight: 800 }}>{s.role} {s.company ? `— ${s.company}` : ""}</div>
        <div style={{ color: "rgba(255,255,255,.5)", fontSize: 12, marginTop: 6 }}>
          {fmtDate(s.started_at)} · {s.level} · {s.difficulty} · planned {s.planned_duration_min} min · actual {fmtDuration(s.actual_duration_seconds)} · {s.user_message_count} answer{s.user_message_count === 1 ? "" : "s"}, {s.assistant_message_count} question{s.assistant_message_count === 1 ? "" : "s"}
        </div>
      </div>

      {s.overall != null && (
        <>
          <div className="mba-grid-3" style={{ marginBottom: 16 }}>
            <div className="mba-metric mba-metric-gold"><div className="mba-metric-label">Overall</div><div className="mba-metric-value" style={{ color: scoreColor(s.overall) }}>{s.overall}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/100</span></div>{s.one_line && <div style={{ fontSize: 12, color: T.muted, marginTop: 6, fontStyle: "italic" }}>"{s.one_line}"</div>}</div>
            {Object.entries(ss).slice(0, 2).map(([k, v]) => (
              <div key={k} className="mba-metric"><div className="mba-metric-label">{k}</div><div className="mba-metric-value">{v}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/10</span></div></div>
            ))}
          </div>

          {Object.keys(ss).length > 2 && (
            <div className="mba-grid-3" style={{ marginBottom: 16 }}>
              {Object.entries(ss).slice(2).map(([k, v]) => (
                <div key={k} className="mba-metric"><div className="mba-metric-label">{k}</div><div className="mba-metric-value">{v}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/10</span></div></div>
              ))}
            </div>
          )}

          {(d.strengths?.length > 0 || d.gaps?.length > 0) && (
            <div className="mba-grid-2" style={{ marginBottom: 16 }}>
              {d.strengths?.length > 0 && <div className="vc" style={{ borderLeft: "3px solid " + T.green }}><div className="vc-h"><span className="vc-t" style={{ color: T.green }}>What went well</span></div><div className="vc-b">{d.strengths.map((x, i) => <div key={i} style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 6 }}>• {x}</div>)}</div></div>}
              {d.gaps?.length > 0 && <div className="vc" style={{ borderLeft: "3px solid " + T.gold }}><div className="vc-h"><span className="vc-t" style={{ color: "#7a5e00" }}>Where to improve</span></div><div className="vc-b">{d.gaps.map((g, i) => <div key={i} style={{ marginBottom: 8 }}><div style={{ fontSize: 13 }}>{g.gap}</div>{g.upskillizeCourse && <div style={{ fontSize: 11, color: T.navy, fontWeight: 700, marginTop: 3 }}>Study: {g.upskillizeCourse}</div>}</div>)}</div></div>}
            </div>
          )}
        </>
      )}

      <div className="vc" style={{ marginBottom: 16 }}>
        <div className="vc-h"><span className="vc-t">Full transcript ({data.messages.length} messages)</span></div>
        <div className="vc-b" style={{ maxHeight: 500, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
          {data.messages.map((m, i) => {
            const isV = m.role === "assistant";
            return (
              <div key={i} style={{ display: "flex", gap: 10, flexDirection: isV ? "row" : "row-reverse" }}>
                <div style={{ width: 28, height: 28, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: isV ? T.navy : T.border, color: isV ? "#fff" : T.navy, fontWeight: 800, fontSize: 10 }}>{isV ? "IQ" : "You"}</div>
                <div style={{ padding: "10px 14px", borderRadius: isV ? "2px 10px 10px 10px" : "10px 2px 10px 10px", maxWidth: "78%", fontSize: 13, lineHeight: 1.6, background: isV ? T.white : T.navy, color: isV ? T.text : "#fff", border: isV ? "1px solid " + T.border : "none" }}>{isV ? renderMd(m.content) : m.content}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// INT-07: DPDPA "Your data" controls — export + two-step erasure.
function SettingsScreen({ onBack }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(false);

  const download = async () => {
    setBusy(true); setError(null); setMsg(null);
    try {
      const data = await fetchMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "interviewiq-my-data.json";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      setMsg("Your data has been downloaded as a JSON file.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const doDelete = async () => {
    setBusy(true); setError(null); setMsg(null);
    try {
      // Two-step: request a short-lived token, then confirm the deletion with it.
      const req = await requestDataDeletion();
      await confirmDataDeletion(req.confirmation_token);
      clearActiveSession();
      setConfirming(false);
      setMsg("Your data has been deleted and is no longer accessible. You can start fresh any time.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "24px 28px", maxWidth: 720 }}>
      <button onClick={onBack} style={{ background: "none", border: "none", color: T.navy, fontWeight: 700, fontSize: 13, cursor: "pointer", padding: 0, marginBottom: 14, fontFamily: T.font }}>← Back</button>

      <div style={{ background: T.navy, borderRadius: 12, padding: "22px 28px", marginBottom: 16 }}>
        <div style={{ color: "#fff", fontWeight: 800, fontSize: 20 }}>Settings</div>
        <div style={{ color: "rgba(255,255,255,.5)", fontSize: 12, marginTop: 4 }}>Manage the data InterviewIQ holds for you.</div>
      </div>

      <div className="vc" style={{ marginBottom: 16 }}>
        <div className="vc-h"><span className="vc-t">Your data</span></div>
        <div className="vc-b">
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: T.navy, marginBottom: 4 }}>Download my data</div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 10 }}>Get a copy of everything we hold for you — your sessions, transcripts, confidence ratings, debriefs and consents — as a JSON file.</div>
            <button onClick={download} disabled={busy} className="vbtn" style={{ width: "auto", display: "inline-flex", opacity: busy ? 0.6 : 1 }}>Download my data</button>
          </div>

          <div style={{ borderTop: "1px solid " + T.border, paddingTop: 18 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: T.navy, marginBottom: 4 }}>Delete my data</div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 10 }}>This removes all your interviews, transcripts and reports from InterviewIQ. Your data becomes inaccessible immediately and is permanently erased after a short recovery window. This cannot be undone.</div>
            {!confirming ? (
              <button onClick={() => { setConfirming(true); setMsg(null); setError(null); }} disabled={busy} className="vbtn" style={{ width: "auto", display: "inline-flex", background: T.white, color: T.red, border: "1.5px solid " + T.red, opacity: busy ? 0.6 : 1 }}>Delete my data</button>
            ) : (
              <div style={{ padding: "14px 16px", borderRadius: 10, background: T.redSoft, border: "1px solid #f5c6c2" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.red, marginBottom: 4 }}>Are you sure?</div>
                <div style={{ fontSize: 13, color: "#7a2018", lineHeight: 1.6, marginBottom: 12 }}>This permanently deletes all your InterviewIQ data. This action cannot be reversed.</div>
                <div style={{ display: "flex", gap: 10 }}>
                  <button onClick={doDelete} disabled={busy} className="vbtn" style={{ width: "auto", display: "inline-flex", background: T.red }}>Yes, delete everything</button>
                  <button onClick={() => setConfirming(false)} disabled={busy} className="vbtn" style={{ width: "auto", display: "inline-flex", background: T.white, color: T.navy, border: "1.5px solid " + T.border }}>Cancel</button>
                </div>
              </div>
            )}
          </div>

          {msg && <div style={{ marginTop: 14, padding: "12px 16px", borderRadius: 10, background: T.greenSoft, color: T.green, fontSize: 13 }}>{msg}</div>}
          {error && <div style={{ marginTop: 14, padding: "12px 16px", borderRadius: 10, background: T.redSoft, color: T.red, fontSize: 13 }}>{error}</div>}
        </div>
      </div>
    </div>
  );
}

// INT-06: shown on load when a stored session is idle > 30 min.
function ResumePrompt({ config, onResume, onDiscard }) {
  return (
    <div style={{ fontFamily: T.font, maxWidth: 460, margin: "80px auto", padding: "0 20px" }}>
      <div className="vc" style={{ padding: 0 }}>
        <div style={{ background: T.navy, borderRadius: "12px 12px 0 0", padding: "20px 24px" }}>
          <div style={{ color: "#fff", fontWeight: 800, fontSize: 18 }}>You have an unfinished interview</div>
          <div style={{ color: "rgba(255,255,255,.5)", fontSize: 13, marginTop: 4 }}>Resume or start fresh?</div>
        </div>
        <div style={{ padding: "20px 24px" }}>
          <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6, marginBottom: 18 }}>
            {config ? <>{config.role}{config.company ? ` — ${config.company}` : ""} · {config.level} · {config.duration_min} min</> : "A previous session was left open."}
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={onResume} className="vbtn">Resume interview</button>
            <button onClick={onDiscard} className="vbtn" style={{ background: T.white, color: T.navy, border: "1.5px solid " + T.border }}>Start fresh</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [screen, setScreen] = useState("loading");   // INT-06: check for a resumable session first
  const [config, setConfig] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [greeting, setGreeting] = useState("");
  const [greetingAudioUrl, setGreetingAudioUrl] = useState(null);
  const [initialState, setInitialState] = useState(null);
  const [initialMessages, setInitialMessages] = useState(null);
  const [startedAt, setStartedAt] = useState(null);
  const [userName, setUserName] = useState("Candidate");
  const [historyDetailId, setHistoryDetailId] = useState(null);
  const [resumeCfg, setResumeCfg] = useState(null);   // stale-session prompt payload

  useEffect(() => {
    try {
      const token = getToken();
      if (!token) return;
      const p = JSON.parse(atob(token.split(".")[1]));
      if (p.exp && p.exp * 1000 < Date.now()) return;
      setUserName(p.full_name?.split(" ")[0] || p.name?.split(" ")[0] || p.email?.split("@")[0] || "Candidate");
    } catch { /* malformed token, ignore */ }
  }, []);

  // INT-06: on load, restore an in-flight session if one is stored.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = loadActiveSession();
      if (!stored?.session_id) { setScreen("setup"); return; }
      try {
        const st = await fetchSessionState(stored.session_id);
        if (cancelled) return;
        setConfig(stored.config);
        setSessionId(stored.session_id);
        setStartedAt(stored.started_at || null);
        setInitialState(st);
        // Finished (or past the questions) → straight to the debrief.
        if (st.next_action === "done" || st.next_action === "readout" ||
            st.status === "completed" || st.status === "abandoned") {
          setScreen("debrief");
          return;
        }
        // Idle too long → let the learner choose resume vs fresh.
        if (st.stale) { setResumeCfg(stored.config); setScreen("resume"); return; }
        // Active & fresh → drop back into the interview with full history.
        const hist = await fetchSessionMessages(stored.session_id).catch(() => ({ messages: [] }));
        if (cancelled) return;
        setInitialMessages(hist.messages || []);
        setScreen("interview");
      } catch (e) {
        // 404 (session gone) or any error → clear silently and start fresh.
        if (cancelled) return;
        clearActiveSession();
        setScreen("setup");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const restart = () => {
    clearActiveSession();
    setConfig(null); setSessionId(null); setGreeting(""); setGreetingAudioUrl(null); setInitialState(null);
    setInitialMessages(null); setStartedAt(null); setResumeCfg(null); setHistoryDetailId(null);
    setScreen("setup");
  };

  const handleStart = (cfg, id, gr, st, audioUrl) => {
    const now = Date.now();
    setConfig(cfg); setSessionId(id); setGreeting(gr); setGreetingAudioUrl(audioUrl || null); setInitialState(st);
    setInitialMessages(null); setStartedAt(now);
    saveActiveSession(id, cfg, now);   // INT-06: persist the instant the session starts
    setScreen("interview");
  };

  // INT-06: resume a stale session — pull history, then re-enter the interview.
  const doResume = async () => {
    setScreen("loading");
    try {
      const hist = await fetchSessionMessages(sessionId);
      setInitialMessages(hist.messages || []);
      setScreen("interview");
    } catch { clearActiveSession(); restart(); }
  };

  if (screen === "loading") {
    return (
      <>
        <style>{CSS}</style>
        <div style={{ textAlign: "center", padding: "120px 20px", fontFamily: T.font }}>
          <div className="mba-spinner" style={{ margin: "0 auto 14px" }} />
          <div style={{ color: T.muted }}>Loading InterviewIQ...</div>
        </div>
      </>
    );
  }

  return (
    <>
      <style>{CSS}</style>
      {screen !== "interview" && screen !== "resume" && (
        <div style={{ fontFamily: T.font, padding: "16px 32px 8", display: "flex", gap: 14, alignItems: "center", justifyContent: "flex-end" }}>
          {screen === "debrief" && <button className="iq-tab" onClick={restart}>+ New Mock</button>}
          {screen !== "history" && <button className="iq-tab" onClick={() => { setHistoryDetailId(null); setScreen("history"); }}>History</button>}
          {screen !== "settings" && <button className="iq-tab" onClick={() => setScreen("settings")}>Settings</button>}
        </div>
      )}
      {screen === "setup" && <SetupScreen userName={userName} onStart={handleStart} />}
      {screen === "resume" && <ResumePrompt config={resumeCfg} onResume={doResume} onDiscard={restart} />}
      {screen === "interview" && <InterviewScreen config={config} sessionId={sessionId} greeting={greeting} greetingAudioUrl={greetingAudioUrl} initialState={initialState} initialMessages={initialMessages} startedAt={startedAt} onEnd={() => setScreen("debrief")} onRestart={restart} />}
      {screen === "debrief" && <DebriefScreen config={config} sessionId={sessionId} onRestart={restart} onViewHistory={() => { setHistoryDetailId(null); setScreen("history"); }} />}
      {screen === "history" && !historyDetailId && <HistoryScreen onPickSession={(sid) => { setHistoryDetailId(sid); }} onStartNew={restart} />}
      {screen === "history" && historyDetailId && <HistoryDetail sessionId={historyDetailId} onBack={() => setHistoryDetailId(null)} />}
      {screen === "settings" && <SettingsScreen onBack={() => setScreen("setup")} />}
    </>
  );
}