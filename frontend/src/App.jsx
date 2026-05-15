import { useState, useRef, useEffect } from "react";

// ── API plumbing ───────────────────────────────────────────────────────────
const API_URL = import.meta.env.VITE_INTERVIEWIQ_API_URL || "https://upskill25-mock-test.hf.space";
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
    if (res.status === 401) throw new Error("Please log in again to continue.");
    if (res.status === 429) throw new Error(serverMsg || "Daily limit reached. Try again tomorrow.");
    if (res.status >= 500) throw new Error("InterviewIQ is having a hiccup. Please try again.");
    throw new Error(serverMsg || `Request failed (${res.status}).`);
  }
  return res.json();
}

const startSession = (c) => api("/session/start", { method: "POST", body: JSON.stringify(c) });
const sendTurn = (sid, msg) => api("/session/turn", { method: "POST", body: JSON.stringify({ session_id: sid, message: msg }) });
const endSession = (sid) => api("/session/end", { method: "POST", body: JSON.stringify({ session_id: sid }) });
const abandonSession = (sid) => api("/session/abandon", { method: "POST", body: JSON.stringify({ session_id: sid }) }).catch(() => {});
const fetchAlumniPreview = (co, ro) => api("/alumni/preview?company=" + encodeURIComponent(co) + "&role=" + encodeURIComponent(ro));
const fetchHistory = (limit = 50, offset = 0) => api(`/user/history?limit=${limit}&offset=${offset}`);
const fetchHistoryDetail = (sid) => api(`/user/history/${encodeURIComponent(sid)}`);
const fetchStats = () => api("/user/stats");

