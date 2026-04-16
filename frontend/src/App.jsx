import { useState, useRef, useEffect } from "react";

// =========================================================================
// API CLIENT
// =========================================================================
const API_URL = import.meta.env.VITE_API_URL || "";
function authHeaders() {
  const t = localStorage.getItem("upskillize_token");
  return t ? { Authorization: "Bearer " + t } : {};
}
async function api(path, opts = {}) {
  const res = await fetch(API_URL + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(opts.headers || {}) },
  });
  if (!res.ok) throw new Error(res.status + ": " + (await res.text()).slice(0, 200));
  return res.json();
}
const startSession = (c) => api("/session/start", { method: "POST", body: JSON.stringify(c) });
const sendTurn = (sid, msg) => api("/session/turn", { method: "POST", body: JSON.stringify({ session_id: sid, message: msg }) });
const endSession = (sid) => api("/session/end", { method: "POST", body: JSON.stringify({ session_id: sid }) });
const fetchAlumniPreview = (co, ro) => api("/alumni/preview?company=" + encodeURIComponent(co) + "&role=" + encodeURIComponent(ro));

// =========================================================================
// MARKDOWN RENDERER
// =========================================================================
function renderMd(text) {
  if (!text) return null;
  return text.split("\n").map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={i} style={{ height: "6px" }} />;
    if (/^[-*]\s/.test(t)) return <div key={i} style={{ display: "flex", gap: "8px", marginBottom: "4px", paddingLeft: "4px" }}><span style={{ color: "#F59E0B", fontWeight: 700 }}>{"•"}</span><span>{fmt(t.replace(/^[-*]\s+/, ""))}</span></div>;
    const nm = t.match(/^(\d+)[.)]\s+(.*)/);
    if (nm) return <div key={i} style={{ display: "flex", gap: "8px", marginBottom: "4px", paddingLeft: "4px" }}><span style={{ color: "#94a3b8", fontWeight: 600, minWidth: "18px" }}>{nm[1]}.</span><span>{fmt(nm[2])}</span></div>;
    return <p key={i} style={{ margin: "0 0 6px" }}>{fmt(t)}</p>;
  });
}
function fmt(text) {
  const parts = [];
  const rx = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let last = 0, m, k = 0;
  while ((m = rx.exec(text)) !== null) {
    if (m.index > last) parts.push(<span key={k++}>{text.slice(last, m.index)}</span>);
    if (m[2]) parts.push(<strong key={k++}>{m[2]}</strong>);
    else if (m[3]) parts.push(<em key={k++}>{m[3]}</em>);
    else if (m[4]) parts.push(<code key={k++} style={{ background: "rgba(0,0,0,0.06)", padding: "1px 5px", borderRadius: "4px", fontSize: "0.9em" }}>{m[4]}</code>);
    last = rx.lastIndex;
  }
  if (last < text.length) parts.push(<span key={k++}>{text.slice(last)}</span>);
  return parts.length > 0 ? parts : text;
}

// =========================================================================
// CONSTANTS
// =========================================================================
const ROLES = ["Software Engineer (SDE)", "Frontend Developer", "Backend Developer", "Full-stack Developer", "Data Analyst", "Data Scientist", "Machine Learning Engineer", "Product Manager", "Business Analyst", "Digital Marketing", "UX / UI Designer", "HR / Recruiter", "Other"];
const LEVELS = ["Fresher", "1-3 years", "3+ years", "MBA", "Career switcher"];
const COMPANIES = [{ value: "", label: "General (mid-tier product)" }, { value: "TCS", label: "TCS / Infosys / Wipro" }, { value: "Amazon", label: "Amazon" }, { value: "Google", label: "Google / Meta / Microsoft" }, { value: "Startup", label: "Product startup" }, { value: "Consulting", label: "Consulting / Banking" }];
const DURATIONS = [{ v: 10, l: "10 min" }, { v: 20, l: "20 min" }, { v: 30, l: "30 min" }, { v: 45, l: "45 min" }];
const DIFFICULTIES = [{ v: "Easy", l: "Easy", d: "Warm-up pace" }, { v: "Realistic", l: "Realistic", d: "Matches real bar" }, { v: "Stretch", l: "Stretch", d: "Tough + curveball" }];
const MODES = [{ v: "interview", l: "Interview mode", d: "Feedback at end only" }, { v: "coach", l: "Coach mode", d: "Feedback after each answer" }];
const FOCUS_OPTIONS = ["Communication", "Technical depth", "Confidence", "Structure (STAR)", "Project storytelling", "Salary negotiation"];

