import { useState, useRef, useEffect } from "react";

const API_URL = "https://upskill25-mock-test.hf.space";
function authHeaders() { const t = localStorage.getItem("upskillize_token") || localStorage.getItem("token"); return t ? { Authorization: "Bearer " + t } : {}; }
async function api(path, opts = {}) {
  const res = await fetch(API_URL + path, { ...opts, headers: { "Content-Type": "application/json", ...authHeaders(), ...(opts.headers || {}) } });
  if (!res.ok) throw new Error(res.status + ": " + (await res.text()).slice(0, 200));
  return res.json();
}
const startSession = (c) => api("/session/start", { method: "POST", body: JSON.stringify(c) });
const sendTurn = (sid, msg) => api("/session/turn", { method: "POST", body: JSON.stringify({ session_id: sid, message: msg }) });
const endSession = (sid) => api("/session/end", { method: "POST", body: JSON.stringify({ session_id: sid }) });
const fetchAlumniPreview = (co, ro) => api("/alumni/preview?company=" + encodeURIComponent(co) + "&role=" + encodeURIComponent(ro));

// ── Markdown ──
function renderMd(text) {
  if (!text) return null;
  return text.split("\n").map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={i} style={{ height: 6 }} />;
    if (/^[-*]\s/.test(t)) return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4, paddingLeft: 4 }}><span style={{ color: "#b8960b", fontWeight: 700 }}>{"\u2022"}</span><span>{fmt(t.replace(/^[-*]\s+/, ""))}</span></div>;
    const nm = t.match(/^(\d+)[.)]\s+(.*)/);
    if (nm) return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4, paddingLeft: 4 }}><span style={{ color: "#a8a49f", fontWeight: 600, minWidth: 18 }}>{nm[1]}.</span><span>{fmt(nm[2])}</span></div>;
    return <p key={i} style={{ margin: "0 0 6px" }}>{fmt(t)}</p>;
  });
}
function fmt(text) {
  const parts = []; const rx = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let last = 0, m, k = 0;
  while ((m = rx.exec(text)) !== null) {
    if (m.index > last) parts.push(<span key={k++}>{text.slice(last, m.index)}</span>);
    if (m[2]) parts.push(<strong key={k++}>{m[2]}</strong>);
    else if (m[3]) parts.push(<em key={k++}>{m[3]}</em>);
    else if (m[4]) parts.push(<code key={k++} style={{ background: "rgba(0,0,0,0.06)", padding: "1px 5px", borderRadius: 4, fontSize: "0.9em" }}>{m[4]}</code>);
    last = rx.lastIndex;
  }
  if (last < text.length) parts.push(<span key={k++}>{text.slice(last)}</span>);
  return parts.length > 0 ? parts : text;
}

// ── Design Tokens (matching LMS) ──
const T = {
  navy: "#1a2744", navyLight: "#2c3e6b", gold: "#b8960b", goldSoft: "#fdf8ed", goldBorder: "#e8d89a",
  white: "#ffffff", bg: "#f7f8fc", border: "#e8e9f0", text: "#1a1a1a", muted: "#72706b", subtle: "#a8a49f",
  green: "#2d6a2d", greenSoft: "#edf7ed", red: "#c0392b", redSoft: "#fdf1f0", blue: "#1e3a6b", blueSoft: "#eef2fb",
  font: "'Plus Jakarta Sans', sans-serif",
};

