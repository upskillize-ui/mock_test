import { useEffect, useRef, useState } from "react";

/**
 * InterviewerCharacter — the illustrated interviewer that replaces the orb.
 *
 * ISOLATED BY DESIGN: everything about the character (art, rig, animation, and the
 * TTS audio analyser that drives the mouth) lives in this file. The dual-theme
 * redesign — or a future vendor avatar — can replace this module wholesale without
 * touching the stage, the state machine, or the voice flow.
 *
 * Layered inline SVG, flat premium-editorial style on the brand palette. Two
 * characters matched to the voice picker: female (ritu) and male (shubh), Indian
 * professional business attire, head-and-shoulders. Deliberately NOT cartoonish:
 * realistic proportions, no oversized features, no emoji faces.
 *
 * Rig (each part is its own group so it can be animated independently):
 *   shoulders (breathing) → neck → head group (tilt / nod) → brows, eyes(+lids),
 *   nose, mouth (5 shapes: closed / small / mid / wide / smile).
 *
 * States are driven by REAL events, not decorative loops:
 *   SPEAKING  mouth openness = live RMS of the ACTUAL TTS audio (AnalyserNode on the
 *             <audio> element), brow lift on amplitude onsets, blinks every 3–6s.
 *   LISTENING attentive: slight tilt toward camera, randomized nods every 4–7s,
 *             steady eyes with blinks, occasional "mm-hm" mouth twitch. Never talks.
 *   THINKING  gaze shifts up-and-aside, brows draw in, stillness + breathing.
 *   IDLE      relaxed neutral, breathing + blinks.
 *
 * prefers-reduced-motion: freezes to a neutral portrait (no rAF, no timers); the
 * persistent text state label outside this component carries the meaning.
 */

// ── Brand palette (kept local so a reskin swaps colour without relayout) ──────
const C = {
  navy: "#0B1628",
  navyMid: "#1B2C4A",
  teal: "#00C4A0",
  gold: "#C8992A",
  skin: "#C98C5E",
  skinShade: "#B0764A",
  hair: "#17120F",
  hairHi: "#2A211B",
  shirt: "#F3EFE7",
  mouthDark: "#5A2A22",
  lip: "#8C4A3C",
  line: "#3A2A20",
};

// ── TTS audio analyser ───────────────────────────────────────────────────────
// The mouth must follow the actual voice, so we tap the shared <audio> element with
// a Web Audio AnalyserNode. Two hard constraints:
//   1. createMediaElementSource() may be called only ONCE per element, and from then
//      on the element's audio flows ONLY through the graph — so we MUST connect to
//      destination, or playback would go silent.
//   2. The context must be running; browsers start it suspended. We therefore wire it
//      from a user gesture (the Start button) and resume defensively on every play.
// If anything throws we leave the element completely untouched: audio keeps working
// and the mouth falls back to a gentle idle (never a fake talking loop).
let _ctx = null;
let _analyser = null;
let _buf = null;
let _tried = false;

export function wireTtsAnalyser(el) {
  if (_tried || !el) return _analyser;
  _tried = true;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    const ctx = new AC();
    const src = ctx.createMediaElementSource(el);
    const an = ctx.createAnalyser();
    an.fftSize = 512;
    an.smoothingTimeConstant = 0.75;
    src.connect(an);
    an.connect(ctx.destination);   // REQUIRED — otherwise the interviewer goes mute
    _ctx = ctx;
    _analyser = an;
    _buf = new Uint8Array(an.fftSize);
    return an;
  } catch {
    _ctx = null; _analyser = null; _buf = null;
    return null;                   // element untouched → audio still plays normally
  }
}

export function resumeTtsAnalyser() {
  try { if (_ctx && _ctx.state !== "running") _ctx.resume(); } catch { /* noop */ }
}