const C = { primary: "#0F172A", accent: "#F59E0B", accentSoft: "#FEF3C7", bg: "#F8FAFC", card: "#FFFFFF", border: "#E2E8F0", text: "#0F172A", muted: "#64748B", ok: "#059669", okBg: "#ECFDF5", warn: "#D97706", warnBg: "#FFFBEB", bad: "#DC2626", badBg: "#FEF2F2" };
const inputSt = { width: "100%", padding: "10px 14px", border: "1px solid " + C.border, borderRadius: "10px", fontSize: "14px", outline: "none", boxSizing: "border-box", fontFamily: "inherit" };

// =========================================================================
// SHARED COMPONENTS
// =========================================================================
function Logo({ big }) {
  const s = big ? 44 : 36;
  return (<div style={{ display: "flex", alignItems: "center", gap: big ? "12px" : "10px" }}>
    <div style={{ width: s, height: s, borderRadius: "10px", background: C.primary, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ color: C.accent, fontWeight: 700, fontSize: big ? "20px" : "16px" }}>V</span>
    </div>
    <div><div style={{ fontWeight: 700, fontSize: big ? "20px" : "15px", color: C.primary, letterSpacing: "-0.02em" }}>Vyom</div><div style={{ fontSize: "11px", color: C.muted, marginTop: "-2px" }}>by Upskillize</div></div>
  </div>);
}
function Chip({ active, onClick, children }) {
  return <button onClick={onClick} style={{ padding: "7px 16px", borderRadius: "20px", fontSize: "13px", fontWeight: 500, border: active ? "none" : "1px solid " + C.border, cursor: "pointer", background: active ? C.primary : C.card, color: active ? "#fff" : C.text, transition: "all 0.15s" }}>{children}</button>;
}
function Card({ children, style = {} }) {
  return <div style={{ background: C.card, border: "1px solid " + C.border, borderRadius: "16px", ...style }}>{children}</div>;
}