const ROLES = ["Software Engineer (SDE)", "Frontend Developer", "Backend Developer", "Full-stack Developer", "Data Analyst", "Data Scientist", "Machine Learning Engineer", "Product Manager", "Business Analyst", "Digital Marketing", "UX / UI Designer", "HR / Recruiter", "Other"];
const LEVELS = ["Fresher", "1-3 years", "3+ years", "MBA", "Career switcher"];
const COMPANIES = [{ value: "", label: "General (mid-tier product)" }, { value: "TCS", label: "TCS / Infosys / Wipro" }, { value: "Amazon", label: "Amazon" }, { value: "Google", label: "Google / Meta / Microsoft" }, { value: "Startup", label: "Product startup" }, { value: "Consulting", label: "Consulting / Banking" }];
const DURATIONS = [{ v: 10, l: "10 min" }, { v: 20, l: "20 min" }, { v: 30, l: "30 min" }, { v: 45, l: "45 min" }];
const DIFFICULTIES = [{ v: "Easy", l: "Easy", d: "Warm-up pace", icon: "\u2615" }, { v: "Realistic", l: "Realistic", d: "Matches real bar", icon: "\ud83c\udfaf" }, { v: "Stretch", l: "Stretch", d: "Tough + curveball", icon: "\ud83d\udd25" }];
const MODES = [{ v: "interview", l: "Interview mode", d: "Feedback at end only", icon: "\ud83c\udfa4" }, { v: "coach", l: "Coach mode", d: "Feedback after each answer", icon: "\ud83d\udcac" }];
const FOCUS_OPTIONS = ["Communication", "Technical depth", "Confidence", "Structure (STAR)", "Project storytelling", "Salary negotiation"];

// ── Shared ──
function Chip({ active, onClick, children }) {
  return <button onClick={onClick} style={{ padding: "8px 18px", borderRadius: 20, fontSize: 13, fontWeight: active ? 700 : 500, border: active ? "none" : "1.5px solid " + T.border, cursor: "pointer", background: active ? T.navy : T.white, color: active ? "#fff" : T.text, transition: "all 0.18s", fontFamily: T.font, boxShadow: active ? "0 2px 8px rgba(26,39,68,.2)" : "none" }}>{children}</button>;
}

