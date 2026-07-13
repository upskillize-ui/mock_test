import { useEffect, useRef, useState } from "react";

/**
 * Lobby — the pre-join "green room" (Interview Room, Phase A).
 *
 * ONE permission moment: a single getUserMedia({audio, video}) call, made only AFTER
 * the learner has read our own pre-prompt card explaining what each device is for.
 * The browser's own permission dialog is never the first thing they see.
 *
 * PRIVACY (non-negotiable):
 *   The camera stream is LOCAL ONLY. It is rendered into a muted <video> for preview
 *   and NEVER recorded, captured to canvas, uploaded, or transmitted. There is no
 *   MediaRecorder on the video track anywhere in this file.
 *   The mic stream here is used ONLY to drive a live level meter (so the learner can
 *   see their mic works). It is torn down before Join; answer capture happens later,
 *   through the existing STT pipeline (transcribe-and-discard), untouched.
 *
 * NEVER HARD-BLOCK: if the learner denies video we continue audio-only; if they deny
 * everything we still let them join in TYPE-ONLY mode. The interview always happens.
 *
 * onJoin({ mic, camera }) — we hand the room the CHOICES, not the streams. The room
 * re-acquires devices itself, so the existing voice pipeline is not disturbed.
 */

const IQ = {
  navy: "#0B1628", navy2: "#1a2744", teal: "#00C4A0", gold: "#C8992A", orange: "#E8521A",
  sans: "'Plus Jakarta Sans', sans-serif",
  mono: "'DM Mono', 'SFMono-Regular', Menlo, monospace",
};

