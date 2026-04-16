import { useState, useRef, useEffect } from "react";

// =========================================================================
// API CLIENT — talks to your FastAPI on Render
// =========================================================================
// If VITE_API_URL is set, use it (split deployment: Netlify + Render).
// If not set (or empty), use same-origin — works when frontend and backend
// are served from the same Hugging Face Space.
const API_URL = import.meta.env.VITE_API_URL || "";

function authHeaders() {
  const token = localStorage.getItem("upskillize_token"); // set by LMS on SSO
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

const startSession = (cfg) =>
  api("/session/start", { method: "POST", body: JSON.stringify(cfg) });

const sendTurn = (session_id, message) =>
  api("/session/turn", {
    method: "POST",
    body: JSON.stringify({ session_id, message }),
  });

const endSession = (session_id) =>
  api("/session/end", {
    method: "POST",
    body: JSON.stringify({ session_id }),
  });

const fetchAlumniPreview = (company, role) =>
  api(`/alumni/preview?company=${encodeURIComponent(company)}&role=${encodeURIComponent(role)}`);

// =========================================================================
// CONSTANTS
// =========================================================================
const ROLES = [
  "Software Engineer (SDE)",
  "Frontend Developer",
  "Backend Developer",
  "Full-stack Developer",
  "Data Analyst",
  "Data Scientist",
  "Machine Learning Engineer",
  "Product Manager",
  "Business Analyst",
  "Digital Marketing",
  "UX / UI Designer",
  "HR / Recruiter",
  "Other",
];
const LEVELS = ["Fresher", "1–3 years", "3+ years", "MBA", "Career switcher"];
const COMPANIES = [
  { value: "", label: "General (mid-tier product)" },
  { value: "TCS", label: "TCS / Infosys / Wipro / Cognizant" },
  { value: "Amazon", label: "Amazon" },
  { value: "Google", label: "Google / Meta / Microsoft" },
  { value: "Startup", label: "Product startup (Series A–C)" },
  { value: "Consulting", label: "Consulting / Banking" },
];
const DURATIONS = [
  { v: 10, l: "Quick · 10 min" },
  { v: 20, l: "Short · 20 min" },
  { v: 30, l: "Standard · 30 min" },
  { v: 45, l: "Full · 45 min" },
];
const DIFFICULTIES = [
  { v: "Easy", l: "Easy", d: "Warm-up pace" },
  { v: "Realistic", l: "Realistic", d: "Matches real bar" },
  { v: "Stretch", l: "Stretch", d: "Tough · curveball" },
];
const MODES = [
  { v: "interview", l: "Interview mode", d: "Feels real — feedback at end" },
  { v: "coach", l: "Coach mode", d: "Brief feedback each turn" },
];
const FOCUS_OPTIONS = [
  "Communication",
  "Technical depth",
  "Confidence",
  "Structure (STAR)",
  "Project storytelling",
  "Salary negotiation",
];

// =========================================================================
// SHARED UI
// =========================================================================
function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="w-9 h-9 rounded-lg bg-indigo-950 flex items-center justify-center">
        <span className="text-amber-400 font-semibold text-lg tracking-tight">V</span>
      </div>
      <div className="leading-tight">
        <div className="text-slate-900 font-semibold tracking-tight">Vyom</div>
        <div className="text-xs text-slate-500">by Upskillize</div>
      </div>
    </div>
  );
}