// =========================================================================
// SETUP SCREEN
// =========================================================================
function SetupScreen({ onStart }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState(ROLES[0]);
  const [level, setLevel] = useState(LEVELS[0]);
  const [company, setCompany] = useState("");
  const [duration, setDuration] = useState(20);
  const [difficulty, setDifficulty] = useState("Realistic");
  const [mode, setMode] = useState("interview");
  const [focus, setFocus] = useState([]);
  const [intro, setIntro] = useState("");
  const [alumniCount, setAlumniCount] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const toggleFocus = (f) => setFocus((c) => c.includes(f) ? c.filter((x) => x !== f) : [...c, f]);

  useEffect(() => {
    if (!company || !role) { setAlumniCount(null); return; }
    let x = false;
    fetchAlumniPreview(company, role).then((r) => !x && setAlumniCount(r.count)).catch(() => {});
    return () => { x = true; };
  }, [company, role]);

  const handleStart = async () => {
    setStarting(true); setError(null);
    try {
      const r = await startSession({ name, role, level, company, duration_min: duration, difficulty, mode, focus, intro });
      onStart({ name, role, level, company, duration_min: duration, difficulty, mode, focus, intro }, r.session_id, r.greeting);
    } catch (e) { setError(e.message); setStarting(false); }
  };

  const inputStyle = { width: "100%", padding: "10px 14px", border: "1.5px solid " + T.border, borderRadius: 8, fontSize: 14, outline: "none", boxSizing: "border-box", fontFamily: T.font, transition: "border-color .18s", background: T.white };

  return (
    <div style={{ fontFamily: T.font }}>
      {/* Hero */}
      <div style={{ background: "linear-gradient(135deg, " + T.navy + " 0%, " + T.navyLight + " 100%)", borderRadius: 12, padding: "24px 28px", marginBottom: 20, display: "flex", alignItems: "center", justifyContent: "space-between", boxShadow: "0 4px 14px rgba(26,39,68,.18)" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(184,150,11,.2)", border: "2px solid rgba(184,150,11,.4)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span style={{ color: T.gold, fontWeight: 800, fontSize: 18 }}>V</span>
            </div>
            <div>
              <div style={{ color: "#fff", fontWeight: 800, fontSize: 20 }}>Vyom AI Mock Interview</div>
              <div style={{ color: "rgba(255,255,255,.5)", fontSize: 12 }}>by Upskillize \u2022 Bridging Academia and Industry</div>
            </div>
          </div>
          <p style={{ color: "rgba(255,255,255,.65)", fontSize: 13, marginTop: 4, lineHeight: 1.6 }}>Practice with real interview questions. Get scored. Know your selection chances.</p>
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          {[{ num: "7", label: "Stages" }, { num: "AI", label: "Powered" }, { num: "\u2605", label: "STAR Scored" }].map((s, i) => (
            <div key={i} style={{ textAlign: "center", padding: "10px 14px", background: "rgba(255,255,255,.06)", borderRadius: 10, minWidth: 70 }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: T.gold }}>{s.num}</div>
              <div style={{ fontSize: 10, color: "rgba(255,255,255,.4)", marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Left column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="mba-card"><div className="mba-card-head"><span className="mba-card-title">\ud83d\udc64 Your Details</span></div><div className="mba-card-body">
            <label className="mba-label">Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="First name" style={inputStyle} className="mba-input" />
            <label className="mba-label" style={{ marginTop: 14 }}>Self-introduction <span style={{ fontWeight: 400, color: T.subtle }}>(optional)</span></label>
            <textarea value={intro} onChange={(e) => setIntro(e.target.value)} rows={3} placeholder="e.g. Final-year CS student, built a chat app with Node..." style={{ ...inputStyle, resize: "none", minHeight: 70 }} className="mba-textarea" />
          </div></div>

          <div className="mba-card"><div className="mba-card-head"><span className="mba-card-title">\ud83c\udfaf Target Role</span></div><div className="mba-card-body">
            <label className="mba-label">Job Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)} style={inputStyle} className="mba-select">{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
            <label className="mba-label" style={{ marginTop: 14 }}>Experience Level</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{LEVELS.map((l) => <Chip key={l} active={level === l} onClick={() => setLevel(l)}>{l}</Chip>)}</div>
            <label className="mba-label" style={{ marginTop: 14 }}>Company Style</label>
            <select value={company} onChange={(e) => setCompany(e.target.value)} style={inputStyle} className="mba-select">{COMPANIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select>
            {alumniCount > 0 && <div style={{ marginTop: 10, padding: "10px 14px", borderRadius: 8, background: T.goldSoft, border: "1px solid " + T.goldBorder, fontSize: 13, color: "#5a4500" }}><strong>{alumniCount} real questions</strong> from alumni who interviewed at {company} for {role}.</div>}
          </div></div>
        </div>

        {/* Right column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="mba-card"><div className="mba-card-head"><span className="mba-card-title">\u2699\ufe0f Session Settings</span></div><div className="mba-card-body">
            <label className="mba-label">Duration</label>
            <div style={{ display: "flex", gap: 6 }}>{DURATIONS.map((d) => <Chip key={d.v} active={duration === d.v} onClick={() => setDuration(d.v)}>{d.l}</Chip>)}</div>
            <label className="mba-label" style={{ marginTop: 14 }}>Difficulty</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              {DIFFICULTIES.map((d) => (
                <button key={d.v} onClick={() => setDifficulty(d.v)} style={{ textAlign: "center", padding: "14px 10px", borderRadius: 10, cursor: "pointer", border: difficulty === d.v ? "2px solid " + T.navy : "1.5px solid " + T.border, background: difficulty === d.v ? T.blueSoft : T.white, fontFamily: T.font, transition: "all .18s" }}>
                  <div style={{ fontSize: 20, marginBottom: 4 }}>{d.icon}</div>
                  <div style={{ fontWeight: 700, fontSize: 13, color: T.navy }}>{d.l}</div>
                  <div style={{ fontSize: 11, color: T.subtle, marginTop: 2 }}>{d.d}</div>
                </button>
              ))}
            </div>
            <label className="mba-label" style={{ marginTop: 14 }}>Mode</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {MODES.map((m) => (
                <button key={m.v} onClick={() => setMode(m.v)} style={{ textAlign: "left", padding: "12px 14px", borderRadius: 10, cursor: "pointer", border: mode === m.v ? "2px solid " + T.navy : "1.5px solid " + T.border, background: mode === m.v ? T.blueSoft : T.white, fontFamily: T.font, transition: "all .18s", display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 22 }}>{m.icon}</span>
                  <div><div style={{ fontWeight: 700, fontSize: 13, color: T.navy }}>{m.l}</div><div style={{ fontSize: 11, color: T.subtle, marginTop: 1 }}>{m.d}</div></div>
                </button>
              ))}
            </div>
          </div></div>

          <div className="mba-card"><div className="mba-card-head"><span className="mba-card-title">\ud83d\udccc Focus Areas <span style={{ fontWeight: 400, color: T.subtle }}>(optional)</span></span></div><div className="mba-card-body">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{FOCUS_OPTIONS.map((f) => <Chip key={f} active={focus.includes(f)} onClick={() => toggleFocus(f)}>{f}</Chip>)}</div>
          </div></div>
        </div>
      </div>

      {error && <div className="mba-alert-error" style={{ marginTop: 14 }}>{error}</div>}

      <button onClick={handleStart} disabled={starting} style={{ width: "100%", marginTop: 20, padding: "14px 24px", background: starting ? T.subtle : T.navy, color: "#fff", border: "none", borderRadius: 10, fontSize: 15, fontWeight: 700, cursor: starting ? "not-allowed" : "pointer", fontFamily: T.font, boxShadow: "0 2px 8px rgba(26,39,68,.2)", transition: "all .18s", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
        {starting ? <><span className="mba-spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> Starting...</> : <>\ud83c\udfa4 Start Interview</>}
      </button>
      <p style={{ textAlign: "center", fontSize: 12, color: T.subtle, marginTop: 10 }}>No judgement, no abuse, no matter how you answer.</p>
    </div>
  );
}

// =========================================================================
// INTERVIEW SCREEN
// =========================================================================
function InterviewScreen({ config, sessionId, greeting, onEnd }) {
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
  useEffect(() => { if (secondsLeft <= 0 && !ended && !loading) { setEnded(true); onEnd(); } }, [secondsLeft, ended, loading]);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages, loading]);

  const send = async () => {
    const text = input.trim(); if (!text || loading || ended) return;
    setMessages(m => [...m, { role: "user", content: text }]); setInput(""); setLoading(true); setError(null);
    try { const res = await sendTurn(sessionId, text); setMessages(m => [...m, { role: "assistant", content: res.reply }]); setTurnCount(res.turn_count); }
    catch (e) { setError(e.message); } finally { setLoading(false); setTimeout(() => inputRef.current?.focus(), 50); }
  };
  const handleKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  const mmss = (s) => Math.floor(Math.max(0, s) / 60) + ":" + String(Math.max(0, s) % 60).padStart(2, "0");
  const timerColor = secondsLeft <= 60 ? T.red : secondsLeft <= 180 ? T.gold : T.navy;
  const stageLabels = ["Warm-up", "About you", "Deep-dive", "Role Q&A", "Pressure", "Your turn", "Wrap-up"];
  const stage = Math.min(7, Math.max(1, Math.ceil((turnCount + 1) / 2)));

  return (
    <div style={{ fontFamily: T.font, display: "flex", flexDirection: "column", height: "calc(100vh - 120px)", minHeight: 500 }}>
      {/* Interview header bar */}
      <div style={{ background: T.navy, borderRadius: "12px 12px 0 0", padding: "12px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: "rgba(184,150,11,.2)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ color: T.gold, fontWeight: 800, fontSize: 14 }}>V</span>
          </div>
          <div><div style={{ color: "#fff", fontWeight: 700, fontSize: 14 }}>Vyom Interview</div><div style={{ color: "rgba(255,255,255,.4)", fontSize: 11 }}>{config.role} \u2022 {config.company || "General"}</div></div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 12px", borderRadius: 20, background: "rgba(255,255,255,.1)", color: "rgba(255,255,255,.7)" }}>{stageLabels[stage - 1]}</span>
          <span style={{ fontSize: 18, fontWeight: 800, color: secondsLeft <= 60 ? "#ff6b6b" : secondsLeft <= 180 ? T.gold : "#fff", fontVariantNumeric: "tabular-nums" }}>{mmss(secondsLeft)}</span>
          <button onClick={() => { setEnded(true); onEnd(); }} style={{ padding: "6px 16px", borderRadius: 8, border: "1px solid rgba(255,255,255,.2)", background: "rgba(255,255,255,.08)", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "#fff", fontFamily: T.font }}>End</button>
        </div>
      </div>

      {/* Chat area */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "20px 20px", background: T.bg, borderLeft: "1px solid " + T.border, borderRight: "1px solid " + T.border }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {messages.map((m, i) => {
            const isV = m.role === "assistant";
            return (
              <div key={i} style={{ display: "flex", gap: 10, flexDirection: isV ? "row" : "row-reverse", alignItems: "flex-start" }}>
                <div style={{ width: 34, height: 34, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: isV ? T.navy : T.gold, color: "#fff", fontWeight: 800, fontSize: 13 }}>
                  {isV ? "V" : (config.name?.[0]?.toUpperCase() || "Y")}
                </div>
                <div style={{ padding: "12px 16px", borderRadius: isV ? "2px 14px 14px 14px" : "14px 2px 14px 14px", maxWidth: "78%", fontSize: 14, lineHeight: 1.65, background: isV ? T.white : T.navy, color: isV ? T.text : "#fff", border: isV ? "1px solid " + T.border : "none", boxShadow: "0 1px 4px rgba(26,39,68,.05)", fontFamily: T.font }}>
                  {isV ? renderMd(m.content) : m.content}
                </div>
              </div>
            );
          })}
          {loading && <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}><div style={{ width: 34, height: 34, borderRadius: "50%", background: T.navy, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ color: T.gold, fontWeight: 800, fontSize: 13 }}>V</span></div><div style={{ padding: "14px 18px", borderRadius: "2px 14px 14px 14px", background: T.white, border: "1px solid " + T.border }}><div style={{ display: "flex", gap: 5 }}>{[0, 1, 2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: T.subtle, animation: "vyomPulse 1.2s ease-in-out infinite", animationDelay: i * 0.15 + "s" }} />)}</div></div></div>}
          {error && <div className="mba-alert-error">{error}</div>}
          {secondsLeft <= 0 && <div style={{ padding: "14px 18px", borderRadius: 10, background: T.goldSoft, border: "1px solid " + T.goldBorder, textAlign: "center", fontSize: 14, color: "#5a4500", fontWeight: 700 }}>Time is up! Generating your performance report...</div>}
        </div>
      </div>

      {/* Input area */}
      <div style={{ background: T.white, borderRadius: "0 0 12px 12px", border: "1px solid " + T.border, borderTop: "none", padding: "14px 20px", flexShrink: 0 }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", gap: 10, alignItems: "flex-end" }}>
          <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey} rows={1} placeholder={ended ? "Interview ended" : "Type your answer..."} disabled={loading || ended} className="mba-textarea" style={{ flex: 1, resize: "none", minHeight: 44, maxHeight: 140, borderRadius: 10 }} />
          <button onClick={send} disabled={loading || !input.trim() || ended} className="mba-btn-primary" style={{ padding: "10px 22px", fontSize: 14, opacity: loading || !input.trim() || ended ? 0.5 : 1 }}>Send</button>
        </div>
        <div style={{ fontSize: 11, color: T.subtle, marginTop: 6, maxWidth: 700, margin: "6px auto 0" }}>Enter to send | Shift+Enter for new line</div>
      </div>
    </div>
  );
}

// =========================================================================
// DEBRIEF SCREEN
// =========================================================================
function DebriefScreen({ config, sessionId, onRestart }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { (async () => { try { setD(await endSession(sessionId)); } catch (e) { setError(e.message); } })(); }, []);

  if (error) return <div className="mba-card" style={{ padding: 28, textAlign: "center" }}><div style={{ fontSize: 16, fontWeight: 700, color: T.navy, marginBottom: 8 }}>Could not generate report</div><div style={{ fontSize: 13, color: T.muted, marginBottom: 20 }}>{error}</div><button onClick={onRestart} className="mba-btn-primary">Start new session</button></div>;

  if (!d) return <div style={{ textAlign: "center", padding: "60px 20px" }}><div className="mba-spinner" style={{ margin: "0 auto 16px" }} /><div style={{ fontSize: 16, fontWeight: 700, color: T.navy }}>Analyzing your interview...</div><div style={{ fontSize: 13, color: T.subtle, marginTop: 4 }}>Reading every answer, scoring each response.</div></div>;

  const score = d.overall || 0;
  const selChance = score >= 85 ? "Very High (85%+)" : score >= 70 ? "Good (60-75%)" : score >= 55 ? "Moderate (35-50%)" : score >= 40 ? "Low (15-30%)" : "Needs Work (<15%)";
  const selColor = score >= 85 ? T.green : score >= 70 ? T.blue : score >= 55 ? T.gold : T.red;
  const scoreColor = score >= 70 ? T.green : score >= 50 ? T.gold : T.red;
  const ss = d.sub_scores || {};

  return (
    <div style={{ fontFamily: T.font }}>
      {/* Score hero */}
      <div style={{ background: "linear-gradient(135deg, " + T.navy + " 0%, " + T.navyLight + " 100%)", borderRadius: 12, padding: "28px 32px", marginBottom: 16, display: "flex", alignItems: "center", gap: 28, boxShadow: "0 4px 14px rgba(26,39,68,.18)" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 100, height: 100, borderRadius: "50%", border: "4px solid " + (score >= 70 ? "rgba(45,106,45,.5)" : score >= 50 ? "rgba(184,150,11,.5)" : "rgba(192,57,43,.5)"), display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(255,255,255,.05)" }}>
            <div><div style={{ fontSize: 36, fontWeight: 800, color: "#fff", lineHeight: 1 }}>{score}</div><div style={{ fontSize: 11, color: "rgba(255,255,255,.5)" }}>/100</div></div>
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "rgba(255,255,255,.4)", marginBottom: 6 }}>Performance Report</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#fff", lineHeight: 1.4, marginBottom: 10 }}>{d.one_line}</div>
          <div style={{ display: "inline-block", padding: "5px 14px", borderRadius: 6, background: "rgba(255,255,255,.1)", border: "1px solid rgba(255,255,255,.15)", fontSize: 13, fontWeight: 700, color: T.gold }}>Selection chances: {selChance}</div>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,.4)", marginTop: 8 }}>{config.role} \u2022 {config.level} \u2022 {config.company || "General"} \u2022 {config.duration_min} min</div>
        </div>
      </div>

      {/* Sub-scores */}
      <div className="mba-grid-3" style={{ marginBottom: 16 }}>
        {Object.entries(ss).map(([k, v]) => {
          const co = v >= 7 ? T.green : v >= 5 ? T.gold : T.red;
          const accent = v >= 7 ? "mba-metric-green" : v >= 5 ? "mba-metric-gold" : "mba-metric-red";
          return <div key={k} className={"mba-metric " + accent}><div className="mba-metric-label">{prettyKey(k)}</div><div className="mba-metric-value">{v}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle }}>/10</span></div><div className="mba-bar-track"><div className="mba-bar-fill" style={{ width: (v * 10) + "%", background: co }} /></div></div>;
        })}
      </div>

      {/* Strengths + Gaps */}
      <div className="mba-grid-2" style={{ marginBottom: 16 }}>
        <div className="mba-card" style={{ borderLeft: "3px solid " + T.green }}><div className="mba-card-head"><span className="mba-card-title" style={{ color: T.green }}>\u2705 What went well</span></div><div className="mba-card-body">
          {(d.strengths || []).map((s, i) => <div key={i} style={{ fontSize: 13, lineHeight: 1.65, marginBottom: 8, paddingLeft: 14, borderLeft: "2px solid " + T.green }}>{s}</div>)}
        </div></div>
        <div className="mba-card" style={{ borderLeft: "3px solid " + T.gold }}><div className="mba-card-head"><span className="mba-card-title" style={{ color: "#7a5e00" }}>\u26a0\ufe0f Where to improve</span></div><div className="mba-card-body">
          {(d.gaps || []).map((g, i) => <div key={i} style={{ marginBottom: 12 }}><div style={{ fontSize: 13, lineHeight: 1.65, paddingLeft: 14, borderLeft: "2px solid " + T.gold }}>{g.gap}</div><div style={{ fontSize: 12, color: T.navy, fontWeight: 700, marginTop: 4, paddingLeft: 14 }}>\u2192 Study: {g.upskillizeCourse}</div></div>)}
        </div></div>
      </div>

      {/* STAR */}
      {d.star_breakdown?.length > 0 && <div className="mba-card" style={{ marginBottom: 16 }}><div className="mba-card-head"><span className="mba-card-title">Answer-by-answer analysis (STAR)</span></div><div className="mba-card-body">
        {d.star_breakdown.map((q, i) => <div key={i} style={{ marginBottom: 16, paddingBottom: 14, borderBottom: i < d.star_breakdown.length - 1 ? "1px solid " + T.border : "none" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: T.navy, marginBottom: 8 }}>{q.question}</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
            {["situation", "task", "action", "result"].map(key => { const val = q[key] || 0; return <span key={key} className={"mba-pill " + (val >= 2 ? "mba-pill-pass" : val === 1 ? "mba-pill-warn" : "mba-pill-fail")}>{key[0].toUpperCase()} {val}/2</span>; })}
          </div>
          <div style={{ fontSize: 12, color: T.muted, fontStyle: "italic" }}>{q.note}</div>
        </div>)}
      </div></div>}

      {/* Interviewer thoughts */}
      {d.interviewer_thoughts?.length > 0 && <div className="mba-card" style={{ marginBottom: 16, borderLeft: "3px solid " + T.gold }}><div className="mba-card-head"><span className="mba-card-title">\ud83e\udde0 What the interviewer was really thinking</span></div><div className="mba-card-body">
        {d.interviewer_thoughts.map((t, i) => <div key={i} style={{ marginBottom: 12 }}><div style={{ fontSize: 11, color: T.subtle, textTransform: "uppercase", letterSpacing: ".04em" }}>Re: {t.answer}</div><div style={{ fontSize: 13, fontStyle: "italic", marginTop: 2, paddingLeft: 12, borderLeft: "2px solid " + T.gold }}>"{t.thought}"</div></div>)}
      </div></div>}

      {/* 7-day plan */}
      <div className="mba-card" style={{ marginBottom: 16 }}><div className="mba-card-head"><span className="mba-card-title">\ud83d\udcc5 Your 7-day action plan</span></div><div className="mba-card-body">
        {(d.plan || []).map((p, i) => <div key={i} style={{ display: "flex", gap: 12, marginBottom: 10, alignItems: "flex-start" }}>
          <div style={{ width: 28, height: 28, borderRadius: 8, flexShrink: 0, background: T.blueSoft, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, color: T.navy }}>{i + 1}</div>
          <div style={{ fontSize: 13, lineHeight: 1.6, paddingTop: 4 }}>{p.replace(/^Day \d:\s*/, "")}</div>
        </div>)}
      </div></div>

      {/* Next focus */}
      <div style={{ background: T.navy, borderRadius: 12, padding: "20px 24px", marginBottom: 20 }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: T.gold, marginBottom: 8 }}>Before your next mock</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", lineHeight: 1.5 }}>{d.next_focus}</div>
      </div>

      <button onClick={onRestart} className="mba-btn-primary" style={{ width: "100%", justifyContent: "center", padding: "13px 24px", fontSize: 15 }}>\ud83c\udfa4 Start Another Mock</button>
    </div>
  );
}

function prettyKey(k) { return { communication: "Communication", roleKnowledge: "Role Knowledge", clarity: "Clarity", confidence: "Confidence", structure: "Structure", problemSolving: "Problem Solving" }[k] || k; }

// =========================================================================
// ROOT
// =========================================================================
export default function App() {
  const [screen, setScreen] = useState("setup");
  const [config, setConfig] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [greeting, setGreeting] = useState("");
  return (
    <>
      <style>{[
        "@keyframes vyomPulse { 0%, 100% { opacity: 0.3; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1); } }",
        "@keyframes vyomLoad { 0% { width: 0%; } 50% { width: 70%; } 100% { width: 100%; } }",
      ].join("\\n")}</style>
      {screen === "setup" && <SetupScreen onStart={(cfg, id, gr) => { setConfig(cfg); setSessionId(id); setGreeting(gr); setScreen("interview"); }} />}
      {screen === "interview" && <InterviewScreen config={config} sessionId={sessionId} greeting={greeting} onEnd={() => setScreen("debrief")} />}
      {screen === "debrief" && <DebriefScreen config={config} sessionId={sessionId} onRestart={() => { setConfig(null); setSessionId(null); setGreeting(""); setScreen("setup"); }} />}
    </>
  );
}