// ── Theme ─────────────────────────────────────────────────────────────────
const T = {
  navy: "#1a2744", navyLight: "#2c3e6b", navyDeep: "#0f1a2e", gold: "#b8960b", goldSoft: "#fdf8ed", goldBorder: "#e8d89a",
  white: "#ffffff", bg: "#f7f8fc", border: "#e8e9f0", text: "#1a1a1a", muted: "#72706b", subtle: "#a8a49f",
  green: "#2d6a2d", greenSoft: "#edf7ed", red: "#c0392b", redSoft: "#fdf1f0", blue: "#1e3a6b", blueSoft: "#eef2fb",
  font: "'Plus Jakarta Sans', sans-serif",
};

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
      };
      const r = await startSession(payload);
      onStart({ ...payload, focus: allFocus }, r.session_id, r.greeting);
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

      {error && <div style={{ marginTop: 14, padding: "12px 16px", borderRadius: 10, background: T.redSoft, border: "1px solid #f5c6c2", color: T.red, fontSize: 13 }}>{error}</div>}
      <button className="vbtn" style={{ marginTop: 16 }} onClick={handleStart}>Start Interview</button>
      <p style={{ textAlign: "center", fontSize: 12, color: T.subtle, marginTop: 10 }}>No judgement. No abuse. No matter how you answer.</p>
    </div>
  );
}
function InterviewScreen({ config, sessionId, greeting, onEnd, onRestart }) {
  const [messages, setMessages] = useState([{ role: "assistant", content: greeting }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [secondsLeft, setSecondsLeft] = useState(config.duration_min * 60);
  const [turnCount, setTurnCount] = useState(0);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { if (secondsLeft <= 0 || ended) return; const t = setInterval(() => setSecondsLeft(s => s - 1), 1000); return () => clearInterval(t); }, [secondsLeft, ended]);
  useEffect(() => { if (secondsLeft <= 0 && !ended && !loading) { setEnded(true); if (messages.filter(m => m.role === "user").length > 0) onEnd(); } }, [secondsLeft, ended, loading, messages, onEnd]);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages, loading]);

  const send = async () => {
    const textVal = input.trim(); if (!textVal || loading || ended) return;
    setMessages(m => [...m, { role: "user", content: textVal }]); setInput(""); setLoading(true); setError(null);
    try { const res = await sendTurn(sessionId, textVal); setMessages(m => [...m, { role: "assistant", content: res.reply }]); setTurnCount(res.turn_count); }
    catch (e) { setError(e.message); } finally { setLoading(false); setTimeout(() => inputRef.current?.focus(), 50); }
  };
  const handleKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  const mmss = (s) => Math.floor(Math.max(0, s) / 60) + ":" + String(Math.max(0, s) % 60).padStart(2, "0");

  const stageLabels = ["Warm-up", "About you", "Deep-dive", "Role Q&A", "Pressure", "Your turn", "Wrap-up"];
  const stage = Math.min(7, Math.max(1, Math.ceil((turnCount + 1) / 2)));
  const uc = messages.filter(m => m.role === "user").length;
  const currentRound = ROUNDS.find(r => r.v === config.round) || ROUNDS[ROUNDS.length - 1];

  const handleEndClick = async () => {
    setEnded(true);
    if (uc > 0) { onEnd(); }
    else { await abandonSession(sessionId); onRestart(); }
  };

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", display: "flex", flexDirection: "column", height: "calc(100vh - 70px)", minHeight: 500 }}>
      <div style={{ background: T.navy, padding: "10px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div>
            <div style={{ color: "#fff", fontWeight: 800, fontSize: 15 }}>InterviewIQ</div>
            <div style={{ color: "rgba(255,255,255,.35)", fontSize: 11 }}>{config.role} — {config.company || "General"}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 14px", borderRadius: 20, background: "rgba(184,150,11,.2)", border: "1px solid rgba(184,150,11,.4)" }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: T.gold }} />
            <span style={{ fontSize: 12, fontWeight: 700, color: T.gold }}>{currentRound.l}</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 6, background: "rgba(255,255,255,.08)", color: "rgba(255,255,255,.6)" }}>Stage {stage}/7 — {stageLabels[stage - 1]}</span>
          <span style={{ fontSize: 18, fontWeight: 800, color: secondsLeft <= 60 ? "#ff6b6b" : secondsLeft <= 180 ? T.gold : "#fff", fontVariantNumeric: "tabular-nums" }}>{mmss(secondsLeft)}</span>
          <button onClick={handleEndClick} style={{ padding: "6px 16px", borderRadius: 8, border: "1px solid rgba(255,255,255,.15)", background: "rgba(255,255,255,.06)", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "#fff", fontFamily: T.font }}>End</button>
        </div>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "20px 28px", background: T.bg }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {messages.map((m, i) => { const isV = m.role === "assistant"; return (
            <div key={i} style={{ display: "flex", gap: 10, flexDirection: isV ? "row" : "row-reverse", alignItems: "flex-start", animation: "iqFade .3s ease" }}>
              <div style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: isV ? T.navy : T.border, color: isV ? "#fff" : T.navy, fontWeight: 800, fontSize: 11 }}>{isV ? "IQ" : (config.name?.[0]?.toUpperCase() || "Y")}</div>
              <div style={{ padding: "12px 16px", borderRadius: isV ? "2px 12px 12px 12px" : "12px 2px 12px 12px", maxWidth: "78%", fontSize: 14, lineHeight: 1.65, background: isV ? T.white : T.navy, color: isV ? T.text : "#fff", border: isV ? "1px solid " + T.border : "none", fontFamily: T.font }}>{isV ? renderMd(m.content) : m.content}</div>
            </div>); })}
          {loading && <div style={{ display: "flex", gap: 10 }}><div style={{ width: 32, height: 32, borderRadius: "50%", background: T.navy, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ color: "#fff", fontWeight: 800, fontSize: 11 }}>IQ</span></div><div style={{ padding: "14px 18px", borderRadius: "2px 12px 12px 12px", background: T.white, border: "1px solid " + T.border }}><div style={{ display: "flex", gap: 5 }}>{[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: T.subtle, animation: "iqPulse 1.2s ease-in-out infinite", animationDelay: i * 0.15 + "s" }} />)}</div></div></div>}
          {error && <div style={{ padding: "10px 14px", borderRadius: 8, background: T.redSoft, color: T.red, fontSize: 13 }}>{error}</div>}
          {secondsLeft <= 0 && <div style={{ padding: "14px 18px", borderRadius: 8, background: T.bg, border: "1px solid " + T.border, textAlign: "center", fontSize: 14, color: T.muted }}>{uc > 0 ? <span style={{ fontWeight: 700 }}>Time is up. Generating your report...</span> : <div><div style={{ fontWeight: 700, marginBottom: 8 }}>Time is up. No answers given.</div><button onClick={onRestart} className="vbtn" style={{ width: "auto", display: "inline-flex", fontSize: 13, padding: "8px 20px" }}>Try Again</button></div>}</div>}
          {ended && uc === 0 && secondsLeft > 0 && <div style={{ padding: "14px 18px", borderRadius: 8, background: T.bg, border: "1px solid " + T.border, textAlign: "center" }}><div style={{ fontWeight: 700, marginBottom: 8, color: T.muted }}>Session ended.</div><button onClick={onRestart} className="vbtn" style={{ width: "auto", display: "inline-flex", fontSize: 13, padding: "8px 20px" }}>Start New Session</button></div>}
        </div>
      </div>

      <div style={{ background: T.white, borderTop: "1px solid " + T.border, padding: "14px 28px", flexShrink: 0 }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", gap: 10, alignItems: "flex-end" }}>
          <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value.slice(0, 4000))} onKeyDown={handleKey} rows={1} maxLength={4000} placeholder={ended ? "Interview ended" : "Type your answer..."} disabled={loading || ended} className="vi" style={{ flex: 1, resize: "none", minHeight: 44, maxHeight: 140, borderRadius: 10 }} />
          <button onClick={send} disabled={loading || !input.trim() || ended} className="mba-btn-primary" style={{ padding: "10px 22px", fontSize: 14, opacity: loading || !input.trim() || ended ? 0.5 : 1 }}>Send</button>
        </div>
        <div style={{ fontSize: 11, color: T.subtle, marginTop: 6, maxWidth: 700, margin: "6px auto 0" }}>Enter to send — Shift+Enter for new line</div>
      </div>
    </div>
  );
}