const Icon = ({ d, size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>{d}</svg>
);
const IconMic = (p) => <Icon {...p} d={<><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0" /><line x1="12" y1="17" x2="12" y2="22" /></>} />;
const IconMicOff = (p) => <Icon {...p} d={<><line x1="2" y1="2" x2="22" y2="22" /><path d="M9 9v3a3 3 0 0 0 5.1 2.1" /><path d="M15 9.3V5a3 3 0 0 0-5.9-.7" /><path d="M5 10a7 7 0 0 0 10.7 6" /><line x1="12" y1="19" x2="12" y2="22" /></>} />;
const IconCam = (p) => <Icon {...p} d={<><path d="M23 7l-7 5 7 5V7z" /><rect x="1" y="5" width="15" height="14" rx="2" /></>} />;
const IconCamOff = (p) => <Icon {...p} d={<><line x1="2" y1="2" x2="22" y2="22" /><path d="M16 16H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2" /><path d="M10 5h4a2 2 0 0 1 2 2v3l5-3.5v9" /></>} />;
const IconKeyboard = (p) => <Icon {...p} d={<><rect x="2" y="6" width="20" height="12" rx="2" /><line x1="8" y1="14" x2="16" y2="14" /><line x1="6" y1="10" x2="6" y2="10" /><line x1="10" y1="10" x2="10" y2="10" /><line x1="14" y1="10" x2="14" y2="10" /><line x1="18" y1="10" x2="18" y2="10" /></>} />;

// [PENDING LEGAL REVIEW] — draft lobby consent copy. Do not ship without legal sign-off.
const CONSENT_COPY =
  "Your mic converts answers to text — audio is never stored. Your camera stays on your " +
  "device — never recorded or uploaded. You can type instead at any time.";
// [PENDING LEGAL REVIEW] — shown only when the camera is part of the choice.
const CONSENT_COPY_CAMERA =
  "During the interview, InterviewIQ notices attention cues (like looking away) on your " +
  "device to coach your interview presence. No video is recorded.";

export default function Lobby({ name, role, onJoin }) {
  const [phase, setPhase] = useState("ask");     // ask | ready
  const [mic, setMic] = useState(false);
  const [camera, setCamera] = useState(false);
  const [level, setLevel] = useState(0);         // 0..1 mic meter
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const ctxRef = useRef(null);
  const rafRef = useRef(null);

  // ── Teardown. Called before Join and on unmount: the lobby must not hold the
  // camera or mic open once the room takes over.
  const teardown = () => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    if (ctxRef.current) { try { ctxRef.current.close(); } catch { /* noop */ } ctxRef.current = null; }
    const s = streamRef.current;
    if (s) { try { s.getTracks().forEach(t => t.stop()); } catch { /* noop */ } streamRef.current = null; }
    if (videoRef.current) videoRef.current.srcObject = null;
  };
  useEffect(() => teardown, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Live mic level meter — proves the mic works before they commit.
  const startMeter = (stream) => {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      ctxRef.current = ctx;
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 5));
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch { /* the meter is a nicety — never block the join on it */ }
  };

  // THE single permission moment.
  const request = async (wantCamera) => {
    setBusy(true);
    setNotice("");
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setNotice("This browser can't reach your mic or camera. You can still type your answers.");
      setMic(false); setCamera(false); setPhase("ready"); setBusy(false);
      return;
    }
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia(
        wantCamera ? { audio: true, video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" } }
          : { audio: true }
      );
    } catch {
      // Denied both, or the device is unavailable. If they asked for camera+mic, try
      // mic alone before giving up — a camera denial must not cost them the mic.
      if (wantCamera) {
        try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
        catch { stream = null; }
        if (stream) setNotice("Camera unavailable — continuing with mic only. You can still type any answer.");
      }
    }

    if (!stream) {
      // Never hard-block: they can always join and type.
      setNotice("No mic or camera access. You can still do the full interview by typing.");
      setMic(false); setCamera(false); setPhase("ready"); setBusy(false);
      return;
    }

    streamRef.current = stream;
    const hasVideo = stream.getVideoTracks().length > 0;
    const hasAudio = stream.getAudioTracks().length > 0;
    setMic(hasAudio);
    setCamera(hasVideo);
    if (hasAudio) startMeter(stream);
    setPhase("ready");
    setBusy(false);
  };

  // Attach the preview once the <video> exists.
  useEffect(() => {
    if (phase === "ready" && camera && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [phase, camera]);

  const typeOnly = () => { teardown(); setMic(false); setCamera(false); setPhase("ready"); };

  const join = () => {
    teardown();                       // hand the devices back before the room takes them
    onJoin({ mic, camera });
  };

  const initial = (name || "You").trim().charAt(0).toUpperCase() || "Y";

  return (
    <div style={{ fontFamily: IQ.sans, margin: "-24px -28px", minHeight: "calc(100vh - 70px)",
      background: IQ.navy, color: "#fff", display: "flex", alignItems: "center",
      justifyContent: "center", padding: "28px 20px" }}>
      <div style={{ width: "100%", maxWidth: 900 }}>
        <div style={{ textAlign: "center", marginBottom: 22 }}>
          <div style={{ fontSize: 22, fontWeight: 800 }}>Ready to join?</div>
          <div style={{ fontSize: 13, color: "rgba(255,255,255,.55)", marginTop: 5 }}>
            {role ? `${role} interview` : "Interview"} — check your setup before you go in.
          </div>
        </div>

        <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "stretch", justifyContent: "center" }}>
          {/* ── Preview tile ── */}
          <div style={{ flex: "1 1 380px", minWidth: 300, maxWidth: 520 }}>
            <div style={{ position: "relative", aspectRatio: "4 / 3", borderRadius: 14, overflow: "hidden",
              background: "#0a1220", border: "1px solid rgba(255,255,255,.10)",
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              {camera ? (
                // LOCAL ONLY. Muted, never recorded, never uploaded.
                <video ref={videoRef} autoPlay muted playsInline
                  style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }} />
              ) : (
                <div style={{ width: 92, height: 92, borderRadius: "50%", background: IQ.navy2,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 34, fontWeight: 800, color: "rgba(255,255,255,.85)",
                  border: "1px solid rgba(255,255,255,.12)" }}>{initial}</div>
              )}
              {phase === "ready" && !camera && (
                <div style={{ position: "absolute", bottom: 10, left: 12, fontSize: 11,
                  color: "rgba(255,255,255,.5)", fontFamily: IQ.mono }}>CAMERA OFF</div>
              )}
            </div>

            {phase === "ready" && (
              <>
                {/* Device toggles */}
                <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 14 }}>
                  <button onClick={() => (mic ? (setMic(false)) : request(camera))}
                    aria-pressed={mic} aria-label={mic ? "Turn mic off" : "Turn mic on"}
                    style={pill(mic)}>{mic ? <IconMic /> : <IconMicOff />}</button>
                  <button onClick={() => (camera ? setCamera(false) : request(true))}
                    aria-pressed={camera} aria-label={camera ? "Turn camera off" : "Turn camera on"}
                    style={pill(camera)}>{camera ? <IconCam /> : <IconCamOff />}</button>
                </div>

                {/* Mic check */}
                <div style={{ marginTop: 14, textAlign: "center" }}>
                  <div style={{ fontSize: 12, color: "rgba(255,255,255,.6)", marginBottom: 7 }}>
                    {mic ? "Say something — the bar should move." : "Mic is off — you can type your answers."}
                  </div>
                  <div style={{ height: 6, borderRadius: 3, background: "rgba(255,255,255,.10)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${Math.round((mic ? level : 0) * 100)}%`,
                      background: IQ.teal, transition: "width .08s linear" }} />
                  </div>
                </div>
              </>
            )}
          </div>

          {/* ── Consent / join panel ── */}
          <div style={{ flex: "1 1 320px", minWidth: 280, maxWidth: 380, display: "flex",
            flexDirection: "column", justifyContent: "center" }}>
            <div style={{ background: "rgba(255,255,255,.05)", border: "1px solid rgba(255,255,255,.10)",
              borderRadius: 14, padding: "18px 18px" }}>
              <div style={{ fontSize: 14, fontWeight: 800, marginBottom: 8 }}>Before you join</div>
              <p style={{ fontSize: 13, lineHeight: 1.65, color: "rgba(255,255,255,.8)", margin: 0 }}>
                {CONSENT_COPY}
              </p>
              {(phase === "ask" || camera) && (
                <p style={{ fontSize: 12.5, lineHeight: 1.6, color: "rgba(255,255,255,.6)", marginTop: 10 }}>
                  {CONSENT_COPY_CAMERA}
                </p>
              )}
              <div style={{ fontSize: 10, color: "rgba(255,255,255,.35)", marginTop: 10, fontFamily: IQ.mono }}>
                DRAFT NOTICE — PENDING LEGAL REVIEW
              </div>

              {phase === "ask" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 16 }}>
                  <button onClick={() => request(true)} disabled={busy} style={btnPrimary}>
                    <IconCam size={16} /> Allow mic &amp; camera
                  </button>
                  <button onClick={() => request(false)} disabled={busy} style={btnGhost}>
                    <IconMic size={16} /> Mic only
                  </button>
                  <button onClick={typeOnly} disabled={busy} style={btnGhost}>
                    <IconKeyboard size={16} /> Type instead
                  </button>
                </div>
              ) : (
                <button onClick={join} style={{ ...btnPrimary, marginTop: 16, justifyContent: "center" }}>
                  Join interview
                </button>
              )}

              {notice && (
                <div style={{ marginTop: 12, fontSize: 12, lineHeight: 1.55, color: IQ.gold }}>{notice}</div>
              )}
              {phase === "ready" && !mic && !camera && (
                <div style={{ marginTop: 10, fontSize: 12, color: "rgba(255,255,255,.55)" }}>
                  Joining in <strong style={{ color: "#fff" }}>type-only</strong> mode — every question can be typed.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const pill = (on) => ({
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 46, height: 46, borderRadius: "50%", cursor: "pointer",
  border: "1px solid " + (on ? "rgba(255,255,255,.18)" : IQ.orange),
  background: on ? "rgba(255,255,255,.08)" : IQ.orange,
  color: "#fff", transition: "all .15s",
});

const btnPrimary = {
  display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "11px 16px",
  borderRadius: 10, border: "none", background: IQ.teal, color: IQ.navy,
  fontSize: 14, fontWeight: 800, cursor: "pointer", fontFamily: IQ.sans,
};
const btnGhost = {
  display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "11px 16px",
  borderRadius: 10, border: "1px solid rgba(255,255,255,.18)", background: "transparent",
  color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: IQ.sans,
};
