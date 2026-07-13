/**
 * focusMonitor — on-device attention signals (Interview Room, Phase C).
 *
 * SHIPPING NOW: the two signals that need NO camera and NO ML model —
 *   s4 tab_hidden   (document hidden > 2s)
 *   s5 window_blur  (window blurred > 3s, e.g. switching apps)
 * These work on every join path, including a camera-off join.
 *
 * DEFERRED: the camera signals (no_face / multiple_faces / looking_away) and the
 * Phase-D presence metrics need a face model. MediaPipe/tfjs fetch their WASM and
 * weights from a CDN at runtime, which our production CSP (script-src 'self';
 * connect-src 'self') blocks — it would pass in `vite dev` and silently do nothing
 * in production. They land once the model assets are self-hosted. See the report.
 *
 * PRIVACY: this file cannot see a camera frame. It emits STRINGS. That is the whole
 * surface — there is no image, canvas, or MediaRecorder path here, by construction.
 *
 * The client debounce (1 event per signal per 30s) is a courtesy to the network; the
 * SERVER re-applies it and is the authority, so a buggy client can't spam the ladder.
 */

export const FOCUS_DEBOUNCE_MS = 30000;
const TAB_HIDDEN_MS = 2000;
const WINDOW_BLUR_MS = 3000;

/** VITE_FOCUS_MONITOR=off disables the whole engine. */
export function focusMonitorEnabled() {
  try {
    return String(import.meta.env?.VITE_FOCUS_MONITOR || "").toLowerCase() !== "off";
  } catch {
    return true;
  }
}

/**
 * start({ onEvent }) -> stop()
 * onEvent(type) is called at most once per signal per FOCUS_DEBOUNCE_MS.
 */
export function startFocusMonitor({ onEvent }) {
  if (typeof document === "undefined" || !focusMonitorEnabled()) return () => {};

  const lastSent = {};                 // type -> timestamp
  const timers = {};                   // type -> pending timeout

  const emit = (type) => {
    const now = Date.now();
    if (lastSent[type] && now - lastSent[type] < FOCUS_DEBOUNCE_MS) return;
    lastSent[type] = now;
    try { onEvent(type); } catch { /* never let a signal break the interview */ }
  };

  // Only fire if the condition PERSISTS — a momentary alt-tab isn't drift.
  const arm = (type, delay) => {
    clearTimeout(timers[type]);
    timers[type] = setTimeout(() => emit(type), delay);
  };
  const disarm = (type) => clearTimeout(timers[type]);

  const onVisibility = () => {
    if (document.hidden) arm("tab_hidden", TAB_HIDDEN_MS);
    else disarm("tab_hidden");
  };
  const onBlur = () => arm("window_blur", WINDOW_BLUR_MS);
  const onFocus = () => disarm("window_blur");

  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("blur", onBlur);
  window.addEventListener("focus", onFocus);

  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("blur", onBlur);
    window.removeEventListener("focus", onFocus);
    Object.values(timers).forEach(clearTimeout);
  };
}