function DebriefScreen({ config, sessionId, onRestart, onViewHistory }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { (async () => { try { const r = await endSession(sessionId); if (r.overall <= 15) { r.one_line = "Session ended before answering. Start another when ready."; r.next_focus = "Prepare your introduction, pick a role, and try again."; } setD(r); } catch (e) { setError(e.message); } })(); }, [sessionId]);

  if (error) return <div className="vc" style={{ padding: 28, textAlign: "center" }}><div style={{ fontSize: 16, fontWeight: 700, color: T.navy, marginBottom: 8 }}>Could not generate report</div><div style={{ fontSize: 13, color: T.muted, marginBottom: 20 }}>{error}</div><button onClick={onRestart} className="mba-btn-primary">Start new session</button></div>;
  if (!d) return <div style={{ textAlign: "center", padding: "80px 20px" }}><div className="mba-spinner" style={{ margin: "0 auto 16px" }} /><div style={{ fontSize: 16, fontWeight: 700, color: T.navy }}>Analyzing your interview...</div><div style={{ fontSize: 13, color: T.subtle, marginTop: 4 }}>Scoring each response against the STAR framework.</div></div>;

  const score = d.overall || 0;
  const selChance = score >= 85 ? "Very High (85%+)" : score >= 70 ? "Good (60-75%)" : score >= 55 ? "Moderate (35-50%)" : score >= 40 ? "Low (15-30%)" : "Needs Work (<15%)";
  const ss = d.sub_scores || {};
  const pk = (k) => ({ communication:"Communication",roleKnowledge:"Role Knowledge",clarity:"Clarity",confidence:"Confidence",structure:"Structure",problemSolving:"Problem Solving" })[k] || k;
  const currentRound = ROUNDS.find(r => r.v === config.round) || ROUNDS[ROUNDS.length - 1];

  return (
    <div style={{ fontFamily: T.font, margin: "-24px -28px", padding: "24px 28px" }}>
      <div style={{ background: T.navy, borderRadius: 12, padding: "28px 32px", marginBottom: 16, display: "flex", alignItems: "center", gap: 28 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 96, height: 96, borderRadius: "50%", border: "3px solid " + (score >= 70 ? "rgba(45,106,45,.5)" : score >= 50 ? "rgba(184,150,11,.5)" : "rgba(192,57,43,.5)"), display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(255,255,255,.05)" }}>
            <div><div style={{ fontSize: 34, fontWeight: 800, color: "#fff", lineHeight: 1 }}>{score}</div><div style={{ fontSize: 11, color: "rgba(255,255,255,.45)" }}>/100</div></div>
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "rgba(255,255,255,.3)" }}>Performance Report</div>
            <div style={{ padding: "3px 10px", borderRadius: 10, background: "rgba(184,150,11,.2)", border: "1px solid rgba(184,150,11,.3)", fontSize: 10, fontWeight: 700, color: T.gold }}>{currentRound.l}</div>
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "#fff", lineHeight: 1.4, marginBottom: 10 }}>{d.one_line}</div>
          <div style={{ display: "inline-block", padding: "5px 14px", borderRadius: 6, background: "rgba(255,255,255,.08)", fontSize: 13, fontWeight: 700, color: "#fff" }}>Selection chances: {selChance}</div>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,.3)", marginTop: 8 }}>{config.role} — {config.level} — {config.company || "General"} — {currentRound.l} — {config.duration_min} min</div>
        </div>
      </div>

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

