# InterviewIQ — Voice Stage Report (two-way conversation mode)

A call-like **presentation mode over the existing state machine**. Stages, ratings,
consent, scoring, delivery metrics and the STT format handling are **unchanged** —
this sprint added no backend code and no new frontend dependencies.

---

## 0. Prerequisite gate (STT last-mile) — PASSED before any stage work

`scripts/e2e_smoke.py`, including the browser-shaped webm/opus step, run against a live backend:

```
PASS step 0: GET /dev/login -> 302, token handed off to 'http://localhost:5173/' via fragment
PASS step 1: POST /session/start -> 200, session_id=7f23a58e-...
PASS step 2: GET /session/{id}/state -> 200, current_stage=WARMUP
PASS step 3: POST /consent (voice_recording) -> 200
PASS step 4: POST /session/stt (webm;codecs=opus) -> 200, transcript='So basically, um, I led the migration and it took about 3 weeks.'
ALL STEPS PASS
```

---

## 1. What shipped

### The stage (replaces the chat log while in voice mode)
- **The orb** — CSS-only: breathing teal sphere, rotating conic-gradient aurora, two
  counter-rotating rings, soft halo. State drives it:
  **SPEAKING** = faster pulse + teal glow + waveform bars below;
  **THINKING** = slow shimmer sweep + `Thinking` mono label;
  **LISTENING** = orb recedes (the learner has the floor — orange never touches the orb);
  **IDLE** = gentle breathe. Every state also renders a **persistent text label**, so
  meaning never rests on colour or motion alone.
- **The learner strip** — while LISTENING, a **live waveform driven by real mic input**
  via a Web Audio `AnalyserNode` (not a fake animation), an elapsed timer in DM Mono, an
  orange recording ring, and tap-to-stop. Idle = a subtle mic pill.
- **No chat bubbles.** The question is spoken, with **optional one-line captions**
  (default ON) under the orb, and the full conversation lives in a **transcript drawer**
  (side sheet ≥760px, bottom sheet below) that opens any time and **auto-opens at the
  rating widget and the readout**.
- **Header** keeps the round beam, telemetry (timer), mute/replay and End; the state chip
  is **removed on the stage** (the orb is the state). Added: a transcript button and a
  voice-settings menu.

### The two-way flow
1. IQ's audio plays → orb SPEAKING.
2. On the audio element's `ended`: if **auto-listen** is on **and consent is already
   granted**, a **600 ms grace beat** runs (soft countdown on the mic pill) and the mic
   opens. **Instant cancel** by tapping the pill or pressing **Esc**.
3. Learner stops via tap, the **3-minute cap**, or **2.5 s trailing-silence detection**
   (RMS via the AnalyserNode). Silence auto-stop only applies in auto-listen mode, and
   only *after* they have actually spoken — so the thinking pause before an answer never
   cuts them off.
