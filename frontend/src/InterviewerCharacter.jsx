import { useEffect, useRef, useState } from "react";

/**
 * InterviewerCharacter — InterviewIQ voice stage (v4.3, VECTORBOTS ONLY)
 * ──────────────────────────────────────────────────────────────────────────
 * Founder decision: the active roster is TWO animated androids — Nova (male)
 * and Nia (female) — both rendered by RobotInterviewer via its `variant` prop.
 * Both are eligible for every difficulty, Critical included.
 *
 * The photo-character machinery below (the roster `img`/`temperaments` shape,
 * POSE_MAP glob, resolvePose, the amplitude-driven emphasis and the opacity
 * crossfade) is KEPT INTACT but DORMANT: no photo rows sit in the roster today,
 * so none of it renders. The pose/portrait PNGs stay on disk — the glob
 * tolerates the extra files — and a future photo character lights up the whole
 * path again the moment a `{ kind:"human", img, temperaments }` row returns.
 *
 * Expression system:
 *   • kind:"vectorbot" — RobotInterviewer draws inside the same tile chrome
 *     (card glow, name chip, thinking arc, listening ring). Its LED-waveform
 *     mouth rides the SAME live Bulbul amplitude the pose badge used; the
 *     server's tone_hint flows into its `tone` prop (brows/eyes/rest-mouth).
 *   • kind:"human" (dormant) — video-call treatment, no face manipulation:
 *     SPEAKING glows + a waveform badge pulses; THINKING a teal arc; LISTENING
 *     a pulse ring + lean-in; IDLE a calm card. Poses crossfade; never a mouth
 *     animated on a photograph.
 *
 * CONTRACT: named exports wireTtsAnalyser / resumeTtsAnalyser; props state,
 * voice, size; optional difficulty ("Easy"|"Realistic"|"Stretch"|"Critical"),
 * seed (pass session_id), and tone (the server tone_hint).
 *
 * ASSETS: photo portraits live in frontend/src/interviewers/. A human roster row
 * must import a file that is actually on disk — an unresolved import is a hard
 * Vite build failure. Vectorbot rows import nothing (they draw as SVG), so the
 * photo imports are gone until a photo row returns.
 */
import RobotInterviewer from "./RobotInterviewer.jsx";

import {
  choosePose, hasPoseSet, resolvePose, nextEmphasis, weightedPool, POSES,
} from "./posePolicy.js";

// ── Pose set (four stills of the same person: listening / smile / intense / thinking).
// FEATURE-DETECTED, never hard-imported: a missing file must not break the build, and a
// character with no poses (robots, art not yet generated) simply keeps its single
// portrait. import.meta.glob resolves whatever is actually on disk at build time — so
// this ships DORMANT today and lights up the moment the PNGs land in poses/.
//
// Naming contract: frontend/src/interviewers/poses/{characterId}_{pose}.png
const _POSE_MODULES = import.meta.glob("./interviewers/poses/*.png", {
  eager: true,
  import: "default",
});
export const POSE_MAP = Object.fromEntries(
  Object.entries(_POSE_MODULES).map(([path, url]) => [
    path.split("/").pop().replace(/\.png$/i, ""),   // "priya_smile"
    url,
  ]),
);

// ── Shared TTS analyser (module-level, one per page) ─────────────────────
// createMediaElementSource() may be called only ONCE per element, and from then
// on the element's audio flows ONLY through the graph — hence the _wiredEl guard
// and the connect to destination. Anything that throws leaves audio untouched.
let _ctx = null;
let _analyser = null;
let _wiredEl = null;

export function wireTtsAnalyser(audioEl) {
  if (!audioEl || _wiredEl === audioEl) return;
  try {
    const AC = typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext);
    if (!AC) return;
    if (!_ctx) _ctx = new AC();
    const src = _ctx.createMediaElementSource(audioEl);
    _analyser = _ctx.createAnalyser();
    _analyser.fftSize = 512;
    _analyser.smoothingTimeConstant = 0.55;
    src.connect(_analyser);
    _analyser.connect(_ctx.destination);
    _wiredEl = audioEl;
  } catch { /* audio still plays; the badge falls back to a talk cycle */ }
}