export default function App() {
  const [screen, setScreen] = useState("setup");
  const [config, setConfig] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [greeting, setGreeting] = useState("");
  const [userName, setUserName] = useState("Candidate");
  const [historyDetailId, setHistoryDetailId] = useState(null);

  useEffect(() => {
    try {
      const token = getToken();
      if (!token) return;
      const p = JSON.parse(atob(token.split(".")[1]));
      if (p.exp && p.exp * 1000 < Date.now()) return;
      setUserName(p.full_name?.split(" ")[0] || p.name?.split(" ")[0] || p.email?.split("@")[0] || "Candidate");
    } catch { /* malformed token, ignore */ }
  }, []);

  const restart = () => { setConfig(null); setSessionId(null); setGreeting(""); setHistoryDetailId(null); setScreen("setup"); };

  return (
    <>
      <style>{CSS}</style>
      {screen !== "interview" && (
        <div style={{ fontFamily: T.font, padding: "16px 32px 8", display: "flex", gap: 14, alignItems: "center", justifyContent: "flex-end" }}>
          {screen === "debrief" && <button className="iq-tab" onClick={restart}>+ New Mock</button>}
          {screen !== "history" && <button className="iq-tab" onClick={() => { setHistoryDetailId(null); setScreen("history"); }}>History</button>}
        </div>
      )}
      {screen === "setup" && <SetupScreen userName={userName} onStart={(cfg, id, gr) => { setConfig(cfg); setSessionId(id); setGreeting(gr); setScreen("interview"); }} />}
      {screen === "interview" && <InterviewScreen config={config} sessionId={sessionId} greeting={greeting} onEnd={() => setScreen("debrief")} onRestart={restart} />}
      {screen === "debrief" && <DebriefScreen config={config} sessionId={sessionId} onRestart={restart} onViewHistory={() => { setHistoryDetailId(null); setScreen("history"); }} />}
      {screen === "history" && !historyDetailId && <HistoryScreen onPickSession={(sid) => { setHistoryDetailId(sid); }} onStartNew={restart} />}
      {screen === "history" && historyDetailId && <HistoryDetail sessionId={historyDetailId} onBack={() => setHistoryDetailId(null)} />}
    </>
  );
}