import { useEffect, useRef, useState } from "react";

/**
 * RobotInterviewer — "Nova" & "Nia" (v2.3, animated android interviewers)
 * variant="nova" (male-voiced android, gold tie) | variant="nia" (female-voiced
 * android: metallic bob crown with a silver streak, lashes, NO jewelry).
 *
 * v2.3 — NIA IS THE SENIOR INTERVIEWER (40+). Five deliberate differences, all
 * gated on `fem` so Nova is byte-for-byte what he was: a squarer cranium, angular
 * "set" visor brows, a silver streak through the bob crown, a higher and sharper
 * peak-lapel collar, and no jewelry (the teal pendant is gone — see the torso).
 * Seniority had to read at 300px with no wrinkles and no grey filter, so it lives
 * entirely in silhouette: harder edges, higher collar, one streak.
 * (Earlier headers here described hoop earrings and a gold chain. Neither ever
 * existed in this file. Only the pendant did, and now that is gone too.)
 * v2.2: tone prop ("warm"|"neutral"|"probing"|"critical") drives visor
 * brows, eye shape and rest-mouth; the gesture arm RIDES the live
 * amplitude (louder = bigger raise) atop a two-beat gesture cycle; the
 * pen scribbles notes while LISTENING; the left hand taps while
 * THINKING; eyes wander subtly at idle. Wire tone from the server's
 * tone_hint (same value the pose engine receives); defaults work fine
 * without it.
 * Roster: { id:"nova", kind:"vectorbot", voice:"male" } and
 *         { id:"nia",  kind:"vectorbot", voice:"female", variant:"nia" }.
 * ─────────────────────────────────────────────────────────────
 * The laugh-proof animated option: a polished android in a blazer at a
 * desk. A robot face means no uncanny cartoon-human problem, and its
 * light-based mouth makes amplitude lip-sync look NATIVE.
 *
 *   • MOUTH: a 7-segment waveform bar on the visor — segment heights ride
 *     the live Bulbul amplitude; at rest it settles into a soft smile arc.
 *   • EYES: glowing teal — round when ready, widened while listening,
 *     upward crescents while thinking, pulse with the voice when speaking.
 *     They blink. The antenna tip pulses while thinking.
 *   • BODY: breathes; head sways/nods/tilts per state; pen-hand gesture
 *     cycle while speaking (same rig as the room's other characters).
 *   • Brand: navy blazer, gold tie, teal glow. prefers-reduced-motion ok.
 *
 * Contract: <RobotInterviewer state amplitude size /> — same as
 * VectorInterviewer. Roster entry: { id:"nova", name:"Nova",
 * kind:"vectorbot", voice:"any", temperaments:[...] }.
 */

const C = {
  headA: "#EAEFF5", headB: "#B9C2CE", headEdge: "#8E99A8",
  visor: "#0C1830", visorEdge: "#22314F",
  teal: "#00C4A0", tealDim: "#0A6B58", gold: "#F5B800",
  blazerA: "#25355C", blazerB: "#1a2744", blazerC: "#111C33",
  shirt: "#F7F5EF", ink: "#241509",
  bgWall: "#20304F", bgShelf: "#2A3C5E", desk: "#3A2A1A", deskHi: "#4E3823",
};

