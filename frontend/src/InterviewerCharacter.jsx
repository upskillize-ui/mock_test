import React, { useEffect } from "react";

/**
 * InterviewerCharacter — InterviewIQ voice stage (v2, anime-style redesign)
 * ─────────────────────────────────────────────────────────────────────────
 * Drop-in replacement for the previous SVG interviewer.
 *
 * Props:
 *   state      "ready" | "speaking" | "listening" | "thinking"   (default "ready")
 *   amplitude  0..1 — live TTS amplitude; drives the mouth while speaking.
 *              Wire it to the same analyser value the old character used.
 *   label      boolean — show the READY / SPEAKING / THINKING caption (default true)
 *   size       px width of the figure (default 300)
 *
 * Design notes (per anime reference brief):
 *   • Male interviewer, navy blazer + gold tie, pen in hand, seated at a desk.
 *   • Large expressive eyes with highlights; brows + pupils shift per state.
 *   • THINKING shows a rotating teal arc around the figure (the "rounding" cue).
 *   • Mouth is a live group: closed smile at rest, opens with `amplitude`.
 *   • Brand palette only. No emojis. Respects prefers-reduced-motion.
 */

const C = {
  navy: "#0B1628",
  navy2: "#1a2744",
  navy3: "#223252",
  gold: "#C8992A",
  goldBright: "#F5B800",
  teal: "#00C4A0",
  orange: "#E8521A",
  skin: "#C98F5F",
  skinShade: "#B3794A",
  hair: "#33200F",
  hairLight: "#4E3218",
  shirt: "#F7F5EF",
  ink: "#241509",
  mouthIn: "#5A2620",
  mist: "#8FA1BD",
};

const STYLE_ID = "iq-character-css";

function injectCSS() {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.textContent = `
    .iq-char { display:flex; flex-direction:column; align-items:center; gap:14px; }
    .iq-char svg { overflow: visible; }
    .iq-bob { animation: iq-bob 4.2s ease-in-out infinite; transform-origin: 160px 200px; }
    .iq-nod { animation: iq-nod 2.6s ease-in-out infinite; transform-origin: 160px 190px; }
    .iq-blink { animation: iq-blink 4.6s infinite; transform-origin: center; transform-box: fill-box; }
    .iq-spin { animation: iq-spin 1.4s linear infinite; transform-origin: 160px 150px; }
    .iq-label { font-family:"DM Mono", ui-monospace, monospace; font-size:12px;
                letter-spacing:.32em; color:${C.mist}; text-transform:uppercase; }
    .iq-label--speaking { color:${C.teal}; }
    .iq-label--thinking { color:${C.goldBright}; }
    @keyframes iq-bob   { 0%,100% { transform: translateY(0) } 50% { transform: translateY(3px) } }
    @keyframes iq-nod   { 0%,100% { transform: rotate(0deg) } 50% { transform: rotate(1.4deg) } }
    @keyframes iq-blink { 0%, 94%, 100% { transform: scaleY(0) } 96%, 98% { transform: scaleY(1) } }
    @keyframes iq-spin  { to { transform: rotate(360deg) } }
    @media (prefers-reduced-motion: reduce) {
      .iq-bob, .iq-nod, .iq-spin, .iq-blink { animation: none; }
    }
  `;
  document.head.appendChild(s);
}

