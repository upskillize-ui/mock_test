# InterviewIQ Camera Self-View — Install (July 2026)

Adds a Google-Meet-style self-view tile to the voice stage. The camera stream
is LOCAL ONLY — rendered in the browser, never recorded, never uploaded.

## STEP 1 — Add the file

Save **SelfView.jsx** into `frontend\src\` (next to InterviewerCharacter.jsx).

## STEP 2 — Wire it into App.jsx (three edits)

### 2a. Import — Ctrl+F: `import InterviewerCharacter`

Add this line directly BELOW that import line:

```jsx
import SelfView from "./SelfView.jsx";
```

### 2b. Render — Ctrl+F: `<InterviewerPresence state={orbState}`

Add this line directly ABOVE the InterviewerPresence line (inside the
`.iq-stage` div, which is position:relative so the tile anchors to its
bottom-right corner):

```jsx
            <SelfView onEnable={() => recordConsent({ consent_type: "camera_selfview", copy_version: CONSENT_COPY_VERSION, session_id: sessionId }).catch(() => {})} />
```

That's it — the component manages its own on/off state, permission-denied
fallback, and cleanup.

## Behaviour

- Off by default. A small "Camera on" pill sits at the bottom-right of the
  stage with the notice: "Optional. Stays on your device — never recorded
  or uploaded." (draft copy — same PENDING LEGAL REVIEW gate as voice).
- On: mirrored 150×100 tile bottom-right, "You" label, one-tap off button.
- Turning it on records a `camera_selfview` consent row (non-blocking),
  same audit pattern as voice consent.
- Permission denied → clear retry guidance, never blocks the interview.
- Tracks are hard-stopped on toggle-off and on unmount — the camera light
  goes out the moment the interview screen does.
- Video only: `audio: false`, so it never touches the STT mic pipeline.

## Legal gate note

This adds a THIRD item to the Amit/legal conversation alongside the voice
consent copy: (1) voice notice, (2) session consent checkbox, (3) camera
self-view notice. All three are marked [PENDING LEGAL REVIEW] in code.

## Roadmap (not built, deliberately)

Body-language / eye-contact analysis from the camera is possible later but
is a materially bigger privacy decision (frames would need processing).
If you ever want it, it should run on-device (TensorFlow.js) with its own
consent — do not bolt it onto this component.

## Verify

1. Start a voice-stage session → "Camera on" pill appears bottom-right.
2. Tap it, allow the browser prompt → mirrored tile with "You" label.
3. Speak an answer — mic recording works simultaneously (separate streams).
4. Tap the off button → tile collapses AND the browser camera light goes out.
5. End the session mid-camera → camera light goes out.