function Chip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3.5 py-1.5 rounded-full text-sm border transition ${
        active
          ? "bg-indigo-950 text-white border-indigo-950"
          : "bg-white text-slate-700 border-slate-300 hover:border-slate-400"
      }`}
    >
      {children}
    </button>
  );
}

function Card({ children, className = "" }) {
  return (
    <div className={`bg-white border border-slate-200 rounded-2xl ${className}`}>
      {children}
    </div>
  );
}

// =========================================================================
// SCREEN 1 — SETUP
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

  const toggleFocus = (f) =>
    setFocus((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  // Golden Point trust signal: show real alumni question count
  useEffect(() => {
    if (!company || !role) {
      setAlumniCount(null);
      return;
    }
    let cancelled = false;
    fetchAlumniPreview(company, role)
      .then((r) => {
        if (!cancelled) setAlumniCount(r.count);
      })
      .catch(() => !cancelled && setAlumniCount(null));
    return () => {
      cancelled = true;
    };
  }, [company, role]);

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    try {
      const result = await startSession({
        name,
        role,
        level,
        company,
        duration_min: duration,
        difficulty,
        mode,
        focus,
        intro,
      });
      onStart(
        { name, role, level, company, duration_min: duration, difficulty, mode, focus, intro },
        result.session_id,
        result.greeting
      );
    } catch (err) {
      setError(err.message);
      setStarting(false);
    }
  };

  return (
    <div className="min-h-screen bg-stone-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-3xl mx-auto px-5 py-4 flex items-center justify-between">
          <Logo />
          <div className="text-xs text-slate-500 hidden sm:block">
            Bridging academia and industry
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-5 py-8 sm:py-12">
        <div className="mb-8">
          <h1 className="text-2xl sm:text-3xl font-semibold text-slate-900 tracking-tight">
            Set up your mock interview
          </h1>
          <p className="text-slate-600 mt-2 text-sm sm:text-base">
            Takes 30 seconds. Vyom tailors every question to your role, level, and target
            company — and pulls from real questions Upskillize alumni were just asked.
          </p>
        </div>

        <div className="space-y-5">
          <Card className="p-5 sm:p-6">
            <label className="block text-sm font-medium text-slate-900 mb-2">Your name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="First name"
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:border-indigo-950 focus:outline-none"
            />
          </Card>

          <Card className="p-5 sm:p-6">
            <label className="block text-sm font-medium text-slate-900 mb-2">Target role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm bg-white focus:border-indigo-950 focus:outline-none"
            >
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>

            <label className="block text-sm font-medium text-slate-900 mt-5 mb-2">
              Experience level
            </label>
            <div className="flex flex-wrap gap-2">
              {LEVELS.map((l) => (
                <Chip key={l} active={level === l} onClick={() => setLevel(l)}>
                  {l}
                </Chip>
              ))}
            </div>

            <label className="block text-sm font-medium text-slate-900 mt-5 mb-2">
              Target company style
            </label>
            <select
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm bg-white focus:border-indigo-950 focus:outline-none"
            >
              {COMPANIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>

            {/* GOLDEN POINT trust signal */}
            {alumniCount !== null && alumniCount > 0 && (
              <div className="mt-3 p-3 rounded-lg bg-amber-50 border border-amber-200">
                <div className="text-sm text-amber-900">
                  <span className="font-semibold">{alumniCount} real questions</span> from
                  Upskillize alumni who recently interviewed at {company} for {role}. Vyom
                  will use these during your session.
                </div>
              </div>
            )}
          </Card>

          <Card className="p-5 sm:p-6">
            <label className="block text-sm font-medium text-slate-900 mb-2">Duration</label>
            <div className="flex flex-wrap gap-2">
              {DURATIONS.map((d) => (
                <Chip key={d.v} active={duration === d.v} onClick={() => setDuration(d.v)}>
                  {d.l}
                </Chip>
              ))}
            </div>

            <label className="block text-sm font-medium text-slate-900 mt-5 mb-2">
              Difficulty
            </label>
            <div className="grid gap-2 sm:grid-cols-3">
              {DIFFICULTIES.map((d) => (
                <button
                  type="button"
                  key={d.v}
                  onClick={() => setDifficulty(d.v)}
                  className={`text-left p-3 rounded-lg border transition ${
                    difficulty === d.v
                      ? "border-indigo-950 bg-indigo-50"
                      : "border-slate-300 bg-white hover:border-slate-400"
                  }`}
                >
                  <div className="font-medium text-sm text-slate-900">{d.l}</div>
                  <div className="text-xs text-slate-600 mt-0.5">{d.d}</div>
                </button>
              ))}
            </div>

            <label className="block text-sm font-medium text-slate-900 mt-5 mb-2">
              Session mode
            </label>
            <div className="grid gap-2 sm:grid-cols-2">
              {MODES.map((m) => (
                <button
                  type="button"
                  key={m.v}
                  onClick={() => setMode(m.v)}
                  className={`text-left p-3 rounded-lg border transition ${
                    mode === m.v
                      ? "border-indigo-950 bg-indigo-50"
                      : "border-slate-300 bg-white hover:border-slate-400"
                  }`}
                >
                  <div className="font-medium text-sm text-slate-900">{m.l}</div>
                  <div className="text-xs text-slate-600 mt-0.5">{m.d}</div>
                </button>
              ))}
            </div>
          </Card>

          <Card className="p-5 sm:p-6">
            <label className="block text-sm font-medium text-slate-900 mb-2">
              Focus areas <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {FOCUS_OPTIONS.map((f) => (
                <Chip key={f} active={focus.includes(f)} onClick={() => toggleFocus(f)}>
                  {f}
                </Chip>
              ))}
            </div>

            <label className="block text-sm font-medium text-slate-900 mt-5 mb-2">
              Quick self-introduction{" "}
              <span className="text-slate-400 font-normal">
                (optional — helps Vyom personalize)
              </span>
            </label>
            <textarea
              value={intro}
              onChange={(e) => setIntro(e.target.value)}
              rows={3}
              placeholder="e.g. Final-year CS student, built a real-time chat app with Node and Redis, interned at a fintech startup..."
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm resize-none focus:border-indigo-950 focus:outline-none"
            />
          </Card>

          {error && (
            <div className="p-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg">
              {error}
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={starting}
            className="w-full bg-indigo-950 hover:bg-indigo-900 disabled:bg-slate-400 text-white font-medium py-3.5 rounded-xl transition"
          >
            {starting ? "Starting your session..." : "Start interview"}
          </button>

          <p className="text-xs text-slate-500 text-center">
            Vyom respects your space — no judgement, no abuse, no matter how you answer.
          </p>
        </div>
      </main>
    </div>
  );
}

// =========================================================================
// SCREEN 2 — INTERVIEW
// =========================================================================
function InterviewScreen({ config, sessionId, greeting, onEnd }) {
  const [messages, setMessages] = useState([{ role: "assistant", content: greeting }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [secondsLeft, setSecondsLeft] = useState(config.duration_min * 60);
  const [turnCount, setTurnCount] = useState(0);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const t = setInterval(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearInterval(t);
  }, [secondsLeft]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const res = await sendTurn(sessionId, text);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
      setTurnCount(res.turn_count);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const mmss = (s) => {
    const m = Math.floor(Math.max(0, s) / 60);
    const r = Math.max(0, s) % 60;
    return `${m}:${r.toString().padStart(2, "0")}`;
  };

  const stage = Math.min(7, Math.max(1, Math.ceil((turnCount + 1) / 2)));
  const stageLabels = [
    "Warm-up",
    "About you",
    "Deep-dive",
    "Role Q&A",
    "Pressure",
    "Your turn",
    "Wrap-up",
  ];

  return (
    <div className="min-h-screen bg-stone-50 flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-3xl mx-auto px-5 py-3 flex items-center justify-between gap-3">
          <Logo />
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 text-xs text-slate-700">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              {stageLabels[stage - 1]}
            </div>
            <div className="text-sm font-medium text-slate-900 tabular-nums">
              {mmss(secondsLeft)}
            </div>
            <button
              onClick={onEnd}
              className="text-sm px-3 py-1.5 rounded-lg border border-slate-300 hover:border-slate-400 text-slate-700 bg-white"
            >
              End
            </button>
          </div>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-5 py-6 space-y-5">
          {messages.map((m, i) => (
            <Message key={i} role={m.role} content={m.content} name={config.name} />
          ))}
          {loading && <TypingBubble />}
          {error && (
            <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-3">
              {error}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-slate-200 bg-white">
        <div className="max-w-3xl mx-auto px-5 py-4">
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              rows={1}
              placeholder="Type your answer..."
              disabled={loading}
              className="flex-1 px-3.5 py-2.5 border border-slate-300 rounded-xl text-sm resize-none focus:border-indigo-950 focus:outline-none disabled:bg-slate-50"
              style={{ minHeight: 44, maxHeight: 160 }}
            />
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              className="bg-indigo-950 hover:bg-indigo-900 disabled:bg-slate-300 text-white font-medium px-5 py-2.5 rounded-xl transition"
            >
              Send
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-2">
            Press Enter to send. Shift + Enter for a new line.
          </p>
        </div>
      </div>
    </div>
  );
}

function Message({ role, content, name }) {
  const isVyom = role === "assistant";
  return (
    <div className={`flex gap-3 ${isVyom ? "" : "flex-row-reverse"}`}>
      <div
        className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-semibold shrink-0 ${
          isVyom ? "bg-indigo-950 text-amber-400" : "bg-amber-100 text-amber-900"
        }`}
      >
        {isVyom ? "V" : name?.[0]?.toUpperCase() || "Y"}
      </div>
      <div
        className={`px-4 py-3 rounded-2xl text-sm max-w-[85%] sm:max-w-[75%] whitespace-pre-wrap leading-relaxed ${
          isVyom
            ? "bg-white border border-slate-200 text-slate-800"
            : "bg-indigo-950 text-white"
        }`}
      >
        {content}
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-lg bg-indigo-950 text-amber-400 flex items-center justify-center text-sm font-semibold shrink-0">
        V
      </div>
      <div className="px-4 py-3.5 rounded-2xl bg-white border border-slate-200">
        <div className="flex gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse"></span>
          <span
            className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse"
            style={{ animationDelay: "0.15s" }}
          ></span>
          <span
            className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse"
            style={{ animationDelay: "0.3s" }}
          ></span>
        </div>
      </div>
    </div>
  );
}

