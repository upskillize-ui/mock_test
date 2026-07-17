import { useState, useRef, useEffect } from "react";
// The character owns the TTS analyser (createMediaElementSource may only be called
// once per element, so there must be exactly ONE analyser in the app).
import InterviewerCharacter, {
  wireTtsAnalyser, resumeTtsAnalyser, pickInterviewer,
} from "./InterviewerCharacter.jsx";
import Lobby from "./Lobby.jsx";
import { startFocusMonitor } from "./focusMonitor.js";
import {
  questionSeconds, expiryAction, shouldArmAbandon, SKIP_MARKER,
  QUESTION_WARN_SECONDS, CAMERA_GRACE_MS, SILENT_ABANDON_MS,
  WRAP_CAMERA_OFF, WRAP_NO_ANSWER, WRAP_SESSION_TIME_UP,
  shouldBackchannel, shouldBargeIn, canArmCapture, BARGE_IN_RMS, BARGE_IN_DUCK_MS,
  textIdleAction, TEXT_IDLE_EXPIRY_MS, TEXT_IDLE_NUDGE_LINE,
} from "./roomPolicy.js";
import { isEmptyReadout, historyStatus, trendDirection } from "./readoutPolicy.js";
// The room's presentation decisions: who has the floor, what the one strip says, what the
// student's tile shows while they answer. Pure and tested — see roomLayout.test.mjs.
import {
  activeSpeaker, statusStrip, studentSurface, chatSlot, bubbleMeta, composerIntent,
  SPEAKER_INTERVIEWER, SPEAKER_STUDENT, SURFACE_LIVE,
} from "./roomLayout.js";

// Realism v2: spoken confidence rating. Accepts digits, English words, Hinglish
// numerals, and an explicit "prefer not to say".
//   returns 1..5  -> a rating
//   returns null  -> "prefer not to say" (a valid, recorded non-answer)
//   returns undefined -> could not parse (caller falls back to the pills)
const SPOKEN_NUMBERS = {
  one: 1, two: 2, three: 3, four: 4, five: 5,
  ek: 1, do: 2, teen: 3, char: 4, chaar: 4, panch: 5, paanch: 5,
};
function parseSpokenRating(text) {
  if (!text) return undefined;
  const t = String(text).toLowerCase();
  if (/(prefer not|rather not|don'?t want|no comment|skip (it|this)|pass)/.test(t)) return null;
  const digit = t.match(/\b([1-5])\b/);
  if (digit) return Number(digit[1]);
  for (const [w, v] of Object.entries(SPOKEN_NUMBERS)) {
    if (new RegExp(`\\b${w}\\b`).test(t)) return v;
  }
  return undefined;
}

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
    let detail = null;
    try {
      const j = await res.json();
      detail = j.detail ?? null;
      // The intake boundary answers with a STRUCTURED detail — {errors, offer_text_mode}
      // — because "voice is down, want to type instead?" is an offer the UI has to act on,
      // not a string to print. Stringifying it here would render "[object Object]" at the
      // student, which is how a seatbelt becomes a dead end.
      serverMsg = typeof detail === "string" ? detail
        : (Array.isArray(detail?.errors) ? detail.errors.join(" ") : "")
        || j.message || "";
    }
    catch { try { serverMsg = (await res.text()).slice(0, 200); } catch { /* noop */ } }
    const attach = (e) => { e.status = res.status; e.detail = detail; return e; };
    // In dev, append the backend's specific reason (auth.py exposes it in `detail`)
    // so "Please log in again" becomes e.g. "Please log in again (token expired)".
    if (res.status === 401) throw attach(new Error("Please log in again to continue." + (import.meta.env?.DEV && serverMsg ? ` (${serverMsg})` : "")));
    if (res.status === 429) throw attach(new Error(serverMsg || "Daily limit reached. Try again tomorrow."));
    if (res.status >= 500) throw attach(new Error("InterviewIQ is having a hiccup. Please try again."));
    throw attach(new Error(serverMsg || `Request failed (${res.status}).`));
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

// Item 10(c): a fire-and-forget warm-up ping. The lobby renders instantly off local state;
// this wakes the backend (cold container / DB pool) in the background so the FIRST real call
// — /session/start on Join — is not the one that pays the cold-start cost. It never blocks
// anything and never surfaces an error: a failed warm-up just means the room warms on Join.
const pingHealth = () => api("/health").catch(() => {});
const startSession = (c) => api("/session/start", { method: "POST", body: JSON.stringify(c) });
// FAST START: /session/start now returns the session ROW and nothing else, so the room can
// render immediately. These two are the rest of the greeting, fetched from inside the room.
//   /session/greeting — the kickoff LLM + the audio for the FIRST SENTENCE only.
//   /session/speech   — the remaining sentences, synthesised WHILE sentence one plays. It
//                       takes an INDEX, never text: it can only ever read back a sentence
//                       this interviewer has already said to this candidate.
const fetchGreeting = (sid, voice) => api("/session/greeting", { method: "POST", body: JSON.stringify({ session_id: sid, voice }) });
const fetchSpeechRest = (sid, voice, fromIndex = 1) => api("/session/speech", { method: "POST", body: JSON.stringify({ session_id: sid, voice, from_index: fromIndex }) });
// The pre-cached clip pack: acknowledgments ("Hmm.", "Accha.") played the instant an answer
// is submitted, and soft backchannels ("mm-hmm") for a natural pause mid-answer. Fetched
// once per session; the clips are synthesised once in the life of the cache.
const fetchClipPack = (voice) => api(`/session/clips?voice=${encodeURIComponent(voice)}`);
// `timeout` (E7.7) is set only when the per-question clock forced this turn:
// "partial" — we cut them off and are submitting what we captured; "skip" — nothing was
// captured, and the server writes the marker itself (we send no text for it).
const sendTurn = (sid, msg, stage, voice, deliveryMetrics, timeout) => api("/session/turn", { method: "POST", body: JSON.stringify({ session_id: sid, message: msg, stage, voice, delivery_metrics: deliveryMetrics || null, timeout: timeout || null }) });
const submitRating = (sid, answerId, rating) => api("/session/turn/rating", { method: "POST", body: JSON.stringify({ session_id: sid, answer_id: answerId, rating }) });
// Realism v2: transcription failed -> IQ says so in character and the mic reopens.
// Consumes NO question slot (the backend inserts no message and changes no state).
const reaskTurn = (sid, voice, kind = "reask") => api("/session/reask", { method: "POST", body: JSON.stringify({ session_id: sid, voice, kind }) });
// Realism v2: correct a mis-transcribed answer from the transcript drawer. Idempotent.
const editLastAnswer = (sid, message) => api("/session/turn/last", { method: "PATCH", body: JSON.stringify({ session_id: sid, message }) });
// Interview Room: ONE attention/device signal, derived on-device. Strings only — no
// frame, image, or landmark can travel on this call, by construction.
const postFocusEvent = (sid, type) => api("/session/focus-event", { method: "POST", body: JSON.stringify({ session_id: sid, type }) });
// Interview Room: end the interview early. The decision is made and PERSISTED server-
// side, so refreshing can't dodge it; completed rounds are still scored normally.
const wrapSession = (sid, reason) => api("/session/wrap", { method: "POST", body: JSON.stringify({ session_id: sid, reason }) });
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
// Item 6 (live self-captions): transcribe a SHORT ROLLING WINDOW of the same recording, for
// the running "You:" caption. Same audio path, same vendor (Saarika) — no browser speech
// service. Display-only and side-effect-free server-side. Returns { transcript } or throws.
async function sttPartial(sessionId, blob) {
  const fd = new FormData();
  fd.append("session_id", sessionId);
  fd.append("audio", blob, "partial.webm");
  const res = await fetch(API_URL + "/session/stt/partial", { method: "POST", headers: { ...authHeaders() }, body: fd });
  if (!res.ok) throw new Error(`partial stt failed (${res.status})`);
  return res.json();
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

// ── Voice Stage prefs (persisted; all default ON, and only ever apply when voice
// is actually available — with voice off the session renders exactly as before).
const STAGE_KEY = "interviewiq_voice_stage";
const CAPTIONS_KEY = "interviewiq_captions";
// Item 6: live self-captions default OFF — turning them on opts into the browser's speech
// service, so it must be the student's explicit choice, made with the honest line shown.
const SELFCAP_KEY = "interviewiq_self_captions";
const getFlagPref = (key, dflt = true) => {
  try { const v = localStorage.getItem(key); return v === null ? dflt : v === "1"; }
  catch { return dflt; }
};
const setFlagPref = (key, on) => { try { localStorage.setItem(key, on ? "1" : "0"); } catch { /* noop */ } };
// Web Audio tuning for the learner strip (real mic input, not a fake animation).
const WAVE_BARS = 28;              // bars in the live waveform
const SILENCE_RMS = 0.018;         // below this counts as silence
const SILENCE_HOLD_MS = 2200;      // ~2.2s trailing silence -> end-of-answer (auto-listen)
const MIN_SPEECH_MS = 2000;        // must have spoken >=2s before trailing silence submits
const AUTO_LISTEN_GRACE_MS = 600;  // grace beat before the mic opens
const RATING_SILENCE_MS = 8000;    // no spoken rating in 8s -> fall back to the pills
const MUTE_FORK_DELAY_MS = 5000;   // muted with an answer due -> IQ offers the fork aloud
// A "full" answer that comes through near-silent means the mic is too quiet/far. A "full"
// answer with strong signal that STILL fails to transcribe means the room is too noisy.
const QUIET_ANSWER_MIN_MS = 2500;  // a real attempt, not a half-second cough
const QUIET_PEAK_RMS = 0.05;       // peak below this over a full answer == a very quiet mic
const NOISE_COACH_AFTER = 2;       // clear-speech-but-unusable attempts before we coach once

// One shared <audio> element across screens so the iOS unlock (done on the Start
// button gesture) carries over to programmatic playback in the interview.
let _player = null;
function player() {
  if (!_player && typeof Audio !== "undefined") { _player = new Audio(); _player.preload = "auto"; }
  return _player;
}
// A SECOND element, for the little human noises (acknowledgments, backchannels). It has to
// be separate: a backchannel plays while the mic is recording and an ack plays while the
// reply is being generated, and either one landing on the main element would tear the
// interviewer's own voice out mid-sentence.
let _clipPlayer = null;
function clipPlayer() {
  if (!_clipPlayer && typeof Audio !== "undefined") {
    _clipPlayer = new Audio();
    _clipPlayer.preload = "auto";
  }
  return _clipPlayer;
}
// Backchannels play UNDER a live mic, into the same room. Loud enough to be heard, quiet
// enough not to be transcribed as part of their answer.
const BACKCHANNEL_VOLUME = 0.32;

// Every mic we open, for anything. echoCancellation is not a nicety here — it is what makes
// barge-in and backchannels possible at all: the interviewer's voice is coming out of the
// same laptop the mic is listening through, and without cancellation she would hear herself
// speak, decide the candidate had interrupted, and stop talking. To herself.
// The processing flags we ASK for on every mic. If the browser grants the mic but silently
// drops one (some Android / Bluetooth stacks do), the per-answer instrumentation line says
// so — a dropped echoCancellation is exactly the kind of thing that turns into "she keeps
// interrupting herself" three bug reports later.
const MIC_DESIRED = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
const MIC_CONSTRAINTS = {
  audio: {
    ...MIC_DESIRED,
    // Saarika (Sarvam STT) transcribes 16 kHz mono; ask for it so we upload what the model
    // wants rather than a 48 kHz stereo stream it has to downsample. `ideal`, never `exact`:
    // a device that cannot hit these must still hand us a working mic.
    sampleRate: { ideal: 16000 },
    channelCount: { ideal: 1 },
  },
};
// Live self-captions (item 6) are driven by OUR OWN Saarika STT: short rolling windows of the
// same mic recording, transcribed as the student speaks. One audio path, one vendor — no
// browser speech service. Supported wherever we can record at all.
const SELF_CAPTIONS_SUPPORTED = typeof MediaRecorder !== "undefined";
const SELFCAP_WINDOW_MS = 3500;    // length of each rolling window we transcribe for the caption
const SELFCAP_MAX_WINDOWS = 30;    // per-answer cap on partial STT calls (client-side cost guard)
// Compare granted MediaTrackSettings against what we asked for; returns the flags the
// browser refused (dropped or forced false). Empty object == everything honoured.
function micSettingsShortfall(settings) {
  const dropped = {};
  if (!settings) return dropped;
  for (const k of Object.keys(MIC_DESIRED)) {
    // A key the browser doesn't report is unknown, not refused — only flag an explicit false.
    if (k in settings && settings[k] === false) dropped[k] = false;
  }
  return dropped;
}
// Minimal silent WAV — played inside the Start-button gesture to unlock autoplay
// on iOS Safari, which otherwise blocks programmatic .play().
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";
async function unlockAudioPlayback() {
  const p = player(); if (!p) return;
  try { p.src = SILENT_WAV; await p.play(); p.pause(); p.currentTime = 0; }
  catch { /* still blocked — the UI will offer a tap-to-play affordance */ }
  // Realism v2: tap the TTS element with an AnalyserNode INSIDE this user gesture, so
  // the AudioContext starts in "running" state. This is what drives the character's
  // lip-sync from the real voice. If it fails, the element is left untouched and audio
  // still plays normally (the mouth simply won't sync).
  wireTtsAnalyser(p);
  resumeTtsAnalyser();
}

// Embedded audio seatbelt: inside the same-origin LMS iframe, a programmatic .play() can be
// refused by the browser's autoplay policy (or routed into a suspended AudioContext). When
// that happens we must NEVER fail silently — log the reason (name + message) so it is
// diagnosable, and let the caller raise the in-brand "Tap to enable audio" affordance. The
// room stays usable regardless: captions carry the words; the chip lets the user unlock sound.
function logAudioBlocked(where, err) {
  try {
    console.warn(`[InterviewIQ audio] play() blocked at ${where}:`, (err && err.name) || err || "unknown", (err && err.message) || "");
  } catch { /* noop */ }
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
// Voice Stage icons.
const IconKeyboard = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="6" width="20" height="12" rx="2" /><line x1="6" y1="10" x2="6" y2="10" /><line x1="10" y1="10" x2="10" y2="10" /><line x1="14" y1="10" x2="14" y2="10" /><line x1="18" y1="10" x2="18" y2="10" /><line x1="8" y1="14" x2="16" y2="14" /></svg>
);
const IconSliders = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" /></svg>
);
const IconClose = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
);
// Interview Room controls (Lucide-style, 1.6px stroke, no emojis).
const IconMicOff = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><line x1="2" y1="2" x2="22" y2="22" /><path d="M9 9v3a3 3 0 0 0 5.1 2.1" /><path d="M15 9.3V5a3 3 0 0 0-5.9-.7" /><path d="M5 10a7 7 0 0 0 10.7 6" /><line x1="12" y1="19" x2="12" y2="22" /></svg>
);
const IconCam = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M23 7l-7 5 7 5V7z" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
);
const IconCamOff = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><line x1="2" y1="2" x2="22" y2="22" /><path d="M16 16H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2" /><path d="M10 5h4a2 2 0 0 1 2 2v3l5-3.5v9" /></svg>
);
const IconCC = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M8 11.5a1.8 1.8 0 1 0 0 1" /><path d="M15 11.5a1.8 1.8 0 1 0 0 1" /></svg>
);
const IconTranscript = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><line x1="7" y1="8" x2="17" y2="8" /><line x1="7" y1="12" x2="13" y2="12" /></svg>
);
// The "captured" tick. Lucide's check-circle, drawn like every other icon here — no
// emoji anywhere on the interview surface.
const IconCheck = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21.8 10.5V12a10 10 0 1 1-5.9-9.1" /><path d="M22 4 12 14l-3-3" /></svg>
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

// When an interview ended early, the readout SAYS so — plainly, in neutral language, and
// with the one thing the learner most needs to hear: nothing was zeroed as a punishment.
// We score what happened and mark what didn't.
//
// WHY (the reason) is separate from the REASSURANCE, because the reassurance is only true
// when there IS something below to be scored. On a session below the evidence floor,
// "what you covered is scored below" is a promise the page does not keep — there are no
// scores below, by design. Composing the two lets the same reason serve both readouts
// without either of them lying.
const EARLY_WRAP_WHY = {
  camera_off: "This interview ended early because the camera stayed off.",
  no_answer_timeout: "This interview ended early after a long silence with no answer.",
  session_time_up: "Time ran out before the last rounds.",
  // The engagement floor: questions kept running out, the interviewer checked in, and that
  // went unanswered too. Said plainly and without blame — we have no idea why they went
  // quiet, and guessing would be both rude and, quite possibly, wrong.
  disengaged: "This interview ended early — the questions kept running out with no answer, and the check-in went unanswered too.",
};