const STYLE_ID = "iq-nova-css";
function injectCSS() {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.textContent = `
  .iqnova svg { display:block; overflow:visible; }
  .nv-head { transform-origin: 180px 175px; }
  .nv-torso { transform-origin: 180px 330px; animation: nvBr 3.8s ease-in-out infinite; }
  .nv-armR { transform-origin: 264px 300px; }
  .nv-lid { transform-box: fill-box; transform-origin: center; }
  .nv-ant { transform-box: fill-box; transform-origin: center bottom; }

  .nv-idle .nv-head { animation: nvSway 5.2s ease-in-out infinite; }
  .nv-listening .nv-head { animation: nvNod 2.8s ease-in-out infinite; }
  .nv-thinking .nv-head { animation: nvTilt 4s ease-in-out infinite; }
  .nv-speaking .nv-head { animation: nvBob 3.4s ease-in-out infinite; }
  .nv-speaking .nv-armR { animation: nvGest 8s ease-in-out infinite; }
  .nv-thinking .nv-antTip { animation: nvPulse 1.1s ease-in-out infinite; }
  .nv-lid { animation: nvBlink 4.6s infinite; }
  .nv-thinking .nv-ant { animation: nvAntSway 1.6s ease-in-out infinite; }

  @keyframes nvSway { 0%,100%{transform:rotate(0)} 50%{transform:rotate(-1.2deg) translateY(1.5px)} }
  @keyframes nvNod  { 0%,100%{transform:rotate(0)} 45%{transform:rotate(1.8deg) translateY(2px)} }
  @keyframes nvTilt { 0%,100%{transform:rotate(0)} 50%{transform:rotate(-2.6deg)} }
  @keyframes nvBob  { 0%,100%{transform:translateY(0) rotate(0)} 30%{transform:translateY(1.6px) rotate(.8deg)} 65%{transform:translateY(-1px) rotate(-.6deg)} }
  @keyframes nvBr   { 0%,100%{transform:scaleY(1)} 50%{transform:scaleY(1.015) translateY(-1px)} }
  @keyframes nvBlink{ 0%,94%,100%{transform:scaleY(0)} 95%,96.5%{transform:scaleY(1)} }
  @keyframes nvGest { 0%,30%,68%,100%{transform:rotate(0)} 8%{transform:rotate(-14deg)} 15%{transform:rotate(-9deg)} 22%{transform:rotate(-13deg)} 76%{transform:rotate(-8deg) translateY(-2px)} 84%{transform:rotate(-12deg)} 91%{transform:rotate(-6deg)} }
  @keyframes nvPulse{ 0%,100%{opacity:.35} 50%{opacity:1} }
  @keyframes nvAntSway{ 0%,100%{transform:rotate(-4deg)} 50%{transform:rotate(4deg)} }

  .nv-listening .nv-penG { animation: nvWrite 1.1s ease-in-out infinite; transform-box: fill-box; transform-origin: 30% 70%; }
  .nv-thinking .nv-handL { animation: nvTapL 0.9s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
  .nv-idle .nv-eyesG { animation: nvWander 7s ease-in-out infinite; }
  .nv-brow { transition: transform .35s ease; }
  @keyframes nvWrite { 0%,100%{transform:translate(0,0) rotate(0)} 25%{transform:translate(1.5px,1px) rotate(2deg)} 55%{transform:translate(-1px,1.5px) rotate(-2deg)} 80%{transform:translate(1px,.5px) rotate(1deg)} }
  @keyframes nvTapL { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-2.5px)} }
  @keyframes nvWander { 0%,18%,100%{transform:translateX(0)} 28%,42%{transform:translateX(3px)} 58%,74%{transform:translateX(-3px)} }
  @media (prefers-reduced-motion: reduce) { .iqnova * { animation: none !important; } }
  `;
  document.head.appendChild(s);
}

const SEG_MULT = [0.45, 0.72, 1.0, 0.85, 1.0, 0.7, 0.5];