export function resumeTtsAnalyser() {
  try { if (_ctx && _ctx.state === "suspended") _ctx.resume(); } catch { /* noop */ }
}

// ── The roster ────────────────────────────────────────────────────────────
const TEAL = "#00C4A0";

// VECTORBOTS ONLY. Two animated androids, one per voice, each rendered by
// RobotInterviewer via `variant`. A vectorbot carries no `temperaments` list —
// it is eligible for EVERY difficulty, Critical included (its face hardens from
// the server's tone_hint, not from an `intense` pose on disk). See eligibleFor.
//
// A future photo character re-enters as a `kind:"human"` row with an `img` import
// and a `temperaments` gate; the pose engine below is kept intact for exactly that.
const ROSTER = [
  { id: "nova", name: "Nova", kind: "vectorbot", voice: "male", variant: "nova" },
  { id: "nia", name: "Nia", kind: "vectorbot", voice: "female", variant: "nia" },
];

function hashSeed(s) {
  let h = 5381;
  const str = String(s || new Date().toDateString());
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// A row with no `temperaments` (every vectorbot) is eligible for ANY difficulty;
// a photo row is gated by its list. Keeps the founder's roster entries verbatim
// while honouring "both eligible for ALL difficulties, Critical included."
const eligibleFor = (c, difficulty) => !c.temperaments || c.temperaments.includes(difficulty);

export function pickInterviewer(voice = "female", difficulty = "Realistic", seed) {
  let pool = ROSTER.filter(c => c.voice === voice && eligibleFor(c, difficulty));
  if (!pool.length) pool = ROSTER.filter(c => c.voice === voice);
  if (!pool.length) pool = ROSTER;
  // Posed characters are weighted up until the whole cast has pose grids — otherwise the
  // pose system is invisible in most sessions. See posePolicy.weightedPool; remove the
  // weighting (one constant) when the grids land.
  const weighted = weightedPool(pool, POSE_MAP);
  return weighted[hashSeed(seed) % weighted.length];
}

// ── CSS (injected once) ───────────────────────────────────────────────────
const STYLE_ID = "iq-character-css-v42";
function injectCSS() {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.textContent = `
    .iqv4 { position:relative; display:inline-block; }
    .iqv4-card { position:relative; overflow:hidden; border-radius:18px;
                 border:1px solid rgba(0,196,160,.28);
                 box-shadow:0 10px 40px rgba(0,0,0,.45), 0 0 24px rgba(0,196,160,.10);
                 transition:transform .5s ease, box-shadow .5s ease, border-color .4s ease; }
    .iqv4-card img { display:block; width:100%; height:100%; object-fit:cover; }
    /* Pose layers: stacked, opacity-only crossfade (350-450ms). */
    .iqv4-pose { position:absolute; inset:0; transition:opacity 400ms ease; will-change:opacity; }
    .iqv4--listening .iqv4-card { transform:scale(1.015);
                 box-shadow:0 10px 40px rgba(0,0,0,.45), 0 0 30px rgba(0,196,160,.22); }
    .iqv4--speaking .iqv4-card { border-color:rgba(0,196,160,.7);
                 box-shadow:0 10px 40px rgba(0,0,0,.45), 0 0 34px rgba(0,196,160,.32); }
    .iqv4-badge { position:absolute; left:50%; bottom:10px; transform:translateX(-50%);
                display:flex; align-items:center; gap:3px; height:22px;
                padding:0 10px; border-radius:999px;
                background:rgba(11,22,40,.72); border:1px solid rgba(0,196,160,.5);
                box-shadow:0 2px 10px rgba(0,0,0,.35); pointer-events:none; }
    .iqv4-badge span { width:3px; border-radius:2px; background:${TEAL};
                transition:height .07s linear; }
    .iqv4-ring { position:absolute; inset:-9px; border-radius:24px; pointer-events:none; }
    .iqv4-ring--listen { border:2px solid rgba(0,196,160,.35);
                animation: iqv4-ringpulse 2s ease-in-out infinite; }
    .iqv4-arcwrap { position:absolute; inset:-14px; pointer-events:none; }
    .iqv4-arc { width:100%; height:100%; animation: iqv4-spin 1.4s linear infinite; }
    .iqv4-vignette { position:absolute; inset:0; pointer-events:none;
                background:linear-gradient(180deg, rgba(11,22,40,0) 62%, rgba(11,22,40,.55) 100%); }
    @keyframes iqv4-spin { to { transform: rotate(360deg) } }
    @keyframes iqv4-ringpulse { 0%,100% { opacity:.35; transform:scale(1) }
                                50% { opacity:.75; transform:scale(1.02) } }
    @media (prefers-reduced-motion: reduce) {
      .iqv4-arc, .iqv4-ring--listen { animation:none; }
      .iqv4-card, .iqv4-badge span { transition:none; }
      /* The pose CROSSFADE is deliberately preserved: it is opacity only, which is
         permitted under reduced-motion. We drop the motion, not the fade — otherwise
         the face would hard-swap, which is exactly what the spec forbids. */
    }
  `;
  document.head.appendChild(s);
}

const BADGE_MULT = [0.5, 0.85, 1.0, 0.7, 0.45];

export default function InterviewerCharacter({
  state = "idle",
  voice = "female",
  size = 220,
  difficulty = "Realistic",
  seed,
  // Pose inputs. `tone` is the server's hint ("warm"|"neutral"|"probing"); when it is
  // absent we fall back to heuristics in posePolicy.
  tone = "",
  escalationLevel = 0,
  stage = "",
  group = 0,
}) {
  useEffect(injectCSS, []);

  const speaking = state === "speaking";
  const thinking = state === "thinking";
  const listening = state === "listening";

  const charRef = useRef(null);
  const keyRef = useRef("");
  const pickKey = `${voice}|${difficulty}|${seed || ""}`;
  if (keyRef.current !== pickKey) {
    keyRef.current = pickKey;
    charRef.current = pickInterviewer(voice, difficulty, seed);
  }
  const c = charRef.current;

  const [amp, setAmp] = useState(0);
  useEffect(() => {
    if (!speaking) { setAmp(0); return; }
    let raf, frame = 0;
    const buf = _analyser ? new Uint8Array(_analyser.fftSize) : null;
    const t0 = performance.now();
    const tick = () => {
      let v;
      if (_analyser && buf) {
        _analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) { const d = (buf[i] - 128) / 128; sum += d * d; }
        v = Math.min(1, Math.sqrt(sum / buf.length) * 4.2);
      } else {
        v = 0.35 + 0.3 * Math.abs(Math.sin((performance.now() - t0) / 150));
      }
      if (frame++ % 2 === 0) setAmp(v);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speaking]);

  // ── Poses ──
  // Preload every pose for this character on mount, so a swap never flash-loads.
  useEffect(() => {
    if (!c?.id || typeof Image === "undefined") return;
    POSES.forEach((pz) => {
      const url = POSE_MAP[`${c.id}_${pz}`];
      if (url) { const im = new Image(); im.src = url; }
    });
  }, [c?.id]);

  const posed = hasPoseSet(POSE_MAP, c.id);

  // Emphasis: while she is speaking warmly or neutrally, a sustained loud passage brings
  // the emphatic-gesture frame up and a settled voice drops it again. Driven by the REAL
  // Bulbul amplitude, so the gesture lands on the words she actually stresses.
  const [emphatic, setEmphatic] = useState(false);
  const emphSwitchRef = useRef(0);
  const emphasisEligible = posed && speaking && (tone === "warm" || tone === "neutral");
  useEffect(() => {
    if (!emphasisEligible) {
      if (emphatic) { setEmphatic(false); emphSwitchRef.current = 0; }
      return;
    }
    const now = performance.now();
    const since = emphSwitchRef.current ? now - emphSwitchRef.current : Infinity;
    const next = nextEmphasis(emphatic, amp, since);
    if (next !== emphatic) { emphSwitchRef.current = now; setEmphatic(next); }
  }, [amp, emphasisEligible, emphatic]);

  const pose = (emphasisEligible && emphatic)
    ? "intense"
    : choosePose({ state, tone, escalationLevel, stage, difficulty, group });
  const src = resolvePose(POSE_MAP, c.id, pose, c.img);

  // Crossfade: two stacked layers, opacity only. Never a hard swap. Opacity fades are
  // permitted under prefers-reduced-motion (it is the MOTION we drop, not the fade).
  const [front, setFront] = useState(src);
  const [back, setBack] = useState(null);
  const [fading, setFading] = useState(false);
  useEffect(() => {
    if (src === front) return;
    setBack(src);
    const raf = requestAnimationFrame(() => setFading(true));
    const t = setTimeout(() => { setFront(src); setBack(null); setFading(false); }, 420);
    return () => { cancelAnimationFrame(raf); clearTimeout(t); };
  }, [src]); // eslint-disable-line react-hooks/exhaustive-deps

  const W = size;
  const H = Math.round(size * 1.25);
  const level = speaking ? Math.max(0.12, amp) : 0;
  const isBot = c.kind === "vectorbot";
  const stateClass = speaking ? " iqv4--speaking" : listening ? " iqv4--listening" : "";
  // A shared object-position per character keeps the face anchored across fades — the
  // poses are cropped quadrants, so framing can shift a little between them.
  const anchor = c.objectPosition ? { objectPosition: c.objectPosition } : undefined;

  return (
    <div className={"iqv4" + stateClass} role="img"
      aria-label={`Interviewer ${c.name} is ${state}`}
      style={{ width: W, height: H }}>
      {thinking && (
        <div className="iqv4-arcwrap">
          <svg className="iqv4-arc" viewBox="0 0 100 124" fill="none" preserveAspectRatio="none">
            <rect x="2" y="2" width="96" height="120" rx="8"
              stroke={TEAL} strokeWidth="2.5" strokeLinecap="round"
              strokeDasharray="52 380" opacity="0.9" />
            <rect x="2" y="2" width="96" height="120" rx="8"
              stroke={TEAL} strokeWidth="2.5" strokeLinecap="round"
              strokeDasharray="14 418" strokeDashoffset="-160" opacity="0.4" />
          </svg>
        </div>
      )}
      {listening && <div className="iqv4-ring iqv4-ring--listen" />}

      <div className="iqv4-card" style={{ width: W, height: H }}>
        {isBot ? (
          /* Vectorbot: the android draws itself inside the SAME card chrome (glow,
             arc, ring, name chip all unchanged, above/around this). Its LED-waveform
             mouth rides `amp` — the very amplitude the pose badge used — and the
             server tone_hint drives its brows/eyes/rest-mouth. It carries its own
             desk scene, so no pose img, vignette or badge here. */
          <RobotInterviewer variant={c.variant} state={state} amplitude={amp}
            size={W} tone={tone || "neutral"} />
        ) : (
          <>
            {/* Two stacked layers, opacity crossfade — never a hard swap. With no pose
                set (art pending) both layers hold the same single portrait and this
                costs nothing. */}
            <img className="iqv4-pose" src={front} alt="" draggable="false"
              style={{ ...anchor, opacity: fading ? 0 : 1 }} />
            {back && (
              <img className="iqv4-pose" src={back} alt="" draggable="false"
                style={{ ...anchor, opacity: fading ? 1 : 0 }} />
            )}
            <div className="iqv4-vignette" />
            {speaking && (
              <div className="iqv4-badge" aria-hidden="true">
                {BADGE_MULT.map((m, i) => (
                  <span key={i} style={{ height: Math.max(3, 4 + level * 12 * m) }} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