const earlyWrapNote = (reason, scored) => {
  const why = EARLY_WRAP_WHY[reason] || "This interview ended early.";
  return scored
    ? `${why} What you covered is scored below exactly as it stood — nothing was zeroed.`
    : `${why} Nothing was zeroed and nothing was marked against you — the next attempt is a clean slate.`;
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
// The fourth difficulty. A stress-interview simulator — a real genre in Indian hiring (bank
// PO panels, consulting partners, some PSU boards) and something candidates ASK for.
//
// It sits apart from the other three, and it costs a second, explicit tap to enter, because
// nobody should land in a pressure panel by mis-clicking a grid. What it changes is the
// interviewer's REGISTER and the number of curveballs. What it does not change — not by one
// word — is the guardrails: the criticism lands on the answer and the reasoning, never on
// the person, and the readout is written in the same mentor voice as every other readout.
const CRITICAL = {
  v: "Critical",
  l: "Critical",
  d: "Pressure panel. Your answers will be challenged and criticised. Not a gentle experience.",
  confirm: "I want the pressure panel",
};
// Item 10(a): the difficulty selector is one row of four equal chips. Critical rides in the
// same row as the other three — a red dot and a short "Pressure panel" subtext are all that
// set it apart on the chip; the full warning lives below the row and only when it is chosen.
const DIFF_CHIPS = [
  ...DIFFICULTIES,
  { v: CRITICAL.v, l: CRITICAL.l, d: "Pressure panel", critical: true },
];
// FEEDBACK — when they hear how it went. The heading says FEEDBACK; the wire field and
// the DB column are still `mode`, which is exactly why the constant below is NOT called
// MODES. Two different things named "mode" is the oldest trap in this codebase.
const MODES = [{ v: "interview", l: "Interview mode", d: "Feedback at end only" }, { v: "coach", l: "Coach mode", d: "Feedback after each answer" }];

// MODE — how they answer. Sent as `session_mode`; weighted by scoring.WEIGHTS["mode"]
// (TEXT 0.90 / AUDIO 1.00 / VIDEO 1.00) and nowhere else.
//   TEXT  — never asks for the mic (we do not request a permission the mode cannot use)
//           and never spends a rupee at Sarvam.
//   AUDIO — the default, and what every session before this picker existed did.
//   VIDEO — camera on, answer by voice or typing per question. Presence metrics are
//           Phase D; the camera is on because the chip says Video, not to measure them.
const SESSION_MODES = [
  { v: "TEXT", l: "Text", d: "Type your answers" },
  { v: "AUDIO", l: "Audio", d: "Speak your answers" },
  { v: "VIDEO", l: "Video", d: "Camera on — speak or type" },
];
const DEFAULT_SESSION_MODE = "AUDIO";
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
  /* Item 10(a): difficulty — one row of four equal chips, wrapping to 2×2 under ~700px. */
  .iq-diff4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
  @media(max-width:700px){.iq-diff4{grid-template-columns:1fr 1fr}}
  .vopt-crit-on{border:2px solid #c0392b;background:#fdf1f0}
  .iq-critical-warn{margin-top:10px;padding:12px 14px;border-radius:10px;background:#fdf1f0;border:1px solid #e2b3ac;font-size:12px;line-height:1.6;color:#7a2318;font-family:'Plus Jakarta Sans',sans-serif;animation:iqFade .2s ease}
  /* The pressure panel (difficulty: Critical). Set apart from the three-up grid on
     purpose — it is not a fourth flavour, it is a different kind of thing, and the UI
     should say so before the interviewer does. */
  .iq-critical{margin-top:8px;border:1.5px solid #e8e9f0;border-radius:10px;overflow:hidden;transition:border-color .2s,background .2s}
  .iq-critical:hover{border-color:#e2b3ac}
  .iq-critical-on{border:2px solid #c0392b;background:#fdf1f0}
  .iq-critical-head{display:block;width:100%;text-align:left;padding:12px 14px;background:transparent;border:none;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif}
  .iq-critical-head:focus-visible{outline:2px solid #c0392b;outline-offset:-2px}
  .iq-critical-dot{width:8px;height:8px;border-radius:50%;background:#c0392b;flex-shrink:0}
  .iq-critical-badge{margin-left:auto;font-size:9px;font-weight:800;letter-spacing:.06em;color:#fff;background:#c0392b;padding:2px 7px;border-radius:4px}
  .iq-critical-confirm{padding:0 14px 14px;animation:iqFade .2s ease}
  .iq-critical-btn{width:100%;padding:10px 16px;border-radius:8px;border:none;background:#c0392b;color:#fff;font-size:13px;font-weight:700;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif;transition:background .15s}
  .iq-critical-btn:hover{background:#a3301f}
  .iq-critical-btn:focus-visible{outline:2px solid #1a1a1a;outline-offset:2px}
  /* FAST START: the caption band while the greeting is still being written. The room is
     already on screen and the interviewer is already there — this is the two seconds in
     which she is drawing breath, and it should read as exactly that. */
  .iq-connecting{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:rgba(255,255,255,.55)}
  .iq-connecting-dot{width:6px;height:6px;border-radius:50%;background:#00C4A0;animation:iqPulse 1.4s ease-in-out infinite}
  .iq-connecting-dot:nth-child(2){animation-delay:.2s}
  .iq-connecting-dot:nth-child(3){animation-delay:.4s}
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

  /* ── THE READOUT — ONE DESIGN LANGUAGE ──────────────────────────────────
     The readout used to render as two stacked designs: a navy report, then a
     second navy scorecard, with the band printed on both. It read as two
     documents about one interview, and a full-page screenshot showed it.

     There are now EXACTLY TWO SURFACES, and the rule is a rule, not a habit:
       .rd-card  — light. Every piece of coaching prose lives on one.
       .rd-navy  — navy. The Session Profile strip and the Readiness block. Only
                   those two. Nothing else on this page is navy.
     One width, one radius, one padding rhythm, one header treatment, so the
     page reads top-to-bottom as a single designed document. */
  .rd-page{width:100%;max-width:820px;margin:0 auto;padding:24px 28px;box-sizing:border-box}
  .rd-card{background:#fff;border:1.5px solid #e8e9f0;border-radius:12px;margin-bottom:14px;overflow:hidden}
  .rd-navy{background:#1a2744;border:1.5px solid #1a2744;border-radius:12px;margin-bottom:14px;overflow:hidden}
  .rd-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:16px 22px 0}
  .rd-navy .rd-h{padding-top:18px}
  .rd-t{font-size:14px;font-weight:800;color:#1a2744;letter-spacing:-.01em}
  .rd-navy .rd-t{color:rgba(255,255,255,.34);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}
  .rd-b{padding:12px 22px 20px}
  .rd-navy .rd-b{padding:14px 22px 22px}
  /* Item 1: the context chip. Every section carries one — no score, anywhere,
     without the context it was earned in. */
  .rd-chip{margin-left:auto;flex-shrink:0;padding:3px 9px;border-radius:6px;font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:10px;font-weight:500;letter-spacing:.02em;background:#f7f8fc;color:#72706b;border:1px solid #e8e9f0;white-space:nowrap}
  .rd-navy .rd-chip{background:rgba(255,255,255,.07);color:rgba(255,255,255,.6);border-color:rgba(255,255,255,.14)}
  /* The Session Profile strip: label/value pairs, data in DM Mono. */
  .rd-strip{display:flex;flex-wrap:wrap;gap:0 26px}
  .rd-strip-i{display:flex;flex-direction:column;gap:3px;padding:6px 0;min-width:0}
  .rd-strip-l{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:rgba(255,255,255,.34)}
  .rd-strip-v{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:13px;color:#fff;font-weight:500;overflow-wrap:anywhere}
  .rd-rule{border-top:1px solid rgba(255,255,255,.12);margin-top:18px;padding-top:16px}
  .rd-sub{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,255,255,.35);margin-bottom:12px}
  /* Item 8: "How this score is calculated" — the working, on demand. <details> so
     it is keyboard-reachable and printable without a line of JS. */
  .rd-math{margin-top:18px;border-top:1px solid rgba(255,255,255,.12);padding-top:14px}
  .rd-math summary{cursor:pointer;font-size:12px;font-weight:700;color:rgba(255,255,255,.72);list-style:none;padding:4px 0;font-family:'Plus Jakarta Sans',sans-serif}
  .rd-math summary::-webkit-details-marker{display:none}
  .rd-math summary:before{content:"+ ";font-family:'DM Mono',monospace}
  .rd-math[open] summary:before{content:"− "}
  .rd-math summary:hover{color:#fff}
  .rd-math-r{display:flex;gap:12px;align-items:baseline;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.07)}
  .rd-math-r:last-child{border-bottom:none}
  .rd-math-v{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:13px;font-weight:500;color:#C8992A;flex-shrink:0;min-width:56px;text-align:right}
  .rd-math-l{font-size:12px;font-weight:700;color:#fff;margin-bottom:2px}
  .rd-math-n{font-size:12px;line-height:1.55;color:rgba(255,255,255,.6)}
  .rd-star{margin-bottom:14px}
  .rd-star summary{cursor:pointer;font-size:14px;font-weight:800;color:#1a2744;list-style:none;padding:16px 22px}
  .rd-star summary::-webkit-details-marker{display:none}
  .rd-star summary:after{content:" ▸";color:#a8a49f}
  .rd-star[open] summary:after{content:" ▾"}
  @media(max-width:640px){
    .rd-page{padding:18px 14px}
    .rd-h,.rd-star summary{padding-left:16px;padding-right:16px}
    .rd-b,.rd-navy .rd-b{padding-left:16px;padding-right:16px}
    .rd-chip{margin-left:0;width:100%;text-align:center}
    .rd-strip{gap:0 18px}
  }

  /* ── VOICE STAGE ────────────────────────────────────────────────────────
     Call-like presentation over the SAME state machine. Everything is built on
     the brand tokens (teal = IQ speaking/intelligence, orange = recording only,
     gold = progress/rating) so the dual-theme reskin swaps colour without
     relayout. All animation is transform/opacity only; every loop is under 2s. */
  @keyframes iqOrbBreathe { 0%,100%{transform:scale(1)} 50%{transform:scale(1.045)} }
  @keyframes iqOrbBreatheFast { 0%,100%{transform:scale(1)} 50%{transform:scale(1.09)} }
  @keyframes iqAurora { to { transform: rotate(360deg); } }
  @keyframes iqAuroraRev { to { transform: rotate(-360deg); } }
  @keyframes iqHalo { 0%,100%{opacity:.30;transform:scale(1)} 50%{opacity:.60;transform:scale(1.12)} }
  @keyframes iqBar { 0%,100%{transform:scaleY(.28)} 50%{transform:scaleY(1)} }
  @keyframes iqSweep { 0%{transform:translateX(-120%)} 100%{transform:translateX(120%)} }
  @keyframes iqRise { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }

  /* ── THE RETIRED ORB STAGE ────────────────────────────────────────────────
     The room used to be a glowing orb on a centred stage (.iq-stage / .iq-orb* /
     .iq-micpill / .iq-review / .iq-caption / a bottom .iq-strip). InterviewerCharacter
     replaced the orb with a real face and the room replaced the stage with two tiles, but
     the CSS stayed — and it was not merely dead. The old bottom-strip rule set
     flex-direction:column and padding:16px 20px 20px on .iq-strip, and the new status
     strip is also .iq-strip: the corpse was reaching up and stacking the live strip's dot
     above its own label. Dead CSS is not free; it collides. It is gone.

     Kept from that block, because they are still load-bearing: the live mic waveform
     (now inside the student's input surface) and the ghost button (the audio seatbelt). */
  /* Live mic waveform — heights are set inline from the real AnalyserNode. */
  .iq-livewave{display:flex;align-items:center;justify-content:center;gap:3px;height:34px}
  .iq-livebar{width:3px;min-height:3px;border-radius:2px;background:#E8521A;transition:height .06s linear}
  .iq-ghostbtn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 14px;border-radius:8px;border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.05);color:rgba(255,255,255,.85);font-size:12px;font-weight:600;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif;transition:all .15s}
  .iq-ghostbtn:hover{background:rgba(255,255,255,.12);color:#fff}
  .iq-ghostbtn:focus-visible{outline:2px solid #00C4A0;outline-offset:2px}

  /* Transcript drawer: side sheet >=760px, bottom sheet below. */
  .iq-drawer-back{position:fixed;inset:0;background:rgba(11,22,40,.5);z-index:60;animation:iqFade .2s ease}
  .iq-drawer{position:fixed;top:0;right:0;bottom:0;width:min(420px,88vw);background:#f7f8fc;z-index:61;display:flex;flex-direction:column;box-shadow:-8px 0 30px rgba(0,0,0,.22);animation:iqDrawerIn .24s ease}
  @keyframes iqDrawerIn { from{transform:translateX(24px);opacity:0} to{transform:translateX(0);opacity:1} }
  @keyframes iqSheetIn { from{transform:translateY(24px);opacity:0} to{transform:translateY(0);opacity:1} }
  .iq-drawer-h{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid #e8e9f0;background:#fff;flex-shrink:0}
  .iq-drawer-b{flex:1;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:12px}
  @media(max-width:760px){
    .iq-drawer{top:auto;left:0;right:0;bottom:0;width:auto;height:72vh;border-radius:16px 16px 0 0;box-shadow:0 -8px 30px rgba(0,0,0,.22);animation:iqSheetIn .24s ease}
  }

  /* Settings menu (header) */
  .iq-menu{position:absolute;top:calc(100% + 8px);right:0;min-width:240px;background:#fff;border:1px solid #e8e9f0;border-radius:12px;box-shadow:0 12px 34px rgba(11,22,40,.20);z-index:80;padding:8px;animation:iqRise .18s ease}
  .iq-menu-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 10px;border-radius:8px;font-size:13px;color:#1a1a1a;font-family:'Plus Jakarta Sans',sans-serif}
  .iq-menu-row:hover{background:#f7f8fc}
  .iq-menu-sep{height:1px;background:#e8e9f0;margin:6px 4px}
  .iq-switch{width:40px;height:22px;border-radius:999px;border:none;background:#e8e9f0;position:relative;cursor:pointer;flex-shrink:0;transition:background .18s}
  .iq-switch:focus-visible{outline:2px solid #0B1628;outline-offset:2px}
  .iq-switch-on{background:#00C4A0}
  .iq-switch-knob{position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:transform .18s;box-shadow:0 1px 3px rgba(0,0,0,.2)}
  .iq-switch-on .iq-switch-knob{transform:translateX(18px)}

  /* ── INTERVIEW ROOM — a two-person call, not a chat log ─────────────────── */
  /* THE SPACING RHYTHM. Every gap, pad and radius in the room comes from these four
     numbers, so the room has one rhythm instead of sixteen opinions. The old room had
     gaps of 8/10/12/16/20/22 and three different radii, which is what "it looks a bit
     off and I can't say why" is made of. */
  .iq-room{
    --gap:16px;          /* between the big boxes: tiles, panel, caption area */
    --pad:20px;          /* the room's own outer margin */
    --tile-pad:10px;     /* inside a tile, to its overlays */
    --radius:14px;       /* every big box */
    --radius-sm:8px;     /* chips and tags */
    flex:1;display:flex;flex-direction:column;background:#0B1628;overflow:hidden;min-height:0;
  }

  /* THE GRID. Two EQUAL tiles (1fr 1fr — equal by construction, not by eye), plus an
     optional third track for the chat panel. The tiles stay equal to each other whether
     the panel is open or not: the panel takes its width from the room, never from one
     tile, so opening it can never make the call lopsided. */
  .iq-room-grid{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;gap:var(--gap);padding:var(--pad) var(--pad) 0;box-sizing:border-box}
  .iq-room-grid--chat{grid-template-columns:1fr 1fr minmax(300px,340px)}

  /* A TILE is a column: a body that flexes, and (on the student's) a surface below it.
     The name tag lives INSIDE the body and the surface is the body's SIBLING — so the
     tag cannot collide with the surface no matter how long either grows. The old room
     pinned the muted chip at bottom:150px to clear the self-view, which held exactly
     until the thing below it changed height. Structure, not magic numbers. */
  .iq-tile{position:relative;min-width:0;min-height:0;display:flex;flex-direction:column;border-radius:var(--radius);overflow:hidden;background:#0a1220;border:1px solid rgba(255,255,255,.10);transition:border-color .18s,box-shadow .18s}
  .iq-tile-body{flex:1;min-height:0;min-width:0;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden}
  /* ACTIVE SPEAKER: the teal ring follows whoever is talking. Exactly one tile can carry
     it (see roomLayout.activeSpeaker) — two lit tiles would be the same as none. */
  .iq-tile--active{border-color:rgba(0,196,160,.85);box-shadow:0 0 0 2px rgba(0,196,160,.5),0 0 26px rgba(0,196,160,.22)}
  .iq-tile--active.iq-tile--talking{animation:iqTileGlow 2s ease-in-out infinite}
  @keyframes iqTileGlow{
    0%,100%{box-shadow:0 0 0 2px rgba(0,196,160,.5),0 0 26px rgba(0,196,160,.22)}
    50%{box-shadow:0 0 0 2px rgba(0,196,160,.75),0 0 34px rgba(0,196,160,.36)}
  }
  /* Participant name tag, bottom-left of the tile — like a Meet label. It now has that
     corner to itself: the state text that used to land on top of it is the status strip. */
  .iq-tile-name{position:absolute;left:var(--tile-pad);bottom:var(--tile-pad);display:inline-flex;align-items:center;gap:7px;padding:5px 10px;border-radius:var(--radius-sm);background:rgba(11,22,40,.78);border:1px solid rgba(255,255,255,.12);color:#fff;font-size:12px;font-weight:700;font-family:'Plus Jakarta Sans',sans-serif;max-width:calc(100% - var(--tile-pad) * 2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;backdrop-filter:blur(4px)}
  .iq-tile-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  /* Student camera. LOCAL ONLY — never recorded, never uploaded, no MediaRecorder on
     this track anywhere. Mirrored, because a self-view that is not mirrored is unnerving. */
  .iq-tile-video{width:100%;height:100%;object-fit:cover;transform:scaleX(-1)}
  .iq-tile-initial{width:88px;height:88px;border-radius:50%;background:#1a2744;border:1px solid rgba(255,255,255,.10);display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.88);font-weight:800;font-size:32px;font-family:'Plus Jakarta Sans',sans-serif}

  /* THE STUDENT'S INPUT SURFACE — their own tile's bottom row, open only while their
     answer is in flight. Speaking an answer finally has a surface of its own; it used to
     borrow the interviewer's caption band and float over the stage. */
  .iq-surface{flex-shrink:0;display:flex;flex-direction:column;gap:8px;padding:10px 12px;background:rgba(0,196,160,.07);border-top:1px solid rgba(0,196,160,.28);animation:iqRise .2s ease}
  .iq-surface--captured{background:rgba(0,196,160,.10)}
  .iq-surface-top{display:flex;align-items:center;gap:10px;min-width:0}
  /* The waveform takes the slack between the "You" tag and the counter, so the row reads
     as one instrument at any tile width instead of a centred blob with gaps either side. */
  .iq-surface-top .iq-livewave{flex:1;min-width:0;height:26px;overflow:hidden}
  .iq-surface-tag{flex-shrink:0;display:inline-flex;align-items:center;gap:6px;font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#00C4A0}
  .iq-surface-time{margin-left:auto;flex-shrink:0;font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:12px;color:#E8521A;font-variant-numeric:tabular-nums}
  /* Their running "You:" transcript. DM Mono, verbatim, never beautified — and it scrolls
     inside a fixed height rather than growing the tile out from under the room. */
  .iq-surface-text{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:12.5px;line-height:1.5;color:#eafaf5;max-height:54px;overflow-y:auto;overflow-wrap:anywhere}
  .iq-surface-idle{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:12px;color:rgba(234,250,245,.5);animation:iqPulse 1.4s ease-in-out infinite}

  /* CAPTIONS — a FIXED-HEIGHT area of its own, and the height is reserved whether or not
     there is a caption in it, so the room never jumps as she starts and stops speaking.
     It SCROLLS; it does not clamp. The old band cut long questions off at two lines with
     an ellipsis, which on a three-sentence case prompt meant the question was literally
     unreadable — a caption that clips mid-sentence is worse than no caption, because it
     looks like it worked. */
  .iq-cc-area{flex-shrink:0;box-sizing:border-box;height:104px;margin:var(--gap) var(--pad) 0;padding:12px 16px;border-radius:var(--radius);background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);overflow-y:auto;scrollbar-width:thin}
  .iq-cc{color:#fff;font-size:15px;line-height:1.5;font-family:'Plus Jakarta Sans','Noto Sans Devanagari',sans-serif;overflow-wrap:anywhere}
  .iq-cc-empty{color:rgba(255,255,255,.3);font-size:13px;font-family:'DM Mono','SFMono-Regular',Menlo,monospace}

  /* Room notices: a blocked autoplay, an error, the rating, time running out. Genuinely
     exceptional, so the row exists only when one of them does — no permanent slot, and
     nothing floating in the middle of the call. */
  .iq-notice-row{flex-shrink:0;display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:10px;padding:var(--gap) var(--pad) 0}
  .iq-notice{padding:9px 14px;border-radius:var(--radius-sm);background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:rgba(255,255,255,.9);font-size:13px;font-weight:700;font-family:'Plus Jakarta Sans',sans-serif;text-align:center;max-width:100%;overflow-wrap:anywhere}
  .iq-notice--gold{background:rgba(200,153,42,.14);border-color:#C8992A;color:#F5B800}
  .iq-notice--err{background:rgba(232,82,26,.16);border-color:rgba(232,82,26,.5);color:#ffbda6}
  .iq-notice--warn{background:rgba(232,82,26,.10);border-color:rgba(232,82,26,.35);color:#ff9068;font-size:12px}

  /* THE ONE STATUS STRIP — under the tiles, above the captions. Every "what is happening"
     the room used to say in three floating places at once (a label under her face, a
     muted chip pinned over the stage, a chip in the header) it now says here, once.
     Colour never carries it alone: the label is always words. */
  .iq-strip-row{flex-shrink:0;display:flex;align-items:center;justify-content:center;padding:var(--gap) var(--pad) 0;min-height:34px;box-sizing:border-box}
  .iq-strip{display:inline-flex;align-items:center;gap:9px;max-width:100%;padding:6px 14px;border-radius:999px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.05);min-width:0}
  .iq-strip-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .iq-strip-label{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:11px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .iq-strip-detail{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:11.5px;color:rgba(255,255,255,.62);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
  .iq-strip--teal{border-color:rgba(0,196,160,.45);background:rgba(0,196,160,.10)}
  .iq-strip--teal .iq-strip-label{color:#00C4A0}
  .iq-strip--teal .iq-strip-dot{background:#00C4A0}
  .iq-strip--orange{border-color:rgba(232,82,26,.5);background:rgba(232,82,26,.12)}
  .iq-strip--orange .iq-strip-label{color:#ff9068}
  .iq-strip--orange .iq-strip-dot{background:#E8521A;animation:iqRecDot 1.1s ease-in-out infinite}
  .iq-strip--navy{border-color:rgba(200,153,42,.42);background:rgba(200,153,42,.10)}
  .iq-strip--navy .iq-strip-label{color:#F5B800}
  .iq-strip--navy .iq-strip-dot{background:#C8992A;animation:iqPulse 1.2s ease-in-out infinite}
  .iq-strip--idle .iq-strip-label{color:rgba(255,255,255,.55)}
  .iq-strip--idle .iq-strip-dot{background:rgba(255,255,255,.28)}
  /* Muted with an answer due: the strip stops describing and starts asking. It pulses to
     carry the eye down to the mic button in the bar below it. */
  .iq-strip--cue{animation:iqMutedCue 1.6s ease-in-out infinite}
  @keyframes iqMutedCue{0%{box-shadow:0 0 0 0 rgba(232,82,26,.45)}70%{box-shadow:0 0 0 8px rgba(232,82,26,0)}100%{box-shadow:0 0 0 0 rgba(232,82,26,0)}}

  /* THE CHAT PANEL — the full session transcript AND the composer, in one place, and
     deliberately MODE-AGNOSTIC: a collapsible third column in voice mode, and the second
     tile itself in text mode. Same component, same bubbles, same send path. */
  .iq-chat{display:flex;flex-direction:column;min-height:0;min-width:0;border-radius:var(--radius);overflow:hidden;background:#0f1c33;border:1px solid rgba(255,255,255,.10)}
  .iq-chat-h{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 12px;border-bottom:1px solid rgba(255,255,255,.08)}
  .iq-chat-title{font-size:12px;font-weight:800;color:#fff;font-family:'Plus Jakarta Sans',sans-serif;letter-spacing:.02em}
  /* Sentence case, not mono caps: this is a quiet aside telling them typing is always an
     option, and a shouted one reads as a warning about something. */
  .iq-chat-sub{font-family:'Plus Jakarta Sans',sans-serif;font-size:11px;color:rgba(255,255,255,.45);margin-top:2px}
  .iq-chat-b{flex:1;min-height:0;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;gap:12px;scrollbar-width:thin}
  .iq-chat-f{flex-shrink:0;display:flex;gap:8px;align-items:flex-end;padding:10px 12px;border-top:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.16)}
  .iq-chat-empty{font-size:12.5px;line-height:1.6;color:rgba(255,255,255,.42);font-family:'Plus Jakarta Sans',sans-serif}
  .iq-turn{display:flex;flex-direction:column;gap:4px;min-width:0}
  .iq-turn--me{align-items:flex-end}
  .iq-turn-who{font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:9.5px;font-weight:700;letter-spacing:.10em;text-transform:uppercase;color:rgba(255,255,255,.38)}
  .iq-bub{max-width:92%;padding:9px 12px;font-size:13px;line-height:1.6;font-family:'Plus Jakarta Sans','Noto Sans Devanagari',sans-serif;overflow-wrap:anywhere}
  .iq-bub--iq{align-self:flex-start;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.10);color:#eaf0fb;border-radius:3px var(--radius) var(--radius) var(--radius)}
  .iq-bub--me{align-self:flex-end;background:rgba(0,196,160,.13);border:1px solid rgba(0,196,160,.32);color:#eafaf5;border-radius:var(--radius) 3px var(--radius) var(--radius)}
  /* The "heard you" tick. A spoken answer is the one with no receipt — they typed nothing,
     they just talked at a laptop — so the tick is the receipt. */
  .iq-bub-meta{display:flex;align-items:center;gap:6px;font-family:'DM Mono','SFMono-Regular',Menlo,monospace;font-size:9.5px;color:rgba(255,255,255,.4)}
  .iq-bub-tick{display:inline-flex;color:#00C4A0}
  .iq-bub-fix{background:none;border:none;padding:0;cursor:pointer;font-size:9.5px;font-weight:700;color:rgba(255,255,255,.55);text-decoration:underline;font-family:'DM Mono','SFMono-Regular',Menlo,monospace}
  .iq-bub-fix:hover{color:#fff}
  .iq-chat-close{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:var(--radius-sm);border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.05);color:rgba(255,255,255,.7);cursor:pointer;flex-shrink:0}
  .iq-chat-close:hover{background:rgba(255,255,255,.12);color:#fff}
  .iq-chat-close:focus-visible{outline:2px solid #00C4A0;outline-offset:2px}
  /* The composer, in the room's dark register. */
  .iq-chat-in{flex:1;min-width:0;resize:none;min-height:40px;max-height:120px;padding:9px 11px;border-radius:var(--radius-sm);border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);color:#fff;font-size:13px;line-height:1.5;font-family:'Plus Jakarta Sans',sans-serif;outline:none;box-sizing:border-box}
  .iq-chat-in::placeholder{color:rgba(255,255,255,.35)}
  .iq-chat-in:focus{border-color:rgba(0,196,160,.6);box-shadow:0 0 0 3px rgba(0,196,160,.14)}
  .iq-chat-in:disabled{opacity:.5;cursor:not-allowed}
  .iq-chat-send{flex-shrink:0;height:40px;padding:0 15px;border-radius:var(--radius-sm);border:none;background:#00C4A0;color:#04231d;font-size:13px;font-weight:800;font-family:'Plus Jakarta Sans',sans-serif;cursor:pointer;transition:opacity .15s}
  .iq-chat-send:disabled{opacity:.35;cursor:not-allowed}
  .iq-chat-send:focus-visible{outline:2px solid #fff;outline-offset:2px}

  /* Bottom control bar — centred Meet-style pills. */
  .iq-bar{flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:10px;padding:14px 16px;background:#0B1628;border-top:1px solid rgba(255,255,255,.07);flex-wrap:wrap}
  .iq-ctl{display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:50%;border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);color:#fff;cursor:pointer;transition:all .15s;flex-shrink:0}
  .iq-ctl:hover{background:rgba(255,255,255,.13)}
  .iq-ctl:focus-visible{outline:2px solid #00C4A0;outline-offset:2px}
  .iq-ctl:disabled{opacity:.4;cursor:not-allowed}
  .iq-ctl--off{background:#E8521A;border-color:#E8521A}       /* device OFF = orange */
  .iq-ctl--off:hover{background:#cf460f}
  .iq-ctl--live{background:#E8521A;border-color:#E8521A;animation:iqMicPulse 1.4s ease-in-out infinite}
  .iq-ctl--on{background:rgba(0,196,160,.16);border-color:rgba(0,196,160,.55);color:#00C4A0}
  .iq-ctl--end{width:auto;padding:0 20px;border-radius:24px;background:#c0392b;border-color:#c0392b;font-weight:700;font-size:14px;font-family:'Plus Jakarta Sans',sans-serif}
  .iq-ctl--end:hover{background:#a33228}
  .iq-ctl-label{font-size:10px;color:rgba(255,255,255,.45);font-family:'DM Mono',monospace;letter-spacing:.06em;text-transform:uppercase}
  /* THE LMS EMBED (~1100–1400px) IS THE TARGET, and the layout is verified at 1100 /
     1280 / 1920. Everything below is what happens OUTSIDE that band — it degrades, it
     never breaks, and at no width does anything overflow or clip.
     At 1100 with the panel open the tiles are still ~350px each and still equal. */
  @media(max-width:1000px){
    /* The panel can no longer be a third column without squeezing the call to nothing,
       so it becomes an overlay ON the room — still the same panel, same component. */
    .iq-room-grid--chat{grid-template-columns:1fr 1fr}
    .iq-chat--side{position:absolute;top:var(--pad);right:var(--pad);bottom:var(--pad);width:min(340px,calc(100% - var(--pad) * 2));z-index:12;box-shadow:0 16px 44px rgba(0,0,0,.5)}
    .iq-room-grid{position:relative}
  }
  @media(max-width:820px){
    /* Under the embed's floor the two tiles stack rather than shrink into slivers. */
    .iq-room-grid{grid-template-columns:1fr;grid-auto-rows:1fr}
    .iq-room{--gap:12px;--pad:12px}
    .iq-cc-area{height:92px}
  }
  @media(max-width:640px){
    .iq-cc{font-size:14px}
    .iq-cc-area{height:86px;padding:10px 12px}
    .iq-ctl{width:44px;height:44px}
    .iq-tile-initial{width:64px;height:64px;font-size:24px}
  }

  /* Accessibility: nothing in the room may carry meaning by motion. Every state that
     animates also has WORDS — the strip's label, the tile's name tag — so switching the
     motion off costs nothing but the motion. Note what stays: the active-speaker RING
     itself, because it is the thing saying who has the floor; only its breathing stops.
     (InterviewerCharacter owns its own reduced-motion handling for the face.) */
  @media (prefers-reduced-motion: reduce) {
    .iq-tile--active.iq-tile--talking,.iq-strip--cue,.iq-strip-dot,.iq-surface-idle{animation:none!important}
    .iq-livebar{transition:none}
  }
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
  const [mode, setMode] = useState("interview");        // FEEDBACK style (interview|coach)
  const [sessionMode, setSessionMode] = useState(DEFAULT_SESSION_MODE);  // MODE: how they answer
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

  // Item 10(c): warm the backend the moment the lobby is on screen — non-blocking, so the
  // lobby itself never waits on it, and the first real call on Join isn't the cold one.
  useEffect(() => { pingHealth(); }, []);

  const handleStart = async () => {
    // Voice Phase 1: unlock audio inside this user gesture so iOS Safari will
    // allow the interviewer's voice to autoplay later.
    unlockAudioPlayback();
    try { localStorage.setItem(VOICE_KEY, voice); } catch { /* noop */ }
    setError(null); setTipIdx(0);
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
        mode,                    // FEEDBACK style — interview | coach
        session_mode: sessionMode,  // MODE — TEXT | AUDIO | VIDEO
        round,
        round_label: selectedRound?.l || "Full Interview",
        round_detail: selectedRound?.detail || "",
        focus: allFocus,
        intro,
        // The JD travels as its OWN field now. It used to be glued onto `intro` behind a
        // "--- JOB DESCRIPTION ---" delimiter that the server split apart again — which
        // meant a student who pasted that literal string into their JD re-partitioned
        // their own session, and (worse) any student with a résumé on file had their JD
        // silently swallowed into the self-intro half and never read as a JD at all.
        // A field cannot be forged by its own contents.
        jd,
        voice,
      };
      // Interview Room: the session is NOT started here any more. The pre-join lobby
      // comes next (one permission moment + mic check), and the session starts when
      // they Join — so camera_at_join and the roster-picked interviewer can ride along
      // on /session/start.
      onStart({ ...payload, focus: allFocus });
    } catch (e) { setError(e.message); setStarting(false); }
  };

  if (starting) return (
    <div style={{ fontFamily: T.font, width: "100%", boxSizing: "border-box", padding: "100px 28px", textAlign: "center" }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: T.navy, marginBottom: 8 }}>Preparing your interview...</div>
      <div style={{ fontSize: 13, color: T.muted, marginBottom: 28 }}>Setting up personalized questions for {userName || "you"}</div>
      <div style={{ width: 200, height: 3, borderRadius: 2, background: T.border, overflow: "hidden", margin: "0 auto 32px" }}>
        <div style={{ height: "100%", background: T.navy, borderRadius: 2, animation: "iqLoad 2s ease-in-out infinite" }} />
      </div>
      <div style={{ padding: "14px 24px", borderRadius: 10, background: T.bg, border: "1px solid " + T.border, display: "inline-block", fontSize: 13, color: T.muted, maxWidth: 400, lineHeight: 1.6, animation: "iqFade .5s ease" }} key={tipIdx}>{LOADING_TIPS[tipIdx]}</div>
    </div>
  );

  return (
    <div style={{ fontFamily: T.font, width: "100%", boxSizing: "border-box", padding: "24px 28px" }}>
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

          {/* MODE — how they answer. Three equal chips (.vg3), same .vchip style as every
              other setting. Default Audio: it is what every session did before this card
              existed, so an untouched picker changes nothing for anyone. */}
          <div className="vc">
            <div className="vc-h"><span className="vc-t">Mode</span></div>
            <div className="vc-b">
              <div className="vg3">
                {SESSION_MODES.map(m => (
                  <button
                    key={m.v}
                    className={"vchip" + (sessionMode === m.v ? " vchip-on" : "")}
                    aria-pressed={sessionMode === m.v}
                    onClick={() => setSessionMode(m.v)}
                    style={{ padding: "8px 6px" }}
                  >
                    {m.l}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 11, color: T.subtle, marginTop: 6 }}>
                {(SESSION_MODES.find(m => m.v === sessionMode) || {}).d}
              </div>
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

              {/* Item 10(a): difficulty is ONE row of four equal chips. Critical is a chip
                  like the others — a red dot + "Pressure panel" subtext mark it apart — and
                  its full warning appears BELOW the row only once it is actually selected.
                  The row wraps to 2×2 under ~700px. */}
              <label className="vl" style={{ marginTop: 14 }}>Difficulty</label>
              <div className="iq-diff4">
                {DIFF_CHIPS.map(d => {
                  const on = difficulty === d.v;
                  return (
                    <button key={d.v}
                      className={"vopt" + (on ? (d.critical ? " vopt-crit-on" : " vopt-on") : "")}
                      onClick={() => setDifficulty(d.v)} aria-pressed={on}
                      style={{ textAlign: "center", padding: "12px 10px" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                        {d.critical && <span className="iq-critical-dot" />}
                        <span style={{ fontWeight: 700, fontSize: 13, color: d.critical && on ? T.red : T.navy }}>{d.l}</span>
                      </div>
                      <div style={{ fontSize: 11, color: T.subtle, marginTop: 2 }}>{d.d}</div>
                    </button>
                  );
                })}
              </div>
              {difficulty === CRITICAL.v && (
                <div className="iq-critical-warn" role="note">
                  The interviewer will challenge every answer you give, push back on weak
                  reasoning, and cut you off if you ramble. She will never insult you — the
                  criticism lands on your answers, never on you — but she will not be kind
                  about the answers.
                </div>
              )}

              {/* Item 10(b): heading only — the Interview / Coach options and their behaviour
                  are unchanged. "Feedback" says what the choice actually controls. */}
              <label className="vl" style={{ marginTop: 14 }}>Feedback</label>
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

      {/* ── A6: the confirmation card ────────────────────────────────────────
          The session you are about to have, in one place, before you pay for it.

          These are the same fields, in the same order, that intake.SessionConfig.card()
          returns on the server — which is what the readout's Session Profile strip and the
          attempt record both render. It reads from form state rather than a round trip
          because every field here is form-owned and FORM WINS (A2): what you typed IS the
          answer, so there is nothing the server could tell us about these that we do not
          already know. Anything NOT form-owned must not be added to this card without
          fetching the merged object, or the card and the readout will drift — which is the
          exact failure A6 exists to prevent. */}
      <div className="vc" style={{ marginTop: 14, borderLeft: "3px solid " + T.teal }}>
        <div className="vc-h"><span className="vc-t">Your session</span></div>
        <div className="vc-b">
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 22px" }}>
            {[
              ["Role", finalRole],
              ["Level", level],
              ["Difficulty", difficulty],
              ["Length", `${duration} min`],
              ["Mode", (SESSION_MODES.find(m => m.v === sessionMode) || {}).l],
              ["Feedback", mode === "coach" ? "Coach" : "Interview"],
              ["Round", (ROUNDS.find(r => r.v === round) || {}).l],
              ["JD", jd.trim() ? "Used" : "Not used"],
            ].map(([k, v]) => (
              <div key={k}>
                <div style={{ fontSize: 10, fontWeight: 700, color: T.subtle, textTransform: "uppercase", letterSpacing: ".04em" }}>{k}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: T.navy, marginTop: 2 }}>{v || "—"}</div>
              </div>
            ))}
          </div>
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
                {/* QA-06: "pending legal review" is an internal process marker, and it was
                    being shown to students — asking them to consent under a notice that says
                    on its face it is not approved. Dev-only now, matching the DRAFT · LEGAL
                    PENDING pill this file already gates the same way. The COPY still needs
                    legal sign-off; hiding the marker does not grant it. */}
                {import.meta.env?.DEV && (
                  <span style={{ color: T.subtle }}> (Draft notice — pending legal review.)</span>
                )}
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


// Voice Phase 2: consent modal shown on first mic use per session. Recorded as
// consent_type="voice_recording", copy_version="v0-draft".
// [PENDING LEGAL REVIEW] — VOICE_CONSENT_FULL below is the disclosure text
// awaiting legal sign-off (production gate #1). Do NOT delete it; only its
// wording may change after review. The compact modal shows a one-line notice
// and keeps the full copy one tap away behind "How voice answers work".
const VOICE_CONSENT_SHORT = "Your answer is saved as text — audio is never stored.";
const VOICE_CONSENT_FULL =
  "InterviewIQ converts your spoken answer to text. Your audio is transcribed " +
  "and immediately discarded — it is never stored. Only the text of your answer " +
  "is saved, exactly as if you had typed it. You can switch to typing at any time.";

function VoiceConsentModal({ onAccept, onDecline, busy }) {
  const [showFull, setShowFull] = useState(false);
  const isDev = import.meta.env?.DEV;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(11,22,40,.72)", backdropFilter: "blur(3px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onDecline}>
      <div onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Use your voice to answer"
        style={{ background: "#FDFCF9", borderRadius: 20, maxWidth: 400, width: "100%", padding: "28px 26px 24px", fontFamily: IQ.sans, boxShadow: "0 24px 64px rgba(4,10,22,.5)", animation: "iqFade .25s ease" }}>
        <div style={{ width: 52, height: 52, borderRadius: 16, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", background: "rgba(0,196,160,.12)", color: IQ.teal }}>
          <IconMic size={24} />
        </div>
        <div style={{ textAlign: "center", color: IQ.navy, fontSize: 19, fontWeight: 800, letterSpacing: "-.01em", marginBottom: 8 }}>
          Use your voice to answer
        </div>
        <p style={{ margin: "0 0 18px", textAlign: "center", color: "#4A5872", fontSize: 14.5, lineHeight: 1.5 }}>
          {VOICE_CONSENT_SHORT}
          {isDev && <span style={{ display: "inline-block", marginLeft: 8, padding: "2px 7px", borderRadius: 999, background: "rgba(232,82,26,.12)", color: IQ.orange, fontSize: 10, fontWeight: 700, letterSpacing: ".06em", verticalAlign: "middle" }}>DRAFT · LEGAL PENDING</span>}
        </p>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onAccept} disabled={busy} className="vbtn" style={{ background: IQ.navy, borderRadius: 12, opacity: busy ? 0.6 : 1 }}>Allow &amp; record</button>
          <button onClick={onDecline} disabled={busy} className="vbtn" style={{ background: "transparent", color: IQ.navy, border: "1.5px solid #D7DCE5", borderRadius: 12 }}>Not now</button>
        </div>
        <button onClick={() => setShowFull(v => !v)}
          style={{ display: "block", margin: "14px auto 0", background: "none", border: "none", color: "#00A88A", fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: IQ.sans }}>
          {showFull ? "Hide details" : "How voice answers work"}
        </button>
        {showFull && (
          <div style={{ margin: "12px 0 0", padding: "12px 14px", borderRadius: 12, background: "#F2F4F8", color: "#4A5872", fontSize: 12.5, lineHeight: 1.55 }}>
            {VOICE_CONSENT_FULL}
          </div>
        )}
      </div>
    </div>
  );
}

// ── VOICE STAGE components ───────────────────────────────────────────────────
// A presentation layer over the SAME state machine — no stage/rating/consent/
// scoring logic lives here. Colour never carries meaning alone: every state also
// shows a persistent text label (and reduced-motion collapses the orb to a ring).

/**
 * useTileHeight — measure a tile so the interviewer's portrait can be sized to fit it.
 *
 * InterviewerCharacter is a fixed-aspect card (size x size*1.25), not a fluid box, so it
 * cannot simply be told to fill. Rather than pick a number and hope — the old room hard-
 * coded 220 and let it overflow whatever it landed in — we measure the tile and derive the
 * size from it. This is what makes 1100→1920 hold without a single width breakpoint for
 * the portrait: it is always exactly as big as the room it is standing in.
 */
function useTileSize(ref) {
  const [box, setBox] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const read = (w, h) => setBox(p => (p.w === w && p.h === h ? p : { w, h }));
    const ro = new ResizeObserver(([e]) => read(e.contentRect.width, e.contentRect.height));
    ro.observe(el);
    const r = el.getBoundingClientRect();
    read(r.width, r.height);
    return () => ro.disconnect();
  }, [ref]);
  return box;
}

/**
 * InterviewerTile — her half of the call.
 *
 * InterviewerCharacter (v4.2) owns BOTH the roster (face + name, picked by voice/difficulty
 * and seeded on the session id) and the TTS analyser that drives its speaking waveform —
 * there must be exactly one analyser in the app, because createMediaElementSource() may be
 * called only once per audio element.
 *
 * The state LABEL that used to sit under her (and land on top of her name tag) is gone from
 * here: it is the status strip's job now, and there is exactly one of it.
 */
function InterviewerTile({ state, active, voice, difficulty, seed, tone, escalationLevel, stage, group, name }) {
  const bodyRef = useRef(null);
  const { w, h } = useTileSize(bodyRef);
  // The card is size x size*1.25 — TALLER than it is wide — so it can run out of either
  // axis, and the size is whichever runs out first. Height alone is the tempting version
  // and it is wrong: at 1100 with the chat panel open the tile is ~350px wide, and a size
  // picked off a 460px-tall body would push a 368px-wide portrait straight out through the
  // sides of its own tile.
  const byHeight = ((h || 260) - 24) / 1.25;
  const byWidth = (w || 260) - 24;
  const size = Math.max(110, Math.min(400, Math.round(Math.min(byHeight, byWidth))));
  return (
    <section className={"iq-tile" + (active ? " iq-tile--active iq-tile--talking" : "")}
      aria-label="Interviewer">
      <div className="iq-tile-body" ref={bodyRef}>
        {h > 0 && (
          <InterviewerCharacter state={state} voice={voice} size={size}
            difficulty={difficulty} seed={seed}
            tone={tone} escalationLevel={escalationLevel} stage={stage} group={group} />
        )}
        <div className="iq-tile-name">
          <span className="iq-tile-dot" style={{ background: active ? IQ.teal : "rgba(255,255,255,.3)" }} />
          {(name || "Interviewer")} · InterviewIQ
        </div>
      </div>
    </section>
  );
}

/**
 * StudentTile — their half of the call: camera (or their initial), name tag, and the
 * INPUT SURFACE that opens underneath while their answer is in flight.
 *
 * PRIVACY (unchanged from SelfView, and the reason this is worth restating):
 *   The camera stream is LOCAL ONLY. It is rendered into a muted <video> and is NEVER
 *   recorded, captured to a canvas, uploaded, or transmitted. There is deliberately no
 *   MediaRecorder anywhere on this track. Attention monitoring (when it lands) runs
 *   on-device and emits event STRINGS — never a frame.
 *
 * The surface is a SIBLING of the body, not an overlay on it, so it cannot collide with the
 * name tag however long the transcript runs. See the CSS note on .iq-tile.
 */
function StudentTile({ on, micOn, initial, name, active, surface, levels, recLabel }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const textRef = useRef(null);

  // Their running transcript scrolls itself, so the newest words are the visible ones —
  // a caption you have to scroll to read is a caption you do not read.
  useEffect(() => {
    const el = textRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [surface.caption]);

  useEffect(() => {
    let cancelled = false;
    const stop = () => {
      const s = streamRef.current;
      if (s) { try { s.getTracks().forEach(t => t.stop()); } catch { /* noop */ } streamRef.current = null; }
      if (videoRef.current) videoRef.current.srcObject = null;
    };
    if (!on || typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      stop();
      return stop;
    }
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        });
        if (cancelled) { s.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      } catch { /* camera unavailable -> the initial-letter tile stands in */ }
    })();
    return () => { cancelled = true; stop(); };
  }, [on]);

  const live = surface.phase === SURFACE_LIVE;
  return (
    <section className={"iq-tile" + (active ? " iq-tile--active iq-tile--talking" : "")}
      aria-label="You">
      <div className="iq-tile-body">
        {on
          ? <video className="iq-tile-video" ref={videoRef} autoPlay muted playsInline />
          : <div className="iq-tile-initial">{initial}</div>}
        <div className="iq-tile-name">
          <span className="iq-tile-dot" style={{ background: micOn ? IQ.teal : IQ.orange }}
            title={micOn ? "Mic on" : "Mic off"} />
          {name || "You"}
        </div>
      </div>

      {/* THE INPUT SURFACE. Live: the real waveform (heights come from the AnalyserNode,
          not an animation) and their own running transcript. Captured: the tick — the
          answer is ours, and they can see that it is, before she starts replying. */}
      {surface.open && (
        <div className={"iq-surface" + (live ? "" : " iq-surface--captured")}>
          <div className="iq-surface-top">
            {live ? (
              <>
                <span className="iq-surface-tag">You</span>
                <LiveWave levels={levels} />
                <span className="iq-surface-time">{recLabel}</span>
              </>
            ) : (
              <span className="iq-surface-tag">
                <span className="iq-bub-tick"><IconCheck size={13} /></span> Answer captured
              </span>
            )}
          </div>
          {surface.showCaption && (
            surface.caption
              ? <div className="iq-surface-text" ref={textRef}>{surface.caption}</div>
              : live && <div className="iq-surface-idle">listening…</div>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * ChatPanel — the session, as a conversation you can read and write.
 *
 * This is ONE component doing three jobs that used to be three places:
 *   - the full transcript (was: a modal drawer you had to open, read, and dismiss);
 *   - the composer (was: `iq-typebar`, a separate slide-out under the control bar);
 *   - the correction affordance for a mis-transcribed answer (was: in the drawer).
 *
 * It is MODE-AGNOSTIC on purpose. In voice mode it is a collapsible third column; in text
 * mode it takes the student tile's place and becomes the primary surface — the room stays
 * two tiles either way. Nothing in here asks which mode it is in; the caller picks the slot
 * (roomLayout.chatSlot) and the panel is the same panel.
 *
 * TYPED = SPOKEN. `onSend` is the same send path a spoken answer takes — the composer is
 * not a fallback for when the mic fails, it is the other way to answer, available on every
 * question, always.
 *
 * READING IS NOT TYPING. The panel reports composer FOCUS to its caller (`onComposer`), not
 * its own visibility. Opening this to re-read an earlier question must not disarm the
 * microphone — see roomLayout.composerIntent, which exists entirely because of this.
 */
function ChatPanel({
  messages, name, onClose, onSend, onEditLast, editBusy,
  input, setInput, disabled, placeholder, onComposer, composerRef,
}) {
  const bodyRef = useRef(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const lastUserIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "user") return i;
    return -1;
  })();
  // Follow the conversation. A transcript panel that sits on turn 1 while she is asking
  // turn 6 is a panel showing you the wrong question.
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, editing]);

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!disabled && input.trim()) onSend(); }
  };

  return (
    <aside className="iq-chat" aria-label="Chat and transcript">
      <div className="iq-chat-h">
        <div style={{ minWidth: 0 }}>
          <div className="iq-chat-title">Chat</div>
          <div className="iq-chat-sub">Type an answer any time</div>
        </div>
        {onClose && (
          <button className="iq-chat-close" onClick={onClose}
            aria-label="Close chat" title="Close chat"><IconClose size={15} /></button>
        )}
      </div>

      <div className="iq-chat-b" ref={bodyRef}>
        {messages.length === 0 && (
          <div className="iq-chat-empty">
            Every question and answer appears here, so you can look back at any of them.
            You can type an answer here at any time.
          </div>
        )}
        {messages.map((m, i) => {
          const isV = m.role === "assistant";
          const isLastAnswer = !isV && i === lastUserIdx && !!onEditLast;
          const meta = isV ? null : bubbleMeta(m.meta);
          return (
            <div key={i} className={"iq-turn" + (isV ? "" : " iq-turn--me")}>
              <span className="iq-turn-who">{isV ? "InterviewIQ" : (name || "You")}</span>
              {isLastAnswer && editing ? (
                <div style={{ width: "100%" }}>
                  <textarea value={draft} onChange={e => setDraft(e.target.value.slice(0, 4000))} rows={4} autoFocus
                    aria-label="Correct your last answer" className="iq-chat-in"
                    style={{ width: "100%", maxHeight: 160 }} />
                  <div style={{ display: "flex", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
                    <button className="iq-chat-close" style={{ width: "auto", padding: "0 12px", height: 32, fontSize: 12, fontWeight: 700 }}
                      onClick={() => setEditing(false)} disabled={editBusy}>Cancel</button>
                    <button className="iq-chat-send" style={{ height: 32, fontSize: 12 }}
                      disabled={editBusy || !draft.trim()}
                      onClick={async () => { await onEditLast(draft.trim()); setEditing(false); }}>
                      {editBusy ? "Saving…" : "Save correction"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className={"iq-bub " + (isV ? "iq-bub--iq" : "iq-bub--me")}>
                  {isV ? renderMd(m.content) : m.content}
                </div>
              )}
              {!isV && !editing && (meta || isLastAnswer) && (
                <div className="iq-bub-meta">
                  {meta && (
                    <>
                      {/* The receipt for an answer they only ever spoke. */}
                      {meta.tick && <span className="iq-bub-tick"><IconCheck size={11} /></span>}
                      <span>{meta.label}</span>
                    </>
                  )}
                  {isLastAnswer && (
                    // Fix a mis-transcription: rewrites the stored answer so the debrief
                    // scores what you meant. (IQ has already replied to the original.)
                    <button className="iq-bub-fix" onClick={() => { setDraft(m.content); setEditing(true); }}>
                      Correct this
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="iq-chat-f">
        <textarea ref={composerRef} className="iq-chat-in" value={input} rows={1} maxLength={4000}
          onChange={e => setInput(e.target.value.slice(0, 4000))}
          onKeyDown={handleKey}
          onFocus={() => onComposer(true)}
          onBlur={() => onComposer(false)}
          disabled={disabled} placeholder={placeholder} aria-label="Type your answer" />
        <button className="iq-chat-send" onClick={onSend} disabled={disabled || !input.trim()}>Send</button>
      </div>
    </aside>
  );
}

// Real mic input — heights come from the Web Audio AnalyserNode, not an animation.
function LiveWave({ levels }) {
  return (
    <div className="iq-livewave" aria-hidden="true">
      {levels.map((v, i) => (
        <span key={i} className="iq-livebar"
          style={{ height: Math.max(3, Math.min(34, Math.round(v * 170))) + "px" }} />
      ))}
    </div>
  );
}

function TranscriptDrawer({ open, onClose, messages, name, onEditLast, editBusy }) {
  // Realism v2: the answer is auto-submitted, so correction happens HERE — the most
  // recent answer can be edited in the drawer and re-submitted idempotently.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const lastUserIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "user") return i;
    return -1;
  })();
  useEffect(() => { if (!open) setEditing(false); }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="iq-drawer-back" onClick={onClose} />
      <aside className="iq-drawer" role="dialog" aria-label="Conversation transcript">
        <div className="iq-drawer-h">
          <span style={{ fontSize: 14, fontWeight: 800, color: T.navy }}>Transcript</span>
          <button onClick={onClose} aria-label="Close transcript" className="iq-audio-btn"
            style={{ background: T.bg, border: "1px solid " + T.border, color: T.navy }}><IconClose /></button>
        </div>
        <div className="iq-drawer-b">
          {messages.length === 0 && <div style={{ fontSize: 13, color: T.muted }}>The conversation will appear here.</div>}
          {messages.map((m, i) => {
            const isV = m.role === "assistant";
            const isLastAnswer = !isV && i === lastUserIdx && !!onEditLast;
            return (
              <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: isV ? "flex-start" : "flex-end" }}>
                <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: T.subtle, marginBottom: 3 }}>
                  {isV ? "InterviewIQ" : (name || "You")}
                </span>
                {isLastAnswer && editing ? (
                  <div style={{ width: "100%" }}>
                    <textarea value={draft} onChange={e => setDraft(e.target.value.slice(0, 4000))} rows={4} autoFocus
                      aria-label="Correct your last answer" className="vi"
                      style={{ width: "100%", resize: "vertical", fontSize: 13, lineHeight: 1.6, borderRadius: 8 }} />
                    <div style={{ display: "flex", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
                      <button className="vchip" style={{ padding: "6px 12px", fontSize: 12 }}
                        onClick={() => setEditing(false)} disabled={editBusy}>Cancel</button>
                      <button className="mba-btn-primary" style={{ padding: "7px 16px", fontSize: 12, opacity: editBusy || !draft.trim() ? 0.5 : 1 }}
                        disabled={editBusy || !draft.trim()}
                        onClick={async () => { await onEditLast(draft.trim()); setEditing(false); }}>
                        {editBusy ? "Saving…" : "Save correction"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ padding: "10px 13px", borderRadius: isV ? "2px 10px 10px 10px" : "10px 2px 10px 10px", maxWidth: "92%", fontSize: 13, lineHeight: 1.6, background: isV ? T.white : T.navy, color: isV ? T.text : "#fff", border: isV ? "1px solid " + T.border : "none" }}>
                    {isV ? renderMd(m.content) : m.content}
                  </div>
                )}
                {!isV && !editing && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                    {m.meta && (
                      <span style={{ fontSize: 10, color: T.subtle, fontFamily: IQ.mono }}>
                        {m.meta === "SPOKEN" ? "Spoken" : m.meta === "SKIPPED" ? "Time ran out" : "Typed"}
                      </span>
                    )}
                    {isLastAnswer && (
                      // Fix a mis-transcription: rewrites the stored answer so the debrief
                      // scores what you meant. (IQ has already replied to the original.)
                      <button onClick={() => { setDraft(m.content); setEditing(true); }}
                        style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 10, fontWeight: 700, color: T.navy, textDecoration: "underline", fontFamily: IQ.sans }}>
                        Correct this
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </aside>
    </>
  );
}

function Switch({ on, onChange, label }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={"iq-switch" + (on ? " iq-switch-on" : "")}>
      <span className="iq-switch-knob" />
    </button>
  );
}

function StageSettingsMenu({ onClose, voiceStage, setVoiceStage,
                            captions, setCaptions, selfCaptions, setSelfCaptions,
                            selfCaptionsSupported, voice, setVoice }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const dim = { opacity: voiceStage ? 1 : 0.45 };
  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 70 }} onClick={onClose} />
      <div className="iq-menu" role="menu">
        <div className="iq-menu-row"><span>Voice mode</span>
          <Switch on={voiceStage} onChange={setVoiceStage} label="Voice mode" /></div>
        <div className="iq-menu-row" style={dim}><span>Captions</span>
          <Switch on={captions} onChange={setCaptions} label="Captions" /></div>
        {selfCaptionsSupported && (
          <div className="iq-menu-row" style={dim}>
            <span>Live captions of me
              <span style={{ display: "block", fontSize: 10.5, color: "rgba(0,0,0,.45)", marginTop: 2, maxWidth: 190, lineHeight: 1.4 }}>
                Transcribes your speech as you talk
              </span>
            </span>
            <Switch on={selfCaptions} onChange={setSelfCaptions} label="Live captions of me" /></div>
        )}
        <div className="iq-menu-sep" />
        <div className="iq-menu-row"><span>Interviewer voice</span>
          <div style={{ display: "flex", gap: 6 }}>
            {["female", "male"].map(v => (
              <button key={v} onClick={() => setVoice(v)}
                className={"vchip" + (voice === v ? " vchip-on" : "")}
                style={{ padding: "5px 12px", fontSize: 12 }}>{v === "female" ? "Female" : "Male"}</button>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function InterviewScreen({ config, sessionId, greeting, greetingSegments, initialState, initialMessages, startedAt, onEnd, onRestart }) {
  // INT-06: on resume we hydrate from server history.
  // FAST START: on a fresh start there is NO greeting yet — /session/start returned the
  // session row and nothing else, so the room could go up immediately. We open with an
  // empty transcript and a "connecting" caption band, and fetch the greeting from here.
  const [messages, setMessages] = useState(() => {
    if (initialMessages && initialMessages.length) return initialMessages;
    if (greeting) return [{ role: "assistant", content: greeting, audio_segments: greetingSegments || [] }];
    return [];
  });
  // True until the interviewer has actually said something. Drives the caption band's
  // shimmer — the room is up, she is there, she is drawing breath.
  const [connecting, setConnecting] = useState(() => !(initialMessages?.length) && !greeting);
  const greetingFetchedRef = useRef(false);
  // Voice Phase 1: playback state.
  // E2: the interviewer is ALWAYS audible — there is no mute control. Accessibility
  // is served by the CC captions toggle, not by silencing the panel.
  const [muted] = useState(false);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);   // autoplay blocked (iOS) → tap-to-play
  const playedIdxRef = useRef(-1);                    // last message index auto-played
  const speakTokenRef = useRef(null);                 // E2: cancels a superseded sentence run
  const playAbortRef = useRef(null);                  // settles the in-flight clip on a barge-in
  // THE CAPTURE INVARIANT (see roomPolicy.canArmCapture). These three say "she has not
  // finished speaking", and they are REFS, not state, on purpose: the mic is armed from
  // callbacks and rAF loops that would read a stale render's `audioPlaying`, and one stale
  // read is a recording that starts over the top of the question it is meant to answer.
  const audioPlayingRef = useRef(false);   // a clip is in the air RIGHT NOW
  const speechQueuedRef = useRef(false);   // her reply has arrived; playback has not begun
  const connectingRef = useRef(true);      // FAST START: her opening has not arrived at all
  const [spokenLine, setSpokenLine] = useState("");   // E2: the sentence being spoken RIGHT NOW
  // POSES: the register the server says this turn carries, and the focus-ladder level.
  // The face follows the words — warm -> smile, probing -> intense, neutral -> alternate.
  const [tone, setTone] = useState("warm");           // the greeting is warm
  const [escalationLevel, setEscalationLevel] = useState(0);
  const audioBlobCache = useRef(new Map());           // audio_url -> object URL (so Replay reuses, no re-fetch)
  // REALISM: the pre-cached clip pack ({acks, backchannels}) and where we are in its
  // rotation. Seeded by the answer count, so the same session never loops the same "Hmm."
  const clipsRef = useRef({ acks: [], backchannels: [] });
  const ackSeedRef = useRef(0);
  // REALISM (backchannels): per-answer state — how many "mm-hmm"s this answer has had, and
  // when the current pause began. Reset at the start of every recording.
  const bcCountRef = useRef(0);
  const bcPauseStartRef = useRef(0);
  // REALISM (barge-in): the mic stays open while the interviewer speaks, purely to hear
  // whether the candidate has started talking over her. `warmStream` is that open mic —
  // handed straight to the recorder on barge-in, so their first word is not lost to a
  // second getUserMedia round trip.
  const bargeCtxRef = useRef(null);
  const bargeRafRef = useRef(null);
  const bargeAboveSinceRef = useRef(0);
  const bargedRef = useRef(false);
  const warmStreamRef = useRef(null);
  // What the interviewer ACTUALLY said aloud, sentence by sentence, this reply. On a
  // barge-in the caption shows this and not the rest — she was interrupted, and pretending
  // otherwise would put words in her mouth that the candidate never heard.
  const spokenSoFarRef = useRef("");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // Voice Phase 2: spoken-answer (STT) state — BEHAVIOURAL round only.
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [recSeconds, setRecSeconds] = useState(0);
  // The LOBBY is the consent moment: joining with the mic on records a voice_recording
  // grant (see App.handleJoin), so re-asking here was a second modal for a permission they
  // had already given — and, worse, it left hands-free DEAD until they clicked the mic
  // once, which is precisely the manual tap the voice stage exists to remove. If they
  // joined muted, consent is still explicit and still asked for at first mic use.
  const [voiceConsented, setVoiceConsented] = useState(() => config.mic !== false);
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

  // ── Voice Stage: presentation state only (the state machine is untouched) ──
  const [voiceStage, setVoiceStageState] = useState(() => getFlagPref(STAGE_KEY, true));
  const [captions, setCaptionsState] = useState(() => getFlagPref(CAPTIONS_KEY, true));
  const [voicePref, setVoicePrefState] = useState(() => config.voice || getVoicePref());
  const [menuOpen, setMenuOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [heard, setHeard] = useState(null);                  // "Heard: …" caption flash (3s)
  const [ratingPills, setRatingPills] = useState(false);     // pills fallback for the rating
  const [editBusy, setEditBusy] = useState(false);           // drawer correction in flight
  const [levels, setLevels] = useState(() => new Array(WAVE_BARS).fill(0));
  const [graceMs, setGraceMs] = useState(0);                 // auto-listen grace beat
  const [selfCaption, setSelfCaption] = useState("");        // live "You:" transcript (item 6)
  const [selfCaptions, setSelfCaptionsState] = useState(() => getFlagPref(SELFCAP_KEY, false));  // default OFF
  const [heardSpeechThisQ, setHeardSpeechThisQ] = useState(false);  // failsafe-chip visibility
  const setVoiceStage = (v) => { setVoiceStageState(v); setFlagPref(STAGE_KEY, v); };
  const setCaptions = (v) => { setCaptionsState(v); setFlagPref(CAPTIONS_KEY, v); };
  // Item 6: live self-captions now transcribe through OUR OWN Saarika STT (the same path the
  // answer already uses) — no third-party speech service — so enabling them opens no new data
  // path. Kept OFF by default only because the rolling-window partials cost extra STT calls;
  // it is a pure cost/product choice now, not a privacy one.
  const setSelfCaptions = (v) => {
    setSelfCaptionsState(v); setFlagPref(SELFCAP_KEY, v);
  };
  const setVoicePref = (v) => { setVoicePrefState(v); try { localStorage.setItem(VOICE_KEY, v); } catch { /* noop */ } };

  // Web Audio (real mic level: live waveform + trailing-silence auto-stop).
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const rafRef = useRef(null);
  const silenceStartRef = useRef(0);
  const spokeRef = useRef(false);      // only arm silence-stop once they've actually spoken
  const graceRafRef = useRef(null);
  const heardTimerRef = useRef(null);
  // ── Capture instrumentation (item 3/4/8) ──
  const peakRmsRef = useRef(0);          // loudest frame this recording (0..1)
  const rmsSumRef = useRef(0);           // running sum + count -> mean RMS over the answer
  const rmsFramesRef = useRef(0);
  const grantedSettingsRef = useRef(null);   // MediaTrackSettings the browser actually gave
  const turnLogRef = useRef(null);       // the one-line-per-answer accumulator
  const noiseCoachCountRef = useRef(0);  // clear-speech-but-unusable attempts, this question run
  const noiseCoachedRef = useRef(false); // the in-session noise line has been said once
  // The failsafe timer chip surfaces only when nothing has been heard yet on this question.
  const heardSpeechThisQRef = useRef(false);
  // Live self-captions from our own Saarika STT (item 6): the rolling-window loop's state.
  const selfCapActiveRef = useRef(false);   // the window loop is running
  const selfCapRecRef = useRef(null);       // the current short-window MediaRecorder
  const selfCapTextRef = useRef("");         // accumulated caption text across windows
  const selfCapWindowsRef = useRef(0);       // windows transcribed this answer (cost cap)
  // Realism v2 flow refs.
  const sttFailRef = useRef(0);          // consecutive STT failures (typed fallback at 2)
  const ratingListeningRef = useRef(false);  // the open mic is capturing a SPOKEN RATING
  const ratingAskedRef = useRef(false);      // the "how confident?" line has been spoken
  const ratingAudioRef = useRef(null);       // audio for that line, from the turn response
  const ratingPromptRef = useRef("");        // its text, for the caption
  const ratingSilenceRef = useRef(null);     // 8s no-speech timer -> show the pills
  const busyRef = useRef(false);             // a re-ask / nudge is in flight
  const loadingRef = useRef(false);         // a TURN is in flight — she is about to speak
  const muteForkRef = useRef(null);          // the 5s "you're on mute" timer
  const muteForkedForRef = useRef("");       // question we already offered the fork for
  // Refs mirror state for the <audio> 'ended' handler and the rAF loop, which would
  // otherwise close over stale values.
  const micOnRef = useRef(true);   // MIC = mute toggle; unmuted is the capture gate
  const roomModeRef = useRef(false);
  const canAnswerRef = useRef(false);
  const consentRef = useRef(false);
  const recordingRef = useRef(false);
  const transcribingRef = useRef(false);
  const typedInVoiceRef = useRef(false);
  const awaitingRatingRef = useRef(false);
  const ratingPillsRef = useRef(false);
  // INT-06: timer remaining is derived from the persisted start time so a refresh
  // resumes the same countdown instead of restarting it.
  const [secondsLeft, setSecondsLeft] = useState(() => {
    const total = config.duration_min * 60;
    if (!startedAt) return total;
    return Math.max(0, total - Math.floor((Date.now() - startedAt) / 1000));
  });
  // ── E7.7: the per-question clock ──
  // Every question carries its own budget, and it is ALWAYS on screen — a clock the
  // candidate cannot see is a trap. When it runs out, something always happens: whatever
  // they got out is submitted, or the question is skipped and the interview moves on.
  // The mic never sits waiting on a question whose time is gone.
  const [qLeft, setQLeft] = useState(null);      // seconds left; null = no clock running
  // "question" | "checkin". The engagement floor's check-in is a direct question with its
  // own short clock — a yes/no does not need three minutes, and giving it three minutes
  // would just be three more minutes of the silence the check-in exists to break.
  const [questionKind, setQuestionKind] = useState("question");
  const checkinSecondsRef = useRef(45);          // the server sends it; this is the fallback
  const qDeadlineRef = useRef(0);                // absolute ms deadline
  const qKeyRef = useRef("");                    // the question that deadline belongs to
  const expiredForRef = useRef("");              // the question we have already expired
  // QA-03: TEXT's clock is an idle clock. When did the composer last change, and have we
  // already said "take your time" for this question? (Once per question, like every other
  // nudge in the room.)
  const textIdleSinceRef = useRef(0);
  const textNudgedForRef = useRef("");
  const timeoutPendingRef = useRef(false);       // a capture the clock cut off -> "partial"
  const expireRef = useRef(null);
  // Device policy (Phase E): the two clocks the meetroom sprint left open.
  const abandonRef = useRef(null);               // 90s both-channels-silent
  const abandonedRef = useRef(false);            // fire once per session, never twice
  const cameraGraceRef = useRef(null);           // 60s camera grace
  const endedRef = useRef(false);                // read by the capture's async onstop

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
  // E7.7 — the SESSION clock expiring is an EARLY WRAP, not a dead screen. We wrap
  // server-side (so a refresh cannot dodge it) and go straight to the readout, which
  // scores what actually happened. A session where nothing was answered gets a real,
  // honest readout that says so — it no longer parks the learner on "no answers given"
  // with a Try Again button and no record of the attempt. We wait out an in-flight turn
  // (!loading) so the wrap can never race the stage machine.
  useEffect(() => {
    if (secondsLeft > 0 || ended || loading) return;
    endedRef.current = true;                   // set before we stop the mic: the capture's
    setEnded(true);                            // onstop must know the session is over
    clearGrace();                              // no "Listening in 0.4s…" on a dead clock
    if (recordingRef.current) stopRecording();
    (async () => { await doEarlyWrap(WRAP_SESSION_TIME_UP); onEnd(); })();
  }, [secondsLeft, ended, loading]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages, loading, awaitingRating]);

  // Backend is the source of truth: when it reports the interview is done, move to the
  // readout — but NOT while the interviewer is still speaking her closing line. She now
  // has one (the courteous early wrap), and cutting to the scorecard mid-sentence would
  // make the one moment we promised to handle gracefully the rudest in the product.
  //
  // `speechPending` covers the gap before playback starts: the state lands and the audio
  // begins in the same render pass, and without it we would route away in between.
  const lastMsg = messages[messages.length - 1];
  const speechPending = !!(
    lastMsg?.role === "assistant"
    && (lastMsg.audio_segments?.length || lastMsg.audio_url)
    && playedIdxRef.current !== messages.length - 1
  );
  useEffect(() => {
    if (ended) return;
    if (nextAction !== "readout" && nextAction !== "done") return;
    if (audioPlaying || speechPending) return;   // let her finish the sentence
    setEnded(true);
    onEnd();
  }, [nextAction, ended, onEnd, audioPlaying, speechPending]);

  // ── FAST START: fetch the greeting from inside the room ──
  // The room is already on screen when this runs. The kickoff LLM and the greeting's first
  // clip are paid for while the candidate is LOOKING at the interviewer, not at a spinner.
  // Guarded by a ref, not just state: React strict mode double-fires mount effects, and a
  // second kickoff would be a second LLM bill (the server is idempotent too — belt and
  // braces, because this one is expensive to get wrong).
  //
  // NOTE — no `cancelled` flag on the cleanup, and that is deliberate. StrictMode
  // double-invokes mount effects (mount -> cleanup -> mount) in development. The ref guard
  // below already makes the fetch fire EXACTLY ONCE; a cancel-on-cleanup on top of it would
  // then throw that one fetch's result away when the simulated unmount ran, and the room
  // would sit on "Connecting…" forever. (It did. That is a bug a build and a unit test both
  // sail straight past, and it only shows up in a browser.) The greeting has no cleanup to
  // do — the worst case on a REAL unmount is a setState that React discards.
  useEffect(() => {
    if (!connecting || greetingFetchedRef.current || !sessionId) return;
    greetingFetchedRef.current = true;
    (async () => {
      try {
        const r = await fetchGreeting(sessionId, voicePref || "female");
        if (import.meta.env?.DEV && r.interviewer_identity) {
          console.debug("[interviewer identity]", r.interviewer_identity);
        }
        if (r.tone) setTone(r.tone);
        speechQueuedRef.current = !!(r.audio_segments || []).length;
        setMessages([{ role: "assistant", content: r.greeting, audio_segments: r.audio_segments || [] }]);
        connectingRef.current = false;   // the gate reads the ref; setState has not landed yet
        setConnecting(false);
      } catch (e) {
        // The greeting is the one thing we cannot degrade around — with no opening line
        // there is no interview. Say so plainly and let them start again.
        setConnecting(false);
        setError(e.message || "The interviewer could not be reached. Please start again.");
      }
    })();
  }, [connecting, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── REALISM: the pre-cached clip pack ──
  // Fetched once, used all session: an acknowledgment the instant an answer is submitted,
  // and a soft backchannel at a natural pause in a long answer. Entirely optional — if this
  // fails, the room is exactly what it was, minus the human noises.
  useEffect(() => {
    let cancelled = false;
    // TEXT has no voice, so it has no human noises either. Without this the room fetched
    // the pack, downloaded every blob, and then played an audible "Hmm." the instant a
    // TYPED answer was submitted — a spoken acknowledgment in the one mode that promises
    // silence. Skipping the fetch is the whole fix: playAck/playBackchannel already return
    // early on an empty pack.
    if (textMode) {
      clipsRef.current = { acks: [], backchannels: [] };
      return;
    }
    (async () => {
      try {
        const r = await fetchClipPack(voicePref || "female");
        if (cancelled) return;
        clipsRef.current = { acks: r.acks || [], backchannels: r.backchannels || [] };
        // Warm the blobs now, so the ack plays INSTANTLY on submit rather than after a
        // fetch. An acknowledgment that arrives late is worse than one that never comes.
        for (const c of [...(r.acks || []), ...(r.backchannels || [])]) {
          if (!c.audio_url || audioBlobCache.current.has(c.audio_url)) continue;
          try {
            audioBlobCache.current.set(c.audio_url, await fetchAudioObjectUrl(c.audio_url));
          } catch { /* one missing clip is nothing */ }
          if (cancelled) return;
        }
      } catch { /* the room does not depend on these */ }
    })();
    return () => { cancelled = true; };
  }, [voicePref]); // eslint-disable-line react-hooks/exhaustive-deps

  // Voice Phase 1: track playback so the avatar can pulse and errors fall back to text.
  useEffect(() => {
    const p = player(); if (!p) return;
    const onPlay = () => { setAudioPlaying(true); setNeedsTap(false); };
    const onStop = () => setAudioPlaying(false);   // state only — the sequencer owns the ref
    // Two-way flow: when IQ finishes speaking, hand the floor to the learner.
    // E2: playback is now SEQUENCED explicitly (playSegments), because a per-sentence
    // 'ended' would otherwise fire mid-reply and open the mic before the question was
    // even asked. This listener only tracks the flag; the hand-off is done by the
    // sequencer when the WHOLE reply has finished.
    const onEnded = () => { /* sequencer owns the hand-off */ };
    p.addEventListener("play", onPlay);
    p.addEventListener("playing", onPlay);
    p.addEventListener("ended", onEnded);
    p.addEventListener("pause", onStop);
    p.addEventListener("error", onStop);
    return () => {
      p.removeEventListener("play", onPlay);
      p.removeEventListener("playing", onPlay);
      p.removeEventListener("ended", onEnded);
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
      resumeTtsAnalyser();   // a suspended context would route the audio into silence
      const pr = p.play();
      if (pr && pr.then) pr.then(() => setNeedsTap(false)).catch((e) => { logAudioBlocked("playAudio", e); setNeedsTap(true); });
    } catch (e) { logAudioBlocked("playAudio", e); setNeedsTap(true); }
  };

  // "She is / is not speaking", written to the ref SYNCHRONOUSLY as well as to state.
  // The mic is armed from callbacks and rAF loops, which would otherwise read the previous
  // render's `audioPlaying` — and one stale read is a recording that starts on top of the
  // question it is supposed to be answering.
  const setSpeaking = (on) => { audioPlayingRef.current = on; setAudioPlaying(on); };

  // The ONE way the interviewer gets a new line into the room. It marks her speech as
  // QUEUED before React has even re-rendered, closing the window between "her reply
  // arrived" and "playback started" — which is precisely the window an arming callback
  // would otherwise slip through and open the mic in.
  const sayNext = (msg) => {
    speechQueuedRef.current = !!(msg.audio_segments?.length || msg.audio_url);
    setMessages(m => [...m, msg]);
  };

  // ── E2: pacing ──
  // Play ONE clip and resolve when it actually finishes. This replaces the old
  // event-driven flow: with per-sentence clips we must sequence explicitly, or the
  // shared 'ended' listener would fire once per sentence and trip auto-listen early.
  const playOne = (url) => new Promise((resolve) => {
    const p = player();
    if (!p || !url) { resolve(); return; }
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      p.removeEventListener("ended", done);
      p.removeEventListener("error", done);
      if (playAbortRef.current === done) playAbortRef.current = null;
      resolve();
    };
    // A barge-in PAUSES the element, which fires neither "ended" nor "error" — so without
    // an explicit abort this promise would never settle and the sequencer would hang on a
    // clip nobody is listening to any more. The interrupter calls this.
    playAbortRef.current = done;
    (async () => {
      try {
        let objUrl = audioBlobCache.current.get(url);
        if (!objUrl) {
          objUrl = await fetchAudioObjectUrl(url);
          audioBlobCache.current.set(url, objUrl);
        }
        p.addEventListener("ended", done);
        p.addEventListener("error", done);
        p.src = objUrl;
        resumeTtsAnalyser();
        const pr = p.play();
        if (pr && pr.catch) pr.catch((e) => { logAudioBlocked("playOne", e); setNeedsTap(true); done(); });
        else setNeedsTap(false);
      } catch (e) { logAudioBlocked("playOne", e); done(); }
    })();
  });

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // ── REALISM: the little human noises ──
  // Fire-and-forget on their OWN audio element, so they can never interrupt the
  // interviewer's actual voice or the candidate's recording. Nothing awaits them and
  // nothing breaks if they fail — an acknowledgment that doesn't arrive costs nothing.
  const playClip = (url, volume = 1) => {
    const p = clipPlayer();
    const objUrl = url && audioBlobCache.current.get(url);
    if (!p || !objUrl) return;                  // not pre-warmed -> skip it, don't stall
    try {
      p.pause();
      p.volume = volume;
      p.src = objUrl;
      // A blocked backchannel is harmless (it is a non-essential human noise, not the
      // question), so this never raises the tap-to-enable chip — but it is logged, not
      // swallowed, so "no acks are playing" is diagnosable rather than invisible.
      p.play()?.catch((e) => logAudioBlocked("playClip(backchannel)", e));
    } catch { /* noop */ }
  };

  /** The instant an answer is submitted: "Hmm." — while the real reply is being written.
   *  This is the whole trick. The thinking gap was always there; what it sounded like was
   *  a machine loading. Now it sounds like a person considering. */
  const playAck = () => {
    const acks = clipsRef.current.acks;
    if (!acks.length) return;
    const clip = acks[Math.abs(ackSeedRef.current++) % acks.length];
    playClip(clip.audio_url, 1);
  };

  /** Mid-answer, at a natural pause in a long one: a soft "mm-hmm". Never twice running,
   *  never in the opening seconds, never loud enough to be heard as an interruption. */
  const playBackchannel = () => {
    const bc = clipsRef.current.backchannels;
    if (!bc.length) return;
    const clip = bc[bcCountRef.current % bc.length];
    playClip(clip.audio_url, BACKCHANNEL_VOLUME);
  };

  /**
   * E2: speak a reply SENTENCE BY SENTENCE, holding a human beat between them
   * (300-450ms) and letting the question land (700ms, or ~1100ms when they have just
   * given a real answer — a person absorbs an answer before firing the next question).
   * The caption advances in exact lockstep with the audio — no progress-bar interpolation.
   * A sentence whose synth failed simply shows its caption for a beat and moves on; the
   * interview never stalls.
   *
   * FAST START: sentences after the first arrive `pending` — the server sent us sentence
   * one the moment it existed, so she can START TALKING, and the rest synthesise while it
   * is in the air. We kick that fetch off here, before playing a note, so it overlaps with
   * the audio rather than following it.
   */
  const playSegments = async (segments) => {
    if (!segments?.length) return;
    const token = {};
    speakTokenRef.current = token;
    bargedRef.current = false;
    spokenSoFarRef.current = "";
    setSpeaking(true);
    // Instrumentation (item 3): her reply is now going out — the last hop. Stamp it and
    // close this answer's log line (a no-op unless a spoken answer is actually in flight).
    if (turnLogRef.current && !turnLogRef.current.playbackTs) {
      turnLogRef.current.playbackTs = Date.now();
      emitTurnLog();
    }

    const restP = segments.some(s => s.pending)
      ? fetchSpeechRest(sessionId, voicePref || "female", 1).catch(() => null)
      : null;
    let rest = null;

    const spoken = [];
    for (let i = 0; i < segments.length; i++) {
      if (speakTokenRef.current !== token) return;        // superseded / barged -> abandon
      let seg = segments[i];
      if (seg.pending && restP) {
        if (!rest) {
          const r = await restP;
          rest = new Map((r?.segments || []).map(s => [s.index, s.audio_url]));
          if (speakTokenRef.current !== token) return;
        }
        seg = { ...seg, audio_url: rest.get(i) || null };
      }
      if (seg.pause_before_ms) await sleep(seg.pause_before_ms);
      if (speakTokenRef.current !== token) return;
      setSpokenLine(seg.text || "");
      spoken.push(seg.text || "");
      spokenSoFarRef.current = spoken.join(" ");          // what she has ACTUALLY said
      if (seg.audio_url) await playOne(seg.audio_url);
      else await sleep(650);                              // TTS failed for this line
    }
    if (speakTokenRef.current !== token) return;
    setSpeaking(false);
    setSpokenLine("");
    audioEndedRef.current?.();                            // hand the floor to the learner
  };

  // Autoplay the newest interviewer message when it arrives (once per message).
  // This is the ONLY thing that plays an interviewer line. The re-ask and the mute fork used
  // to ALSO play their own clip explicitly, which meant the same audio was started twice on
  // the same element — and the second start tore the first out mid-word.
  useEffect(() => {
    const idx = messages.length - 1;
    const last = messages[idx];
    if (!last || last.role !== "assistant") return;
    if (idx === playedIdxRef.current) return;
    if (!last.audio_segments?.length && !last.audio_url) {
      speechQueuedRef.current = false;   // nothing to say aloud — she is not holding the floor
      return;
    }
    playedIdxRef.current = idx;
    speechQueuedRef.current = false;     // no longer QUEUED: it is in the air as of now
    if (last.audio_segments?.length) playSegments(last.audio_segments);
    // A single-clip line (the re-ask, the mute fork). Same contract as a reply: the
    // caption shows what is in the air, and the mic does not open until it is over.
    else (async () => {
      setSpeaking(true);
      setSpokenLine(last.content || "");
      await playOne(last.audio_url);
      setSpeaking(false);
      setSpokenLine("");
      audioEndedRef.current?.();
    })();
  }, [messages]); // eslint-disable-line react-hooks/exhaustive-deps

  const lastAssistantIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
    return -1;
  })();
  // A reply is spoken from its SENTENCE CLIPS; only the short one-off lines (re-ask, mute
  // fork) carry a single audio_url. Both are replayable, so ask the message, not the shape.
  const lastAssistant = lastAssistantIdx >= 0 ? messages[lastAssistantIdx] : null;
  const canReplay = !!(lastAssistant?.audio_segments?.length || lastAssistant?.audio_url);

  // E2: no toggleMute — the interviewer is always audible. Replay stays (re-hear a
  // question), and CC captions carry accessibility.
  const replay = () => {
    if (lastAssistant?.audio_segments?.length) playSegments(lastAssistant.audio_segments);
    else if (lastAssistant?.audio_url) playAudio(lastAssistant.audio_url, true);
  };

  // Embedded audio seatbelt: the tap behind the "Tap to enable audio" chip. It is a user
  // gesture, so it unlocks playback / resumes the AudioContext and then replays the current
  // question — turning a silently-blocked autoplay into one tap to sound.
  const enableAudio = async () => { await unlockAudioPlayback(); replay(); };

  // ── Voice Phase 2/3: record → transcribe → drop editable text into the input ──
  const sttAvailable = !!sstate?.stt_available;
  // Phase 3 Part B: voice works in EVERY answering round (Warm-up, Domain,
  // Behavioural, Case, Reverse) — i.e. whenever the learner can submit an answer.
  //
  // ...but NOT while `connecting`. FAST START opens the room on the session row, which
  // already says next_action="answer" — so for the two or three seconds before the
  // greeting lands, every "is it their turn?" check would say yes. Without this the mic
  // would open, the question clock would start, and the 90-second abandonment timer would
  // arm, all before the interviewer had said a single word. It is not their turn until
  // somebody has asked them something.
  const canAnswer = !ended && !connecting && !awaitingRating
    && (nextAction === "answer" || nextAction === "reverse_question");

  // Text mode puts the panel in the student tile's slot. The room stays two tiles; the
  // panel is already mode-agnostic, so this is the whole change.
  //
  // This is the sprint that "landing later" meant. It used to read `config.mode === "text"`
  // — a placeholder that could never fire, because `config.mode` is the FEEDBACK style
  // (interview | coach) and never once held "text". The MODE lives in `session_mode`, and
  // its values are upper-case.
  const textMode = (config.session_mode || "").toUpperCase() === "TEXT";
  // QA-04: VIDEO is the only mode with a camera. AUDIO shared the camera button (and the
  // self-view) with VIDEO under a single !textMode gate, so an AUDIO student who took the
  // lobby's default path got a camera prompt, a live self-view, and a control for a device
  // their mode never promised.
  const videoMode = (config.session_mode || "").toUpperCase() === "VIDEO";

  // Voice Stage: a presentation mode over the same state machine. Only ever active
  // when voice is available; switch it off and the session renders exactly as today.
  //
  // QA-02: these were always TWO ideas wearing one name, and the collision is what told a
  // TEXT student they were on mute. `stt_available` now answers "can this session use STT",
  // which is false for TEXT — but the ROOM is not a voice feature, and keying its render on
  // STT would drop a TEXT student back into the old chat log. So:
  //   roomMode  — the room UI and its state machine are live (all three modes)
  //   voiceLive — voice is actually usable this session (never TEXT)
  // Anything that opens a mic, listens, barges, or offers a device fork gates on voiceLive.
  // Anything that draws the room, or drives the turn flow inside it, gates on roomMode.
  const roomMode = (sttAvailable || textMode) && voiceStage;
  const voiceLive = sttAvailable && voiceStage;
  const orbState = recording ? "listening"
    // FAST START: while the greeting is being written she is THINKING, not idle — which is
    // both what is actually happening and what the candidate should see her doing.
    : (transcribing || loading || connecting) ? "thinking"
    : audioPlaying ? "speaking" : "idle";
  const lastAssistantText = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return messages[i].content;
    return "";
  })();

  // ── Interview Room: devices + CC captions ──
  // Device toggles start from what they committed to in the lobby.
  const [micOn, setMicOn] = useState(() => config.mic !== false);
  // QA-04: `&& videoMode` is the belt to the lobby's braces. The self-view opens the camera
  // from this flag alone, so deriving it from `config.camera` unqualified meant any path
  // that ever set camera:true — a stale config, a future lobby edit — would open a camera
  // in AUDIO. The mode is the authority on whether this session has one.
  const [camOn, setCamOn] = useState(() => !!config.camera && videoMode);
  // The chat panel's visibility and, SEPARATELY, whether the student has actually chosen to
  // type. These used to be one flag — "the typing drawer is open" — which was a fair proxy
  // while that drawer did nothing but type. The panel does something else: it is where you
  // RE-READ an earlier question. Left as one flag, opening the transcript to check what was
  // asked would have silently disarmed the microphone. Reading is not typing.
  const [chatOpen, setChatOpen] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const composerRef = useRef(null);
  // E2 CC: the caption is the sentence ACTUALLY being spoken. Because the reply is
  // synthesised one clip per sentence, the sequencer knows exactly which line is in the
  // air — so captions land in true lockstep instead of being interpolated off a
  // progress bar. When nothing is playing, show the whole question so it can be read.
  //
  // BARGE-IN: except when she was interrupted. Then the caption shows only what she
  // actually got out (`spoken_prefix`) — the rest of that reply was never said aloud, and
  // captioning it would be captioning words this candidate never heard.
  const lastAssistantMsg = lastAssistantIdx >= 0 ? messages[lastAssistantIdx] : null;
  const idleCaption = lastAssistantMsg?.spoken_prefix || lastAssistantText || "";
  const ccLine = spokenLine || (audioPlaying ? "" : idleCaption);

  // PROGRESSIVE REVEAL. The caption area is a fixed height that SCROLLS rather than a clamp
  // that clips, so a long question is fully readable — but only if the area follows her
  // voice down. Each sentence she reaches scrolls into view; when she finishes, the area is
  // holding the whole question, scrolled to the end, and they can scroll back through it.
  const ccRef = useRef(null);
  useEffect(() => {
    const el = ccRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [ccLine, connecting]);

  // Mirror state into refs — the <audio> 'ended' handler and the rAF meter loop are
  // registered once and would otherwise close over stale values.
  useEffect(() => { micOnRef.current = micOn; }, [micOn]);
  useEffect(() => { roomModeRef.current = roomMode; }, [roomMode]);
  useEffect(() => { canAnswerRef.current = canAnswer; }, [canAnswer]);
  useEffect(() => { consentRef.current = voiceConsented; }, [voiceConsented]);
  useEffect(() => { recordingRef.current = recording; }, [recording]);
  useEffect(() => { transcribingRef.current = transcribing; }, [transcribing]);
  // THE CAPTURE INVARIANT's `typing` input: the composer itself (focused, or holding a
  // draft), never the panel's visibility. See roomLayout.composerIntent.
  const typingNow = composerIntent({ focused: composerFocused, draft: input });
  useEffect(() => { typedInVoiceRef.current = typingNow; }, [typingNow]);
  useEffect(() => { awaitingRatingRef.current = awaitingRating; }, [awaitingRating]);
  useEffect(() => { ratingPillsRef.current = ratingPills; }, [ratingPills]);
  useEffect(() => { endedRef.current = ended; }, [ended]);
  useEffect(() => { connectingRef.current = connecting; }, [connecting]);
  // A turn in flight means her reply is on its way. The mic must not open into the gap —
  // that gap is the thinking pause, and it belongs to her, not to their answer.
  useEffect(() => { loadingRef.current = loading; }, [loading]);
  // The transcript drawer auto-opens at the readout. (It no longer force-opens at the
  // rating, because the rating is now ASKED ALOUD and answered by voice.)
  useEffect(() => {
    if (roomMode && nextAction === "readout") setDrawerOpen(true);
  }, [roomMode, nextAction]);

  // ── REALISM: BARGE-IN ──
  // You can interrupt a person, and that is most of what makes them one. While the
  // interviewer is speaking and the floor is about to be the candidate's anyway, we hold
  // the mic open for exactly one purpose: to hear whether they have started talking over
  // her. When they have, she ducks out over 200ms — a hard cut sounds like a crash, a fade
  // sounds like someone stopping because you started — and the floor is theirs.
  //
  // She does NOT re-say the sentences she was interrupted out of. Nobody does that, and a
  // candidate who cuts in has already decided they do not need the rest.
  const releaseWarmStream = () => {
    const s = warmStreamRef.current;
    if (s) { try { s.getTracks().forEach(t => t.stop()); } catch { /* noop */ } warmStreamRef.current = null; }
  };

  const stopBargeMonitor = ({ keepStream = false } = {}) => {
    if (bargeRafRef.current) { cancelAnimationFrame(bargeRafRef.current); bargeRafRef.current = null; }
    const ctx = bargeCtxRef.current;
    if (ctx) { try { ctx.close(); } catch { /* noop */ } bargeCtxRef.current = null; }
    bargeAboveSinceRef.current = 0;
    if (!keepStream) releaseWarmStream();
  };

  const onBargeIn = async () => {
    stopBargeMonitor({ keepStream: true });   // the open mic BECOMES their recording
    speakTokenRef.current = null;             // the sequencer abandons the rest of the reply

    const p = player();
    if (p) {
      const from = p.volume;
      const steps = 8;
      for (let i = 1; i <= steps; i++) {
        p.volume = Math.max(0, from * (1 - i / steps));
        await sleep(BARGE_IN_DUCK_MS / steps);
      }
      try { p.pause(); } catch { /* noop */ }
      p.volume = from;                        // restore it for her next reply
    }
    playAbortRef.current?.();                 // a paused clip fires no 'ended' — settle it
    setSpeaking(false);
    setSpokenLine("");

    // The caption keeps ONLY what she actually said aloud. Showing the sentences she was
    // cut out of would put words in her mouth that this candidate never heard.
    const spoken = spokenSoFarRef.current;
    if (spoken) {
      setMessages(m => m.map((msg, i) => (
        i === m.length - 1 && msg.role === "assistant" ? { ...msg, spoken_prefix: spoken } : msg
      )));
    }

    // Their turn began a second ago. Record on the mic that is ALREADY live rather than
    // spending another getUserMedia on it — that round trip is their opening word.
    //
    // This goes through the SAME gate as everything else, and passes it honestly: she has
    // been stopped and the rest of her reply ABANDONED (not postponed) a few lines above,
    // so by now she really does have nothing left to say. Barge-in is not an exception to
    // the invariant — it is the one path that satisfies it by force.
    armCapture({ stream: warmStreamRef.current });
  };

  const startBargeMonitor = async () => {
    if (bargeCtxRef.current) return;                                  // already listening
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return;
    let stream = warmStreamRef.current;
    if (!stream || !stream.active) {
      try { stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS); }
      catch { return; }        // no mic / denied -> no barge-in. The room is unchanged.
      warmStreamRef.current = stream;
    }
    const AC = typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext);
    if (!AC) return;
    let an;
    try {
      const ctx = new AC();
      bargeCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      an = ctx.createAnalyser();
      an.fftSize = 512;
      an.smoothingTimeConstant = 0.6;
      src.connect(an);        // deliberately NOT wired to destination: never echo them back
    } catch { stopBargeMonitor({ keepStream: true }); return; }

    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      if (!bargeCtxRef.current || bargedRef.current) return;
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const rms = Math.sqrt(sum / buf.length);
      const now = performance.now();
      if (rms > BARGE_IN_RMS) {
        if (!bargeAboveSinceRef.current) bargeAboveSinceRef.current = now;
        if (shouldBargeIn({ rms, aboveSinceMs: now - bargeAboveSinceRef.current })) {
          bargedRef.current = true;
          onBargeIn();
          return;
        }
      } else {
        bargeAboveSinceRef.current = 0;
      }
      bargeRafRef.current = requestAnimationFrame(tick);
    };
    bargeRafRef.current = requestAnimationFrame(tick);
  };

  // Arm the listener only while she is actually speaking AND the floor is about to be
  // theirs. Not while a rating is due (what they would be interrupting is the rating ask,
  // and cutting that short helps nobody). Not while MUTED — a muted mic is never opened,
  // and that is the whole contract of the mute button, barge-in included.
  const bargeArmed = audioPlaying && voiceLive && micOn && voiceConsented
    && canAnswer && !recording && !transcribing && !ended;
  useEffect(() => {
    if (!bargeArmed) { stopBargeMonitor({ keepStream: true }); return; }
    startBargeMonitor();
    return () => stopBargeMonitor({ keepStream: true });
  }, [bargeArmed]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // Graceful fallback (unchanged contract): toast +, on the stage, swap straight to
  // the typed composer so a voice failure is never a dead end.
  //
  // QA-05: this called setTypeOpen(), which does not exist and never has — one reference
  // in the whole codebase, no definition. So the rescue threw a ReferenceError on the one
  // path that exists to rescue: every STT failure and mic denial in voice mode. The
  // student with the broken mic got the dead end this function's own comment promises
  // they never would. openChat() is the real thing: it opens the panel AND lands the
  // caret in the composer, which is what "swap straight to the typed composer" means.
  const voiceFallback = () => {
    showToast("Voice input unavailable — please type your answer");
    if (roomModeRef.current) openChat();
  };

  // Realism v2: "Heard: …" flashes for 3s under the character. The answer itself is
  // already on its way and is appended to the drawer by the normal message flow.
  const flashHeard = (text) => {
    if (heardTimerRef.current) clearTimeout(heardTimerRef.current);
    setHeard(text);
    heardTimerRef.current = setTimeout(() => setHeard(null), 6000);
  };

  // Instrumentation (item 3): ONE line per answer attempt, emitted once. It carries the
  // shapes and timings a "my answer wasn't heard" report needs — granted mic settings,
  // RMS/peak, capture duration, bytes, STT status, transcript length/confidence, and the
  // per-hop latency (capture→STT→LLM/TTS→playback) — and NEVER the transcript text or audio.
  const emitTurnLog = () => {
    const t = turnLogRef.current;
    if (!t || t.emitted) return;
    t.emitted = true;
    const r3 = (x) => Math.round((x || 0) * 1000) / 1000;
    const d = (a, b) => (a && b && b >= a) ? (b - a) : null;
    const dropped = t.dropped ? Object.keys(t.dropped) : [];
    try {
      console.info("[answer] " + JSON.stringify({
        capture_ms: Math.round(t.captureMs || 0),
        bytes: t.bytes || 0,
        mime: t.mime || "",
        peak_rms: r3(t.peakRms),
        mean_rms: r3(t.meanRms),
        mic_flags_dropped: dropped.length ? dropped : "none",
        sample_rate: t.granted?.sampleRate ?? null,
        channels: t.granted?.channelCount ?? null,
        stt: t.sttStatus || "n/a",
        transcript_len: t.transcriptLen || 0,
        confidence: t.confidence ?? null,
        latency_ms: {
          capture: Math.round(t.captureMs || 0),
          stt: d(t.sttStartTs, t.sttEndTs),
          llm_tts: d(t.llmStartTs, t.llmEndTs),
          playback: d(t.llmEndTs, t.playbackTs),
        },
      }));
    } catch { /* logging must never break the interview */ }
    turnLogRef.current = null;
  };

  // Realism v2: a failed transcription is NOT a dead end and NOT a lost question. IQ says
  // (in character) that it didn't catch the answer and the mic reopens — the backend
  // /session/reask changes no state, so no question slot is consumed.
  //
  // `kind` picks WHICH line she says: "reask" (generic), "quiet" (mic too quiet/far, item
  // 4), or "noise" (heavy background noise, item 8). Environmental kinds do NOT count toward
  // the two-strikes-then-type rule — the fix is in the room, not in the pipeline, and the
  // invisible per-question timer is the ultimate backstop against a loop. A generic failure
  // still swaps in the composer after two in a row so voice can never become a dead end.
  const doReask = async (kind = "reask", { strike = true } = {}) => {
    if (!roomModeRef.current) { voiceFallback(); return; }
    if (strike) {
      sttFailRef.current += 1;
      if (sttFailRef.current >= 2) { sttFailRef.current = 0; voiceFallback(); return; }
    } else {
      sttFailRef.current = 0;   // environmental issue — don't hold it against the mic
    }
    busyRef.current = true;
    try {
      const r = await reaskTurn(sessionId, voicePref || "female", kind);
      sayNext({ role: "assistant", content: r.reply, audio_url: r.audio_url });
      busyRef.current = false;
      // Playback (and the hand-off back to the mic when it finishes) is the autoplay
      // sequencer's job — see the effect below.
      if (!r.audio_url) startGrace();                  // TTS off -> just reopen the mic
    } catch {
      busyRef.current = false;
      voiceFallback();
    }
  };
  const handleSttFailure = () => doReask("reask");

  // ── Live self-captions from our OWN Saarika STT (item 6) ──
  // While the student speaks, a "You:" line shows their running transcript. We build it by
  // transcribing SHORT ROLLING WINDOWS of the SAME mic stream we already record, through our
  // own STT (/session/stt/partial → Saarika). There is ONE audio path (the mic) and ONE
  // vendor — no browser speech service, no second capture of a third party.
  //
  // It is DISPLAY ONLY: it never feeds the capture gate, never becomes the answer, and never
  // touches the authoritative transcript (still the full-blob upload on stop). The window
  // recorder is a SEPARATE MediaRecorder on the same stream, so a partial that fails — or the
  // whole caption path — can never disturb the recording it is describing. Verbatim: the
  // window transcripts are joined as-is, never beautified.

  // Record ONE short window off the shared stream and resolve with its blob (or null).
  const recordSelfCapWindow = (stream, ms) => new Promise((resolve) => {
    let mr;
    const chunks = [];
    try { mr = new MediaRecorder(stream); } catch { resolve(null); return; }
    selfCapRecRef.current = mr;
    let settled = false;
    const finish = (blob) => { if (!settled) { settled = true; resolve(blob); } };
    mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    mr.onstop = () => finish(chunks.length ? new Blob(chunks, { type: mr.mimeType || "audio/webm" }) : null);
    try { mr.start(); } catch { finish(null); return; }
    setTimeout(() => { try { if (mr.state !== "inactive") mr.stop(); } catch { finish(null); } }, ms);
  });

  const startSelfCaption = (stream) => {
    setSelfCaption("");
    selfCapTextRef.current = "";
    selfCapWindowsRef.current = 0;
    if (!SELF_CAPTIONS_SUPPORTED || !selfCaptions || !stream) return;   // opted-out -> waveform only
    selfCapActiveRef.current = true;
    (async () => {
      while (selfCapActiveRef.current && recordingRef.current
             && selfCapWindowsRef.current < SELFCAP_MAX_WINDOWS) {
        const clip = await recordSelfCapWindow(stream, SELFCAP_WINDOW_MS);
        if (!selfCapActiveRef.current) break;
        if (!clip) continue;
        selfCapWindowsRef.current += 1;
        try {
          const r = await sttPartial(sessionId, clip);
          if (!selfCapActiveRef.current) break;
          const text = r && r.transcript ? r.transcript.trim() : "";
          if (text) {
            selfCapTextRef.current += (selfCapTextRef.current ? " " : "") + text;
            setSelfCaption(selfCapTextRef.current);   // verbatim, never beautified
          }
        } catch { /* a partial that fails is just a caption that does not grow */ }
      }
    })();
  };
  const stopSelfCaption = () => {
    selfCapActiveRef.current = false;
    const mr = selfCapRecRef.current;
    selfCapRecRef.current = null;
    if (mr) { try { if (mr.state !== "inactive") mr.stop(); } catch { /* noop */ } }
    setSelfCaption("");
  };

  // ── Web Audio meter: the REAL mic level drives the live waveform and the
  // trailing-silence auto-stop. If Web Audio is unavailable the recording still
  // works — only the waveform/silence-stop degrade.
  const teardownMeter = () => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    analyserRef.current = null;
    const ctx = audioCtxRef.current;
    if (ctx) { try { ctx.close(); } catch { /* noop */ } audioCtxRef.current = null; }
    silenceStartRef.current = 0; spokeRef.current = false;
    setLevels(new Array(WAVE_BARS).fill(0));
  };

  const startMeter = (stream) => {
    const AC = typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext);
    if (!AC) return;
    let an;
    try {
      const ctx = new AC();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      an = ctx.createAnalyser();
      an.fftSize = 512;
      an.smoothingTimeConstant = 0.8;
      src.connect(an);
      analyserRef.current = an;
    } catch { teardownMeter(); return; }
    const buf = new Uint8Array(an.fftSize);
    let frame = 0;
    const tick = () => {
      const a = analyserRef.current;
      if (!a || !recordingRef.current) return;
      a.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const rms = Math.sqrt(sum / buf.length);
      // Instrumentation (item 3/4/8): the loudest frame and the running mean over the whole
      // answer. finishRecording reads these to tell a too-quiet mic apart from a too-noisy
      // room — a distinction the transcript alone cannot make.
      if (rms > peakRmsRef.current) peakRmsRef.current = rms;
      rmsSumRef.current += rms; rmsFramesRef.current += 1;
      // Throttle React updates to ~20fps; the rAF itself stays at display rate.
      if (frame++ % 3 === 0) setLevels(prev => { const next = prev.slice(1); next.push(rms); return next; });
      if (rms > SILENCE_RMS * 1.6 && !spokeRef.current) {
        spokeRef.current = true;
        // Item 7: something was heard this question, so the failsafe timer chip can recede.
        if (!heardSpeechThisQRef.current) { heardSpeechThisQRef.current = true; setHeardSpeechThisQ(true); }
      }
      // End-of-answer auto-stop (item 7) — ONLY in auto-listen mode, only after they have
      // actually spoken, and only once the answer is a real one (>=2s): the thinking pause
      // before an answer, and a half-second cough, must never be read as "finished".
      const spokeEnoughMs = recStartRef.current ? Date.now() - recStartRef.current : 0;
      if (micOnRef.current && spokeRef.current && spokeEnoughMs >= MIN_SPEECH_MS) {
        if (rms < SILENCE_RMS) {
          if (!silenceStartRef.current) silenceStartRef.current = performance.now();
          else if (performance.now() - silenceStartRef.current >= SILENCE_HOLD_MS) { stopRecording(); return; }
        } else silenceStartRef.current = 0;
      }

      // ── REALISM: LISTENING BACKCHANNELS ──
      // A soft "mm-hmm" at a natural pause in a long answer. It runs off the SAME rms we
      // already compute for the waveform, so it costs nothing, and every condition in
      // shouldBackchannel is there to stop it becoming an interruption: long answers only,
      // never in the opening seconds, never at a pause long enough to be them FINISHING,
      // and never more than twice. A rating capture is not an answer and gets none.
      if (spokeRef.current && !ratingListeningRef.current) {
        const now = performance.now();
        if (rms < SILENCE_RMS) {
          if (!bcPauseStartRef.current) bcPauseStartRef.current = now;
          const elapsedMs = recStartRef.current ? Date.now() - recStartRef.current : 0;
          if (shouldBackchannel({
            elapsedMs,
            pauseMs: now - bcPauseStartRef.current,
            playedCount: bcCountRef.current,
            endOfAnswerMs: SILENCE_HOLD_MS,
          })) {
            bcCountRef.current += 1;
            bcPauseStartRef.current = 0;      // at most one per pause
            playBackchannel();
          }
        } else {
          bcPauseStartRef.current = 0;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  };

  // ── Auto-listen: a short grace beat after IQ stops speaking, then the mic opens.
  // Instantly cancelable (tap the pill or press Esc).
  const clearGrace = () => {
    if (graceRafRef.current) { cancelAnimationFrame(graceRafRef.current); graceRafRef.current = null; }
    setGraceMs(0);
  };
  const startGrace = () => {
    clearGrace();
    const started = performance.now();
    setGraceMs(AUTO_LISTEN_GRACE_MS);
    const step = () => {
      const left = AUTO_LISTEN_GRACE_MS - (performance.now() - started);
      if (left <= 0) { graceRafRef.current = null; setGraceMs(0); armCapture(); return; }
      setGraceMs(left);
      graceRafRef.current = requestAnimationFrame(step);
    };
    graceRafRef.current = requestAnimationFrame(step);
  };
  const maybeAutoListen = () => {
    // One gate, asked once. (This used to be seven hand-written checks that had drifted out
    // of step with the other five arming sites — which is how three of them ended up
    // opening the mic while the interviewer was still talking.)
    if (!canArmCapture(captureState())) return;
    startGrace();
  };

  // ── ITEM 1: LISTENING is LEVEL-TRIGGERED, not edge-triggered ──
  // The mic must arm whenever ALL of "a question is open", "the student is unmuted", and
  // "the interviewer has finished" hold — no matter which of the three became true LAST.
  // The old flow armed only on discrete EVENTS (she finished / they tapped unmute), so
  // unmuting mid-question and then having her finish could fall between the events and
  // strand the mic on READY. This effect closes that gap: any time the gate is open and it
  // is genuinely an ANSWER that is due (never a rating — that has its own capture path), it
  // starts the same auto-listen grace beat. canArmCapture() remains the ONE authority; this
  // only decides WHEN to ask it, so the capture invariant is untouched — connecting /
  // speaking / speechQueued still hold the mic shut here exactly as everywhere else.
  useEffect(() => {
    if (!voiceLive || awaitingRating) return;   // rating capture is startRatingCapture's job
    if (graceMs > 0) return;                     // a grace beat is already counting down
    if (!canArmCapture(captureState())) return;  // the invariant + "is it their turn?" gate
    startGrace();
  }, [voiceLive, micOn, canAnswer, audioPlaying, connecting, recording, transcribing,
      loading, awaitingRating, ratingPills, typingNow, ended, voiceConsented, graceMs]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Realism v2: the spoken confidence rating ──
  // IQ asks aloud; we open the mic and parse the reply. The pills are the FALLBACK,
  // shown only when we cannot parse what was said, or after 8s of silence.
  const clearRatingSilence = () => {
    if (ratingSilenceRef.current) { clearTimeout(ratingSilenceRef.current); ratingSilenceRef.current = null; }
  };
  const startRatingCapture = () => {
    ratingListeningRef.current = true;    // finishRecording reads this: a rating, not an answer
    setRatingPills(false);
    if (!armCapture({ ratingDue: true })) { ratingListeningRef.current = false; return; }
    clearRatingSilence();
    ratingSilenceRef.current = setTimeout(() => {
      // 8s and they haven't said anything usable -> stop listening and offer the pills.
      if (!ratingListeningRef.current) return;
      ratingListeningRef.current = false;
      if (recordingRef.current) stopRecording();
      setRatingPills(true);
    }, RATING_SILENCE_MS);
  };
  const failRatingToPills = () => {
    clearRatingSilence();
    ratingListeningRef.current = false;
    setRatingPills(true);
  };
  // What happens when IQ finishes speaking. Three cases:
  //   1. a rating is due and IQ hasn't asked for it yet -> play the spoken rating ask;
  //   2. the rating ask has been spoken -> open the mic to capture the spoken rating;
  //   3. otherwise -> hand the floor back for the next answer (auto-listen).
  const onAudioEnded = async () => {
    if (!roomModeRef.current) return;
    if (awaitingRatingRef.current) {
      if (!ratingAskedRef.current && ratingAudioRef.current) {
        // Speak the rating ask, then open the mic for it. Sequenced explicitly (E2) —
        // we no longer bounce off the audio element's 'ended' event.
        ratingAskedRef.current = true;
        setSpeaking(true);
        setSpokenLine(ratingPromptRef.current || "");
        await playOne(ratingAudioRef.current);
        setSpeaking(false);
        setSpokenLine("");
      }
      if (micOnRef.current && consentRef.current && !ratingPillsRef.current) startRatingCapture();
      return;
    }
    maybeAutoListen();
  };

  // The <audio> 'ended' listener is registered ONCE on mount, so it must not capture
  // a first-render closure (that would carry a stale sstate and post the wrong stage).
  // Route it through a ref that always points at this render's implementation.
  const audioEndedRef = useRef(null);
  useEffect(() => { audioEndedRef.current = onAudioEnded; });

  // ── THE ONLY DOOR TO THE MICROPHONE ──────────────────────────────────────
  // Everything that wants to capture — auto-listen, unmuting, the mic button, accepting the
  // consent modal, the spoken rating, barge-in — comes through here, and here asks
  // roomPolicy.canArmCapture. Nothing else may call openMicUnsafe: a test (captureInvariant
  // .test.mjs) fails the build if anything does.
  //
  // The reason this is structural rather than a convention is that the convention had
  // already failed. Three of the six arming sites were opening the mic mid-reply — unmuting,
  // tapping the mic, and accepting the consent modal — so the recorder was capturing the
  // interviewer's own voice and submitting it as the candidate's answer.
  const captureState = (extra = {}) => ({
    inRoom: roomModeRef.current,
    micOn: micOnRef.current,
    consented: consentRef.current,
    answerDue: canAnswerRef.current,
    ratingDue: awaitingRatingRef.current && roomModeRef.current && !ratingPillsRef.current,
    connecting: connectingRef.current,
    speaking: audioPlayingRef.current,
    speechQueued: speechQueuedRef.current,
    recording: recordingRef.current,
    transcribing: transcribingRef.current,
    busy: busyRef.current || loadingRef.current,
    typing: typedInVoiceRef.current,
    ended: endedRef.current,
    ...extra,
  });

  /** Open the mic IF AND ONLY IF the interviewer has finished and it is genuinely their
   *  turn. Returns whether it did, so a caller can undo any state it set in anticipation. */
  const armCapture = ({ stream, ...extra } = {}) => {
    if (!canArmCapture(captureState(extra))) return false;
    openMicUnsafe(stream);
    return true;
  };

  // Actually acquire the mic and start capturing. NEVER call this directly — call
  // armCapture(). It is named `unsafe` because it asks no questions: it will happily record
  // straight over the top of a question the candidate has not finished hearing.
  //
  // `existing` is the barge-in monitor's already-live mic, handed over rather than
  // re-acquired: a second getUserMedia here would cost ~200ms, and those 200ms are the
  // first word of whatever they cut in to say.
  const openMicUnsafe = async (existing) => {
    if (recording || transcribing) return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      voiceFallback(); return;
    }
    // Take the mic that is ALREADY open if there is one — either the stream handed over by
    // a barge-in, or the one the barge-in listener left warm when she finished speaking.
    // Opening a second one would both leak the first (two live mics, two indicator lights)
    // and cost a getUserMedia round trip at the exact moment they start talking.
    const warm = warmStreamRef.current;
    let stream = (existing && existing.active) ? existing
      : (warm && warm.active) ? warm
        : null;
    if (stream) {
      // It belongs to the recorder now — the monitor must not stop it out from under us.
      if (warmStreamRef.current === stream) warmStreamRef.current = null;
      stopBargeMonitor({ keepStream: true });
    } else {
      try {
        stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
      } catch {
        // Permission denied or no device → fall back to typing, zero degradation.
        voiceFallback(); return;
      }
    }
    mediaStreamRef.current = stream;
    // A fresh answer: it has had no backchannels, and it is not mid-pause.
    bcCountRef.current = 0;
    bcPauseStartRef.current = 0;
    // Instrumentation (item 3/4): what the browser ACTUALLY granted us, and which of the
    // processing flags it refused. Read from the live track, once, per answer.
    try {
      const tr = stream.getAudioTracks?.()[0];
      grantedSettingsRef.current = tr?.getSettings ? tr.getSettings() : null;
    } catch { grantedSettingsRef.current = null; }
    // Reset the RMS aggregates for this answer (they drive the quiet-mic / noise verdicts).
    peakRmsRef.current = 0; rmsSumRef.current = 0; rmsFramesRef.current = 0;
    startSelfCaption(stream);   // live "You:" caption while they speak (display-only, item 6)
    let mr;
    try { mr = new MediaRecorder(stream); }   // mimeType left to the browser (the STT fix handles it)
    catch { stopMediaStream(); stopSelfCaption(); voiceFallback(); return; }
    recChunksRef.current = [];
    mr.ondataavailable = (e) => { if (e.data && e.data.size) recChunksRef.current.push(e.data); };
    mr.onstop = () => finishRecording(mr.mimeType);
    mediaRecorderRef.current = mr;
    try { mr.start(); }
    catch { stopMediaStream(); stopSelfCaption(); voiceFallback(); return; }
    recStartRef.current = Date.now();
    recordingRef.current = true;   // set before the meter loop reads it
    startMeter(stream);
    setRecording(true); setRecSeconds(0);
    recTimerRef.current = setInterval(() => setRecSeconds(s => {
      const next = s + 1;
      if (next >= MAX_REC_SECONDS) stopRecording();   // auto-stop at the cap
      return next;
    }), 1000);
  };

  const stopRecording = () => {
    clearRecTimer();
    recordingRef.current = false;   // stops the meter loop on its next frame
    teardownMeter();
    stopSelfCaption();              // the live "You:" caption ends with the recording
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") { try { mr.stop(); } catch { /* noop */ } }   // fires onstop → finishRecording
    setRecording(false);
  };

  // Called from MediaRecorder.onstop: bundle chunks, upload, insert transcript.
  const finishRecording = async (mimeType) => {
    stopMediaStream();
    const chunks = recChunksRef.current; recChunksRef.current = [];
    // The session clock died while they were still talking. Their words can no longer
    // become a turn, so we do not upload them, and IQ does not pipe up after the wrap.
    if (endedRef.current) { timeoutPendingRef.current = false; return; }
    if (!chunks.length) { voiceFallback(); return; }
    const type = mimeType || "audio/webm";
    const blob = new Blob(chunks, { type });
    const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : type.includes("wav") ? "wav" : "webm";
    const durationSeconds = recStartRef.current ? (Date.now() - recStartRef.current) / 1000 : 0;
    // A rating capture is NOT an answer — it never becomes a turn.
    const isRating = ratingListeningRef.current;
    // E7.7: the per-question clock cut this capture off. Whatever it heard is their
    // answer — a partial one — and it gets submitted rather than thrown away. The flag is
    // consumed here so a later, ordinary recording can never inherit it.
    const forcedTimeout = timeoutPendingRef.current;
    timeoutPendingRef.current = false;
    // The clock ran out and the capture yielded nothing usable: fall back to a typed
    // draft if one is sitting there, else skip the question. Never a dead end.
    const submitExpiry = () => {
      const { timeout, text } = expiryAction({ draft: inputRef.current?.value || "" });
      send(text, { timeout });
    };
    // Instrumentation (item 3): open this answer's log line with everything known at capture
    // time — granted mic settings, the flags the browser refused, RMS peak/mean, bytes and
    // duration. A rating capture is not an answer and is never logged as one.
    const meanRms = rmsFramesRef.current ? rmsSumRef.current / rmsFramesRef.current : 0;
    const peakRms = peakRmsRef.current;
    if (!isRating) {
      const dropped = micSettingsShortfall(grantedSettingsRef.current);
      turnLogRef.current = {
        captureMs: durationSeconds * 1000, bytes: blob.size, mime: type,
        peakRms, meanRms, granted: grantedSettingsRef.current,
        dropped: Object.keys(dropped).length ? dropped : null,
        sttStatus: "", transcriptLen: 0, confidence: null,
        sttStartTs: 0, sttEndTs: 0, llmStartTs: 0, llmEndTs: 0, playbackTs: 0, emitted: false,
      };
    }
    setTranscribing(true); transcribingRef.current = true;
    try {
      if (turnLogRef.current) turnLogRef.current.sttStartTs = Date.now();
      const res = await sttTranscribe(sessionId, blob, `answer.${ext}`, durationSeconds);
      const transcript = res && res.transcript ? res.transcript : null;
      if (turnLogRef.current) {
        turnLogRef.current.sttEndTs = Date.now();
        turnLogRef.current.transcriptLen = (transcript || "").length;
        turnLogRef.current.confidence = res?.delivery_metrics?.articulation ?? null;
        turnLogRef.current.sttStatus = transcript ? "ok" : "empty";
      }

      if (isRating) {
        clearRatingSilence();
        ratingListeningRef.current = false;
        const val = parseSpokenRating(transcript);
        if (val === undefined) failRatingToPills();   // unparseable -> offer the pills
        else await rate(val);                          // 1..5, or null = "prefer not to say"
        return;
      }

      if (transcript) {
        sttFailRef.current = 0;
        noiseCoachCountRef.current = 0;   // a clean transcript resets the noise streak
        // Phase 3: mark this answer as SPOKEN and stash its delivery metrics for Send.
        answeredByVoiceRef.current = true;
        pendingDeliveryRef.current = res.delivery_metrics || null;
        if (forcedTimeout) {
          // Cut off mid-answer: submit what they DID get out. The interviewer responds to
          // an incomplete answer in persona — it is never silently dropped.
          flashHeard(transcript);
          send(transcript.slice(0, 4000), { timeout: "partial" });
        } else if (roomModeRef.current) {
          // INSTANT FLOW: no review card, no Send. Flash what we heard and submit now;
          // the answer is correctable afterwards from the transcript drawer.
          flashHeard(transcript);
          send(transcript.slice(0, 4000));
        } else {
          // Classic mode: straight into the editable composer, exactly as before.
          setInput(prev => ((prev ? prev.trimEnd() + " " : "") + transcript).slice(0, 4000));
          setTimeout(() => inputRef.current?.focus(), 50);
        }
      } else if (forcedTimeout) {
        emitTurnLog();
        submitExpiry();
      } else {
        // Nothing usable came back on a real attempt. The RMS aggregates tell us WHY, and
        // that decides which line she says (items 4 + 8):
        //   near-silent over a full answer -> the mic is too quiet/far  -> "quiet"
        //   strong signal but still unusable, twice -> the room is noisy -> "noise" (once)
        //   otherwise -> the generic "I didn't catch that".
        emitTurnLog();
        const durMs = durationSeconds * 1000;
        const fullAttempt = durMs >= QUIET_ANSWER_MIN_MS;
        if (fullAttempt && peakRms < QUIET_PEAK_RMS) {
          await doReask("quiet", { strike: false });
        } else if (fullAttempt) {
          noiseCoachCountRef.current += 1;
          if (noiseCoachCountRef.current >= NOISE_COACH_AFTER && !noiseCoachedRef.current) {
            noiseCoachedRef.current = true;   // in-session noise coaching is said ONCE
            await doReask("noise", { strike: false });
          } else {
            await handleSttFailure();
          }
        } else {
          await handleSttFailure();
        }
      }
    } catch {
      if (isRating) failRatingToPills();
      else if (forcedTimeout) { emitTurnLog(); submitExpiry(); }
      else {
        if (turnLogRef.current) turnLogRef.current.sttStatus = "fail";
        emitTurnLog();
        await handleSttFailure();
      }
    } finally { setTranscribing(false); transcribingRef.current = false; }
  };

  // Mic button: toggle stop while recording; otherwise gate on consent then record.
  // The mic is usable for an answer, OR to speak the confidence rating.
  const micUsable = canAnswer || (awaitingRating && roomMode && !ratingPills);

  const onMicClick = () => {
    if (graceMs > 0) { clearGrace(); return; }   // instant cancel of the auto-listen beat
    if (recording) { stopRecording(); return; }
    if (transcribing) return;
    if (!voiceConsented) { setShowVoiceConsent(true); return; }
    // She is still talking. Reaching for the mic mid-question IS an interruption, so treat
    // it as one: stop her (she does not re-say the rest) and hand them the floor. What we do
    // NOT do is record over her and submit her own question back to us as their answer.
    if (audioPlayingRef.current && canAnswerRef.current && !bargedRef.current) {
      bargedRef.current = true;
      onBargeIn();
      return;
    }
    if (awaitingRating && roomMode) { startRatingCapture(); return; }   // spoken rating
    armCapture();
  };

  // ── MIC = MEET SEMANTICS ──
  // The button is a PERSISTENT MUTE TOGGLE, not tap-to-speak. The state survives across
  // questions until the student changes it.
  //   UNMUTED — every answer window opens capture automatically; unmuting mid-question
  //             starts capture immediately, with no extra tap.
  //   MUTED   — no capture EVER occurs.
  // We NEVER auto-unmute. Unmuting is always the student's explicit act (mic privacy).
  const toggleMic = () => {
    if (micOn) {
      micOnRef.current = false;          // set the ref first: the meter loop reads it
      setMicOn(false);
      clearGrace();
      if (recording) stopRecording();    // muting stops any capture in flight
      // MUTED MEANS MUTED. The barge-in listener holds a live mic while she speaks; on
      // mute it is torn down and the TRACK IS STOPPED, so the browser's recording
      // indicator goes out. A mute button that leaves the mic open is a lie.
      stopBargeMonitor();
      return;
    }
    // UNMUTE — an explicit act. Consent is still explicit and separate.
    if (!voiceConsented) { setShowVoiceConsent(true); return; }
    // Embedded audio seatbelt: unmuting is a user gesture, so resume the AudioContext here.
    // Inside the iframe the context can be suspended (or was never resumed if the room was
    // deep-linked without the Start gesture); a suspended context routes the interviewer's
    // voice into silence. This touches only the Web Audio context, never the mic gate.
    resumeTtsAnalyser();
    micOnRef.current = true;
    setMicOn(true);
    clearMuteFork();
    // If an answer (or a rating) is already due, start capturing right now — no extra tap.
    // ...unless the interviewer is still speaking, in which case the gate holds the mic shut
    // and auto-listen opens it the moment she finishes. Unmuting mid-question used to start
    // recording instantly, straight over the top of her.
    if (awaitingRating && roomMode && !ratingPills) startRatingCapture();
    else armCapture();
  };

  // Muted with an answer due -> after ~5s the interviewer offers the fork ALOUD
  // ("You're on mute — unmute, or switch to typing"). Once per question. It costs no
  // question slot (the endpoint inserts no message and changes no state), and it never
  // unmutes anyone.
  const clearMuteFork = () => {
    if (muteForkRef.current) { clearTimeout(muteForkRef.current); muteForkRef.current = null; }
  };
  const clearAbandon = () => {
    if (abandonRef.current) { clearTimeout(abandonRef.current); abandonRef.current = null; }
  };
  const clearCameraGrace = () => {
    if (cameraGraceRef.current) { clearTimeout(cameraGraceRef.current); cameraGraceRef.current = null; }
  };
  const questionKey = `${sstate?.current_stage || ""}|${sstate?.round_index ?? 0}|${sstate?.answer_count ?? 0}`;
  // Item 7: a new question opens with nothing heard yet, so the failsafe timer chip shows
  // until they start speaking. Reset the signal whenever the question changes.
  useEffect(() => {
    heardSpeechThisQRef.current = false;
    setHeardSpeechThisQ(false);
  }, [questionKey]);
  useEffect(() => {
    clearMuteFork();
    // Not while they are typing: somebody mid-sentence in the composer has already picked
    // their fork, and offering it aloud would be talking over an answer in progress.
    //
    // QA-02: `voiceLive`, not `roomMode`. Read the guard in TEXT: micOn is permanently
    // false there (the lobby joins with mic:false), so `|| micOn` PASSES rather than
    // blocks — a mic-off check cannot gate a mode that has no mic. The fork then fired at
    // five seconds, on every question, at a student whose pre-flight had just promised
    // "no microphone needed". A mode without a mic cannot be muted.
    if (!voiceLive || micOn || typingNow) return;
    if (!canAnswer || loading || audioPlaying || recording || transcribing) return;
    if (muteForkedForRef.current === questionKey) return;   // already offered for this question
    muteForkRef.current = setTimeout(async () => {
      muteForkedForRef.current = questionKey;
      try {
        const r = await reaskTurn(sessionId, voicePref || "female", "mute");
        sayNext({ role: "assistant", content: r.reply, audio_url: r.audio_url });
      } catch { /* a nudge must never break the interview */ }
    }, MUTE_FORK_DELAY_MS);
    return clearMuteFork;
  }, [voiceLive, micOn, typingNow, canAnswer, loading, audioPlaying, recording, transcribing, questionKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Interview Room (Phase C/E) ──
  // Attention signals are derived ON-DEVICE and reported as STRINGS. The camera never
  // leaves the browser — there is no frame path on this wire at all.
  const doEarlyWrap = async (reason) => {
    try {
      const r = await wrapSession(sessionId, reason);
      if (r?.state) setSstate(r.state);   // next_action becomes "readout" -> the debrief
    } catch { /* never trap the learner in a broken wrap */ }
  };

  useEffect(() => {
    if (ended || !sessionId) return;
    const stop = startFocusMonitor({
      onEvent: async (type) => {
        try {
          const r = await postFocusEvent(sessionId, type);
          // The SERVER owns the ladder; we just obey its verdict.
          if (typeof r?.escalation_level === "number") setEscalationLevel(r.escalation_level);
          if (r?.device_action === "wrap") await doEarlyWrap("camera_off");
        } catch { /* a dropped signal must never break the interview */ }
      },
    });
    return stop;
  }, [sessionId, ended]); // eslint-disable-line react-hooks/exhaustive-deps

  // Device commitment: report a camera that goes off mid-interview. The server runs the
  // ladder (nudge -> warn -> wrap) and the interviewer raises it in persona on the next
  // turn. Only ever applies if they JOINED with the camera on.
  const reportCameraOff = async () => {
    if (!config.camera) return;   // camera-off join is an accessibility path, not a breach
    try {
      const r = await postFocusEvent(sessionId, "camera_off");
      if (r?.device_action === "wrap") await doEarlyWrap("camera_off");
    } catch { /* noop */ }
  };

  // ══ THE ROOM'S CLOCKS ═════════════════════════════════════════════════════
  // The answer window is open once the interviewer has stopped talking and it is
  // genuinely the candidate's turn. That is when a question's clock starts — never while
  // IQ is still asking, and never while a rating is due.
  const answerWindowOpen = canAnswer && !loading && !audioPlaying && !transcribing
    && !ended && secondsLeft > 0;

  // ── E7.7: the per-question clock ──
  // The deadline is stamped ONCE per question and is absolute, so a re-render, a replayed
  // question or a mute nudge can't quietly hand them extra time.
  //
  // QA-03: ...except in TEXT, where "absolute" was the bug. There the deadline measures
  // continuous inactivity and every keystroke pushes it out (see roomPolicy). Reading and
  // thinking are free; the session clock is the only real limit.
  useEffect(() => {
    if (!answerWindowOpen || qKeyRef.current === questionKey) return;
    qKeyRef.current = questionKey;
    const budget = textMode
      ? TEXT_IDLE_EXPIRY_MS / 1000
      : questionSeconds(sstate?.current_stage, questionKind, checkinSecondsRef.current);
    qDeadlineRef.current = Date.now() + budget * 1000;
    textIdleSinceRef.current = Date.now();
    setQLeft(budget);
  }, [answerWindowOpen, questionKey, sstate?.current_stage, questionKind, textMode]);

  // QA-03: typing is the opposite of idling, so it resets the TEXT deadline. Keyed on the
  // draft rather than on focus: a caret parked in an empty composer is not an answer in
  // progress, and pretending it is would hand a walked-away student unlimited time.
  useEffect(() => {
    if (!textMode || !answerWindowOpen || qKeyRef.current !== questionKey) return;
    textIdleSinceRef.current = Date.now();
    qDeadlineRef.current = Date.now() + TEXT_IDLE_EXPIRY_MS;
  }, [input, textMode, answerWindowOpen, questionKey]);

  useEffect(() => {
    if (!answerWindowOpen || qKeyRef.current !== questionKey) { setQLeft(null); return; }
    const tick = () => {
      const left = Math.ceil((qDeadlineRef.current - Date.now()) / 1000);
      setQLeft(Math.max(0, left));
      // The gentle one, once per question, and only after a long true silence.
      if (textMode && textNudgedForRef.current !== questionKey
          && textIdleAction(Date.now() - textIdleSinceRef.current) === "nudge") {
        textNudgedForRef.current = questionKey;
        showToast(TEXT_IDLE_NUDGE_LINE);
      }
      if (left <= 0) expireRef.current?.();
    };
    tick();
    const t = setInterval(tick, 500);
    return () => clearInterval(t);
  }, [answerWindowOpen, questionKey, textMode]);

  // Expiry. Exactly two outcomes, and neither of them is a dead end: submit what they
  // got out, or skip the question and let the interviewer move the interview on. The
  // "waiting for an answer that can no longer be given" state is gone.
  const expireQuestion = () => {
    if (expiredForRef.current === questionKey) return;   // once per question, ever
    expiredForRef.current = questionKey;
    clearGrace();          // the mic must never sit counting into a question that is over
    clearMuteFork();
    clearAbandon();
    if (recordingRef.current || transcribingRef.current) {
      // A capture is in flight. Let it land: finishRecording submits whatever it heard as
      // the partial answer (and skips only if it heard nothing at all).
      timeoutPendingRef.current = true;
      if (recordingRef.current) stopRecording();
      return;
    }
    const { timeout, text } = expiryAction({ draft: input });
    send(text, { timeout });
  };
  useEffect(() => { expireRef.current = expireQuestion; });

  // ── Device policy: 90s of two dead channels is abandonment ──
  // Muted mic AND an empty composer, with an answer due. An unmuted candidate sitting
  // quiet is thinking (that is the per-question clock's business, and it ends in a skip);
  // a muted candidate who is typing is answering. Only the total dead end wraps, once.
  //
  // `voiceLive`, not `roomMode` (QA-02): "two dead channels" presumes a second channel.
  // TEXT has one, and its mic is off by definition — so the rule read every reading
  // student as an abandonment and armed a wrap against them at ninety seconds. In TEXT
  // the per-question clock is the only timer with standing.
  useEffect(() => {
    clearAbandon();
    if (abandonedRef.current) return;
    if (!shouldArmAbandon({
      inRoom: voiceLive, answerDue: answerWindowOpen, micOn, typedChars: input.trim().length,
    })) return;
    abandonRef.current = setTimeout(() => {
      abandonedRef.current = true;
      // The server persists the wrap; its state comes back with next_action "readout",
      // and the effect above routes us to the scored readout.
      doEarlyWrap(WRAP_NO_ANSWER);
    }, SILENT_ABANDON_MS);
    return clearAbandon;
  }, [voiceLive, answerWindowOpen, micOn, input, questionKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Device policy: the 60s camera grace ──
  // Turn the camera back on inside the grace and NOTHING escalates — it is a real second
  // chance, not a countdown. Let it lapse with the camera still off and we report it
  // again, which walks the server's ladder one rung (nudge -> warn -> wrap). The server
  // owns the ladder and the wrap decision; all we own here is the clock.
  useEffect(() => {
    clearCameraGrace();
    if (!config.camera || camOn || ended) return;   // a camera-off JOIN is never policed
    const stillOff = async () => {
      try {
        const r = await postFocusEvent(sessionId, "camera_off");
        if (r?.device_action === "wrap") { await doEarlyWrap(WRAP_CAMERA_OFF); return; }
      } catch { /* a dropped signal must never break the interview */ }
      cameraGraceRef.current = setTimeout(stillOff, CAMERA_GRACE_MS);
    };
    cameraGraceRef.current = setTimeout(stillOff, CAMERA_GRACE_MS);
    return clearCameraGrace;
  }, [camOn, ended, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Esc: cancel the auto-listen beat, else stop an in-flight recording.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (graceMs > 0) { clearGrace(); return; }
      if (recording) stopRecording();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [graceMs, recording]); // eslint-disable-line react-hooks/exhaustive-deps

  const acceptVoiceConsent = async () => {
    setConsentBusy(true);
    try { await recordConsent({ consent_type: "voice_recording", copy_version: CONSENT_COPY_VERSION, session_id: sessionId }); }
    catch { /* non-blocking: the server-side gate is authoritative */ }
    setConsentBusy(false);
    setVoiceConsented(true);
    setShowVoiceConsent(false);
    consentRef.current = true;   // the gate reads the ref, and setState has not landed yet
    armCapture();
  };

  const declineVoiceConsent = () => { setShowVoiceConsent(false); };

  // Cleanup: stop any in-flight recording/stream/timers/audio-graph on unmount.
  useEffect(() => () => {
    clearRecTimer();
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    if (graceRafRef.current) cancelAnimationFrame(graceRafRef.current);
    if (heardTimerRef.current) clearTimeout(heardTimerRef.current);
    if (ratingSilenceRef.current) clearTimeout(ratingSilenceRef.current);
    if (muteForkRef.current) clearTimeout(muteForkRef.current);
    if (abandonRef.current) clearTimeout(abandonRef.current);
    if (cameraGraceRef.current) clearTimeout(cameraGraceRef.current);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (bargeRafRef.current) cancelAnimationFrame(bargeRafRef.current);
    recordingRef.current = false;
    const ctx = audioCtxRef.current;
    if (ctx) { try { ctx.close(); } catch { /* noop */ } audioCtxRef.current = null; }
    const bctx = bargeCtxRef.current;
    if (bctx) { try { bctx.close(); } catch { /* noop */ } bargeCtxRef.current = null; }
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") { try { mr.stop(); } catch { /* noop */ } }
    stopMediaStream();
    // The live self-caption window recorder (item 6) runs off the same stream — stop it too.
    selfCapActiveRef.current = false;
    try { const wr = selfCapRecRef.current; selfCapRecRef.current = null; if (wr && wr.state !== "inactive") wr.stop(); } catch { /* noop */ }
    // The barge-in listener's mic outlives any single recording, so it has to be stopped
    // here explicitly — otherwise leaving the interview leaves the mic light on.
    const warm = warmStreamRef.current;
    if (warm) { try { warm.getTracks().forEach(t => t.stop()); } catch { /* noop */ } warmStreamRef.current = null; }
    try { clipPlayer()?.pause(); } catch { /* noop */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Diagnostics (dev only): surface stt_available once per state change so a
  // missing mic is instantly attributable — e.g. `undefined` means the client is
  // talking to a backend without the flags, `false` means a flag is off.
  useEffect(() => {
    if (import.meta.env?.DEV && sstate) {
      console.debug("[voice] stt_available =", sstate.stt_available, "| stage =", sstate.current_stage);
    }
  }, [sstate]);

  const send = async (overrideText, opts = {}) => {
    // overrideText comes from the Voice Stage review card; otherwise use the composer.
    // `opts.timeout` (E7.7) is set only when the per-question clock forced this turn.
    const timeout = opts.timeout || null;
    const textVal = (overrideText !== undefined ? overrideText : input).trim();
    if (loading || ended || awaitingRating) return;
    // A skip is the ONE turn allowed to carry no text — the server writes the marker.
    if (!textVal && timeout !== "skip") return;
    // Phase 3: this answer is SPOKEN if it came from the mic, else TYPED. Consume the
    // pending metrics/flag so a later typed answer doesn't inherit them. A skip has no
    // recording behind it, so it is neither.
    const skipped = timeout === "skip";
    const spoken = !skipped && answeredByVoiceRef.current;
    const metrics = pendingDeliveryRef.current;
    answeredByVoiceRef.current = false; pendingDeliveryRef.current = null;
    setMessages(m => [...m, { role: "user", content: skipped ? SKIP_MARKER : textVal, meta: skipped ? "SKIPPED" : spoken ? "SPOKEN" : "TYPED" }]); setInput(""); setLoading(true); setError(null);

    // ── REALISM: the acknowledgment ──
    // "Hmm." — NOW, on a pre-cached clip, while the reply is still being written. This is
    // the whole point: the thinking gap was always going to be two or three seconds long,
    // and what it sounded like was a machine loading. A skip gets none — there was nothing
    // to acknowledge, and "Interesting." after a silence would be absurd.
    if (!skipped) playAck();

    try {
      if (turnLogRef.current) turnLogRef.current.llmStartTs = Date.now();   // instrumentation
      const res = await sendTurn(sessionId, textVal, sstate?.current_stage, voicePref || "female", spoken ? metrics : null, timeout);
      if (turnLogRef.current) turnLogRef.current.llmEndTs = Date.now();     // LLM+first-clip TTS
      sayNext({ role: "assistant", content: res.reply, audio_segments: res.audio_segments || [] });
      setSstate(res.state);
      // The engagement floor: a check-in is a direct question and carries its own short
      // clock (45s), not the round's full three-minute budget.
      setQuestionKind(res.question_kind || "question");
      if (res.checkin_seconds) checkinSecondsRef.current = res.checkin_seconds;
      // Realism v2: if this answer is rating-gated, IQ asks for the rating ALOUD once
      // the reply finishes playing (see onAudioEnded).
      if (res.tone) setTone(res.tone);
      if (typeof res.escalation_level === "number") setEscalationLevel(res.escalation_level);
      ratingAudioRef.current = res.rating_audio_url || null;
      ratingPromptRef.current = res.rating_prompt || "";
      ratingAskedRef.current = false;
      setRatingPills(false);
      // With TTS off there is no audio, so no sequencer finish to drive the flow — nudge
      // it manually so the hands-free loop still works. This MUST test the segments: they
      // are the only thing a reply is spoken from now, and keying it off the old
      // whole-reply audio_url would hand the floor back while IQ was still asking.
      if (roomModeRef.current && !res.audio_segments?.length) setTimeout(() => audioEndedRef.current?.(), 300);
      // TTS off (no audio) -> there is no playback hop to wait for; close the log line now.
      if (!res.audio_segments?.length) emitTurnLog();
    } catch (e) {
      setError(e.message);
      if (turnLogRef.current) turnLogRef.current.sttStatus = turnLogRef.current.sttStatus || "ok";
      emitTurnLog();   // the turn errored — still record the line rather than lose it
      try { setSstate(await fetchSessionState(sessionId)); } catch { /* noop */ }
    } finally {
      setLoading(false);
      // Refocus the composer whenever one is actually on screen (classic, or the
      // typed fallback inside voice mode). On the pure stage there is nothing to focus.
      if (!roomModeRef.current || typedInVoiceRef.current) setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const rate = async (val) => {
    if (ratingBusy || !awaitingRating || !sstate?.last_answer_id) return;
    setRatingBusy(true); setError(null);
    try {
      const res = await submitRating(sessionId, sstate.last_answer_id, val);
      setSstate(res.state);
      // Rating done: reset the spoken-rating machinery and hand the floor straight
      // back for the next answer (its question was already spoken with the reply).
      clearRatingSilence();
      ratingListeningRef.current = false;
      ratingAskedRef.current = false;
      ratingAudioRef.current = null;
      setRatingPills(false);
      if (roomModeRef.current) setTimeout(() => audioEndedRef.current?.(), 400);
    } catch (e) {
      setError(e.message);
      try { setSstate(await fetchSessionState(sessionId)); } catch { /* noop */ }
    } finally { setRatingBusy(false); }
  };

  // Realism v2: correct a mis-transcribed answer from the drawer (idempotent PATCH).
  const onEditLast = async (textVal) => {
    setEditBusy(true);
    try {
      await editLastAnswer(sessionId, textVal);
      setMessages(m => {
        const copy = [...m];
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].role === "user") { copy[i] = { ...copy[i], content: textVal }; break; }
        }
        return copy;
      });
    } catch (e) { setError(e.message); }
    finally { setEditBusy(false); }
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

  // Item 7: the per-question clock is now an INVISIBLE FAILSAFE on the stage. It still runs
  // exactly as before (the expiry ladder is untouched), but its chip surfaces only when it
  // is actually useful: in the final 30 seconds, or when no speech has been detected at all
  // for this question (dead air, where a visible clock is reassuring rather than pressuring).
  // In classic typed mode there is no speech signal, so the clock stays visible as before.
  //
  // QA-10: the dead-air clause is a VOICE failsafe, so it gates on voiceLive. In TEXT
  // `recording` is always false and `heardSpeechThisQ` is only ever set by the mic meter,
  // so the clause was permanently true and the "invisible failsafe" was a countdown that
  // never left the screen — ticking at a student mid-sentence, which is the exact pressure
  // the design set out to remove. In TEXT the chip now appears at the 30s warning only.
  const qWarnNow = qLeft != null && qLeft <= QUESTION_WARN_SECONDS;
  const showQChip = qLeft != null && (
    !roomMode || qWarnNow || (voiceLive && !recording && !heardSpeechThisQ)
  );
  // ── THE ROOM, DERIVED ONCE ───────────────────────────────────────────────
  // The lit tile, the strip and her face are three renderings of ONE state, so they are
  // computed from one set of signals, in one place, by tested functions. The room used to
  // answer "what is happening?" in three floating overlays that each did their own
  // arithmetic — which is how the state label ended up on top of the name tag, and how
  // "You're muted" ended up pinned 150px off an edge that moved.
  const roomSignals = {
    recording, transcribing, loading, connecting, speaking: audioPlaying,
    micOn, answerDue: canAnswer, ended,
  };
  const speaker = activeSpeaker(roomSignals);
  const strip = statusStrip({ ...roomSignals, recLabel: mmss(recSeconds), textMode });
  const surface = studentSurface({
    recording, transcribing, heard: heard || "", selfCaption, selfCaptionsOn: selfCaptions,
  });
  const slot = chatSlot({ textMode, chatOpen });

  // Typing is always available, on every question — never a fallback of last resort — and it
  // routes through exactly the same answer path as speech.
  const composerPlaceholder = awaitingRating ? "Rate your confidence to continue"
    : ended ? "Interview ended"
    : reverseMode ? "Ask your question…"
    : "Type your answer…";

  const openChat = () => {
    setChatOpen(true);
    // Opening it from the keyboard button is a request to TYPE, so land in the composer.
    // (Opening it from the transcript button is a request to READ, and does not focus —
    // focusing would tell canArmCapture they chose the composer, and kill hands-free.)
    setTimeout(() => composerRef.current?.focus(), 0);
  };

  return (
    <div style={{ fontFamily: T.font, width: "100%", maxWidth: "100%", boxSizing: "border-box", overflowX: "hidden", display: "flex", flexDirection: "column", height: "100%", minHeight: 500 }}>
      {/* Interview HUD — responsive header (replaces the legacy fixed-row header
          that clipped its title on narrow viewports). Wraps and truncates; no
          fixed heights; safe padding down to 360px. */}
      <div className="iq-hud">
        <div className="iq-hud-bar">
          <div className="iq-hud-brand">
            <div className="iq-hud-title">InterviewIQ</div>
            <div className="iq-hud-sub">{config.role}{config.company ? ` — ${config.company}` : " — General"}</div>
          </div>
          <div className="iq-hud-right" style={{ position: "relative" }}>
            {/* E2: NO interviewer-mute control — the panel is always audible. Replay
                stays (re-hear a question); accessibility is carried by CC captions. */}
            {canReplay && (
              <div className="iq-hud-audio">
                <button className="iq-audio-btn" onClick={replay} title="Replay question" aria-label="Replay question">
                  <IconReplay />
                </button>
              </div>
            )}
            {/* The transcript is the chat panel. This opens it to READ — deliberately
                without focusing the composer, because focus is what tells the capture gate
                they chose to type, and looking up an earlier question must not cost them
                the microphone. In text mode the panel is always on screen already. */}
            {roomMode && !textMode && (
              <button className="iq-audio-btn" onClick={() => setChatOpen(true)}
                title="Open transcript" aria-label="Open transcript">
                <IconTranscript />
              </button>
            )}
            {/* Classic typed mode keeps the modal drawer — there is no room column to put
                a panel in when the whole screen is already the conversation. */}
            {!roomMode && (
              <button className="iq-audio-btn" onClick={() => setDrawerOpen(true)} title="Open transcript" aria-label="Open transcript">
                <IconTranscript />
              </button>
            )}
            {sttAvailable && (
              <button className="iq-audio-btn" onClick={() => setMenuOpen(o => !o)} title="Voice settings"
                aria-label="Voice settings" aria-expanded={menuOpen} aria-haspopup="menu">
                <IconSliders />
              </button>
            )}
            <span className="iq-hud-timer" style={{ color: secondsLeft <= 60 ? "#ff6b6b" : secondsLeft <= 180 ? T.gold : "#fff" }}>{mmss(secondsLeft)}</span>
            <button className="iq-hud-end" onClick={handleEndClick}>End</button>
            {menuOpen && (
              <StageSettingsMenu
                onClose={() => setMenuOpen(false)}
                voiceStage={voiceStage} setVoiceStage={setVoiceStage}
                captions={captions} setCaptions={setCaptions}
                selfCaptions={selfCaptions} setSelfCaptions={setSelfCaptions}
                selfCaptionsSupported={SELF_CAPTIONS_SUPPORTED}
                voice={voicePref} setVoice={setVoicePref}
              />
            )}
          </div>
        </div>
        <div className="iq-hud-stage-row">
          <span className="iq-hud-stage">
            <span className="iq-hud-stage-dot" />
            <span className="iq-hud-stage-label">{stageLabel}</span>
          </span>
          {/* E7.7 + item 7: the clock on THIS question. On the stage it is an INVISIBLE
              failsafe — it runs the whole time (the expiry ladder is unchanged), but the
              chip only surfaces in the final 30s or when no speech has been heard at all, so
              a relaxed answerer is never watched by a ticking clock. When it hits zero we
              submit what they have or move on, so it is never a cliff either. */}
          {showQChip && (
            <span aria-live="off" title="Time left on this question"
              style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: 10, padding: "2px 10px", borderRadius: 999, background: "rgba(255,255,255,0.10)", fontFamily: IQ.mono, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", fontVariantNumeric: "tabular-nums", color: qLeft <= 10 ? "#ff6b6b" : qLeft <= QUESTION_WARN_SECONDS ? T.gold : "rgba(255,255,255,.75)" }}>
              This question {mmss(qLeft)}
            </span>
          )}
          {/* On the stage the ORB is the state indicator, so the chip is removed there. */}
          {!roomMode && voiceChip && (
            <span aria-live="polite" style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: 10, padding: "2px 10px", borderRadius: 999, background: "rgba(255,255,255,0.10)", fontFamily: IQ.mono, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "#fff" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: voiceChip.color, animation: "iqRecDot 1.1s ease-in-out infinite", flexShrink: 0 }} />
              {voiceChip.label}
            </span>
          )}
        </div>
      </div>

      {roomMode ? (
        <>
          {/* ══ THE INTERVIEW ROOM ══ A two-person call, not a chat log.
              Read top to bottom, the room is now four rows and nothing floats:
                the GRID    — two equal tiles (+ the chat panel's column when open)
                the STRIP   — the one line saying what is happening
                the CAPTIONS— a fixed-height area that scrolls rather than clips
                the BAR     — the controls
              Everything that used to be absolutely positioned over the stage — the state
              label, the muted chip, the waveform, the "Heard:" flash — now lives in the row
              that owns it. */}
          <div className="iq-room">
            <div className={"iq-room-grid" + (slot === "side" ? " iq-room-grid--chat" : "")}>
              <InterviewerTile state={orbState} active={speaker === SPEAKER_INTERVIEWER}
                voice={voicePref} difficulty={config.difficulty}
                seed={config.roomSeed || sessionId}
                tone={tone} escalationLevel={escalationLevel}
                stage={sstate?.current_stage || ""} group={messages.length}
                name={config.interviewerName} />

              {/* The second tile is THEIRS — the camera in voice mode, the chat panel in
                  text mode. Two tiles either way; only the occupant changes. */}
              {slot === "student-tile" ? (
                <ChatPanel
                  messages={messages} name={config.name}
                  onSend={send} input={input} setInput={setInput}
                  disabled={inputDisabled} placeholder={composerPlaceholder}
                  onComposer={setComposerFocused} composerRef={composerRef}
                  onEditLast={ended ? null : onEditLast} editBusy={editBusy} />
              ) : (
                <StudentTile on={camOn} micOn={micOn}
                  initial={(config.name || "You").trim().charAt(0).toUpperCase() || "Y"}
                  name={config.name || "You"} active={speaker === SPEAKER_STUDENT}
                  surface={surface} levels={levels} recLabel={mmss(recSeconds)} />
              )}

              {/* The collapsible third column. Below ~1000px the CSS floats it over the
                  grid instead — same panel, same component, it just runs out of room. */}
              {slot === "side" && (
                <div className="iq-chat--side" style={{ display: "flex", minHeight: 0, minWidth: 0 }}>
                  <ChatPanel
                    messages={messages} name={config.name} onClose={() => setChatOpen(false)}
                    onSend={send} input={input} setInput={setInput}
                    disabled={inputDisabled} placeholder={composerPlaceholder}
                    onComposer={setComposerFocused} composerRef={composerRef}
                    onEditLast={ended ? null : onEditLast} editBusy={editBusy} />
                </div>
              )}
            </div>

            {/* ══ THE ONE STATUS STRIP ══ Under both tiles: SPEAKING / LISTENING (with the
                rec counter) / THINKING, and — the only state that is an instruction rather
                than a description — muted-with-an-answer-due. It replaces the label that
                used to sit under her face and land on her name tag, and the muted chip that
                floated over the stage. One place, one answer. */}
            <div className="iq-strip-row">
              <div className={`iq-strip iq-strip--${strip.tone}` + (strip.cue ? " iq-strip--cue" : "")}
                role="status" aria-live="polite">
                {strip.key === "muted"
                  ? <span style={{ display: "inline-flex", color: IQ.orange }}><IconMicOff size={13} /></span>
                  : <span className="iq-strip-dot" />}
                <span className="iq-strip-label">{strip.label}</span>
                {strip.detail && <span className="iq-strip-detail">{strip.detail}</span>}
                {/* The auto-listen grace beat: the one thing the strip counts DOWN to.
                    Shown here rather than as its own overlay, because "the mic is about to
                    open" is a state of the room like any other. */}
                {graceMs > 0 && !recording && (
                  <span className="iq-strip-detail">
                    Listening in {(graceMs / 1000).toFixed(1)}s — mute to cancel
                  </span>
                )}
              </div>
            </div>

            {/* ══ CAPTIONS ══ Fixed height, reserved whether or not there is anything in it,
                so the room does not jump as she starts and stops. It SCROLLS: a long case
                prompt is fully readable, where the old two-line clamp cut it off with an
                ellipsis and looked like it had worked. Speaking: the sentence in the air.
                Idle: the whole question, so it can always be re-read.
                It is HERS alone now — the student's running transcript has its own surface
                in their own tile, which is where their words belong. */}
            <div className="iq-cc-area" ref={ccRef}>
              {/* FAST START: the room is up and she is on screen — this is the beat in
                  which she is drawing breath, and it should read as exactly that rather
                  than as a page that has not finished loading. */}
              {connecting ? (
                <div className="iq-connecting">
                  <span className="iq-connecting-dot" />
                  <span className="iq-connecting-dot" />
                  <span className="iq-connecting-dot" />
                  <span>Connecting you with your interviewer…</span>
                </div>
              ) : captions && ccLine ? (
                <div className="iq-cc">{ccLine}</div>
              ) : (
                <div className="iq-cc-empty">
                  {captions ? "Captions will appear here." : "Captions are off."}
                </div>
              )}
            </div>

            {/* Room-level notices. These are genuinely exceptional — a blocked autoplay, an
                error, the session clock running out — so they get a row only when one is
                actually live, rather than a permanent slot or a floating overlay. */}
            {(needsTap && canReplay && !muted) || error || sttToast || reverseMode || secondsLeft <= 0
              || (awaitingRating && !loading && (ratingPills || chatOpen || !micOn)) ? (
              <div className="iq-notice-row">
                {awaitingRating && !loading && (ratingPills || chatOpen || !micOn) && (
                  <RatingWidget busy={ratingBusy} onRate={rate} />
                )}
                {reverseMode && !loading && !awaitingRating && (
                  <div className="iq-notice iq-notice--gold">Your turn to interview us. Ask us two questions.</div>
                )}
                {/* Embedded audio seatbelt: playback was blocked (autoplay policy /
                    suspended context inside the iframe). Rather than fail silently, we offer
                    one in-brand tap that unlocks sound and replays the current question. */}
                {needsTap && canReplay && !muted && (
                  <button onClick={enableAudio} className="iq-ghostbtn">
                    <IconSpeaker size={15} /> Tap to enable audio
                  </button>
                )}
                {error && <div className="iq-notice iq-notice--err">{error}</div>}
                {sttToast && <div className="iq-notice iq-notice--warn">{sttToast}</div>}
                {/* The session clock ran out. There is no "no answers given" cul-de-sac
                    any more: we wrap the interview server-side and score what happened,
                    however little of it there was. */}
                {secondsLeft <= 0 && (
                  <div className="iq-notice">That&apos;s time — wrapping up. Generating your report...</div>
                )}
              </div>
            ) : null}
          </div>

          {/* ══ CONTROL BAR ══ Meet-style. The mic doubles as push-to-talk in the
              auto-listen gaps, preserving the existing tap-to-speak semantics. */}
          <div className="iq-bar">
            {/* TEXT shows neither a mic nor a camera control, and that is a PROMISE being
                kept rather than a tidy-up. Unmuting calls getUserMedia — so leaving the
                button here left a one-tap route to the exact permission dialog a TEXT
                session guarantees the student will never see. A control for a device the
                mode does not use is at best clutter and at worst a broken promise. */}
            {!textMode && (
              <>
                {/* MEET SEMANTICS: a persistent MUTE TOGGLE, not tap-to-speak. Unmuted, every
                    answer window captures automatically and this shows live state. Muted, no
                    capture ever happens. We never auto-unmute. */}
                <button
                  className={"iq-ctl" + (!micOn ? " iq-ctl--off" : recording ? " iq-ctl--live" : "")}
                  onClick={toggleMic}
                  aria-pressed={!micOn}
                  title={micOn ? (recording ? "Listening — click to mute" : "Mute") : "Unmute"}
                  aria-label={micOn ? (recording ? "Listening. Click to mute." : "Mute microphone") : "Unmute microphone"}>
                  {micOn ? <IconMic /> : <IconMicOff />}
                </button>

                {/* QA-04: the camera control is VIDEO's, for the same reason the whole
                    block is not TEXT's — turning it on calls getUserMedia, so in AUDIO it
                    was a one-tap route to a camera prompt that mode promises never to show. */}
                {videoMode && (
                  <button
                    className={"iq-ctl" + (camOn ? "" : " iq-ctl--off")}
                    onClick={() => {
                      const next = !camOn;
                      setCamOn(next);
                      if (!next) reportCameraOff();   // the server runs the ladder
                    }}
                    title={camOn ? "Turn camera off" : "Turn camera on"}
                    aria-label={camOn ? "Turn camera off" : "Turn camera on"}>
                    {camOn ? <IconCam /> : <IconCamOff />}
                  </button>
                )}
              </>
            )}

            {/* QA-15: captions caption the sentence being SPOKEN. TEXT has no speech, so
                the control toggles nothing — the same "a control for a device the mode does
                not use is at best clutter and at worst a broken promise" rule the mic and
                camera buttons already follow one block up. */}
            {voiceLive && (
              <button className={"iq-ctl" + (captions ? " iq-ctl--on" : "")}
                onClick={() => setCaptions(!captions)}
                title={captions ? "Turn captions off" : "Turn captions on"}
                aria-pressed={captions} aria-label="Toggle captions">
                <IconCC />
              </button>
            )}

            {/* TYPING and the TRANSCRIPT were two buttons opening two surfaces (a slide-out
                composer and a modal drawer) that were really one thing: the conversation.
                One toggle now, one panel. Typing is ALWAYS available, on every question —
                never a fallback of last resort — and it routes through exactly the same
                answer path as speech. In text mode the panel IS the second tile and cannot
                be collapsed away, so there is nothing here to toggle. */}
            {!textMode && (
              <button className={"iq-ctl" + (chatOpen ? " iq-ctl--on" : "")}
                onClick={() => (chatOpen ? setChatOpen(false) : openChat())}
                title={chatOpen ? "Close chat" : "Chat — read the transcript or type an answer"}
                aria-pressed={chatOpen} aria-label="Chat and transcript">
                <IconKeyboard />
              </button>
            )}

            <button className="iq-ctl iq-ctl--end" onClick={handleEndClick} aria-label="End interview">
              End
            </button>
          </div>
        </>
      ) : (
        <>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "20px 28px", background: T.bg }}>
        <div style={{ maxWidth: 700, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {messages.map((m, i) => { const isV = m.role === "assistant"; const speaking = isV && i === lastAssistantIdx && audioPlaying; return (
            <div key={i} style={{ display: "flex", gap: 10, flexDirection: isV ? "row" : "row-reverse", alignItems: "flex-start", animation: "iqFade .3s ease" }}>
              <div className={speaking ? "iq-avatar-speaking" : ""} style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: isV ? T.navy : T.border, color: isV ? "#fff" : T.navy, fontWeight: 800, fontSize: 11 }}>{isV ? "IQ" : (config.name?.[0]?.toUpperCase() || "Y")}</div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: isV ? "flex-start" : "flex-end", maxWidth: "78%" }}>
                <div style={{ padding: "12px 16px", borderRadius: isV ? "2px 12px 12px 12px" : "12px 2px 12px 12px", fontSize: 14, lineHeight: 1.65, background: isV ? T.white : T.navy, color: isV ? T.text : "#fff", border: isV ? "1px solid " + T.border : "none", fontFamily: T.font }}>{isV ? renderMd(m.content) : m.content}</div>
                {!isV && m.meta && <span style={{ fontSize: 10, color: T.subtle, marginTop: 3, fontFamily: IQ.mono, letterSpacing: "0.05em" }}>{m.meta === "SPOKEN" ? "Spoken" : m.meta === "SKIPPED" ? "Time ran out" : "Typed"}</span>}
              </div>
            </div>); })}
          {loading && <div style={{ display: "flex", gap: 10 }}><div style={{ width: 32, height: 32, borderRadius: "50%", background: T.navy, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ color: "#fff", fontWeight: 800, fontSize: 11 }}>IQ</span></div><div style={{ padding: "14px 18px", borderRadius: "2px 12px 12px 12px", background: T.white, border: "1px solid " + T.border }}><div style={{ display: "flex", gap: 5 }}>{[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: T.subtle, animation: "iqPulse 1.2s ease-in-out infinite", animationDelay: i * 0.15 + "s" }} />)}</div></div></div>}
          {needsTap && canReplay && !muted && (
            <button onClick={replay} style={{ alignSelf: "flex-start", display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 20, border: "1px solid " + IQ.teal, background: "#fff", color: IQ.navy, fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: T.font }}>
              <span style={{ color: IQ.teal, display: "inline-flex" }}><IconSpeaker size={16} /></span> Tap to hear the question
            </button>
          )}
          {awaitingRating && !loading && <RatingWidget busy={ratingBusy} onRate={rate} />}
          {reverseMode && !loading && <div style={{ padding: "12px 16px", borderRadius: 10, background: IQ.cream, border: "1px solid " + IQ.gold, color: "#5a4500", fontSize: 13, fontWeight: 600, fontFamily: IQ.sans }}>Your turn to interview us. Ask us two questions.</div>}
          {error && <div style={{ padding: "10px 14px", borderRadius: 8, background: T.redSoft, color: T.red, fontSize: 13 }}>{error}</div>}
          {secondsLeft <= 0 && <div style={{ padding: "14px 18px", borderRadius: 8, background: T.bg, border: "1px solid " + T.border, textAlign: "center", fontSize: 14, color: T.muted }}><span style={{ fontWeight: 700 }}>That&apos;s time — wrapping up. Generating your report...</span></div>}
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
          <button onClick={() => send()} disabled={inputDisabled || !input.trim()} className="mba-btn-primary" style={{ padding: "10px 22px", fontSize: 14, opacity: inputDisabled || !input.trim() ? 0.5 : 1 }}>Send</button>
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
        </>
      )}

      {/* The full conversation is always one tap away in either mode — but it is a
          different object in each. On the stage it is the CHAT PANEL, a column of the room.
          In classic typed mode the whole screen is already the conversation, so there is no
          column to put a panel in, and the modal drawer stays. Both carry the correction
          affordance, because the answer is auto-submitted and a mis-transcription has to be
          fixable wherever you are reading it. */}
      {!roomMode && (
        <TranscriptDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)}
          messages={messages} name={config.name}
          onEditLast={ended ? null : onEditLast} editBusy={editBusy} />
      )}

      {showVoiceConsent && <VoiceConsentModal onAccept={acceptVoiceConsent} onDecline={declineVoiceConsent} busy={consentBusy} />}
    </div>
  );
}

// ── THE READOUT ────────────────────────────────────────────────────────────
// ONE document, read top to bottom, and the ORDER IS THE COACHING:
//
//   1 context  -> 2 verdict -> 3 what went well -> 4 delivery -> 5 presence
//   -> 6 the fixes -> 7 the plan -> 8 READINESS (the band, once, last)
//   -> 9 the working -> 10 when to come back
//
// Two things this fixes, both of which a full-page screenshot used to show:
//   * It rendered as TWO stacked designs — a navy report, then a second navy
//     scorecard — with the band printed on both. Now: two surfaces, one card
//     system, and the band exists in exactly one place (the Readiness block).
//   * A score with no context read as a verdict. Every section now carries the
//     context chip, and the Session Profile strip opens the page, because
//     "100" means nothing until you know it was Easy and it was ten minutes.
//
// The band goes LAST on purpose. It used to open the page, which meant the first
// thing a struggling learner saw was a label, and everything after it was noise.
// Nobody hears a correction until they have been met.

// The context every number on this page is read against. Item 1: no score anywhere
// without it.
const profileChip = (p) => {
  if (!p) return "";
  return [p.difficulty, p.duration_min ? `${p.duration_min} min` : "", p.feedback === "coach" ? "Coach" : "Interview"]
    .filter(Boolean).join(" · ");
};

const ContextChip = ({ profile }) => {
  const t = profileChip(profile);
  return t ? <span className="rd-chip">{t}</span> : null;
};

// The one card. Everything that is coaching prose is one of these — same width,
// same radius, same padding rhythm, same header treatment.
function RdCard({ title, titleColor, accent, profile, children }) {
  return (
    <div className="rd-card" style={accent ? { borderLeft: "3px solid " + accent } : null}>
      <div className="rd-h">
        <span className="rd-t" style={titleColor ? { color: titleColor } : null}>{title}</span>
        <ContextChip profile={profile} />
      </div>
      <div className="rd-b">{children}</div>
    </div>
  );
}

// Item 10, last line: missing data is an honest one-line card, never a silently
// absent section. A section that vanishes leaves the learner wondering whether
// they failed it; a card that says "we didn't measure this" cannot be misread.
function RdMissing({ title, profile, children }) {
  return (
    <RdCard title={title} profile={profile}>
      <div style={{ fontSize: 13, color: T.muted, fontFamily: IQ.sans, lineHeight: 1.6 }}>{children}</div>
    </RdCard>
  );
}

// Item 1: the SESSION PROFILE STRIP. Navy, DM Mono, and the first thing on the page.
// Every readout opens with this — the whole sprint is here in one component: the
// context comes before the number, always, because Easy/10-min/100 and
// Critical/45-min/75 are not the same achievement and a bare score says they are.
function SessionProfileStrip({ profile, early, scored }) {
  const p = profile || {};
  const covered = p.rounds_covered || [];
  const skipped = p.rounds_skipped || [];
  const item = (label, value) => (
    <div className="rd-strip-i" key={label}>
      <div className="rd-strip-l">{label}</div>
      <div className="rd-strip-v">{value || "—"}</div>
    </div>
  );
  return (
    <div className="rd-navy">
      <div className="rd-h"><span className="rd-t">Session profile</span></div>
      <div className="rd-b">
        <div className="rd-strip">
          {item("Role", p.company ? `${p.role} — ${p.company}` : p.role)}
          {item("Level", p.level)}
          {item("Difficulty", p.difficulty)}
          {item("Duration", p.duration_min ? `${p.duration_min} min` : "")}
          {/* Reserved until the Intake sprint ships the TEXT/VOICE/HYBRID selector.
              It shows an em-dash rather than a guess — this strip is the one place
              on the page that must never be wrong. */}
          {item("Mode", p.mode)}
          {item("Feedback", p.feedback === "coach" ? "Coach" : "Interview")}
        </div>
        <div className="rd-rule">
          <div className="rd-sub">Rounds</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {covered.map((r) => (
              <span key={r} className="mba-pill" style={{ background: "rgba(0,196,160,.14)", color: IQ.teal }}>{r}</span>
            ))}
            {skipped.map((r) => (
              <span key={r} className="mba-pill" style={{ background: "rgba(255,255,255,.06)", color: "rgba(255,255,255,.45)" }}>{r} — not reached</span>
            ))}
            {covered.length === 0 && skipped.length === 0 && (
              <span style={{ fontSize: 12, color: "rgba(255,255,255,.45)" }}>No rounds recorded.</span>
            )}
          </div>
          {skipped.length > 0 && (
            <div style={{ fontSize: 12, color: "rgba(255,255,255,.5)", marginTop: 10, lineHeight: 1.55 }}>
              A round you didn&rsquo;t reach is not a round you failed. It isn&rsquo;t marked against your answers —
              it only means we saw less of you.
            </div>
          )}
          {early && (
            <div style={{ fontSize: 12, color: "rgba(255,255,255,.55)", marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,.12)", lineHeight: 1.55 }}>
              {earlyWrapNote(early, scored)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Voice Phase 3 Part D: Delivery Profile — informational, and NOT in the benchmark.
// Item 9: its readiness pill is gone. Delivery is report-only; a readiness verdict was
// never its to make, and printing one here is how the page came to say a band twice.
function DeliveryBlock({ delivery, profile }) {
  // QA-08: TEXT readouts have no Delivery Profile — not an empty one, not a "we couldn't
  // measure it" one. Every branch below reports on a VOICE that a typed session never had,
  // so the kindest of them still told a student who chose typing to "answer aloud next
  // session" on the scorecard for the mode they chose. scoring.py already says the readout
  // "NEVER fabricates a voice Delivery metric for a session that had no voice"; this is
  // that rule applied to the block itself rather than only to the numbers inside it.
  if (String(profile?.mode || "").toUpperCase() === "TEXT") return null;
  if (!delivery || Object.keys(delivery).length === 0) {
    return <RdMissing title="Delivery Profile" profile={profile}>Your delivery wasn&rsquo;t measured this session, so there&rsquo;s nothing to report here — and nothing counted against you for it.</RdMissing>;
  }
  if (!delivery.enough_data) {
    return <RdMissing title="Delivery Profile" profile={profile}>{delivery.message || "Not enough spoken answers to read your delivery. Answer aloud next session and this fills in."}</RdMissing>;
  }
  const metric = (label, val, suffix) => (
    <div className="mba-metric"><div className="mba-metric-label">{label}</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono }}>{val ?? "—"}{suffix ? <span style={{ fontSize: 12, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>{suffix}</span> : null}</div></div>
  );
  const line = (t) => t ? <div style={{ fontSize: 13, lineHeight: 1.65, color: T.text, fontFamily: IQ.sans, marginBottom: 6 }}>{t}</div> : null;
  return (
    <RdCard title="Delivery Profile" profile={profile}>
      <div className="mba-grid-3" style={{ marginBottom: 14 }}>
        {metric("Avg Pace", delivery.avg_wpm, " wpm")}
        {metric("Fillers / min", delivery.filler_per_min, "")}
        {metric("Spoken Answers", delivery.spoken_answers, "")}
      </div>
      {line(delivery.pace_verdict)}
      {line(delivery.filler_note)}
      {line(delivery.pause_note)}
      {delivery.note && <div style={{ fontSize: 11, color: T.subtle, fontStyle: "italic", marginTop: 4 }}>{delivery.note}</div>}
    </RdCard>
  );
}

// E6: a strength used to be a bare string. It is now {strength, evidence} — the mentor
// quotes the candidate back to themselves, because a readout that could have been written
// without listening to THIS person is worthless. Sessions scored before the change (and
// every row in History) still hold strings, so normalise instead of crashing on them.
const asStrength = (s) => (typeof s === "string" ? { strength: s, evidence: "" } : (s || {}));

// Interview Room: the presence card. It reports COUNTS of observable behaviour and one
// coaching line — never an emotion, never a judgement about the person, and (item 9)
// never a band: presence is report-only and never enters the benchmark.
function PresenceBlock({ presence, profile }) {
  const p = presence || {};
  if (!p.measured && !p.coaching_note) {
    return <RdMissing title="Presence Profile" profile={profile}>Attention signals weren&rsquo;t measured this session, so there&rsquo;s nothing to report — and nothing counted against you for it.</RdMissing>;
  }
  const counts = Object.entries(p.by_type || {});
  const LABELS = {
    tab_hidden: "Left the interview tab", window_blur: "Switched window",
    no_face: "Out of frame", multiple_faces: "Someone else in frame",
    looking_away: "Looked away from camera",
  };
  return (
    <RdCard title="Presence Profile" profile={profile}>
      {counts.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          {counts.map(([k, v]) => (
            <span key={k} className="mba-pill mba-pill-warn">{LABELS[k] || k} ×{v}</span>
          ))}
        </div>
      )}
      <div style={{ fontSize: 13, lineHeight: 1.65, color: T.text, fontFamily: IQ.sans }}>{p.coaching_note}</div>
      {p.camera_signals_disabled && (
        <div style={{ fontSize: 11, color: T.subtle, fontStyle: "italic", marginTop: 10 }}>
          You joined with your camera off, so camera cues were never measured — and are never counted against you.
        </div>
      )}
    </RdCard>
  );
}

// Item 8: SHOW THE MATH. The expandable working behind the benchmark, in plain words,
// listing THIS attempt's real factors — read from what the server stored, so an old
// attempt explains itself with the weights it was actually scored on.
//
// A student who cannot see why 100 became 42 has simply been told they are worse than
// they are. This is the difference between a score and an accusation.
function ShowTheMath({ math }) {
  if (!math || math.length === 0) return null;
  return (
    <details className="rd-math">
      <summary>How this score is calculated</summary>
      <div style={{ marginTop: 8 }}>
        {math.map((r, i) => (
          <div key={i} className="rd-math-r">
            <span className="rd-math-v">{r.value}</span>
            <div style={{ minWidth: 0 }}>
              <div className="rd-math-l">{r.label}</div>
              <div className="rd-math-n">{r.note}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="rd-math-n" style={{ marginTop: 12, fontStyle: "italic" }}>
        Your experience level is already built into the first line — it is not weighted
        again, so nothing here counts it twice.
      </div>
    </details>
  );
}

// Item 10 (7): THE READINESS BLOCK — the last major section, and the ONE place a band
// exists on this page. The band, the per-round pills, the calibration delta, the
// competency bars, the benchmark and the working are all folded into this single navy
// block. There is no second scorecard below it: that is exactly what "two stacked
// designs" used to be.
function ReadinessBlock({ d, profile }) {
  const band = d.overall_band || "Not Ready";
  const bandStyle = BAND_STYLE[band] || BAND_STYLE["Not Ready"];
  const roundBands = d.round_bands || {};
  const cal = d.calibration || {};
  const ss = d.sub_scores || {};
  const score = d.score || null;
  const calHasData = cal.profile && cal.profile !== "insufficient_data" && cal.avg_confidence != null;
  const calCopy = CALIBRATION_COPY[cal.profile];
  const ssEntries = Object.entries(ss);
  const pk = (k) => ({ communication: "Communication", roleKnowledge: "Role Knowledge", clarity: "Clarity", confidence: "Confidence", structure: "Structure", problemSolving: "Problem Solving" })[k] || k;

  return (
    <div className="rd-navy">
      <div className="rd-h">
        <span className="rd-t">Readiness</span>
        <ContextChip profile={profile} />
      </div>
      <div className="rd-b">
        <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
          <div style={{ display: "inline-flex", alignItems: "center", padding: "10px 24px", borderRadius: 10, background: bandStyle.bg, color: bandStyle.fg, fontFamily: IQ.display, fontWeight: 700, letterSpacing: "-0.01em", fontSize: 26 }}>{band}</div>
          {score && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "rgba(255,255,255,.35)" }}>Benchmark</div>
              <div style={{ fontFamily: IQ.mono, fontSize: 30, fontWeight: 500, color: "#fff", lineHeight: 1.15 }}>
                {score.benchmark}<span style={{ fontSize: 14, color: "rgba(255,255,255,.4)" }}>/100</span>
              </div>
            </div>
          )}
        </div>

        {/* Item 3: the gate copy. A cap with no explanation is a number that feels
            unfair; a cap that names the next rung is a next session. */}
        {score && score.capped && score.gate_copy && (
          <div style={{ marginTop: 16, padding: "12px 16px", borderRadius: 10, background: "rgba(200,153,42,.13)", border: "1px solid rgba(200,153,42,.32)" }}>
            <div style={{ fontFamily: IQ.mono, fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase", color: IQ.gold, marginBottom: 5 }}>Band gate</div>
            <div style={{ fontSize: 13, lineHeight: 1.6, color: "rgba(255,255,255,.92)" }}>{score.gate_copy}</div>
          </div>
        )}

        {Object.keys(roundBands).length > 0 && (
          <div className="rd-rule">
            <div className="rd-sub">By round</div>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {Object.entries(roundBands).map(([k, v]) => { const bs = BAND_STYLE[v] || BAND_STYLE["Not Ready"]; return (
                <div key={k} style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                  <span style={{ fontSize: 10, color: "rgba(255,255,255,.4)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".04em" }}>{ROUND_BAND_LABELS[k] || k}</span>
                  <span style={{ padding: "3px 12px", borderRadius: 8, background: bs.bg, color: bs.fg, fontFamily: IQ.display, fontWeight: 700, fontSize: 13 }}>{v}</span>
                </div>
              ); })}
            </div>
          </div>
        )}

        {/* Item 12: calibration keeps its own place here, untouched. Confidence never
            enters the benchmark formula — it is a different question (do you know what
            you know?) and folding it into a score would answer neither. */}
        {calHasData && (
          <div className="rd-rule">
            <div className="rd-sub">Calibration — confidence vs. performance</div>
            {cal.sentence && (
              <div style={{ fontSize: 14, color: "rgba(255,255,255,.9)", lineHeight: 1.6, marginBottom: 14 }}>{cal.sentence}</div>
            )}
            <div className="mba-grid-3" style={{ marginBottom: calCopy ? 14 : 0 }}>
              {[
                ["Avg Confidence", cal.avg_confidence, "/5"],
                ["Avg Score", cal.avg_score, "/5"],
                ["Delta", (cal.calibration_delta > 0 ? "+" : "") + cal.calibration_delta, ""],
              ].map(([label, val, suffix], i) => (
                <div key={i} style={{ padding: "12px 14px", borderRadius: 10, background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.10)" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,.5)", textTransform: "uppercase", letterSpacing: ".05em" }}>{label}</div>
                  <div style={{ fontSize: 24, fontWeight: 500, color: "#fff", marginTop: 4, fontFamily: IQ.mono }}>{val}<span style={{ fontSize: 13, fontWeight: 400, color: "rgba(255,255,255,.5)", fontFamily: IQ.sans }}>{suffix}</span></div>
                </div>
              ))}
            </div>
            {calCopy && (
              <div style={{ display: "inline-block", padding: "10px 16px", borderRadius: 10, background: calCopy.bg, color: IQ.cream }}>
                <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 2 }}>{calCopy.label}</div>
                <div style={{ fontSize: 13, lineHeight: 1.5 }}>{calCopy.copy}</div>
              </div>
            )}
          </div>
        )}

        {/* Competency /10 — the working, folded into the verdict rather than a second card. */}
        {ssEntries.length > 0 && (
          <div className="rd-rule">
            <div className="rd-sub">By competency</div>
            <div className="mba-grid-3">
              {ssEntries.map(([k, v]) => { const co = v >= 7 ? IQ.teal : v >= 5 ? IQ.gold : IQ.orange; return (
                <div key={k} style={{ padding: "12px 14px", borderRadius: 10, background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.10)" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,.5)", textTransform: "uppercase", letterSpacing: ".05em" }}>{pk(k)}</div>
                  <div style={{ fontSize: 22, fontWeight: 500, color: "#fff", marginTop: 4, fontFamily: IQ.mono }}>{v}<span style={{ fontSize: 13, fontWeight: 400, color: "rgba(255,255,255,.5)", fontFamily: IQ.sans }}>/10</span></div>
                  <div style={{ height: 4, borderRadius: 2, background: "rgba(255,255,255,.12)", marginTop: 8, overflow: "hidden" }}><div style={{ height: "100%", borderRadius: 2, width: Math.max(0, Math.min(100, v * 10)) + "%", background: co }} /></div>
                </div>
              ); })}
            </div>
          </div>
        )}

        {score && <ShowTheMath math={score.math} />}
      </div>
    </div>
  );
}

function DebriefScreen({ config, sessionId, onRestart, onViewHistory }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { (async () => { try {
    setD(await endSession(sessionId));
  } catch (e) { setError(e.message); } })(); }, [sessionId]);

  if (error) return <div className="vc" style={{ padding: 28, textAlign: "center" }}><div style={{ fontSize: 16, fontWeight: 700, color: T.navy, marginBottom: 8 }}>Could not generate report</div><div style={{ fontSize: 13, color: T.muted, marginBottom: 20 }}>{error}</div><button onClick={onRestart} className="mba-btn-primary">Start new session</button></div>;
  if (!d) return <div style={{ textAlign: "center", padding: "80px 20px" }}><div className="mba-spinner" style={{ margin: "0 auto 16px" }} /><div style={{ fontSize: 16, fontWeight: 700, color: T.navy }}>Analyzing your interview...</div><div style={{ fontSize: 13, color: T.subtle, marginTop: 4 }}>Scoring each response against the STAR framework.</div></div>;

  // The strip always renders, so fall back to what the lobby knows if the server
  // sent no profile (a drifted or older backend). The context is never optional.
  const profile = (d.profile && d.profile.role) ? d.profile : {
    role: config.role, company: config.company, level: config.level,
    difficulty: config.difficulty, duration_min: config.duration_min,
    // `session_mode` = how they answered; `mode` = the feedback style. The lobby knows
    // both, so the fallback strip no longer has to print "—" for a mode the student
    // explicitly chose two screens ago.
    mode: config.session_mode || null, feedback: config.mode,
    rounds_covered: [], rounds_skipped: [],
  };
  const strengths = (d.strengths || []).map(asStrength).filter((s) => s.strength);
  const gaps = d.gaps || [];
  const reattempt = d.reattempt_window || {};

  const actions = (
    <div style={{ display: "flex", gap: 10 }}>
      <button onClick={onRestart} className="vbtn">Start Another Mock</button>
      <button onClick={onViewHistory} className="vbtn" style={{ background: T.white, color: T.navy, border: "1.5px solid " + T.border }}>View History</button>
    </div>
  );

  // Item 4: below the evidence floor there is no band, no benchmark and no tiles —
  // the "Insufficient evidence" card is the whole readout (plus Presence, which is the
  // one thing that can exist without an answer). A band printed on two answers is a
  // guess wearing a verdict's clothes, and "Not Ready · 0/10" for a session nobody
  // answered is the exact failure this guards against. Skipped ≠ failed.
  if (isEmptyReadout(d)) {
    const ev = d.evidence || {};
    return (
      <div className="rd-page">
        <SessionProfileStrip profile={profile} early={d.early_wrap} scored={false} />
        <RdCard title="Insufficient evidence" profile={profile} accent={T.navy}>
          <div style={{ fontSize: 15, fontWeight: 700, color: T.navy, lineHeight: 1.5, marginBottom: 8 }}>
            This session ended before there was enough to score.
          </div>
          <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.65 }}>
            {ev.copy || "A readiness band needs at least three substantive answers. That is a statement about the evidence, not about you — nothing has been marked against you, and the next attempt starts clean."}
          </div>
        </RdCard>
        <PresenceBlock presence={d.professional_presence} profile={profile} />
        <RdCard title="When to come back" profile={profile}>
          <div style={{ fontSize: 13, color: T.text, lineHeight: 1.65, marginBottom: 14 }}>
            Whenever you have twenty quiet minutes. There is nothing to make up for here — there is just an interview you have not had yet.
          </div>
          {actions}
        </RdCard>
      </div>
    );
  }

  return (
    <div className="rd-page">
      {/* 1. THE CONTEXT — before any number, always. */}
      <SessionProfileStrip profile={profile} early={d.early_wrap} scored={true} />

      {/* 2. THE VERDICT — one sentence, in the interviewer's own voice. No band here:
             the band lives once, in the Readiness block, at the bottom. */}
      <RdCard title="Your readout" profile={profile} accent={T.navy}>
        <div style={{ fontSize: 16, fontWeight: 700, color: T.navy, lineHeight: 1.5 }}>{d.one_line}</div>
      </RdCard>

      {/* 3. WHAT WENT WELL — first, and in their own words. */}
      {strengths.length > 0 ? (
        <RdCard title="What went well" titleColor={T.green} accent={T.green} profile={profile}>
          {strengths.map((s, i) => (
            <div key={i} style={{ marginBottom: i < strengths.length - 1 ? 14 : 0, paddingLeft: 14, borderLeft: "2px solid " + T.green }}>
              <div style={{ fontSize: 13, lineHeight: 1.65 }}>{s.strength}</div>
              {s.evidence && (
                <div style={{ fontSize: 12, color: T.muted, fontStyle: "italic", marginTop: 5, lineHeight: 1.55 }}>
                  Your words: &ldquo;{s.evidence}&rdquo;
                </div>
              )}
            </div>
          ))}
        </RdCard>
      ) : (
        <RdMissing title="What went well" profile={profile}>
          There wasn&rsquo;t a moment we could quote back to you this time. That is not a verdict on you — it is the honest read of a short session, and it is the first thing that changes on the next one.
        </RdMissing>
      )}

      {/* 4 + 5. HOW YOU CAME ACROSS. Both report-only: neither moves the band. */}
      <DeliveryBlock delivery={d.delivery || {}} profile={profile} />
      <PresenceBlock presence={d.professional_presence} profile={profile} />

      {/* 6. THE FIXES THAT MATTER — each with something to do about it tomorrow. */}
      {gaps.length > 0 ? (
        <RdCard title={`The ${gaps.length} ${gaps.length === 1 ? "fix" : "fixes"} that matter`} titleColor="#7a5e00" accent={T.gold} profile={profile}>
          {gaps.map((g, i) => (
            <div key={i} style={{ marginBottom: 16, paddingBottom: i < gaps.length - 1 ? 14 : 0, borderBottom: i < gaps.length - 1 ? "1px solid " + T.border : "none" }}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                <span style={{ fontFamily: IQ.mono, fontSize: 12, fontWeight: 800, color: T.gold, flexShrink: 0 }}>{String(i + 1).padStart(2, "0")}</span>
                <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.5, color: T.text }}>{g.gap}</div>
              </div>
              {g.cost && <div style={{ fontSize: 13, lineHeight: 1.6, color: T.muted, marginTop: 5, paddingLeft: 32 }}>{g.cost}</div>}
              {g.tryThisNextTime && (
                <div style={{ marginTop: 10, marginLeft: 32, padding: "10px 14px", borderRadius: 8, background: IQ.cream, border: "1px solid " + T.gold }}>
                  <div style={{ fontFamily: IQ.mono, fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase", color: "#7a5e00", marginBottom: 4 }}>Try this next time</div>
                  <div style={{ fontSize: 13, lineHeight: 1.6, color: "#5a4500", fontWeight: 600 }}>{g.tryThisNextTime}</div>
                </div>
              )}
              {g.upskillizeCourse && <div style={{ fontSize: 12, color: T.navy, fontWeight: 700, marginTop: 8, paddingLeft: 32 }}>Study: {g.upskillizeCourse}</div>}
            </div>
          ))}
        </RdCard>
      ) : (
        <RdMissing title="The fixes that matter" profile={profile}>
          Nothing specific enough to name as a fix came out of this session.
        </RdMissing>
      )}

      {/* 7. THE PLAN — the fixes, spread over the week the re-attempt window assumes. */}
      {(d.plan || []).length > 0 && (
        <RdCard title="Your 7-day action plan" profile={profile}>
          {(d.plan || []).map((p, i) => (
            <div key={i} style={{ display: "flex", gap: 12, marginBottom: 10 }}>
              <div style={{ width: 26, height: 26, borderRadius: 6, flexShrink: 0, background: T.bg, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: IQ.mono, fontSize: 12, fontWeight: 500, color: T.navy, border: "1px solid " + T.border }}>{i + 1}</div>
              <div style={{ fontSize: 13, lineHeight: 1.6, paddingTop: 3 }}>{p.replace(/^Day \d:\s*/, "")}</div>
            </div>
          ))}
        </RdCard>
      )}

      {/* 8. THE READINESS BLOCK — last major section, and the only band on the page. */}
      <ReadinessBlock d={d} profile={profile} />

      {/* 9. THE WORKING — answer by answer, collapsed. It is evidence for the verdict
             above, not part of reading it, so it opens on request. */}
      {(d.star_breakdown?.length > 0 || d.interviewer_thoughts?.length > 0) && (
        <details className="rd-card rd-star">
          <summary>View answer-by-answer</summary>
          <div className="rd-b" style={{ paddingTop: 0 }}>
            {d.star_breakdown?.length > 0 && (
              <>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: T.subtle, marginBottom: 12 }}>STAR breakdown</div>
                {d.star_breakdown.map((q, i) => (
                  <div key={i} style={{ marginBottom: 16, paddingBottom: 14, borderBottom: i < d.star_breakdown.length - 1 ? "1px solid " + T.border : "none" }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: T.navy, marginBottom: 8 }}>{q.question}</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                      {["situation", "task", "action", "result"].map((key) => { const val = q[key] || 0; return <span key={key} className={"mba-pill " + (val >= 2 ? "mba-pill-pass" : val === 1 ? "mba-pill-warn" : "mba-pill-fail")} style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{key[0].toUpperCase()} {val}/2</span>; })}
                    </div>
                    <div style={{ fontSize: 12, color: T.muted, fontStyle: "italic", lineHeight: 1.55 }}>{q.note}</div>
                  </div>
                ))}
              </>
            )}
            {d.interviewer_thoughts?.length > 0 && (
              <div style={{ marginTop: d.star_breakdown?.length > 0 ? 18 : 0, paddingTop: d.star_breakdown?.length > 0 ? 16 : 0, borderTop: d.star_breakdown?.length > 0 ? "1px solid " + T.border : "none" }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: T.subtle, marginBottom: 12 }}>What the interviewer was thinking</div>
                {d.interviewer_thoughts.map((t, i) => (
                  <div key={i} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 11, color: T.subtle, textTransform: "uppercase" }}>Re: {t.answer}</div>
                    <div style={{ fontSize: 13, fontStyle: "italic", marginTop: 2, paddingLeft: 12, borderLeft: "2px solid " + T.navy, lineHeight: 1.6 }}>&ldquo;{t.thought}&rdquo;</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>
      )}

      {/* 10. WHEN TO COME BACK — the re-attempt window, and one closing line. */}
      <RdCard title="When to come back" profile={profile}>
        {reattempt.days && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
            <span style={{ fontFamily: IQ.mono, fontSize: 22, fontWeight: 500, color: T.navy }}>{reattempt.days}</span>
            <span style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", color: T.subtle }}>{reattempt.days === 1 ? "day" : "days"}</span>
          </div>
        )}
        <div style={{ fontSize: 13, color: T.text, lineHeight: 1.65 }}>{reattempt.copy || "Come back when you have twenty quiet minutes."}</div>
        {d.next_focus && (
          <div style={{ marginTop: 14, padding: "12px 16px", borderRadius: 8, background: T.bg, border: "1px solid " + T.border }}>
            <div style={{ fontFamily: IQ.mono, fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase", color: T.muted, marginBottom: 4 }}>Before your next mock</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: T.navy, lineHeight: 1.5 }}>{d.next_focus}</div>
          </div>
        )}
        {/* One closing line. Funny-but-sharp is allowed; quirky is not. It is the last
            thing they read, so it carries the whole point: this was practice, and
            practice is the only part of the process you control. */}
        <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.65, marginTop: 14, fontStyle: "italic" }}>
          Nobody has ever walked out of a real interview wishing they had rehearsed less.
        </div>
        <div style={{ marginTop: 16 }}>{actions}</div>
      </RdCard>
    </div>
  );
}

// Item 7: what the trend actually means, said in one clause. An arrow is not a sentence.
const TREND_COPY = {
  up: "Up on your recent average",
  down: "Down on your recent average",
  flat: "Holding steady",
  none: "One session so far — not a trend yet",
};

function HistoryScreen({ onPickSession, onStartNew }) {
  const [items, setItems] = useState(null);
  const [trend, setTrend] = useState([]);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("all");

  useEffect(() => {
    (async () => {
      try {
        const [h, s] = await Promise.all([fetchHistory(100, 0), fetchStats()]);
        setItems(h.sessions); setTrend(h.trend || []); setStats(s);
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
    <div style={{ fontFamily: T.font, width: "100%", boxSizing: "border-box", padding: "24px 28px" }}>
      <div style={{ background: T.navy, borderRadius: 12, padding: "22px 28px", marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ color: "#fff", fontWeight: 800, fontSize: 22, letterSpacing: "-.02em" }}>InterviewIQ History</div>
          <div style={{ color: "rgba(255,255,255,.4)", fontSize: 12, marginTop: 2 }}>Every mock interview, scored and stored.</div>
        </div>
        <button onClick={onStartNew} className="mba-btn-primary" style={{ background: T.gold }}>+ New Mock</button>
      </div>

      {/* Item 7 — TREND OVER TROPHY. "Best Score" is gone, deliberately: it was a raw
          score from whichever session happened to be easiest and shortest, held up as
          who this person is. What replaces it is where they are NOW — the average of
          their latest three BENCHMARKS, which are the only scores comparable to each
          other across different difficulties and durations. */}
      <div className="mba-grid-3" style={{ marginBottom: 18 }}>
        <div className="mba-metric mba-metric-gold">
          <div className="mba-metric-label">Latest {summary.window || 3} — average</div>
          <div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{summary.latest_average != null ? summary.latest_average : "—"}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>/100</span></div>
          <div style={{ fontSize: 10, color: T.subtle, marginTop: 4 }}>Benchmark, not raw score</div>
        </div>
        <div className="mba-metric mba-metric-green"><div className="mba-metric-label">Where you are now</div><div className="mba-metric-value" style={{ fontFamily: IQ.display, fontSize: 20 }}>{summary.latest_band || "—"}</div><div style={{ fontSize: 10, color: T.subtle, marginTop: 4 }}>{trend.length > 0 ? TREND_COPY[trendDirection(trend.map(t => t.benchmark))] : "No scored sessions yet"}</div></div>
        <div className="mba-metric"><div className="mba-metric-label">Total Sessions</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{summary.total_sessions || 0}</div></div>
        <div className="mba-metric"><div className="mba-metric-label">Scored</div><div className="mba-metric-value" style={{ color: T.green, fontFamily: IQ.mono, fontWeight: 500 }}>{summary.scored_sessions ?? 0}</div></div>
        <div className="mba-metric"><div className="mba-metric-label">Completed</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{summary.completed || 0}</div></div>
        <div className="mba-metric"><div className="mba-metric-label">Total Practice Time</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{totalMinutes}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}> min</span></div></div>
      </div>

      {/* The benchmark trend, newest FLAGGED — so a glance lands on where they are, not
          on their best day. Each bar carries the context it was earned in, because that
          is the whole reason these numbers can sit next to each other at all. */}
      {trend.length > 0 && (
        <div className="vc" style={{ marginBottom: 16 }}>
          <div className="vc-h"><span className="vc-t">Benchmark trend</span></div>
          <div className="vc-b">
            <div style={{ display: "flex", alignItems: "flex-end", gap: 10, overflowX: "auto", paddingBottom: 4 }}>
              {[...trend].reverse().map((t, i) => {
                const bs = BAND_STYLE[t.band] || BAND_STYLE["Not Ready"];
                return (
                  <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minWidth: 62, flexShrink: 0 }}>
                    <div style={{ fontFamily: IQ.mono, fontSize: 12, fontWeight: 500, color: t.latest ? T.navy : T.muted }}>{t.benchmark}</div>
                    <div style={{ width: 26, height: Math.max(6, Math.round((t.benchmark / 100) * 84)), borderRadius: 4, background: bs.bg, opacity: t.latest ? 1 : 0.45 }} />
                    <div style={{ fontSize: 9, color: T.subtle, textAlign: "center", lineHeight: 1.3 }}>{t.difficulty}<br />{t.duration_min}m</div>
                    {t.latest && <span className="mba-pill" style={{ background: T.navy, color: "#fff", fontSize: 9 }}>LATEST</span>}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {stats?.by_role?.length > 0 && (
        <div className="vc" style={{ marginBottom: 16 }}>
          <div className="vc-h"><span className="vc-t">Average benchmark by role</span></div>
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
        const st = historyStatus(s);
        const bs = BAND_STYLE[st.label] || { bg: T.bg, fg: T.navy };
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
            {/* Item 6 — EARLY EXITS ARE VISIBLE. A session that fell below the evidence
                floor still appears, and it appears in navy and neutral: "Ended early —
                not scored". Quitting cannot hide a run, and a run nobody scored is not a
                run somebody failed. The number shown is the BENCHMARK, never the raw
                score — a raw 100 from Easy/10-min next to a raw 75 from Critical/45 is
                the comparison this whole sprint removed. */}
            <div style={{ textAlign: "right", minWidth: 92, flexShrink: 0 }}>
              {st.benchmark != null ? (
                <>
                  <div style={{ fontFamily: IQ.mono, fontSize: 26, fontWeight: 500, color: T.navy }}>{st.benchmark}</div>
                  <div style={{ fontSize: 10, color: T.subtle, fontWeight: 600 }}>BENCHMARK</div>
                  {st.label && <span className="iq-pill" style={{ background: bs.bg, color: bs.fg, marginTop: 5, display: "inline-block", fontFamily: IQ.display }}>{st.label}</span>}
                </>
              ) : (
                <div style={{ fontSize: 12, color: T.subtle, lineHeight: 1.4 }}>{st.label}</div>
              )}
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
  const st = historyStatus(s);
  const ss = d.subScores || {};

  return (
    <div style={{ fontFamily: T.font, width: "100%", boxSizing: "border-box", padding: "24px 28px" }}>
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

      {/* Item 6: an attempt below the evidence floor is SHOWN here too, and shown as
          what it was — not scored — rather than as a zero. */}
      {st.benchmark == null && (
        <div className="vc" style={{ marginBottom: 16 }}>
          <div className="vc-b" style={{ paddingTop: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: T.navy, marginBottom: 6 }}>{st.label}</div>
            <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.6 }}>
              {s.scored === false
                ? "There wasn't enough here to score — a readiness band needs at least three substantive answers. Nothing was marked against you."
                : "This session has no benchmark. The transcript below is exactly as it stood."}
            </div>
          </div>
        </div>
      )}

      {st.benchmark != null && (
        <>
          <div className="mba-grid-3" style={{ marginBottom: 16 }}>
            {/* The BENCHMARK leads, because it is the number that means the same thing
                from one session to the next. The raw score sits underneath it, labelled
                as what it is: the rubric's read of the answers, before context. */}
            <div className="mba-metric mba-metric-gold">
              <div className="mba-metric-label">Benchmark</div>
              <div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{st.benchmark}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>/100</span></div>
              {st.label && <div style={{ fontSize: 12, color: T.navy, fontWeight: 700, marginTop: 4, fontFamily: IQ.display }}>{st.label}</div>}
              {s.one_line && <div style={{ fontSize: 12, color: T.muted, marginTop: 6, fontStyle: "italic" }}>&ldquo;{s.one_line}&rdquo;</div>}
            </div>
            {s.overall != null && (
              <div className="mba-metric">
                <div className="mba-metric-label">Raw answers</div>
                <div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{s.overall}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>/100</span></div>
                <div style={{ fontSize: 10, color: T.subtle, marginTop: 4, lineHeight: 1.4 }}>Before weighting for {s.difficulty} · {s.planned_duration_min} min</div>
              </div>
            )}
            {Object.entries(ss).slice(0, 1).map(([k, v]) => (
              <div key={k} className="mba-metric"><div className="mba-metric-label">{k}</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{v}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>/10</span></div></div>
            ))}
          </div>

          {Object.keys(ss).length > 1 && (
            <div className="mba-grid-3" style={{ marginBottom: 16 }}>
              {Object.entries(ss).slice(1).map(([k, v]) => (
                <div key={k} className="mba-metric"><div className="mba-metric-label">{k}</div><div className="mba-metric-value" style={{ fontFamily: IQ.mono, fontWeight: 500 }}>{v}<span style={{ fontSize: 14, fontWeight: 400, color: T.subtle, fontFamily: IQ.sans }}>/10</span></div></div>
              ))}
            </div>
          )}

          {(d.strengths?.length > 0 || d.gaps?.length > 0) && (
            <div className="mba-grid-2" style={{ marginBottom: 16 }}>
              {d.strengths?.length > 0 && <div className="vc" style={{ borderLeft: "3px solid " + T.green }}><div className="vc-h"><span className="vc-t" style={{ color: T.green }}>What went well</span></div><div className="vc-b">{d.strengths.map(asStrength).map((x, i) => <div key={i} style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 6 }}>• {x.strength}</div>)}</div></div>}
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
    <div style={{ fontFamily: T.font, width: "100%", boxSizing: "border-box", padding: "24px 28px", maxWidth: 720, margin: "0 auto" }}>
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
  const [pendingConfig, setPendingConfig] = useState(null);   // Interview Room: config -> lobby -> start
  const [joinError, setJoinError] = useState(null);
  // A5: {message, retry} when the voice vendor is unavailable and TEXT is the honest offer.
  const [seatbeltOffer, setSeatbeltOffer] = useState(null);
  const [retryAsText, setRetryAsText] = useState(false);
  const [config, setConfig] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [greeting, setGreeting] = useState("");
  const [greetingSegments, setGreetingSegments] = useState([]);   // E2: the greeting, one clip per sentence — the only shape a reply is spoken in
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
    // (setGreetingAudioUrl used to be called here. It has not existed since the whole-reply
    // clip was removed, so "Start fresh" threw a ReferenceError and did nothing at all.)
    setConfig(null); setSessionId(null); setGreeting(""); setGreetingSegments([]); setInitialState(null);
    setInitialMessages(null); setStartedAt(null); setResumeCfg(null); setHistoryDetailId(null);
    // QA-13: the leftovers of the LAST attempt. Without these, "Start fresh" carried a
    // stale red join error, or the gold "continue in text" seatbelt, into the next
    // session's lobby — a warning about a failure that already happened, shown to someone
    // who has not failed yet. The same class of bug as the setGreetingAudioUrl line above.
    setJoinError(null); setSeatbeltOffer(null); setPendingConfig(null);
    setScreen("setup");
  };

  const handleStart = (cfg, id, gr, st, segments) => {
    const now = Date.now();
    setConfig(cfg); setSessionId(id); setGreeting(gr);
    setGreetingSegments(segments || []); setInitialState(st);
    setInitialMessages(null); setStartedAt(now);
    saveActiveSession(id, cfg, now);   // INT-06: persist the instant the session starts
    setScreen("interview");
  };

  // Interview Room: config is done -> show the pre-join lobby (Phase A).
  const handleConfigured = (payload) => { setPendingConfig(payload); setScreen("lobby"); };

  // Interview Room: they pressed Join. NOW we start the session, carrying the devices
  // they committed to and the interviewer the roster picked — so the face on screen,
  // the TTS voice and the improvised persona are all the same person.
  const handleJoin = async ({ mic, camera }) => {
    const payload = pendingConfig;
    if (!payload) { restart(); return; }
    // Embedded audio seatbelt: Join is the room-entry gesture, so unlock playback and
    // create/resume the AudioContext HERE, synchronously in the click — before the await
    // below breaks the user-gesture context. Same-origin iframes still enforce autoplay
    // policy, and a room reached by deep-link may never have seen the Start gesture.
    unlockAudioPlayback();
    setScreen("loading");
    // Seed the roster pick with a value we control and PERSIST, so the same interviewer
    // survives a refresh (session_id doesn't exist yet — we need the name to start).
    const roomSeed = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    const iv = pickInterviewer(payload.voice || "female", payload.difficulty || "Realistic", roomSeed);
    try {
      const r = await startSession({
        ...payload,
        interviewer_name: iv.name,      // the persona ADOPTS the face's name
        camera_at_join: !!camera,       // a camera-off join is never penalised
      });

      // FAST START: /session/start is now just the session row, so we are HERE in well
      // under a second — and the room goes up NOW, with the interviewer already in it. The
      // greeting is fetched from inside the room (InterviewScreen), and she starts talking
      // the moment her first sentence has audio. What the candidate used to get instead was
      // a fourteen-second spinner.
      //
      // The consent writes are deliberately NOT awaited: they are a ledger entry, they are
      // non-blocking by design (the server-side gate is the real enforcement), and making
      // the room wait on three round trips would hand back the time we just bought.
      const grants = [{ consent_type: "data_processing", copy_version: CONSENT_COPY_VERSION }];
      if (mic) grants.push({ consent_type: "voice_recording", copy_version: CONSENT_COPY_VERSION });
      if (camera) grants.push({ consent_type: "camera_selfview", copy_version: CONSENT_COPY_VERSION });
      for (const g of grants) {
        recordConsent({ ...g, session_id: r.session_id }).catch(() => { /* non-blocking */ });
      }
      try { localStorage.setItem(CONSENT_KEY, "1"); } catch { /* noop */ }

      handleStart(
        { ...payload, roomSeed, mic: !!mic, camera: !!camera, interviewerName: iv.name },
        r.session_id, r.greeting || "", r.state, r.audio_segments || [],
      );
    } catch (e) {
      // A5, THE VENDOR SEATBELT. The voice vendor being down is not the student's problem
      // to solve, and it is not a reason to send them back to a lobby with a red line on
      // it. TEXT is a real, complete interview — so we offer it, and if they take it the
      // session starts immediately in TEXT rather than making them find the picker and
      // work out for themselves what went wrong.
      if (e?.detail?.offer_text_mode) {
        setSeatbeltOffer({
          message: (e.detail.errors || []).join(" ") || e.message,
          retry: () => {
            setSeatbeltOffer(null);
            setPendingConfig((c) => ({ ...c, session_mode: "TEXT" }));
            setRetryAsText(true);
          },
        });
        setScreen("lobby");
        return;
      }
      setJoinError(e.message);
      setScreen("lobby");
    }
  };

  // The seatbelt's second half: pendingConfig has just been switched to TEXT, so re-run
  // Join against the new config. Split out because setPendingConfig is async — joining in
  // the same tick would re-send the AUDIO config we just replaced and 422 again.
  useEffect(() => {
    if (!retryAsText) return;
    setRetryAsText(false);
    handleJoin({ mic: false, camera: false });
  }, [retryAsText]);   // eslint-disable-line react-hooks/exhaustive-deps

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
        /* QA-09: this padding read "16px 32px 8" — a unitless length, which is invalid CSS
           everywhere except zero, so the browser dropped the WHOLE shorthand. On its own
           that would only have meant no padding. What made it a 280px cream band is that
           React reuses this <div> from the `screen === "loading"` branch above (same
           position, same element type), and that branch sets `padding: "120px 20px"`.
           React assigns the new value, the browser rejects it, and the loading screen's
           120px top AND bottom simply stay: 120 + 42px button + 120 = the band — on every
           screen, since the app always boots through "loading". One missing unit,
           inherited. */
        <div style={{ fontFamily: T.font, padding: "16px 32px 8px", display: "flex", gap: 14, alignItems: "center", justifyContent: "flex-end" }}>
          {screen === "debrief" && <button className="iq-tab" onClick={restart}>+ New Mock</button>}
          {screen !== "history" && <button className="iq-tab" onClick={() => { setHistoryDetailId(null); setScreen("history"); }}>History</button>}
          {screen !== "settings" && <button className="iq-tab" onClick={() => setScreen("settings")}>Settings</button>}
        </div>
      )}
      {screen === "setup" && <SetupScreen userName={userName} onStart={handleConfigured} />}
      {screen === "lobby" && (
        <>
          {joinError && (
            <div style={{ fontFamily: T.font, maxWidth: 900, margin: "0 auto", padding: "0 20px" }}>
              <div style={{ padding: "10px 14px", borderRadius: 8, background: T.redSoft, color: T.red, fontSize: 13 }}>{joinError}</div>
            </div>
          )}
          {/* A5: not an error — an offer. Gold, not red: nothing has gone wrong for THEM,
              and a red box would say "you broke something" about our vendor being down. */}
          {seatbeltOffer && (
            <div style={{ fontFamily: T.font, maxWidth: 900, margin: "0 auto", padding: "0 20px" }}>
              <div style={{ padding: "12px 16px", borderRadius: 8, background: T.goldSoft,
                border: "1px solid " + T.goldBorder, color: "#5a4500", fontSize: 13,
                display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <span style={{ flex: 1, minWidth: 220 }}>{seatbeltOffer.message}</span>
                <button onClick={seatbeltOffer.retry} className="vchip vchip-on"
                  style={{ flexShrink: 0 }}>
                  Continue in text
                </button>
              </div>
            </div>
          )}
          <Lobby name={userName} role={pendingConfig?.role} onJoin={handleJoin}
            sessionMode={pendingConfig?.session_mode || DEFAULT_SESSION_MODE} />
        </>
      )}
      {screen === "resume" && <ResumePrompt config={resumeCfg} onResume={doResume} onDiscard={restart} />}
      {screen === "interview" && <InterviewScreen config={config} sessionId={sessionId} greeting={greeting} greetingSegments={greetingSegments} initialState={initialState} initialMessages={initialMessages} startedAt={startedAt} onEnd={() => setScreen("debrief")} onRestart={restart} />}
      {screen === "debrief" && <DebriefScreen config={config} sessionId={sessionId} onRestart={restart} onViewHistory={() => { setHistoryDetailId(null); setScreen("history"); }} />}
      {screen === "history" && !historyDetailId && <HistoryScreen onPickSession={(sid) => { setHistoryDetailId(sid); }} onStartNew={restart} />}
      {screen === "history" && historyDetailId && <HistoryDetail sessionId={historyDetailId} onBack={() => setHistoryDetailId(null)} />}
      {screen === "settings" && <SettingsScreen onBack={() => setScreen("setup")} />}
    </>
  );
}