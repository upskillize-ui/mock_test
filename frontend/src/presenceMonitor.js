/**
 * presenceMonitor — on-device MediaPipe glue for the Phase-D presence metrics (m1–m8).
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * PRIVACY — DO NOT WEAKEN WITHOUT LEGAL REVIEW
 *   Frames are COMPUTED AND DISCARDED. Each animation frame we hand the <video>
 *   element to MediaPipe, read a handful of derived numbers off the result, fold them
 *   into the accumulator, and let the frame go. Nothing is captured to a canvas, kept
 *   in an array, uploaded, or drawn anywhere. The ONLY thing that ever leaves this
 *   module is the eight numbers returned by stop() — and the ONLY thing that ever
 *   leaves the client is those eight numbers, posted once at session close.
 *
 * SELF-HOSTED ASSETS (D1)
 *   The WASM runtime and the .task models are served from OUR origin (/mediapipe/…),
 *   never a CDN. The strict production CSP (script-src 'self' 'wasm-unsafe-eval';
 *   connect-src 'self'; worker-src 'self' blob:) allows exactly this and nothing more.
 *
 * DARK BY DEFAULT (D7)
 *   Gated by VITE_PRESENCE_METRICS. Off (the default) → isPresenceMonitorEnabled() is
 *   false, the caller never imports MediaPipe, and not a single frame is processed.
 *
 * FAILURE IS A NON-EVENT (D6)
 *   Assets missing, model load throws, WebGL unavailable, camera off — any failure
 *   resolves to a monitor whose stop() returns null. null means "send nothing", the
 *   readout shows the no-data line, and the session is scored EXACTLY as if presence
 *   metrics did not exist. A broken detector never harms an interview.
 *
 * BEHAVIOUR, NEVER EMOTION
 *   We derive observable facts (gaze direction, head pose spread, blink edges, smile
 *   blendshape, framing, posture lean, hand movement). No emotion is inferred here or
 *   anywhere downstream — the words come from app/presence.py, which is emotion-linted.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { createPresenceAccumulator } from "./presenceMetrics.js";

/** VITE_PRESENCE_METRICS=on turns the feature on. Anything else (incl. unset) = dark. */
export function isPresenceMonitorEnabled() {
  try {
    return String(import.meta.env?.VITE_PRESENCE_METRICS || "").toLowerCase() === "on";
  } catch {
    return false;
  }
}

// Self-hosted asset locations (served same-origin from /public/mediapipe).
const WASM_BASE = "/mediapipe/wasm";
const FACE_MODEL = "/mediapipe/face_landmarker.task";
const POSE_MODEL = "/mediapipe/pose_landmarker_lite.task";

// Thresholds for turning a frame into a behaviour observation. Heuristic — these numbers
// are reported as behaviour, never scored, so they are tuned for "did this roughly happen".
const GAZE_YAW_DEG = 22;      // |head yaw| under this, looking roughly at the screen
const GAZE_PITCH_DEG = 18;    // |head pitch| under this, looking roughly at the screen
const SMILE_ON = 0.4;         // mean smile blendshape above this = smiling
const BLINK_ON = 0.5;         // eyeBlink blendshape above this = eye closed
const LEAN_ON = 0.14;         // shoulder-midpoint drift from baseline that counts as a lean
const LEAN_DEBOUNCE_MS = 3000;// one lean event at most this often (a held slouch is 1 event)
const GESTURE_SPEED = 0.03;   // normalised wrist speed above this = a hand gesture this frame

// A monitor whose stop() yields null — the value of every no-op / failure path.
function nullMonitor() {
  return { stop: async () => null };
}

/**
 * startPresenceMonitor(videoEl, { signal }) -> Promise<{ stop }>
 *
 * Resolves to a live monitor, or a nullMonitor() if anything at all goes wrong. stop()
 * ends the loop and returns the eight numbers (or null when nothing was measured).
 */
