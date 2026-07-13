import { useEffect, useRef, useState } from "react";

/**
 * SelfView — InterviewIQ voice stage camera tile (v1)
 * ────────────────────────────────────────────────────
 * A Google-Meet-style self-view: the learner sees themselves in a small
 * mirrored tile while the interviewer speaks. Practising under the camera
 * is half of interview pressure training.
 *
 * ⚠ PRIVACY BY DESIGN — DO NOT CHANGE WITHOUT LEGAL REVIEW
 *   The camera stream is LOCAL ONLY. It renders into a muted <video>
 *   element and never leaves the browser:
 *     • No MediaRecorder in this file. Nothing is recorded.
 *     • No upload, no canvas capture, no frames sent anywhere.
 *     • Tracks are hard-stopped on toggle-off and on unmount.
 *   The notice copy below is a DRAFT — [PENDING LEGAL REVIEW], same gate
 *   as the voice consent copy.
 *
 * Props:
 *   onEnable()  optional — called once when the learner turns the camera on;
 *               wire it to recordConsent({ consent_type: "camera_selfview",
 *               copy_version, session_id }) for the audit trail (non-blocking).
 *
 * Usage (inside the voice stage, which is position:relative):
 *   <SelfView onEnable={...} />
 */

const NOTICE = "Optional. Stays on your device — never recorded or uploaded."; // [PENDING LEGAL REVIEW]

const STYLE_ID = "iq-selfview-css";
function injectCSS() {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.textContent = `
    .iqsv { position:absolute; right:16px; bottom:16px; z-index:5;
            display:flex; flex-direction:column; align-items:flex-end; gap:6px;
            font-family:'Plus Jakarta Sans', system-ui, sans-serif; }
    .iqsv-tile { position:relative; width:150px; height:100px; border-radius:12px;
            overflow:hidden; background:#0E1B30;
            border:1px solid rgba(255,255,255,.14);
            box-shadow:0 8px 24px rgba(0,0,0,.4); }
    .iqsv-tile video { width:100%; height:100%; object-fit:cover;
            transform:scaleX(-1); display:block; }   /* mirrored, like Meet */
    .iqsv-you { position:absolute; left:8px; bottom:6px; padding:2px 8px;
            border-radius:999px; background:rgba(11,22,40,.65); color:#fff;
            font-size:10px; font-weight:700; letter-spacing:.04em; }
    .iqsv-off { position:absolute; top:6px; right:6px; width:26px; height:26px;
            border-radius:8px; border:none; cursor:pointer; display:flex;
            align-items:center; justify-content:center;
            background:rgba(11,22,40,.65); color:#fff; }
    .iqsv-off:hover { background:rgba(232,82,26,.85); }
    .iqsv-btn { display:inline-flex; align-items:center; gap:8px;
            padding:8px 14px; border-radius:999px; cursor:pointer;
            border:1px solid rgba(255,255,255,.16);
            background:rgba(255,255,255,.05); color:rgba(255,255,255,.85);
            font-size:12px; font-weight:600; font-family:inherit;
            transition:all .15s; }
    .iqsv-btn:hover { background:rgba(255,255,255,.12); color:#fff; }
    .iqsv-btn:focus-visible { outline:2px solid #00C4A0; outline-offset:2px; }
    .iqsv-note { max-width:190px; text-align:right; font-size:10px;
            line-height:1.45; color:rgba(255,255,255,.45); }
    .iqsv-note--warn { color:#ffbda6; }
    @media (max-width: 560px) {
      .iqsv { right:10px; bottom:10px; }
      .iqsv-tile { width:110px; height:74px; }
      .iqsv-note { display:none; }
    }
  `;
  document.head.appendChild(s);
}

const IconCam = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M23 7l-7 5 7 5V7z" /><rect x="1" y="5" width="15" height="14" rx="2" />
  </svg>
);
const IconCamOff = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5 0h4a2 2 0 0 1 2 2v4m0 4l7 5V7l-4 2.86" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
);

export default function SelfView({ onEnable }) {
  const [status, setStatus] = useState("off");   // off | on | denied
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const enabledOnceRef = useRef(false);

  useEffect(injectCSS, []);

  const stop = () => {
    const s = streamRef.current;
    if (s) { try { s.getTracks().forEach(t => t.stop()); } catch { /* noop */ } }
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  const turnOn = async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setStatus("denied"); return;
    }
    try {
      // Video only — the mic pipeline stays fully owned by the STT flow.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false,
      });
      streamRef.current = stream;
      setStatus("on");
      if (!enabledOnceRef.current) {
        enabledOnceRef.current = true;
        try { onEnable && onEnable(); } catch { /* non-blocking audit hook */ }
      }
    } catch {
      setStatus("denied");
    }
  };

  const turnOff = () => { stop(); setStatus("off"); };

  // Attach the stream once the <video> exists.
  useEffect(() => {
    if (status === "on" && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [status]);

  // Hard cleanup on unmount — the camera light must go out when the
  // interview screen goes away, no exceptions.
  useEffect(() => () => stop(), []);

  if (status === "on") {
    return (
      <div className="iqsv">
        <div className="iqsv-tile">
          <video ref={videoRef} autoPlay muted playsInline />
          <span className="iqsv-you">You</span>
          <button className="iqsv-off" onClick={turnOff}
                  title="Turn camera off" aria-label="Turn camera off">
            <IconCamOff />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="iqsv">
      <button className="iqsv-btn" onClick={turnOn} aria-label="Turn camera on">
        <IconCam /> {status === "denied" ? "Retry camera" : "Camera on"}
      </button>
      <div className={"iqsv-note" + (status === "denied" ? " iqsv-note--warn" : "")}>
        {status === "denied"
          ? "Camera blocked — allow it in your browser's site permissions, then retry."
          : NOTICE}
      </div>
    </div>
  );
}