/** Current RMS of the TTS audio (0..~0.4), or null when no analyser is available. */
export function ttsLevel() {
  if (!_analyser || !_buf) return null;
  _analyser.getByteTimeDomainData(_buf);
  let sum = 0;
  for (let i = 0; i < _buf.length; i++) { const v = (_buf[i] - 128) / 128; sum += v * v; }
  return Math.sqrt(sum / _buf.length);
}

// ── Mouth shapes (5) ─────────────────────────────────────────────────────────
const MOUTH = {
  closed: { d: "M99 141 Q110 145 121 141", fill: "none", stroke: C.lip, w: 2.2 },
  smile: { d: "M97 139 Q110 151 123 139", fill: "none", stroke: C.lip, w: 2.2 },
  small: { d: "M102 139 Q110 136 118 139 Q110 146 102 139 Z", fill: C.mouthDark, stroke: C.lip, w: 1 },
  mid: { d: "M100 138 Q110 133 120 138 Q110 150 100 138 Z", fill: C.mouthDark, stroke: C.lip, w: 1 },
  wide: { d: "M99 137 Q110 131 121 137 Q110 155 99 137 Z", fill: C.mouthDark, stroke: C.lip, w: 1 },
};

function mouthForLevel(level) {
  const l = Math.min(1, Math.max(0, level * 4.5));   // normalize RMS -> 0..1
  if (l < 0.08) return "closed";
  if (l < 0.26) return "small";
  if (l < 0.52) return "mid";
  return "wide";
}

const prefersReduced = () => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch { return false; }
};

