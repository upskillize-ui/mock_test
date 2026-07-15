# InterviewIQ Robot Roster — Install (July 2026)

Prerequisite: the earlier PATCH_STEPS.md edits (consent modal, caption font fix)
are independent of this — do them too if you haven't.

## STEP 1 — Place the images

Copy the whole `interviewers` folder (4 PNGs) into `frontend\src\` so you have:

```
frontend\src\interviewers\mira_warm_female.png
frontend\src\interviewers\veda_formal_female.png
frontend\src\interviewers\neo_warm_male.png
frontend\src\interviewers\rex_stern_male.png
```

Names must match exactly — the component imports them by these names.

## STEP 2 — Swap the character file

Open `frontend\src\InterviewerCharacter.jsx`, select all, delete, paste the
full contents of the new **InterviewerCharacter.jsx** from this folder, save.

This alone already works: the character picks by voice, with a daily-rotating
default. Step 3 upgrades it to per-session, difficulty-aware selection.

## STEP 3 — Wire difficulty + session (App.jsx, two tiny edits)

### 3a. Ctrl+F: `function InterviewerPresence`

Replace the whole function (it's 8 lines) with:

```jsx
function InterviewerPresence({ state, voice, difficulty, seed }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
      <InterviewerCharacter state={state} voice={voice} size={220}
        difficulty={difficulty} seed={seed} />
      <div className="iq-stage-label" role="status" aria-live="polite">{STATE_LABEL[state]}</div>
    </div>
  );
}
```

### 3b. Ctrl+F: `<InterviewerPresence state={orbState}`

Replace that line with:

```jsx
            <InterviewerPresence state={orbState} voice={voicePref}
              difficulty={config.difficulty} seed={sessionId} />
```

## How selection works (v4.2 — six Indian human interviewers, robots removed)

These SIX PNGs go in `frontend\src\interviewers\` (exact names, as delivered).
The four robot PNGs from v4.1 are no longer imported — delete them from the
folder (or leave them; unused files are harmless but Vite bundles nothing).

| Character | Voice | Shows up for difficulty |
|---|---|---|
| Priya (warm, hair down) | Female | Easy, Realistic |
| Ananya (friendly) | Female | Easy |
| Kavya (composed, hair back) | Female | Realistic, Stretch |
| Meera (confident) | Female | Realistic, Stretch |
| Arjun (approachable, grey suit) | Male | Easy, Realistic |
| Vikram (formal, dark suit) | Male | Realistic, Stretch |

Speaking is shown video-call style: the card frame glows and a live waveform
badge pulses under the portrait, driven by the real Bulbul amplitude. Thinking
keeps the rotating teal arc; listening keeps the soft pulse. Every voice x
difficulty pool has 1–2 options, so Realistic sessions rotate faces.

The robot designs (Mira, Veda, Neo, Rex) remain saved in your Canva account —
useful for marketing or an "AI interviewer" mode later.

The pick is seeded by the session ID: random-feeling across sessions, but the
SAME interviewer survives a mid-interview refresh — matching how the improvised
identity persists via migration 005. Realistic difficulty has two options per
voice, so back-to-back Realistic sessions usually rotate faces.

## Expression system (no extra images needed)

- SPEAKING — LED voice-bar over the mouth + eye glow, driven by live Bulbul
  amplitude through the same wireTtsAnalyser plumbing as before
- THINKING — teal arc rotates around the card, eyes pulse slowly
- LISTENING — soft pulse ring, slight lean-in
- IDLE — calm resting glow

## Calibration (optional)

If a glow spot sits slightly off an eye, open InterviewerCharacter.jsx, find
that character in ROSTER, and nudge its `eyes` / `mouth` x,y values (fractions
of card width/height; ±0.02 steps). Save — Vite hot-reloads instantly.

## Growing the roster later

Generate a new portrait in Canva (the alternates from today's generation jobs
are still in your Canva account), export PNG into `src\interviewers\`, add one
entry to ROSTER with voice, temperaments, eye/mouth coords. Nothing else.

## Verify

1. `npm run dev`, hard refresh, start a session with Female voice + Easy —
   expect Mira. End it, start Male + Stretch — expect Rex.
2. While she speaks, the LED bar and eyes should move with the audio.
3. During "Thinking", the teal arc should rotate around the card.
4. Refresh mid-interview — same interviewer should return.
