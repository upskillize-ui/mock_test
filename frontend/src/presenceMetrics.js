/**
 * presenceMetrics — the pure fold from per-frame observations to the eight numbers
 * m1–m8 (Interview Room, Phase D).
 *
 * PRIVACY BY CONSTRUCTION: this module never touches a camera frame, a canvas, or a
 * MediaPipe landmark. It receives ALREADY-DERIVED per-frame observations (a handful of
 * booleans and small numbers), folds them incrementally, and returns eight numbers. The
 * frames are consumed and discarded upstream in presenceMonitor; nothing here retains one.
 * There is deliberately no array of frames — the accumulator holds running sums only.
 *
 * BEHAVIOUR, NEVER EMOTION: the outputs are ratios and counts of observable behaviour
 * (looked at the screen, held the head steady, changed posture). This file assigns no
 * meaning to them — the behaviour sentences live server-side in app/presence.py, linted
 * for emotion words. m1–m8 are the same ids the server and the report use.
 *
 * REPORT-ONLY: these numbers never reach a score. They exist to render the Presence
 * Profile and nothing else.
 *
 * Deliberately React-free and dependency-free so it runs under `node --test`.
 */

const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

// Scales that map raw dispersion onto [0,1]. Heuristic and deliberately gentle — these
// numbers are shown as behaviour, never scored, so precision beyond "did this mostly
// happen" is false confidence. Tuned once the feature is un-darkened against real users.
const HEAD_STABLE_DEG = 18;   // std of yaw+pitch (deg) at/above which "steady" is fully lost
const EXPR_RANGE_SCALE = 0.14; // std of expression activation that reads as a full range
const BLINK_MIN_PER_MIN = 6;   // below this, blink rate reads as unusually low
const BLINK_MAX_PER_MIN = 32;  // above this, unusually high; between = steady/natural

/**
 * createPresenceAccumulator() -> { addFrame, addPostureEvent, frameCount, result }
 *
 * addFrame(sample): fold one frame's observations. `sample` fields (all optional):
 *   hasFace       bool    — a single clear face was detected this frame
 *   gazeOnScreen  bool    — gaze fell within the screen (m1)
 *   headYaw       number  — head yaw in degrees (m2 dispersion)
 *   headPitch     number  — head pitch in degrees (m2 dispersion)
 *   expression    number  — aggregate facial activation 0..1 (m4 dispersion)
 *   smiling       bool    — a smile blendshape was active (m5)
 *   blink         bool    — true on the frame a blink COMPLETED (m6 rate)
 *   gesturing     bool    — hand movement above a threshold (m7)
 *   centered      bool    — face centred in the frame (m8)
 *
 * addPostureEvent(): the monitor edge-detects a lean/slouch (debounced) and calls this
 *   once per event (m3). Kept separate from addFrame so a sustained slouch is ONE event,
 *   not one-per-frame.
 *
 * result(elapsedMs): the eight numbers, or null when there was nothing to measure (no
 * frame ever saw a face). null means "send nothing" — the readout then shows the no-data
 * line, which is never a penalty.
 */
export function createPresenceAccumulator() {
  let frames = 0;         // total frames folded
  let faceFrames = 0;     // frames with a clear face (the denominator for face metrics)
  let gazeOn = 0;
  let smiling = 0;
  let centered = 0;
  let gesturing = 0;
  let blinks = 0;
  let postureEvents = 0;

  // Running mean/variance via sum + sum of squares (no frame array retained).
  let yawS = 0, yawSq = 0, poseN = 0;
  let pitchS = 0, pitchSq = 0;
  let exprS = 0, exprSq = 0, exprN = 0;

  const std = (s, sq, n) => {
    if (n < 2) return 0;
    const v = sq / n - (s / n) * (s / n);
    return v > 0 ? Math.sqrt(v) : 0;
  };

  return {
    addFrame(sample) {
      if (!sample || typeof sample !== "object") return;
      frames += 1;
      if (sample.gesturing) gesturing += 1;   // gesture is measured whether or not a face is seen
      if (!sample.hasFace) return;             // face metrics need a face in frame
      faceFrames += 1;
      if (sample.gazeOnScreen) gazeOn += 1;
      if (sample.smiling) smiling += 1;
      if (sample.centered) centered += 1;
      if (sample.blink) blinks += 1;
      if (typeof sample.headYaw === "number" && typeof sample.headPitch === "number") {
        yawS += sample.headYaw; yawSq += sample.headYaw * sample.headYaw;
        pitchS += sample.headPitch; pitchSq += sample.headPitch * sample.headPitch;
        poseN += 1;
      }
      if (typeof sample.expression === "number") {
        exprS += sample.expression; exprSq += sample.expression * sample.expression;
        exprN += 1;
      }
    },

    addPostureEvent() { postureEvents += 1; },

    get frameCount() { return frames; },
    get faceFrameCount() { return faceFrames; },

    result(elapsedMs) {
      if (faceFrames === 0) return null;   // nothing was ever measured

      // m2: dispersion of head pose -> steadiness. More spread = less steady.
      const poseStd = std(yawS, yawSq, poseN) + std(pitchS, pitchSq, poseN);
      const m2 = clamp01(1 - poseStd / HEAD_STABLE_DEG);

      // m4: dispersion of expression activation -> range. More spread = more range.
      const m4 = clamp01(std(exprS, exprSq, exprN) / EXPR_RANGE_SCALE);

      // m6: blink rate mapped to a "steady/natural" band. Extremes (very low or very
      // high) read as uneven; the middle reads as steady. Needs elapsed wall time.
      const minutes = Math.max(1e-6, (elapsedMs || 0) / 60000);
      const perMin = blinks / minutes;
      let m6;
      if (perMin >= BLINK_MIN_PER_MIN && perMin <= BLINK_MAX_PER_MIN) {
        m6 = 1;
      } else if (perMin < BLINK_MIN_PER_MIN) {
        m6 = clamp01(perMin / BLINK_MIN_PER_MIN);
      } else {
        m6 = clamp01(1 - (perMin - BLINK_MAX_PER_MIN) / BLINK_MAX_PER_MIN);
      }

      return {
        m1: round4(gazeOn / faceFrames),
        m2: round4(m2),
        m3: postureEvents,
        m4: round4(m4),
        m5: round4(smiling / faceFrames),
        m6: round4(m6),
        m7: round4(gesturing / Math.max(1, frames)),
        m8: round4(centered / faceFrames),
      };
    },
  };
}

const round4 = (x) => Math.round(clamp01(x) * 10000) / 10000;