export default function RobotInterviewer({ state = "idle", amplitude = 0, size = 300, variant = "nova", tone = "neutral" }) {
  const fem = variant === "nia";
  const probing = tone === "probing" || tone === "critical";
  const warm = tone === "warm";
  const EYE_X = fem ? [158, 202] : [156, 204];
  const eyeGrow = fem ? 1 : 0;
  useEffect(injectCSS, []);
  const speaking = state === "speaking";
  const thinking = state === "thinking";
  const listening = state === "listening";

  // live wobble so equal loudness never freezes the bar
  const [t, setT] = useState(0);
  const raf = useRef(null);
  useEffect(() => {
    if (!speaking) return;
    const tick = () => { setT(performance.now()); raf.current = requestAnimationFrame(tick); };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [speaking]);

  const level = speaking
    ? Math.max(0.12, Math.min(1, amplitude + (Math.sin(t / 90) + Math.sin(t / 47)) * 0.1))
    : 0;

  // eye geometry per state (glowing shapes on the visor)
  const eye = thinking
    ? { rx: 9, ry: 4, dy: -6, arc: true }        // upward crescents
    : listening
    ? { rx: 8.5, ry: 11, dy: 0, arc: false }     // widened, attentive
    : speaking
    ? { rx: 8, ry: 8 + level * 3, dy: 0, arc: false } // pulse with voice
    : { rx: 8, ry: 8, dy: 0, arc: false };       // ready

  const stateClass =
    speaking ? "nv-speaking" : thinking ? "nv-thinking" : listening ? "nv-listening" : "nv-idle";

  const segH = (m) => (speaking ? Math.max(3, level * 16 * m) : 3);

  return (
    <div className={`iqnova ${stateClass}`} role="img" aria-label={`Interviewer Nova is ${state}`}>
      <svg width={size} height={size * 1.25} viewBox="0 0 360 450" fill="none">
        <defs>
          <linearGradient id="nvHead" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={C.headA} /><stop offset="1" stopColor={C.headB} />
          </linearGradient>
          <linearGradient id="nvBlz" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={C.blazerA} /><stop offset=".5" stopColor={C.blazerB} /><stop offset="1" stopColor={C.blazerC} />
          </linearGradient>
          <linearGradient id="nvDesk" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={C.deskHi} /><stop offset="1" stopColor={C.desk} />
          </linearGradient>
          <radialGradient id="nvGlow" cx="0.5" cy="0.35" r="0.6">
            <stop offset="0" stopColor="#31507F" /><stop offset="1" stopColor={C.bgWall} />
          </radialGradient>
          <linearGradient id="nvTie" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={C.gold} /><stop offset="1" stopColor="#C8992A" />
          </linearGradient>
        </defs>

        {/* backdrop */}
        <rect x="0" y="0" width="360" height="450" rx="16" fill="url(#nvGlow)" />
        <g opacity="0.5">
          <rect x="18" y="40" width="86" height="150" rx="8" fill={C.bgShelf} />
          <rect x="26" y="54" width="70" height="10" rx="3" fill="#33466B" />
          <rect x="26" y="76" width="70" height="10" rx="3" fill="#33466B" />
          <rect x="26" y="98" width="46" height="10" rx="3" fill="#33466B" />
          <ellipse cx="316" cy="150" rx="26" ry="40" fill="#1E4D3F" />
          <ellipse cx="300" cy="130" rx="16" ry="30" fill="#256050" transform="rotate(-20 300 130)" />
          <rect x="306" y="182" width="22" height="20" rx="4" fill="#6B4A2B" />
        </g>

        {/* torso */}
        <g className="nv-torso">
          {/* squared shoulders · open blazer · white shirt */}
          {/* shirt column */}
          <path d="M146 292 L146 450 L214 450 L214 292 Z" fill={C.shirt} />
          <path d="M146 292 L146 450 L156 450 L156 292 Z" fill="#E2DFD3" />
          <path d="M214 292 L214 450 L204 450 L204 292 Z" fill="#E2DFD3" />
          {/* collar points — nia's sit HIGHER (y=252 vs 264) and cut SHARPER: a narrower
              spread and a longer point. Nova's are untouched. A high, crisp collar is what
              reads as "senior" at 300px without a single extra element on screen. */}
          {fem ? (
            <>
              {/* The apexes sit at x=172/188 — INSIDE the neck joint's x-range (168-192),
                  which is drawn after the torso and therefore covers them. That is what
                  makes the collar read as rising from BEHIND the neck rather than as two
                  wings pinned beside the jaw. (It did exactly that when the apexes were at
                  x=167/193: a one-pixel sliver of each escaped past the neck's edge.)
                  Higher (250 vs 264) and narrower than Nova's, so the V is a deeper, more
                  vertical notch. */}
              <path d="M172 250 L180 286 L156 292 Z" fill={C.shirt} />
              <path d="M188 250 L180 286 L204 292 Z" fill={C.shirt} />
            </>
          ) : (
            <>
              <path d="M163 264 L180 284 L154 292 Z" fill={C.shirt} />
              <path d="M197 264 L180 284 L206 292 Z" fill={C.shirt} />
            </>
          )}
          {/* open blazer panels */}
          <path d="M94 450 L94 302 Q94 292 104 292 L164 292 C156 330 148 390 144 450 Z" fill="url(#nvBlz)" />
          <path d="M266 450 L266 302 Q266 292 256 292 L196 292 C204 330 212 390 216 450 Z" fill="url(#nvBlz)" />
          <path d="M164 292 C156 330 148 390 144 450 L136 450 C140 388 147 328 155 292 Z" fill={C.blazerC} opacity="0.55" />
          <path d="M196 292 C204 330 212 390 216 450 L224 450 C220 388 213 328 205 292 Z" fill={C.blazerC} opacity="0.55" />
          {/* lapels — nia gets a PEAK lapel (a sharp upward point at the notch) against
              nova's soft notch, and it starts higher to meet her raised collar. Same navy,
              same palette; only the geometry is harder. Nova's four paths are unchanged. */}
          {fem ? (
            <>
              {/* A PEAK lapel: the inner edge rises to a point (176/184, 300) instead of
                  Nova's soft notch, and the outer edge runs longer and straighter to a
                  sharper tip. Everything stays at or below the shoulder line (y=292) —
                  an earlier attempt put the peak ABOVE it, and two navy spikes duly
                  stabbed up through the white shirt and read as a bow tie. */}
              <path d="M164 292 L148 326 L178 308 L176 300 Z" fill={C.blazerA} />
              <path d="M196 292 L212 326 L182 308 L184 300 Z" fill={C.blazerA} />
              <path d="M164 292 L148 326 L156 323 Z" fill={C.blazerC} opacity="0.5" />
              <path d="M196 292 L212 326 L204 323 Z" fill={C.blazerC} opacity="0.5" />
            </>
          ) : (
            <>
              <path d="M164 292 L150 324 L176 312 Z" fill={C.blazerA} />
              <path d="M196 292 L210 324 L184 312 Z" fill={C.blazerA} />
              <path d="M164 292 L150 324 L158 322 Z" fill={C.blazerC} opacity="0.5" />
              <path d="M196 292 L210 324 L202 322 Z" fill={C.blazerC} opacity="0.5" />
            </>
          )}
          {/* squared shoulder seams */}
          <path d="M104 292 L164 292" stroke="#33466B" strokeWidth="2" opacity="0.6" />
          <path d="M196 292 L256 292" stroke="#33466B" strokeWidth="2" opacity="0.6" />
          {/* teal pocket square */}
          <path d="M112 318 L132 318 L127 306 L120 312 L116 306 Z" fill={C.teal} />
          {/* nova: gold tie + LED tie-pin · nia: NO JEWELRY, by design — see below */}
          {!fem && (
            <g>
              <path d="M180 292 L171 302 L180 312 L189 302 Z" fill="url(#nvTie)" />
              <path d="M174 310 L180 378 L186 310 L180 316 Z" fill="url(#nvTie)" />
              <circle cx="180" cy="330" r="3.5" fill={C.teal} opacity={speaking ? 0.95 : 0.6} />
            </g>
          )}
          {/* Nia wore a glowing teal pendant here. It is gone and must not come back: the
              senior interviewer wears nothing decorative. Nova keeps the tie because a tie
              is what he is wearing to work, not an ornament — the asymmetry is the point.
              Her authority is in the cut of the collar and the set of the brows, and
              anything sparkly at the throat pulls the eye straight off both. */}

          {/* left arm — structured square sleeve */}
          <path d="M94 306 L88 356 C86 388 92 406 102 416 L134 410 C126 392 124 366 128 344 L128 306 Z" fill="url(#nvBlz)" />
          <g className="nv-handL">
            <ellipse cx="120" cy="416" rx="16" ry="11" fill="url(#nvHead)" />
            <rect x="106" y="408" width="8" height="10" rx="3" fill={C.headEdge} opacity="0.5" />
          </g>

          {/* right arm + pen, gestures while speaking */}
          <g className="nv-armR">
           <g style={{ transform: `rotate(${speaking ? -(level * 7) : 0}deg)`, transformOrigin: "264px 300px", transition: "transform 130ms linear" }}>
            <path d="M266 306 L272 356 C274 388 268 406 258 416 L226 408 C234 390 236 366 232 344 L232 306 Z" fill="url(#nvBlz)" />
            <path d="M258 404 C254 410 248 414 242 415 L228 408 C234 404 238 398 240 392 Z" fill={C.shirt} />
            <ellipse cx="240" cy="414" rx="15" ry="11" fill="url(#nvHead)" />
            <rect x="228" y="404" width="7" height="9" rx="3" fill={C.headEdge} opacity="0.5" />
            <g className="nv-penG" transform="rotate(-32 240 412)">
              <rect x="218" y="408" width="46" height="8" rx="4" fill={C.blazerC} />
              <rect x="236" y="408" width="5" height="8" fill={C.gold} />
              <path d="M264 408 L272 412 L264 416 Z" fill={C.ink} />
            </g>
           </g>
          </g>
        </g>

        {/* head */}
        <g className="nv-head">
          {/* neck joint */}
          <rect x={fem ? 168 : 164} y="228" width={fem ? 24 : 32} height="34" rx="10" fill="url(#nvHead)" />
          <rect x={fem ? 168 : 164} y="238" width={fem ? 24 : 32} height="5" rx="2.5" fill={C.headEdge} opacity="0.6" />
          <rect x={fem ? 168 : 164} y="248" width={fem ? 24 : 32} height="5" rx="2.5" fill={C.headEdge} opacity="0.6" />

          {/* ear discs */}
          <circle cx={fem ? 120 : 112} cy="170" r={fem ? 12 : 15} fill="url(#nvHead)" stroke={C.headEdge} strokeWidth="1.5" />
          <circle cx={fem ? 120 : 112} cy="170" r={fem ? 5.5 : 6.5} fill="none" stroke={C.teal} strokeWidth="2.5"
                  opacity={listening ? 0.95 : 0.45} />
          <circle cx={fem ? 240 : 248} cy="170" r={fem ? 12 : 15} fill="url(#nvHead)" stroke={C.headEdge} strokeWidth="1.5" />
          <circle cx={fem ? 240 : 248} cy="170" r={fem ? 5.5 : 6.5} fill="none" stroke={C.teal} strokeWidth="2.5"
                  opacity={listening ? 0.95 : 0.45} />


          {/* antenna */}
          <g className="nv-ant">
            <rect x="177.5" y="72" width="5" height="22" rx="2.5" fill={C.headEdge} />
            <circle className="nv-antTip" cx="180" cy="68" r="6" fill={C.teal}
                    opacity={thinking ? 1 : 0.35} />
          </g>

          {/* cranium — nia's is SQUARER than it was: the crown flattens across the top
              (the control points pull toward the corners instead of rounding through them)
              and the temples run straighter before turning. Same width and height, so the
              visor, bob and ear discs all still line up; only the silhouette hardens. */}
          <path d={fem
                ? "M124 168 C122 106 144 90 180 90 C216 90 238 106 236 168 C236 210 214 234 180 234 C146 234 124 210 124 168 Z"
                : "M116 168 C112 110 140 88 180 88 C220 88 248 110 244 168 C244 208 222 236 180 236 C138 236 116 208 116 168 Z"}
                fill="url(#nvHead)" stroke={C.headEdge} strokeWidth="1.5" />
          {/* crown seam + bolt */}
          {!fem && (
            <g>
              <path d="M132 110 C148 98 212 98 228 110" stroke={C.headEdge} strokeWidth="1.5" fill="none" opacity="0.7" />
              <circle cx="180" cy="100" r="3" fill={C.headEdge} opacity="0.8" />
            </g>
          )}
          {fem && (
            <g transform="translate(180 0) scale(0.94 1) translate(-180 0)">
              {/* sleek metallic bob crown framing the visor */}
              <path d="M114 172 C108 106 138 86 180 86 C222 86 252 106 246 172
                       C246 150 240 132 230 122 L230 176 C236 178 240 184 240 192
                       C240 202 232 208 224 206 L224 128
                       C212 112 196 106 180 106 C164 106 148 112 136 128 L136 206
                       C128 208 120 202 120 192 C120 184 124 178 130 176 L130 122
                       C120 132 114 150 114 172 Z"
                    fill="#6E7A8C" stroke={C.headEdge} strokeWidth="1" />
              <path d="M136 128 C148 112 164 106 180 106 C168 108 152 116 144 130 Z"
                    fill="#8B97A8" opacity="0.7" />
              {/* THE SILVER STREAK — the one element that says 40+ without a wrinkle, a
                  greyscale filter, or any of the other ways this could have gone wrong.
                  It sweeps from the crown down the right of the parting, following the
                  bob's own curve so it reads as hair and not as a scratch on the visor.
                  C.headA (#EAEFF5) is the brand's lightest metal — deliberately ON
                  palette, unlike the bob's own #6E7A8C, which predates it. */}
              <path d="M186 88 C198 92 210 102 218 118 C222 128 224 140 224 152
                       L216 152 C216 140 214 130 210 121 C203 106 194 97 183 93 Z"
                    fill={C.headA} opacity="0.85" />
              <path d="M186 88 C196 91 205 98 212 109 C205 100 195 94 184 91 Z"
                    fill="#FFFFFF" opacity="0.5" />
            </g>
          )}

          {/* visor */}
          <path d={fem
                ? "M136 140 C136 124 154 116 180 116 C206 116 224 124 224 140 L224 180 C224 204 206 222 180 222 C154 222 136 204 136 180 Z"
                : "M130 138 C130 122 150 114 180 114 C210 114 230 122 230 138 L230 186 C230 208 210 220 180 220 C150 220 130 208 130 186 Z"}
                fill={C.visor} stroke={C.visorEdge} strokeWidth="2" />
          <path d="M136 130 C150 120 176 117 180 117 C176 124 152 128 142 136 Z"
                fill="#FFFFFF" opacity="0.08" />

          {/* visor brows — tone-driven expression.
              NIA'S ARE ANGULAR AND SET. Three differences from Nova's, and each one is
              doing a job:
                • rx 1.6 -> 0.3   a squared-off bar instead of a rounded lozenge. Rounded
                                  ends read soft at any angle; this is the whole "angular".
                • +4deg inward    a permanent slight converge, on TOP of the tone rotation.
                                  This is "set": her neutral is already level-eyed and
                                  unimpressed, where Nova's neutral is flat.
                • dy +1           sits a touch closer to the eye. A low brow reads
                                  attentive; a high one reads surprised, and she is never
                                  surprised.
              The tone response itself (probing/warm) is UNCHANGED and still applies to
              both — a senior interviewer still warms up, she just starts from further in. */}
          {EYE_X.map((cx, i) => {
            const inward = i === 0 ? 1 : -1;
            const toneRot = probing ? inward * 14 : warm ? -inward * 8 : 0;
            const rot = toneRot + (fem ? inward * 4 : 0);
            const dy = (probing ? 3 : warm ? -1 : 0) + (fem ? 1 : 0);
            return (
              <rect key={"b" + i} className="nv-brow"
                x={cx - 8} y={139 + dy} width="16" height={fem ? 3.6 : 3.2}
                rx={fem ? 0.3 : 1.6}
                fill={C.teal} opacity="0.75"
                style={{ transform: `rotate(${rot}deg)`, transformOrigin: `${cx}px ${141 + dy}px` }} />
            );
          })}

          {/* eyes — glowing, state-shaped, blinking */}
          <g className="nv-eyesG">
          {EYE_X.map((cx, i) => (
            <g key={i}>
              {(warm && !speaking && !thinking) ? (
                <path d={`M${cx - 9} ${162 + eye.dy} Q${cx} ${150 + eye.dy} ${cx + 9} ${162 + eye.dy}`}
                      stroke={C.teal} strokeWidth="5" strokeLinecap="round" fill="none"
                      style={{ filter: `drop-shadow(0 0 6px ${C.teal})` }} />
              ) : eye.arc ? (
                <path d={`M${cx - 9} ${158 + eye.dy} Q${cx} ${146 + eye.dy} ${cx + 9} ${158 + eye.dy}`}
                      stroke={C.teal} strokeWidth="5" strokeLinecap="round" fill="none"
                      style={{ filter: `drop-shadow(0 0 6px ${C.teal})` }} />
              ) : (
                <ellipse cx={cx} cy={158 + eye.dy} rx={eye.rx + eyeGrow} ry={(probing ? eye.ry * 0.72 : eye.ry) + eyeGrow} fill={C.teal}
                         style={{ filter: `drop-shadow(0 0 7px ${C.teal})` }} />
              )}
              {/* blink lid — visor-colored */}
              <rect className="nv-lid" x={cx - 11} y={158 + eye.dy - 13} width="22" height="26"
                    fill={C.visor} style={{ animationDelay: `${i * 0.05}s` }} />
            </g>
          ))}
          {fem && EYE_X.map((cx, i) => (
            <g key={"l" + i} stroke={C.teal} strokeWidth="1.6" strokeLinecap="round" opacity="0.85">
              <path d={`M${cx + 9} ${150 + eye.dy} L${cx + 13} ${146 + eye.dy}`} />
              <path d={`M${cx + 11} ${154 + eye.dy} L${cx + 15.5} ${151 + eye.dy}`} />
            </g>
          ))}
          </g>

          {/* MOUTH — 7-segment waveform; smile arc at rest */}
          <g transform="translate(180 196)">
            {!speaking && (
              <path d={warm ? "M-18 -1 Q0 11 18 -1" : probing ? "M-14 2 Q0 3.5 14 2" : "M-16 0 Q0 8 16 0"} stroke={C.teal} strokeWidth="3.5"
                    strokeLinecap="round" fill="none" opacity="0.8"
                    style={{ filter: `drop-shadow(0 0 5px ${C.teal})` }} />
            )}
            {speaking && SEG_MULT.map((m, i) => (
              <rect key={i} x={-17.5 + i * 5.4} y={-segH(m) / 2} width="3.6" height={segH(m)}
                    rx="1.8" fill={C.teal}
                    style={{ filter: `drop-shadow(0 0 5px ${C.teal})` }} />
            ))}
          </g>
        </g>

        {/* desk */}
        <rect x="8" y="404" width="344" height="46" rx="10" fill="url(#nvDesk)" />
        <rect x="8" y="404" width="344" height="4" rx="2" fill={C.gold} opacity="0.35" />
        <g transform="rotate(-3 120 416)">
          <rect x="80" y="410" width="86" height="18" rx="3" fill="#F2EEE3" />
          <rect x="88" y="415" width="60" height="1.8" fill="#9AA3B5" opacity="0.6" />
          <rect x="88" y="420" width="44" height="1.8" fill="#9AA3B5" opacity="0.45" />
        </g>
        <g opacity="0.9">
          <rect x="292" y="384" width="26" height="34" rx="4" fill="#8FB4D9" opacity="0.35" />
          <rect x="292" y="398" width="26" height="20" rx="4" fill="#B7D2EA" opacity="0.4" />
          <rect x="292" y="384" width="26" height="34" rx="4" fill="none" stroke="#C9DCEE" strokeWidth="1.4" opacity="0.6" />
        </g>
      </svg>
    </div>
  );
}