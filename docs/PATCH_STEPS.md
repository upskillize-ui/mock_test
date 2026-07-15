# InterviewIQ UI Patch — App.jsx + fonts (July 2026)

Three edits in `frontend\src\App.jsx`, one line in `frontend\index.html`,
one full-file swap of `frontend\src\InterviewerCharacter.jsx`.
Do them in order, save, then restart `npm run dev`.

---

## STEP 1 — Swap the character file

Open `frontend\src\InterviewerCharacter.jsx`, select all (Ctrl+A), delete,
paste the full contents of the new **InterviewerCharacter.jsx** delivered
alongside this patch, save. No App.jsx changes needed — the new file keeps
the same exports (`wireTtsAnalyser`, `resumeTtsAnalyser`) and props.

---

## STEP 2 — Font for Hinglish captions (index.html)

Open `frontend\index.html`. Inside `<head>`, on the line after the existing
Google Fonts `<link>` tags, add:

```html
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600&display=swap" rel="stylesheet">
```

---

## STEP 3 — Fix the caption CSS (App.jsx, inside the `const CSS = \`` block)

### 3a. Press Ctrl+F, search for:  `.iq-caption{`

Replace that ENTIRE line with:

```
  .iq-caption{max-width:640px;text-align:center;color:rgba(255,255,255,.92);font-size:15px;line-height:1.5;font-family:'Plus Jakarta Sans','Noto Sans Devanagari','Noto Sans',sans-serif;overflow:hidden;overflow-wrap:anywhere;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;animation:iqRise .3s ease}
```

### 3b. Press Ctrl+F, search for:  `.iq-heard{`

Replace that ENTIRE line (keep the comment line above it) with:

```
  .iq-heard{max-width:640px;text-align:center;color:rgba(255,255,255,.92);font-size:14px;line-height:1.55;font-family:'Plus Jakarta Sans','Noto Sans Devanagari','Noto Sans',sans-serif;padding:10px 16px;border-radius:12px;background:rgba(0,196,160,.10);border:1px solid rgba(0,196,160,.35);overflow:hidden;overflow-wrap:anywhere;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;animation:iqRise .25s ease}
```

Why: the transcript can contain Devanagari, which 'Plus Jakarta Sans' has no
glyphs for — that plus single-line clipping is the garbled text from UAT.

---

## STEP 4 — Replace the consent modal (App.jsx)

Press Ctrl+F, search for:  `function VoiceConsentModal`

Select from the comment block that starts:

```
// Voice Phase 2: consent modal shown on first mic use per session.
```

…all the way down to the closing `}` of the `VoiceConsentModal` function —
i.e. everything up to (but NOT including) the line:

```
// ── VOICE STAGE components ───────────────────────────────────────────────────
```

Delete that selection and paste this in its place:

```jsx
// Voice Phase 2: consent modal shown on first mic use per session. Recorded as
// consent_type="voice_recording", copy_version="v0-draft".
// [PENDING LEGAL REVIEW] — VOICE_CONSENT_FULL below is the disclosure text
// awaiting legal sign-off (production gate #1). Do NOT delete it; only its
// wording may change after review. The compact modal shows a one-line notice
// and keeps the full copy one tap away behind "How voice answers work".
const VOICE_CONSENT_SHORT = "Your answer is saved as text — audio is never stored.";
const VOICE_CONSENT_FULL =
  "InterviewIQ converts your spoken answer to text. Your audio is transcribed " +
  "and immediately discarded — it is never stored. Only the text of your answer " +
  "is saved, exactly as if you had typed it. You can switch to typing at any time.";

function VoiceConsentModal({ onAccept, onDecline, busy }) {
  const [showFull, setShowFull] = useState(false);
  const isDev = import.meta.env?.DEV;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(11,22,40,.72)", backdropFilter: "blur(3px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onDecline}>
      <div onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Use your voice to answer"
        style={{ background: "#FDFCF9", borderRadius: 20, maxWidth: 400, width: "100%", padding: "28px 26px 24px", fontFamily: IQ.sans, boxShadow: "0 24px 64px rgba(4,10,22,.5)", animation: "iqFade .25s ease" }}>
        <div style={{ width: 52, height: 52, borderRadius: 16, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", background: "rgba(0,196,160,.12)", color: IQ.teal }}>
          <IconMic size={24} />
        </div>
        <div style={{ textAlign: "center", color: IQ.navy, fontSize: 19, fontWeight: 800, letterSpacing: "-.01em", marginBottom: 8 }}>
          Use your voice to answer
        </div>
        <p style={{ margin: "0 0 18px", textAlign: "center", color: "#4A5872", fontSize: 14.5, lineHeight: 1.5 }}>
          {VOICE_CONSENT_SHORT}
          {isDev && <span style={{ display: "inline-block", marginLeft: 8, padding: "2px 7px", borderRadius: 999, background: "rgba(232,82,26,.12)", color: IQ.orange, fontSize: 10, fontWeight: 700, letterSpacing: ".06em", verticalAlign: "middle" }}>DRAFT · LEGAL PENDING</span>}
        </p>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onAccept} disabled={busy} className="vbtn" style={{ background: IQ.navy, borderRadius: 12, opacity: busy ? 0.6 : 1 }}>Allow &amp; record</button>
          <button onClick={onDecline} disabled={busy} className="vbtn" style={{ background: "transparent", color: IQ.navy, border: "1.5px solid #D7DCE5", borderRadius: 12 }}>Not now</button>
        </div>
        <button onClick={() => setShowFull(v => !v)}
          style={{ display: "block", margin: "14px auto 0", background: "none", border: "none", color: "#00A88A", fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: IQ.sans }}>
          {showFull ? "Hide details" : "How voice answers work"}
        </button>
        {showFull && (
          <div style={{ margin: "12px 0 0", padding: "12px 14px", borderRadius: 12, background: "#F2F4F8", color: "#4A5872", fontSize: 12.5, lineHeight: 1.55 }}>
            {VOICE_CONSENT_FULL}
          </div>
        )}
      </div>
    </div>
  );
}

```

(Leave the `// ── VOICE STAGE components` line exactly where it is, below
what you just pasted.)

---

## STEP 5 (optional, for UAT screenshots) — hold the "Heard:" caption longer

Press Ctrl+F, search for:  `setHeard(null), 3000`

Change `3000` to `6000` so the Hinglish caption stays on screen 6 seconds —
much easier to screenshot. Revert to 3000 (or leave it) after UAT; 6s is
arguably better UX anyway.

---

## Verify

1. Restart the dev server, hard-refresh (Ctrl+Shift+R).
2. Character: new anime-style interviewer at the desk; female for the
   female voice, male (blazer + gold tie) for male.
3. Thinking: teal arc rotates around the figure; pupils glance upward.
4. Speaking: mouth opens in sync with the Bulbul audio.
5. Consent modal: compact card, one line, "How voice answers work" expands
   the full notice. Orange DRAFT chip visible in dev only.
6. Hinglish answer: "Heard:" caption renders Devanagari cleanly, wraps to
   up to 3 lines, no garbling.