export async function startPresenceMonitor(videoEl, opts = {}) {
  if (!isPresenceMonitorEnabled()) return nullMonitor();
  if (typeof window === "undefined" || !videoEl) return nullMonitor();

  let vision, FaceLandmarker, PoseLandmarker, FilesetResolver;
  try {
    // Dynamic import so MediaPipe is NEVER pulled into the main bundle while dark, and a
    // missing package cannot break the build for everyone else.
    ({ FaceLandmarker, PoseLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision"));
    vision = await FilesetResolver.forVisionTasks(WASM_BASE);
  } catch (e) {
    // Assets not self-hosted yet, or package absent → silent no-op. This is the exact
    // "MediaPipe failed to load → degrade to Audio behaviour, no penalty" path.
    return nullMonitor();
  }

  let face = null, pose = null;
  try {
    face = await FaceLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: FACE_MODEL },
      runningMode: "VIDEO",
      numFaces: 1,
      outputFaceBlendshapes: true,
      outputFacialTransformationMatrixes: true,
    });
  } catch {
    face = null;
  }
  try {
    pose = await PoseLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: POSE_MODEL },
      runningMode: "VIDEO",
      numPoses: 1,
    });
  } catch {
    pose = null;
  }
  if (!face && !pose) return nullMonitor();

  const acc = createPresenceAccumulator();
  let running = true;
  let startedAt = null;         // first successful frame timestamp (perf clock)
  let lastAt = null;
  let leanBaseline = null;      // first-seen shoulder midpoint x, the "sitting normally" ref
  let lastLeanEventAt = -Infinity;
  let prevWrist = null;         // previous-frame wrist positions, for gesture speed
  const poseRan = { value: false };

  const now = () => (window.performance?.now ? window.performance.now() : 0);

  const readFace = (ts) => {
    let res;
    try { res = face.detectForVideo(videoEl, ts); } catch { return null; }
    const sample = { hasFace: false };
    if (!res || !res.faceLandmarks || res.faceLandmarks.length === 0) return sample;
    sample.hasFace = true;

    // Head pose (yaw/pitch) from the 4x4 facial transformation matrix (column-major).
    const mat = res.facialTransformationMatrixes?.[0]?.data;
    if (mat && mat.length >= 16) {
      const yaw = Math.atan2(mat[8], mat[10]) * 180 / Math.PI;
      const pitch = Math.atan2(-mat[9], Math.hypot(mat[8], mat[10])) * 180 / Math.PI;
      sample.headYaw = yaw;
      sample.headPitch = pitch;
      sample.gazeOnScreen = Math.abs(yaw) <= GAZE_YAW_DEG && Math.abs(pitch) <= GAZE_PITCH_DEG;
    }

    // Blendshapes: blink edges, smile, and an aggregate "expression activation" for range.
    const shapes = res.faceBlendshapes?.[0]?.categories;
    if (shapes) {
      const get = (name) => shapes.find((c) => c.categoryName === name)?.score || 0;
      const blinkNow = (get("eyeBlinkLeft") + get("eyeBlinkRight")) / 2 > BLINK_ON;
      // Count a blink on the CLOSING edge (open -> closed), once per blink.
      sample.blink = blinkNow && !readFace._eyeClosed;
      readFace._eyeClosed = blinkNow;
      sample.smiling = (get("mouthSmileLeft") + get("mouthSmileRight")) / 2 > SMILE_ON;
      // Expression activation: how much the face is doing right now (brows, smile, jaw,
      // squint). Its spread over the session becomes m4 (range) — never an emotion label.
      sample.expression = Math.min(1,
        get("browInnerUp") + get("jawOpen")
        + (get("mouthSmileLeft") + get("mouthSmileRight")) / 2
        + (get("eyeSquintLeft") + get("eyeSquintRight")) / 2);
    }

    // Framing: nose (landmark 1) near the centre of the frame.
    const nose = res.faceLandmarks[0]?.[1];
    if (nose) {
      sample.centered = Math.abs(nose.x - 0.5) < 0.2 && Math.abs(nose.y - 0.5) < 0.28;
    }
    return sample;
  };

  const readPose = (ts, sample) => {
    let res;
    try { res = pose.detectForVideo(videoEl, ts); } catch { return; }
    const lm = res?.landmarks?.[0];
    if (!lm) return;
    poseRan.value = true;
    // Posture lean: horizontal drift of the shoulder midpoint from its first-seen position.
    const ls = lm[11], rs = lm[12];   // left/right shoulder
    if (ls && rs) {
      const mid = (ls.x + rs.x) / 2;
      if (leanBaseline == null) leanBaseline = mid;
      else if (Math.abs(mid - leanBaseline) > LEAN_ON && ts - lastLeanEventAt > LEAN_DEBOUNCE_MS) {
        acc.addPostureEvent();
        lastLeanEventAt = ts;
      }
    }
    // Gesture: wrist movement between frames (normalised coords), a per-frame boolean.
    const lw = lm[15], rw = lm[16];   // left/right wrist
    if (lw && rw) {
      if (prevWrist) {
        const d = Math.hypot(lw.x - prevWrist.lx, lw.y - prevWrist.ly)
                + Math.hypot(rw.x - prevWrist.rx, rw.y - prevWrist.ry);
        if (d > GESTURE_SPEED) sample.gesturing = true;
      }
      prevWrist = { lx: lw.x, ly: lw.y, rx: rw.x, ry: rw.y };
    }
  };

  const tick = () => {
    if (!running) return;
    // Only when the video actually has pixels this frame — before that, MediaPipe throws.
    if (videoEl.readyState >= 2 && videoEl.videoWidth > 0) {
      const ts = now();
      // MediaPipe requires strictly increasing timestamps; guard against a stalled clock.
      if (lastAt == null || ts > lastAt) {
        lastAt = ts;
        if (startedAt == null) startedAt = ts;
        const sample = face ? readFace(ts) : { hasFace: false };
        if (pose) readPose(ts, sample);
        acc.addFrame(sample);   // fold, then the frame is gone
      }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  // Belt-and-braces: an abort signal (e.g. the tile unmounting) stops the loop.
  if (opts.signal) {
    try { opts.signal.addEventListener("abort", () => { running = false; }, { once: true }); }
    catch { /* no signal support -> stop() still works */ }
  }

  return {
    async stop() {
      running = false;
      const elapsed = startedAt != null && lastAt != null ? lastAt - startedAt : 0;
      const out = acc.result(elapsed);
      try { face?.close(); } catch { /* noop */ }
      try { pose?.close(); } catch { /* noop */ }
      if (out && !poseRan.value) {
        // Pose never produced a read → m3 (posture) and m7 (gestures) were not measured.
        // Omit them rather than report a misleading 0 ("settled", "hands still").
        delete out.m3;
        delete out.m7;
      }
      return out;
    },
  };
}