// =========================================================================
// SCREEN 3 — DEBRIEF
// =========================================================================
function DebriefScreen({ config, sessionId, onRestart }) {
  const [debrief, setDebrief] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const result = await endSession(sessionId);
        setDebrief(result);
      } catch (err) {
        setError(err.message);
      }
    })();
    // eslint-disable-next-line
  }, []);

  if (error) {
    return (
      <div className="min-h-screen bg-stone-50 flex items-center justify-center p-6">
        <Card className="p-6 max-w-md w-full">
          <h2 className="font-semibold text-slate-900 mb-2">Couldn't generate the debrief</h2>
          <p className="text-sm text-slate-600 mb-4">{error}</p>
          <button
            onClick={onRestart}
            className="w-full bg-indigo-950 text-white py-2.5 rounded-lg text-sm"
          >
            Start a new session
          </button>
        </Card>
      </div>
    );
  }

  if (!debrief) {
    return (
      <div className="min-h-screen bg-stone-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-xl bg-indigo-950 flex items-center justify-center mx-auto mb-4">
            <span className="text-amber-400 font-semibold text-xl">V</span>
          </div>
          <p className="text-slate-900 font-medium">Grading your interview...</p>
          <p className="text-slate-500 text-sm mt-1">Reading through every answer with care.</p>
        </div>
      </div>
    );
  }

  const scoreColor =
    debrief.overall >= 80
      ? "text-emerald-700"
      : debrief.overall >= 60
      ? "text-amber-700"
      : "text-rose-700";

  return (
    <div className="min-h-screen bg-stone-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-4xl mx-auto px-5 py-4 flex items-center justify-between">
          <Logo />
          <button
            onClick={onRestart}
            className="text-sm px-3.5 py-2 rounded-lg border border-slate-300 hover:border-slate-400 text-slate-700 bg-white"
          >
            New session
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-5 py-8 sm:py-12 space-y-6">
        <Card className="p-6 sm:p-8">
          <div className="flex flex-col sm:flex-row sm:items-center gap-6 sm:gap-8">
            <div className="text-center sm:text-left">
              <div className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                Overall performance
              </div>
              <div className={`text-6xl sm:text-7xl font-semibold tracking-tight ${scoreColor}`}>
                {debrief.overall}
              </div>
              <div className="text-slate-500 text-sm mt-1">out of 100</div>
            </div>
            <div className="flex-1">
              <div className="text-lg sm:text-xl text-slate-900 font-medium leading-snug">
                {debrief.one_line}
              </div>
              <div className="mt-3 text-sm text-slate-600">
                {config.role} · {config.level} · {config.company || "General"} ·{" "}
                {config.duration_min} min
              </div>
            </div>
          </div>
        </Card>

        <Card className="p-6 sm:p-8">
          <h3 className="font-semibold text-slate-900 mb-5">Sub-scores</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {Object.entries(debrief.sub_scores || {}).map(([k, v]) => (
              <SubScore key={k} label={prettyKey(k)} value={v} />
            ))}
          </div>
        </Card>

        <div className="grid sm:grid-cols-2 gap-6">
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
              <h3 className="font-semibold text-slate-900">Top strengths</h3>
            </div>
            <ul className="space-y-3">
              {(debrief.strengths || []).map((s, i) => (
                <li key={i} className="text-sm text-slate-700 leading-relaxed">
                  <span className="text-emerald-600 font-medium">→</span> {s}
                </li>
              ))}
            </ul>
          </Card>

          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-2 h-2 rounded-full bg-amber-500"></div>
              <h3 className="font-semibold text-slate-900">Gaps to close</h3>
            </div>
            <ul className="space-y-4">
              {(debrief.gaps || []).map((g, i) => (
                <li key={i} className="text-sm">
                  <div className="text-slate-700 leading-relaxed">
                    <span className="text-amber-600 font-medium">→</span> {g.gap}
                  </div>
                  <div className="mt-1 ml-4 text-xs text-indigo-900 font-medium">
                    Study: {g.upskillizeCourse}
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {debrief.star_breakdown?.length > 0 && (
          <Card className="p-6 sm:p-8">
            <h3 className="font-semibold text-slate-900 mb-5">STAR breakdown</h3>
            <div className="space-y-4">
              {debrief.star_breakdown.map((q, i) => (
                <div key={i} className="border-l-2 border-slate-200 pl-4">
                  <div className="text-sm font-medium text-slate-900">{q.question}</div>
                  <div className="flex gap-2 mt-2 flex-wrap">
                    <StarPill label="S" value={q.situation} />
                    <StarPill label="T" value={q.task} />
                    <StarPill label="A" value={q.action} />
                    <StarPill label="R" value={q.result} />
                  </div>
                  <div className="text-xs text-slate-600 mt-2 italic">{q.note}</div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {debrief.interviewer_thoughts?.length > 0 && (
          <Card className="p-6 sm:p-8">
            <h3 className="font-semibold text-slate-900 mb-1">What the interviewer thought</h3>
            <p className="text-xs text-slate-500 mb-5">
              The silent evaluation happening in a real interview
            </p>
            <div className="space-y-3">
              {debrief.interviewer_thoughts.map((t, i) => (
                <div key={i} className="text-sm">
                  <div className="text-slate-500 text-xs">Re: {t.answer}</div>
                  <div className="text-slate-800 italic mt-0.5">"{t.thought}"</div>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card className="p-6 sm:p-8">
          <h3 className="font-semibold text-slate-900 mb-1">Your 7-day plan</h3>
          <p className="text-xs text-slate-500 mb-5">A focused week to close the gaps</p>
          <ol className="space-y-3">
            {(debrief.plan || []).map((d, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <div className="w-7 h-7 rounded-lg bg-indigo-50 text-indigo-950 font-semibold text-xs flex items-center justify-center shrink-0">
                  {i + 1}
                </div>
                <div className="text-slate-700 leading-relaxed pt-0.5">
                  {d.replace(/^Day \d:\s*/, "")}
                </div>
              </li>
            ))}
          </ol>
        </Card>

        <Card className="p-6 sm:p-8 bg-indigo-950 border-indigo-950">
          <div className="text-amber-400 text-xs uppercase tracking-wider mb-2">
            Before your next mock
          </div>
          <div className="text-white text-lg sm:text-xl font-medium leading-snug">
            {debrief.next_focus}
          </div>
        </Card>

        <button
          onClick={onRestart}
          className="w-full bg-indigo-950 hover:bg-indigo-900 text-white font-medium py-3 rounded-xl transition"
        >
          Start another mock
        </button>
      </main>
    </div>
  );
}

function prettyKey(k) {
  const map = {
    communication: "Communication",
    roleKnowledge: "Role knowledge",
    clarity: "Clarity",
    confidence: "Confidence",
    structure: "Structure",
    problemSolving: "Problem-solving",
  };
  return map[k] || k;
}

function SubScore({ label, value }) {
  const pct = (value / 10) * 100;
  return (
    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200">
      <div className="text-xs text-slate-600">{label}</div>
      <div className="flex items-baseline gap-1 mt-1">
        <div className="text-xl font-semibold text-slate-900">{value}</div>
        <div className="text-xs text-slate-500">/10</div>
      </div>
      <div className="h-1 rounded-full bg-slate-200 mt-2 overflow-hidden">
        <div className="h-full bg-indigo-950 rounded-full" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function StarPill({ label, value }) {
  const fullLabel = { S: "Situation", T: "Task", A: "Action", R: "Result" }[label];
  const color =
    value >= 2
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : value === 1
      ? "bg-amber-50 text-amber-700 border-amber-200"
      : "bg-rose-50 text-rose-700 border-rose-200";
  return (
    <div className={`text-xs px-2 py-1 rounded-md border ${color}`} title={fullLabel}>
      <span className="font-semibold">{label}</span>
      <span className="ml-1 opacity-70">{value}/2</span>
    </div>
  );
}

// =========================================================================
// ROOT
// =========================================================================
export default function App() {
  const [screen, setScreen] = useState("setup");
  const [config, setConfig] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [greeting, setGreeting] = useState("");

  const handleStart = (cfg, id, greet) => {
    setConfig(cfg);
    setSessionId(id);
    setGreeting(greet);
    setScreen("interview");
  };

  const handleEnd = () => setScreen("debrief");

  const handleRestart = () => {
    setConfig(null);
    setSessionId(null);
    setGreeting("");
    setScreen("setup");
  };

  if (screen === "setup") return <SetupScreen onStart={handleStart} />;
  if (screen === "interview")
    return (
      <InterviewScreen
        config={config}
        sessionId={sessionId}
        greeting={greeting}
        onEnd={handleEnd}
      />
    );
  return <DebriefScreen config={config} sessionId={sessionId} onRestart={handleRestart} />;
}