export default function InterviewerCharacter({ state = "idle", voice = "female", size = 200 }) {
  const reduced = useRef(prefersReduced()).current;
  const [rig, setRig] = useState({
    mouth: "closed", browY: 0, browTilt: 0, tilt: 0, headY: 0,
    gazeX: 0, gazeY: 0, blink: false,
  });

  const rafRef = useRef(null);
  const blinkAt = useRef(0);
  const nodAt = useRef(0);
  const nodUntil = useRef(0);
  const twitchUntil = useRef(0);
  const browUntil = useRef(0);
  const prevLevel = useRef(0);
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  useEffect(() => {
    if (reduced) return;   // frozen neutral portrait — no loop, no timers

    const now0 = performance.now();
    blinkAt.current = now0 + 2500 + Math.random() * 2500;
    nodAt.current = now0 + 4000 + Math.random() * 3000;

    const tick = () => {
      const t = performance.now();
      const st = stateRef.current;
      const next = {
        mouth: "closed", browY: 0, browTilt: 0, tilt: 0, headY: 0,
        gazeX: 0, gazeY: 0, blink: false,
      };

      // Blink on a randomized 3–6s cadence in every non-frozen state.
      if (t > blinkAt.current) {
        next.blink = true;
        if (t > blinkAt.current + 120) blinkAt.current = t + 3000 + Math.random() * 3000;
      }

      if (st === "speaking") {
        const lvl = ttsLevel();
        if (lvl == null) {
          // No analyser (Web Audio unavailable): stay neutral rather than fake a talk
          // loop. Audio still plays; only the lip-sync degrades.
          next.mouth = "closed";
        } else {
          next.mouth = mouthForLevel(lvl);
          // Sentence starts read as amplitude ONSETS — lift the brows briefly.
          if (lvl - prevLevel.current > 0.06 && lvl > 0.10) browUntil.current = t + 260;
          prevLevel.current = lvl;
          next.headY = -Math.min(1.4, lvl * 5);   // faint bob with the voice
        }
        if (t < browUntil.current) next.browY = -3;
      } else if (st === "listening") {
        next.tilt = -3;                 // attentive lean toward the candidate
        next.gazeX = 0.6;
        if (t > nodAt.current) { nodUntil.current = t + 620; nodAt.current = t + 4000 + Math.random() * 3000; }
        if (t < nodUntil.current) {
          const k = 1 - (nodUntil.current - t) / 620;      // 0..1 across the nod
          const s = Math.sin(k * Math.PI);                  // ease down-and-up
          next.headY = 3.4 * s;
          next.tilt = -3 + 1.8 * s;
          if (s > 0.55 && t > twitchUntil.current) twitchUntil.current = t + 180;   // "mm-hm"
        }
        if (t < twitchUntil.current) next.mouth = "small";
      } else if (st === "thinking") {
        next.gazeX = 1.9;               // gaze up-and-aside
        next.gazeY = -2.2;
        next.browY = 1.6;               // brows draw slightly in/down
        next.browTilt = 3;
        next.tilt = -1.5;
      } else {
        next.mouth = "closed";          // idle / ready — relaxed neutral
      }

      setRig(next);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [reduced]);

  const r = reduced
    ? { mouth: "closed", browY: 0, browTilt: 0, tilt: 0, headY: 0, gazeX: 0, gazeY: 0, blink: false }
    : rig;
  const m = MOUTH[r.mouth] || MOUTH.closed;
  const female = voice !== "male";

  return (
    <div style={{ width: "100%", maxWidth: size, lineHeight: 0 }}>
      <style>{`
        @keyframes iqBreathe { 0%,100%{transform:translateY(0)} 50%{transform:translateY(1.6px)} }
        .iq-ch-body{animation:iqBreathe 3.8s ease-in-out infinite;transform-origin:110px 240px;will-change:transform}
        .iq-ch-head{transition:transform .18s ease-out;will-change:transform}
        .iq-ch-part{transition:transform .16s ease-out}
        @media (prefers-reduced-motion: reduce){ .iq-ch-body{animation:none} .iq-ch-head,.iq-ch-part{transition:none} }
      `}</style>
      <svg viewBox="0 0 220 250" width="100%" height="auto" role="img"
        aria-label={`InterviewIQ interviewer, ${female ? "female" : "male"} — ${state}`}>
        <defs>
          <clipPath id="iq-face-clip">
            <ellipse cx="110" cy="112" rx="42" ry="51" />
          </clipPath>
        </defs>

        {/* ── SHOULDERS / TORSO (breathing) ── */}
        <g className="iq-ch-body">
          {/* suit */}
          <path d="M28 250 C32 208 62 190 92 183 L128 183 C158 190 188 208 192 250 Z" fill={C.navy} />
          {/* shirt / inner */}
          <path d="M92 183 L110 214 L128 183 L120 180 L100 180 Z" fill={C.shirt} />
          {/* lapels */}
          <path d="M92 183 L110 214 L96 250 L74 250 C76 214 82 194 92 183 Z" fill={C.navyMid} />
          <path d="M128 183 L110 214 L124 250 L146 250 C144 214 138 194 128 183 Z" fill={C.navyMid} />
          {female ? (
            // teal dupatta / scarf accent over one shoulder
            <path d="M128 183 C150 192 168 210 176 250 L150 250 C146 218 138 198 122 188 Z" fill={C.teal} opacity="0.92" />
          ) : (
            // tie
            <path d="M110 214 L104 222 L110 250 L116 222 Z" fill={C.teal} />
          )}
          {/* collar edge */}
          <path d="M96 180 L110 196 L124 180" fill="none" stroke={C.gold} strokeWidth="1.6" strokeLinecap="round" opacity="0.75" />
          {/* neck */}
          <path d="M97 156 L123 156 L123 182 C123 190 97 190 97 182 Z" fill={C.skinShade} />
        </g>

        {/* ── HEAD (tilt / nod) ── */}
        <g className="iq-ch-head"
          style={{ transform: `translateY(${r.headY}px) rotate(${r.tilt}deg)`, transformOrigin: "110px 170px" }}>
          {/* hair behind */}
          {female ? (
            <path d="M62 116 C58 70 82 50 110 50 C138 50 162 70 158 116 C158 130 154 138 152 142 L152 96 L68 96 L68 142 C66 138 62 130 62 116 Z" fill={C.hair} />
          ) : (
            <path d="M66 110 C62 70 84 52 110 52 C136 52 158 70 154 110 L154 96 L66 96 Z" fill={C.hair} />
          )}

          {/* ears */}
          <ellipse cx="68" cy="116" rx="6" ry="9" fill={C.skinShade} />
          <ellipse cx="152" cy="116" rx="6" ry="9" fill={C.skinShade} />
          {female && <circle cx="68" cy="126" r="2.4" fill={C.gold} />}
          {female && <circle cx="152" cy="126" r="2.4" fill={C.gold} />}

          {/* face */}
          <ellipse cx="110" cy="112" rx="42" ry="51" fill={C.skin} />
          {/* soft cheek shading (flat, single tone) */}
          <g clipPath="url(#iq-face-clip)" opacity="0.16">
            <ellipse cx="110" cy="176" rx="42" ry="26" fill={C.skinShade} />
          </g>

          {/* hair front / fringe */}
          {female ? (
            <path d="M68 100 C72 66 92 56 110 56 C128 56 148 66 152 100 C146 86 132 78 110 78 C88 78 74 86 68 100 Z" fill={C.hair} />
          ) : (
            <path d="M69 100 C74 68 92 58 110 58 C130 58 148 70 151 100 C142 82 128 76 110 76 C90 76 78 84 69 100 Z" fill={C.hair} />
          )}
          <path d="M96 62 C104 58 118 58 128 64" fill="none" stroke={C.hairHi} strokeWidth="2" strokeLinecap="round" opacity="0.55" />

          {/* eyebrows */}
          <g className="iq-ch-part" style={{ transform: `translateY(${r.browY}px)` }}>
            <path d="M83 97 Q93 92 103 96" fill="none" stroke={C.hair} strokeWidth="3" strokeLinecap="round"
              style={{ transform: `rotate(${r.browTilt}deg)`, transformOrigin: "93px 95px" }} />
            <path d="M117 96 Q127 92 137 97" fill="none" stroke={C.hair} strokeWidth="3" strokeLinecap="round"
              style={{ transform: `rotate(${-r.browTilt}deg)`, transformOrigin: "127px 95px" }} />
          </g>

          {/* eyes (+ lids) */}
          {r.blink ? (
            <g>
              <path d="M85 111 Q93 116 101 111" fill="none" stroke={C.line} strokeWidth="2.2" strokeLinecap="round" />
              <path d="M119 111 Q127 116 135 111" fill="none" stroke={C.line} strokeWidth="2.2" strokeLinecap="round" />
            </g>
          ) : (
            <g className="iq-ch-part">
              <ellipse cx="93" cy="111" rx="8.4" ry="5.2" fill="#FBF7EF" />
              <ellipse cx="127" cy="111" rx="8.4" ry="5.2" fill="#FBF7EF" />
              <circle cx={93 + r.gazeX} cy={111 + r.gazeY} r="3.5" fill={C.line} />
              <circle cx={127 + r.gazeX} cy={111 + r.gazeY} r="3.5" fill={C.line} />
              {/* upper lid line keeps the eye from reading as cartoonish */}
              <path d="M84.6 108.4 Q93 103.6 101.4 108.4" fill="none" stroke={C.line} strokeWidth="1.6" strokeLinecap="round" />
              <path d="M118.6 108.4 Q127 103.6 135.4 108.4" fill="none" stroke={C.line} strokeWidth="1.6" strokeLinecap="round" />
            </g>
          )}

          {/* nose */}
          <path d="M110 114 L106 128 Q110 130 114 128" fill="none" stroke={C.skinShade} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

          {/* mouth — the shape is chosen from the live TTS amplitude while speaking */}
          <path className="iq-ch-part" d={m.d} fill={m.fill} stroke={m.stroke} strokeWidth={m.w} strokeLinecap="round" />

          {female && <circle cx="110" cy="82" r="2.6" fill={C.gold} opacity="0.9" />}
        </g>
      </svg>
    </div>
  );
}