export default function InterviewerCharacter({
  state = "ready",
  amplitude = 0,
  label = true,
  size = 300,
}) {
  useEffect(injectCSS, []);

  const speaking = state === "speaking";
  const thinking = state === "thinking";
  const listening = state === "listening";

  // Mouth openness 0..1 — floor keeps the mouth alive between syllables.
  const open = speaking ? Math.max(0.1, Math.min(1, amplitude)) : 0;
  const mouthRy = 2.5 + open * 11;      // vertical opening
  const mouthRx = 15 - open * 4;        // narrows slightly as it opens

  // Pupils drift up-and-aside while thinking (classic "recalling" look).
  const pupilDx = thinking ? 4 : 0;
  const pupilDy = thinking ? -4 : 0;

  // Brows: raised + asymmetric while thinking, gently lifted while speaking.
  const browLift = thinking ? -5 : speaking ? -2 : 0;
  const browTilt = thinking ? -7 : 0;

  const bodyMotion = listening ? "iq-nod" : "iq-bob";

  return (
    <div className="iq-char" role="img" aria-label={`Interviewer is ${state}`}>
      <svg width={size} height={size * 1.2} viewBox="0 0 320 384" fill="none">
        <defs>
          <linearGradient id="iqTie" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={C.goldBright} />
            <stop offset="1" stopColor={C.gold} />
          </linearGradient>
          <linearGradient id="iqDesk" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={C.navy3} />
            <stop offset="1" stopColor={C.navy2} />
          </linearGradient>
          <radialGradient id="iqGlow" cx="0.5" cy="0.42" r="0.55">
            <stop offset="0" stopColor={C.teal} stopOpacity="0.10" />
            <stop offset="1" stopColor={C.teal} stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* soft stage glow */}
        <rect x="0" y="0" width="320" height="384" fill="url(#iqGlow)" />

        {/* thinking spinner — rotating teal arc around the figure */}
        {thinking && (
          <g className="iq-spin">
            <circle
              cx="160" cy="150" r="118"
              stroke={C.teal} strokeWidth="3" strokeLinecap="round"
              strokeDasharray="80 660" opacity="0.9" fill="none"
            />
            <circle
              cx="160" cy="150" r="118"
              stroke={C.teal} strokeWidth="3" strokeLinecap="round"
              strokeDasharray="18 722" strokeDashoffset="-140"
              opacity="0.45" fill="none"
            />
          </g>
        )}

        {/* listening pulse ring */}
        {listening && (
          <circle cx="160" cy="150" r="118" stroke={C.teal} strokeWidth="2"
                  opacity="0.25" fill="none" />
        )}

        <g className={bodyMotion}>
          {/* ───────── body ───────── */}
          {/* blazer */}
          <path
            d="M58 384 L63 268 C68 228 106 210 130 205 L160 216 L190 205
               C214 210 252 228 257 268 L262 384 Z"
            fill={C.navy2}
          />
          {/* blazer shading */}
          <path d="M58 384 L63 268 C66 240 84 222 104 213 L96 384 Z"
                fill={C.navy} opacity="0.45" />
          <path d="M262 384 L257 268 C254 240 236 222 216 213 L224 384 Z"
                fill={C.navy} opacity="0.45" />
          {/* shirt V */}
          <path d="M130 205 L160 262 L190 205 L181 199 L160 236 L139 199 Z"
                fill={C.shirt} />
          {/* collar points */}
          <path d="M139 199 L160 216 L146 224 Z" fill={C.shirt} />
          <path d="M181 199 L160 216 L174 224 Z" fill={C.shirt} />
          <path d="M139 199 L160 216 L146 224 Z" fill={C.navy} opacity="0.08" />
          {/* lapels */}
          <path d="M130 205 L160 262 L142 276 L118 226 Z" fill={C.navy} opacity="0.55" />
          <path d="M190 205 L160 262 L178 276 L202 226 Z" fill={C.navy} opacity="0.55" />
          {/* tie */}
          <path d="M160 216 L151 227 L160 236 L169 227 Z" fill="url(#iqTie)" />
          <path d="M154 234 L160 320 L166 234 L160 240 Z" fill="url(#iqTie)" />
          <path d="M154 234 L160 320 L160 240 Z" fill={C.gold} opacity="0.5" />
          {/* pocket square */}
          <path d="M104 252 L124 252 L119 240 L112 246 L108 240 Z" fill={C.teal} />

          {/* right arm + pen (viewer's right) */}
          <path
            d="M257 292 C250 268 232 258 214 261 C200 264 192 274 193 286
               L214 306 C230 308 248 306 257 300 Z"
            fill={C.navy2}
          />
          <path d="M257 292 C252 276 240 266 226 263 L222 268 C236 272 246 282 251 296 Z"
                fill={C.navy} opacity="0.4" />
          {/* cuff */}
          <path d="M196 276 C193 282 193 288 196 293 L208 296 C204 289 204 282 207 276 Z"
                fill={C.shirt} />
          {/* pen — navy barrel, gold band, dark nib */}
          <g transform="rotate(-38 200 286)">
            <rect x="176" y="281" width="48" height="9" rx="4.5" fill={C.navy} />
            <rect x="176" y="281" width="48" height="9" rx="4.5" fill="#2E4066" opacity="0.6" />
            <rect x="196" y="281" width="5" height="9" fill={C.goldBright} />
            <path d="M224 281 L233 285.5 L224 290 Z" fill={C.ink} />
          </g>
          {/* hand gripping pen */}
          <ellipse cx="200" cy="287" rx="13" ry="11" fill={C.skin} />
          <ellipse cx="193" cy="281" rx="5" ry="4" fill={C.skinShade} opacity="0.5" />
          <ellipse cx="206" cy="292" rx="6" ry="4.5" fill={C.skin} />

          {/* ───────── neck + head ───────── */}
          <path d="M146 178 L146 208 C146 216 174 216 174 208 L174 178 Z" fill={C.skin} />
          <path d="M146 182 C150 192 170 192 174 182 L174 178 L146 178 Z"
                fill={C.skinShade} opacity="0.55" />

          {/* ears */}
          <ellipse cx="101" cy="128" rx="8" ry="12" fill={C.skin} />
          <ellipse cx="219" cy="128" rx="8" ry="12" fill={C.skin} />
          <ellipse cx="101" cy="128" rx="3.5" ry="6" fill={C.skinShade} opacity="0.5" />
          <ellipse cx="219" cy="128" rx="3.5" ry="6" fill={C.skinShade} opacity="0.5" />

          {/* face */}
          <path
            d="M102 116 C102 74 128 52 160 52 C192 52 218 74 218 116
               C218 152 196 184 160 184 C124 184 102 152 102 116 Z"
            fill={C.skin}
          />
          {/* jaw shadow */}
          <path d="M120 160 C132 176 188 176 200 160 C190 180 130 180 120 160 Z"
                fill={C.skinShade} opacity="0.35" />

          {/* hair — anime fringe with strands */}
          <path
            d="M100 122 C94 66 126 40 160 40 C194 40 226 66 220 122
               C216 108 210 98 204 94 C207 102 206 108 204 112
               C198 96 190 88 182 86 C186 92 186 98 184 102
               C176 88 166 82 154 84 C158 90 158 94 156 98
               C146 86 134 86 126 94 C129 99 129 104 127 108
               C118 104 112 110 108 122 Z"
            fill={C.hair}
          />
          <path d="M126 94 C134 86 146 86 156 98 C150 92 138 90 126 94 Z"
                fill={C.hairLight} opacity="0.8" />
          <path d="M160 40 C186 40 210 56 218 88 C206 62 184 48 160 46 Z"
                fill={C.hairLight} opacity="0.5" />
          {/* sideburns */}
          <path d="M102 116 C102 106 105 100 109 98 L110 126 Z" fill={C.hair} />
          <path d="M218 116 C218 106 215 100 211 98 L210 126 Z" fill={C.hair} />

          {/* brows */}
          <g transform={`translate(0 ${browLift})`}>
            <path d="M122 106 Q138 98 152 105" stroke={C.ink} strokeWidth="4.5"
                  strokeLinecap="round" fill="none"
                  transform={`rotate(${browTilt} 137 103)`} />
            <path d="M168 105 Q182 98 198 106" stroke={C.ink} strokeWidth="4.5"
                  strokeLinecap="round" fill="none" />
          </g>

          {/* eyes */}
          {[137, 183].map((cx, i) => (
            <g key={i}>
              <ellipse cx={cx} cy="126" rx="11" ry="12.5" fill="#FFFFFF" />
              <circle cx={cx + pupilDx} cy={126 + pupilDy} r="7" fill="#5B3A1E" />
              <circle cx={cx + pupilDx} cy={126 + pupilDy} r="3.6" fill={C.ink} />
              <circle cx={cx + pupilDx - 2.4} cy={123 + pupilDy - 1} r="2.4" fill="#FFFFFF" />
              <circle cx={cx + pupilDx + 2.2} cy={129 + pupilDy} r="1.1"
                      fill="#FFFFFF" opacity="0.85" />
              {/* upper lash line */}
              <path d={`M${cx - 11} 122 Q${cx} 111 ${cx + 11} 122`}
                    stroke={C.ink} strokeWidth="3.2" strokeLinecap="round" fill="none" />
              {/* blink lid */}
              <ellipse className="iq-blink" cx={cx} cy="126" rx="11.5" ry="13"
                       fill={C.skin} style={{ animationDelay: `${i * 0.05}s` }} />
            </g>
          ))}

          {/* nose */}
          <path d="M160 138 Q163 147 158 151" stroke={C.skinShade}
                strokeWidth="2.5" strokeLinecap="round" fill="none" />

          {/* subtle blush */}
          <ellipse cx="122" cy="146" rx="9" ry="4.5" fill={C.orange} opacity="0.12" />
          <ellipse cx="198" cy="146" rx="9" ry="4.5" fill={C.orange} opacity="0.12" />

          {/* mouth — closed smile at rest, amplitude-driven when speaking */}
          <g transform="translate(160 163)">
            {open < 0.12 ? (
              <path d="M-13 0 Q0 9 13 0" stroke="#7A3B2E" strokeWidth="3.5"
                    strokeLinecap="round" fill="none" />
            ) : (
              <g>
                <ellipse cx="0" cy={mouthRy * 0.4} rx={mouthRx} ry={mouthRy}
                         fill={C.mouthIn} />
                {open > 0.35 && (
                  <rect x={-mouthRx * 0.7} y={mouthRy * 0.4 - mouthRy}
                        width={mouthRx * 1.4} height={mouthRy * 0.45}
                        rx="2" fill="#FFFFFF" opacity="0.9" />
                )}
                <ellipse cx="0" cy={mouthRy * 0.75} rx={mouthRx * 0.55}
                         ry={mouthRy * 0.4} fill={C.orange} opacity="0.55" />
              </g>
            )}
          </g>
        </g>

        {/* ───────── desk (drawn last so it sits in front) ───────── */}
        <rect x="14" y="330" width="292" height="54" rx="10" fill="url(#iqDesk)" />
        <rect x="14" y="330" width="292" height="3" rx="1.5" fill={C.gold} opacity="0.55" />
        {/* clipboard + sheet on the desk */}
        <g transform="rotate(-4 96 340)">
          <rect x="52" y="332" width="88" height="16" rx="4" fill="#0E1B30" />
          <rect x="58" y="329" width="76" height="14" rx="3" fill={C.shirt} />
          <rect x="88" y="325" width="16" height="6" rx="3" fill={C.gold} />
          <rect x="66" y="333" width="52" height="1.6" fill={C.mist} opacity="0.5" />
          <rect x="66" y="337" width="40" height="1.6" fill={C.mist} opacity="0.35" />
        </g>
      </svg>

      {label && (
        <div
          className={
            "iq-label" +
            (speaking ? " iq-label--speaking" : thinking ? " iq-label--thinking" : "")
          }
        >
          {state}
        </div>
      )}
    </div>
  );
}