4. → THINKING → the transcript returns into an **inline review card** ("Here's what I
   heard — edit if needed") with **Send** and **Edit**, plus a **visible 6 s countdown**
   that auto-sends only if untouched. Any edit pauses it. Review stays mandatory (our STT
   design: nothing is ever sent unseen); the countdown just automates the common case.
5. The **rating widget renders on the stage** (same component, centred, drawer behind).
6. **Typed fallback is always one tap away** (keyboard icon swaps in the composer without
   leaving voice mode) and **engages automatically whenever STT returns null**, reusing the
   existing graceful-fallback toast.

### Settings (header menu) — all persisted
Voice mode on/off, Auto-listen on/off (default on), Captions on/off (default on), and the
interviewer voice picker. Voice mode defaults **ON when voice is available**.

### Accessibility
Captions default on; `prefers-reduced-motion` **collapses the orb to a static,
state-coloured ring** (all orb/bar animation disabled); every control is keyboard-reachable
(`role="switch"`, Esc closes the drawer/menu and cancels listening); state labels persist so
colour is never the only signal.

### Tokens / tech
Existing brand palette only — **teal** = IQ speaking/intelligence, **orange** = recording
*only*, **gold** = progress/rating. No emojis; Lucide-style inline SVGs at 1.6px. All
animation is `transform`/`opacity`; every loop is under 2s. **No new dependencies.**
MediaRecorder's mimeType choice is untouched (the STT fix normalizes it server-side).

---

## 2. Regression proof

- **Toggle voice mode OFF → exactly today's UI.** The classic chat log + composer JSX is
  rendered unchanged in the `else` branch; the state chip returns; the mic button behaves
  as before. The only header addition when voice is available is the settings/transcript
  buttons (needed to turn the mode back on).
- **Backend untouched this sprint** — no files under `backend/` or `db/` were changed for
  the stage. Backend suite still **70/70 green**; `vite build` passes.
- Leaving voice mode with a transcript still in the review card **carries the text into the
  classic composer** rather than dropping it.

---

## 3. Manual UAT script

Pre-req: `TTS_ENABLED`, `STT_ENABLED`, `VOICE_ENABLED` on; mic-equipped device;
Chrome/Edge/Firefox. Open `http://localhost:8000/dev/login` to land logged in, start a session.

1. **Full hands-free loop** — the orb speaks the greeting (SPEAKING, bars animate). On the
   first mic use accept the consent modal. After IQ stops, the pill shows *"Listening in
   0.6s"*, the mic opens (LISTENING, live waveform tracks your actual voice), you answer,
   pause → it auto-stops → THINKING → the review card shows your transcript → leave it alone
   → it auto-sends at the end of the 6s countdown → the next question plays. **Repeat with no
   clicks at all.** ✅
2. **Cancel mid-listen** — during the grace beat, tap the pill (or press **Esc**): listening
   is cancelled immediately and nothing records. Then tap the mic to record manually. ✅
3. **Silence auto-stop** — start speaking, then stop talking and wait ~2.5s: recording ends
   by itself. Confirm a *thinking pause before you start speaking* does **not** end it. ✅
4. **Hinglish answer** — speak a code-mixed answer (e.g. *"Basically maine team ko lead kiya,
   um, jab deadline miss ho rahi thi, so I restructured the sprint"*). The transcript appears
   in the review card and is editable before Send. ✅
5. **Captions toggle** — settings menu → Captions off: the caption line under the orb
   disappears; on: it returns. ✅
6. **Transcript drawer** — tap the transcript icon: side sheet (desktop) / bottom sheet
   (narrow) with the full conversation, Spoken/Typed tags, Esc closes. ✅
7. **Rating on the stage** — after a scored answer, the 1–5 widget appears centred on the
   stage and the drawer auto-opens behind it. Rating advances the round as before. ✅
8. **Typed fallback on STT failure** — deny mic permission, or point `SARVAM_API_KEY` at an
   invalid value: the *"Voice input unavailable — please type your answer"* toast fires and
   the composer **swaps in automatically**, still inside voice mode. The "Voice" button
   returns you to speaking. ✅
9. **Reduced motion** — enable OS "reduce motion": the orb collapses to a static ring that is
   teal (speaking) / gold (thinking) / orange (listening); labels still say the state. ✅
10. **360px mobile** — the orb scales down, the drawer becomes a bottom sheet, the header
    wraps, and nothing clips or scrolls horizontally. ✅
11. **Toggle OFF** — settings → Voice mode off: the session returns to **exactly** the
    classic chat + composer UI. ✅

---

## 4. Known gaps / decisions

- **Auto-listen requires consent to already exist.** We never open the mic implicitly on a
  learner who hasn't granted `voice_recording` — the first mic use is always an explicit tap
  → consent modal. After that, auto-listen runs hands-free for the session.
- **Silence threshold is fixed** (RMS 0.018 / 2.5s). It is not adaptive to room noise; a very
  loud room may not trigger the auto-stop (tap-to-stop always works). Worth calibrating from
  UAT before tuning.
- **Captions show the question text, not live word-by-word captions** — the TTS vendor gives
  no word timing, so the caption is the full question line, shown while it is spoken.
- **The orb is CSS-only by design** (no canvas/WebGL), per the "no new deps + reskin without
  relayout" constraint. The full orb/waveform art direction lands in the dual-theme redesign;
  this is structured on tokens so that reskin is colour-only.
- The header gains a settings/transcript button whenever voice is available — this is the one
  intentional deviation from "byte-identical" classic UI, since the toggle needs a home.