// =========================================================================
// SCREEN 1 - SETUP
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
  return (
    <div style={{ minHeight: "100vh", background: C.bg }}>
      <header style={{ borderBottom: "1px solid " + C.border, background: C.card, padding: "14px 20px" }}>
        <div style={{ maxWidth: "720px", margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Logo /><div style={{ fontSize: "12px", color: C.muted }}>Bridging academia and industry</div>
        </div>
      </header>
      <main style={{ maxWidth: "720px", margin: "0 auto", padding: "32px 20px" }}>
        <h1 style={{ fontSize: "26px", fontWeight: 700, color: C.primary, margin: "0 0 8px", letterSpacing: "-0.02em" }}>Set up your mock interview</h1>
        <p style={{ color: C.muted, fontSize: "14px", margin: "0 0 28px" }}>Takes 30 seconds. Vyom tailors every question to your profile.</p>
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Card style={{ padding: "20px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Your name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="First name" style={inputSt} />
          </Card>
          <Card style={{ padding: "20px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Target role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)} style={{ ...inputSt, background: C.card }}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
            <div style={{ marginTop: "18px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Experience level</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>{LEVELS.map((l) => <Chip key={l} active={level === l} onClick={() => setLevel(l)}>{l}</Chip>)}</div>
            </div>
            <div style={{ marginTop: "18px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Target company style</label>
              <select value={company} onChange={(e) => setCompany(e.target.value)} style={{ ...inputSt, background: C.card }}>{COMPANIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select>
              {alumniCount > 0 && <div style={{ marginTop: "10px", padding: "10px 14px", borderRadius: "10px", background: C.accentSoft, border: "1px solid #FDE68A", fontSize: "13px", color: "#92400E" }}><strong>{alumniCount} real questions</strong> from Upskillize alumni who recently interviewed at {company} for {role}.</div>}
            </div>
          </Card>
          <Card style={{ padding: "20px" }}>
            <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: "200px" }}>
                <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Duration</label>
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>{DURATIONS.map((d) => <Chip key={d.v} active={duration === d.v} onClick={() => setDuration(d.v)}>{d.l}</Chip>)}</div>
              </div>
              <div style={{ flex: 1, minWidth: "200px" }}>
                <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Difficulty</label>
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>{DIFFICULTIES.map((d) => <Chip key={d.v} active={difficulty === d.v} onClick={() => setDifficulty(d.v)}>{d.l}</Chip>)}</div>
              </div>
            </div>
            <div style={{ marginTop: "18px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Session mode</label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                {MODES.map((m) => <button key={m.v} onClick={() => setMode(m.v)} style={{ textAlign: "left", padding: "12px", borderRadius: "10px", cursor: "pointer", border: mode === m.v ? "2px solid " + C.primary : "1px solid " + C.border, background: mode === m.v ? "#EEF2FF" : C.card }}><div style={{ fontWeight: 600, fontSize: "13px", color: C.text }}>{m.l}</div><div style={{ fontSize: "12px", color: C.muted, marginTop: "2px" }}>{m.d}</div></button>)}
              </div>
            </div>
          </Card>
          <Card style={{ padding: "20px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Focus areas <span style={{ fontWeight: 400, color: C.muted }}>(optional)</span></label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>{FOCUS_OPTIONS.map((f) => <Chip key={f} active={focus.includes(f)} onClick={() => toggleFocus(f)}>{f}</Chip>)}</div>
            <div style={{ marginTop: "18px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: C.text, marginBottom: "8px" }}>Quick self-introduction <span style={{ fontWeight: 400, color: C.muted }}>(optional)</span></label>
              <textarea value={intro} onChange={(e) => setIntro(e.target.value)} rows={3} placeholder="e.g. Final-year CS student, built a chat app with Node and Redis..." style={{ ...inputSt, resize: "none", minHeight: "80px" }} />
            </div>
          </Card>
          {error && <div style={{ padding: "12px 16px", borderRadius: "10px", background: C.badBg, border: "1px solid #FECACA", color: C.bad, fontSize: "13px" }}>{error}</div>}
          <button onClick={handleStart} disabled={starting} style={{ width: "100%", padding: "14px", background: starting ? C.muted : C.primary, color: "#fff", border: "none", borderRadius: "12px", fontSize: "15px", fontWeight: 600, cursor: starting ? "not-allowed" : "pointer" }}>{starting ? "Starting your session..." : "Start Interview"}</button>
          <p style={{ textAlign: "center", fontSize: "12px", color: C.muted }}>No judgement, no abuse, no matter how you answer.</p>
        </div>
      </main>
    </div>
  );
}

// =========================================================================
// SCREEN 2 - INTERVIEW (markdown, scrollbar, auto-timeout)
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

  useEffect(() => {
    if (secondsLeft <= 0 || ended) return;
    const t = setInterval(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearInterval(t);
  }, [secondsLeft, ended]);

  useEffect(() => {
    if (secondsLeft <= 0 && !ended && !loading) { setEnded(true); onEnd(); }
  }, [secondsLeft, ended, loading]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, loading]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading || ended) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput(""); setLoading(true); setError(null);
    try {
      const res = await sendTurn(sessionId, text);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
      setTurnCount(res.turn_count);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); setTimeout(() => inputRef.current?.focus(), 50); }
  };

  const handleKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  const mmss = (s) => { const m = Math.floor(Math.max(0, s) / 60); const r = Math.max(0, s) % 60; return m + ":" + String(r).padStart(2, "0"); };
  const timerColor = secondsLeft <= 60 ? C.bad : secondsLeft <= 180 ? C.warn : C.text;
  const stageLabels = ["Warm-up", "About you", "Deep-dive", "Role Q&A", "Pressure", "Your turn", "Wrap-up"];
  const stage = Math.min(7, Math.max(1, Math.ceil((turnCount + 1) / 2)));

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: C.bg }}>
      <header style={{ borderBottom: "1px solid " + C.border, background: C.card, padding: "10px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
        <Logo />
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "11px", fontWeight: 600, padding: "4px 12px", borderRadius: "20px", background: "#EEF2FF", color: C.primary }}>{stageLabels[stage - 1]}</span>
          <span style={{ fontSize: "18px", fontWeight: 700, color: timerColor, fontVariantNumeric: "tabular-nums", minWidth: "50px", textAlign: "right" }}>{mmss(secondsLeft)}</span>
          <button onClick={() => { setEnded(true); onEnd(); }} style={{ padding: "6px 16px", borderRadius: "8px", border: "1px solid " + C.border, background: C.card, cursor: "pointer", fontSize: "13px", fontWeight: 500, color: C.text }}>End</button>
        </div>
      </header>
      <div ref={scrollRef} className="vyom-chat-scroll" style={{ flex: 1, overflowY: "auto", padding: "24px 20px" }}>
        <div style={{ maxWidth: "720px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "16px" }}>
          {messages.map((m, i) => <MsgBubble key={i} role={m.role} content={m.content} name={config.name} />)}
          {loading && <Typing />}
          {error && <div style={{ padding: "10px 14px", borderRadius: "10px", background: C.badBg, color: C.bad, fontSize: "13px" }}>{error}</div>}
          {secondsLeft <= 0 && <div style={{ padding: "14px 18px", borderRadius: "12px", background: C.accentSoft, border: "1px solid #FDE68A", textAlign: "center", fontSize: "14px", color: "#92400E", fontWeight: 600 }}>Time is up! Generating your performance report...</div>}
        </div>
      </div>
      <div style={{ borderTop: "1px solid " + C.border, background: C.card, padding: "14px 20px", flexShrink: 0 }}>
        <div style={{ maxWidth: "720px", margin: "0 auto" }}>
          <div style={{ display: "flex", gap: "10px", alignItems: "flex-end" }}>
            <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKey} rows={1} placeholder={ended ? "Interview ended" : "Type your answer..."} disabled={loading || ended} style={{ flex: 1, padding: "10px 14px", border: "1px solid " + C.border, borderRadius: "12px", fontSize: "14px", resize: "none", minHeight: "44px", maxHeight: "140px", outline: "none", fontFamily: "inherit", background: ended ? "#f1f5f9" : "#fff" }} />
            <button onClick={send} disabled={loading || !input.trim() || ended} style={{ padding: "10px 22px", borderRadius: "10px", border: "none", fontWeight: 600, fontSize: "14px", cursor: loading || !input.trim() || ended ? "not-allowed" : "pointer", background: loading || !input.trim() || ended ? "#cbd5e1" : C.primary, color: "#fff" }}>Send</button>
          </div>
          <div style={{ fontSize: "11px", color: C.muted, marginTop: "6px" }}>Enter to send | Shift+Enter for new line</div>
        </div>
      </div>
    </div>
  );
}

function MsgBubble({ role, content, name }) {
  const v = role === "assistant";
  return (
    <div style={{ display: "flex", gap: "10px", flexDirection: v ? "row" : "row-reverse", alignItems: "flex-start" }}>
      <div style={{ width: "32px", height: "32px", borderRadius: "8px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: v ? C.primary : C.accentSoft, color: v ? C.accent : "#92400E", fontWeight: 700, fontSize: "13px" }}>
        {v ? "V" : (name?.[0]?.toUpperCase() || "Y")}
      </div>
      <div style={{ padding: "12px 16px", borderRadius: "14px", maxWidth: "78%", fontSize: "14px", lineHeight: "1.6", background: v ? C.card : C.primary, color: v ? C.text : "#fff", border: v ? "1px solid " + C.border : "none" }}>
        {v ? renderMd(content) : content}
      </div>
    </div>
  );
}

function Typing() {
  return (
    <div style={{ display: "flex", gap: "10px", alignItems: "flex-start" }}>
      <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: C.primary, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ color: C.accent, fontWeight: 700, fontSize: "13px" }}>V</span>
      </div>
      <div style={{ padding: "14px 18px", borderRadius: "14px", background: C.card, border: "1px solid " + C.border }}>
        <div style={{ display: "flex", gap: "5px" }}>
          {[0, 1, 2].map((i) => <div key={i} style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#94a3b8", animation: "vyomPulse 1.2s ease-in-out infinite", animationDelay: i * 0.15 + "s" }} />)}
        </div>
      </div>
    </div>
  );
}

// =========================================================================
// SCREEN 3 - DEBRIEF (structured report, selection chances)
// =========================================================================
function DebriefScreen({ config, sessionId, onRestart }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { (async () => { try { setD(await endSession(sessionId)); } catch (e) { setError(e.message); } })(); }, []);

  if (error) return (
    <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center", padding: "20px" }}>
      <Card style={{ padding: "28px", maxWidth: "420px", width: "100%", textAlign: "center" }}>
        <div style={{ fontSize: "16px", fontWeight: 600, marginBottom: "8px" }}>Could not generate report</div>
        <div style={{ fontSize: "13px", color: C.muted, marginBottom: "20px" }}>{error}</div>
        <button onClick={onRestart} style={{ width: "100%", padding: "10px", background: C.primary, color: "#fff", border: "none", borderRadius: "10px", fontWeight: 600, cursor: "pointer" }}>Start new session</button>
      </Card>
    </div>
  );

  if (!d) return (
    <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <Logo big />
        <div style={{ marginTop: "20px", fontSize: "16px", fontWeight: 600 }}>Analyzing your interview...</div>
        <div style={{ fontSize: "13px", color: C.muted, marginTop: "4px" }}>Reading every answer, scoring each response.</div>
        <div style={{ marginTop: "20px", width: "200px", height: "3px", borderRadius: "2px", background: C.border, overflow: "hidden", margin: "20px auto 0" }}>
          <div style={{ height: "100%", background: C.accent, borderRadius: "2px", animation: "vyomLoad 2s ease-in-out infinite" }} />
        </div>
      </div>
    </div>
  );

  const score = d.overall || 0;
  const selChance = score >= 85 ? "Very high (85%+)" : score >= 70 ? "Good (60-75%)" : score >= 55 ? "Moderate (35-50%)" : score >= 40 ? "Low (15-30%)" : "Needs work (<15%)";
  const selColor = score >= 85 ? C.ok : score >= 70 ? "#2563EB" : score >= 55 ? C.warn : C.bad;
  const scoreColor = score >= 70 ? C.ok : score >= 50 ? C.warn : C.bad;
  const ss = d.sub_scores || {};

  return (
    <div style={{ minHeight: "100vh", background: C.bg }} className="vyom-chat-scroll">
      <style>{"@media(max-width:640px){.vg2{grid-template-columns:1fr!important}}"}</style>
      <header style={{ borderBottom: "1px solid " + C.border, background: C.card, padding: "14px 20px" }}>
        <div style={{ maxWidth: "800px", margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Logo />
          <button onClick={onRestart} style={{ padding: "8px 18px", borderRadius: "8px", border: "1px solid " + C.border, background: C.card, cursor: "pointer", fontSize: "13px", fontWeight: 500 }}>New Session</button>
        </div>
      </header>
      <main style={{ maxWidth: "800px", margin: "0 auto", padding: "28px 20px 48px" }}>
        <div style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: C.muted, marginBottom: "6px" }}>Performance Report</div>
        <h1 style={{ fontSize: "22px", fontWeight: 700, color: C.primary, margin: "0 0 24px", letterSpacing: "-0.01em" }}>{config.role} | {config.level} | {config.company || "General"} | {config.duration_min} min</h1>

        {/* Score hero */}
        <Card style={{ padding: "28px", marginBottom: "16px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "28px", alignItems: "center" }}>
            <div style={{ textAlign: "center", minWidth: "100px" }}>
              <div style={{ fontSize: "56px", fontWeight: 800, color: scoreColor, lineHeight: 1, letterSpacing: "-0.03em" }}>{score}</div>
              <div style={{ fontSize: "12px", color: C.muted, marginTop: "4px" }}>out of 100</div>
            </div>
            <div style={{ flex: 1, minWidth: "200px" }}>
              <div style={{ fontSize: "16px", fontWeight: 600, color: C.text, lineHeight: 1.5, marginBottom: "12px" }}>{d.one_line}</div>
              <div style={{ display: "inline-block", padding: "6px 14px", borderRadius: "8px", background: selColor + "14", border: "1px solid " + selColor + "30", fontSize: "13px", fontWeight: 600, color: selColor }}>Selection chances: {selChance}</div>
            </div>
          </div>
        </Card>

        {/* Sub-scores */}
        <Card style={{ padding: "24px", marginBottom: "16px" }}>
          <div style={{ fontSize: "14px", fontWeight: 700, marginBottom: "16px" }}>Skill breakdown</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }} className="vg2">
            {Object.entries(ss).map(([k, v]) => <SubBar key={k} label={prettyKey(k)} value={v} />)}
          </div>
        </Card>

        {/* Strengths + Gaps */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }} className="vg2">
          <Card style={{ padding: "24px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px" }}><div style={{ width: "8px", height: "8px", borderRadius: "50%", background: C.ok }} /><div style={{ fontSize: "14px", fontWeight: 700 }}>What went well</div></div>
            {(d.strengths || []).map((s, i) => <div key={i} style={{ fontSize: "13px", lineHeight: 1.6, marginBottom: "8px", paddingLeft: "16px", borderLeft: "2px solid " + C.ok }}>{s}</div>)}
          </Card>
          <Card style={{ padding: "24px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px" }}><div style={{ width: "8px", height: "8px", borderRadius: "50%", background: C.warn }} /><div style={{ fontSize: "14px", fontWeight: 700 }}>Where to improve</div></div>
            {(d.gaps || []).map((g, i) => <div key={i} style={{ marginBottom: "12px" }}><div style={{ fontSize: "13px", lineHeight: 1.6, paddingLeft: "16px", borderLeft: "2px solid " + C.warn }}>{g.gap}</div><div style={{ fontSize: "12px", color: "#6D28D9", fontWeight: 600, marginTop: "4px", paddingLeft: "16px" }}>Study: {g.upskillizeCourse}</div></div>)}
          </Card>
        </div>

        {/* STAR */}
        {d.star_breakdown?.length > 0 && <Card style={{ padding: "24px", marginBottom: "16px" }}>
          <div style={{ fontSize: "14px", fontWeight: 700, marginBottom: "16px" }}>Answer-by-answer analysis (STAR)</div>
          {d.star_breakdown.map((q, i) => <div key={i} style={{ marginBottom: "16px", paddingBottom: "16px", borderBottom: i < d.star_breakdown.length - 1 ? "1px solid " + C.border : "none" }}>
            <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "8px" }}>{q.question}</div>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "6px" }}>
              {["situation", "task", "action", "result"].map((key) => { const val = q[key] || 0; const co = val >= 2 ? C.ok : val === 1 ? C.warn : C.bad; const bg = val >= 2 ? C.okBg : val === 1 ? C.warnBg : C.badBg; return <span key={key} style={{ fontSize: "11px", fontWeight: 600, padding: "3px 10px", borderRadius: "6px", background: bg, color: co }}>{key[0].toUpperCase()} {val}/2</span>; })}
            </div>
            <div style={{ fontSize: "12px", color: C.muted, fontStyle: "italic" }}>{q.note}</div>
          </div>)}
        </Card>}

        {/* Interviewer thoughts */}
        {d.interviewer_thoughts?.length > 0 && <Card style={{ padding: "24px", marginBottom: "16px" }}>
          <div style={{ fontSize: "14px", fontWeight: 700, marginBottom: "4px" }}>What the interviewer was really thinking</div>
          <div style={{ fontSize: "12px", color: C.muted, marginBottom: "16px" }}>The silent evaluation in a real interview</div>
          {d.interviewer_thoughts.map((t, i) => <div key={i} style={{ marginBottom: "12px" }}>
            <div style={{ fontSize: "11px", color: C.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>Re: {t.answer}</div>
            <div style={{ fontSize: "13px", fontStyle: "italic", marginTop: "2px", paddingLeft: "12px", borderLeft: "2px solid " + C.accent }}>"{t.thought}"</div>
          </div>)}
        </Card>}

        {/* 7-day plan */}
        <Card style={{ padding: "24px", marginBottom: "16px" }}>
          <div style={{ fontSize: "14px", fontWeight: 700, marginBottom: "4px" }}>Your 7-day action plan</div>
          <div style={{ fontSize: "12px", color: C.muted, marginBottom: "16px" }}>A focused week to close gaps and get interview-ready</div>
          {(d.plan || []).map((p, i) => <div key={i} style={{ display: "flex", gap: "12px", marginBottom: "10px", alignItems: "flex-start" }}>
            <div style={{ width: "28px", height: "28px", borderRadius: "8px", flexShrink: 0, background: "#EEF2FF", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "12px", fontWeight: 700, color: C.primary }}>{i + 1}</div>
            <div style={{ fontSize: "13px", lineHeight: 1.6, paddingTop: "4px" }}>{p.replace(/^Day \d:\s*/, "")}</div>
          </div>)}
        </Card>

        {/* Next focus CTA */}
        <Card style={{ padding: "24px", background: C.primary, border: "none", marginBottom: "20px" }}>
          <div style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: C.accent, marginBottom: "8px" }}>Before your next mock</div>
          <div style={{ fontSize: "17px", fontWeight: 600, color: "#fff", lineHeight: 1.5 }}>{d.next_focus}</div>
        </Card>

        <button onClick={onRestart} style={{ width: "100%", padding: "14px", background: C.primary, color: "#fff", border: "none", borderRadius: "12px", fontSize: "15px", fontWeight: 600, cursor: "pointer" }}>Start Another Mock</button>
      </main>
    </div>
  );
}

function SubBar({ label, value }) {
  const pct = (value / 10) * 100;
  const co = value >= 7 ? C.ok : value >= 5 ? C.warn : C.bad;
  return (
    <div style={{ padding: "10px 14px", borderRadius: "10px", background: "#F8FAFC", border: "1px solid " + C.border }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "6px" }}>
        <span style={{ fontSize: "12px", color: C.muted }}>{label}</span>
        <span style={{ fontSize: "16px", fontWeight: 700, color: co }}>{value}<span style={{ fontSize: "11px", fontWeight: 400, color: C.muted }}>/10</span></span>
      </div>
      <div style={{ height: "4px", borderRadius: "2px", background: "#E2E8F0", overflow: "hidden" }}>
        <div style={{ height: "100%", width: pct + "%", borderRadius: "2px", background: co, transition: "width 0.6s ease" }} />
      </div>
    </div>
  );
}

function prettyKey(k) {
  return { communication: "Communication", roleKnowledge: "Role knowledge", clarity: "Clarity", confidence: "Confidence", structure: "Structure", problemSolving: "Problem-solving" }[k] || k;
}

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
        "* { box-sizing: border-box; }",
        "body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif; }",
        ".vyom-chat-scroll::-webkit-scrollbar { width: 6px; }",
        ".vyom-chat-scroll::-webkit-scrollbar-track { background: transparent; }",
        ".vyom-chat-scroll::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 3px; }",
        ".vyom-chat-scroll::-webkit-scrollbar-thumb:hover { background: #94A3B8; }",
        "@keyframes vyomPulse { 0%, 100% { opacity: 0.3; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1); } }",
        "@keyframes vyomLoad { 0% { width: 0%; } 50% { width: 70%; } 100% { width: 100%; } }",
      ].join("\n")}</style>
      {screen === "setup" && <SetupScreen onStart={(cfg, id, gr) => { setConfig(cfg); setSessionId(id); setGreeting(gr); setScreen("interview"); }} />}
      {screen === "interview" && <InterviewScreen config={config} sessionId={sessionId} greeting={greeting} onEnd={() => setScreen("debrief")} />}
      {screen === "debrief" && <DebriefScreen config={config} sessionId={sessionId} onRestart={() => { setConfig(null); setSessionId(null); setGreeting(""); setScreen("setup"); }} />}
    </>
  );
}
