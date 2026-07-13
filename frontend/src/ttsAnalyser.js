/**
 * TTS audio analyser — taps the shared <audio> element so the interviewer character's
 * mouth can follow the ACTUAL voice (live RMS), not a fake loop.
 *
 * This used to live inside InterviewerCharacter.jsx. It now stands alone so the
 * character component is purely presentational (it just takes an `amplitude` prop) and
 * can be redesigned or swapped for a vendor avatar without dragging the audio graph
 * along with it.
 *
 * Two hard constraints:
 *   1. createMediaElementSource() may be called only ONCE per element, and from then on
 *      the element's audio flows ONLY through the graph — so we MUST connect to
 *      destination, or playback goes silent.
 *   2. The context starts suspended in browsers. We therefore wire it from a user
 *      gesture (the Start button) and resume() defensively on every play.
 * If anything throws we leave the element completely untouched: audio keeps working and
 * the mouth simply doesn't sync.
 */
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

/** RMS normalised to the 0..1 the character's mouth expects. */
export function ttsAmplitude() {
  const rms = ttsLevel();
  if (rms == null) return 0;
  return Math.min(1, rms * 4.5);
}
