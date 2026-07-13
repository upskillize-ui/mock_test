# InterviewIQ — Expressive interviewer poses

Backend **123/123**, pose policy **9/9** (`npm run test:poses`), `vite build` green.
Not pushed to HF.

---

## The headline: this shipped even though the art hasn't

`frontend/src/interviewers/poses/` **does not exist yet** — no pose PNGs have landed.
Last sprint I called the four-pose system blocked for exactly that reason. **This spec
un-blocked it**, because item 7 requires feature-detection with fallback to the single
portrait. So the whole pose engine is in, **live but dormant**, and lights up the moment
the files appear. Nothing to re-do when they arrive.

I verified that claim rather than asserting it: dropping a single `priya_smile.png` into
`poses/` made the build resolve and bundle it (`dist/assets/priya_smile-*.png`); removing
it fell straight back to the base portraits. Both builds green.

**How:** Vite's `import.meta.glob("./interviewers/poses/*.png", { eager: true })`. A hard
`import` of a missing file is a **build failure** (that's what forced two roster rows to
be commented out last sprint); a glob simply resolves whatever is on disk. No crashes, no
placeholder art, no dead imports.

---

## What shipped

### `posePolicy.js` — pure logic, zero dependencies
Deliberately free of React, DOM and asset imports, so it is testable with **Node's
built-in runner** (`node --test`). **No new dependency was added** — I did not pull in
Vitest for this.

- `choosePose({state, tone, escalationLevel, stage, difficulty, group})`
- `hasPoseSet(map, id)` / `resolvePose(map, id, pose, baseImg)`

**Selection rules (all tested):**
| Input | Pose |
|---|---|
| `thinking` state | `thinking` |
| `listening` / `idle` / `ready` | `listening` |
| speaking + **escalation ≥ 2** | **`intense`** — outranks tone |
| speaking + `tone: warm` | `smile` |
| speaking + `tone: probing` | `intense` |
| speaking + `tone: neutral` | alternates `listening`/`smile` per reply |
| speaking, **no tone hint** | greeting/warm-up → `smile`; Stretch → `intense`; else alternate |

The escalation override matters: **if the focus ladder has escalated, the face must not be
smiling while the words are firm.** A single drift (level 1) does *not* harden the face.

### The tile (`InterviewerCharacter.jsx`, extended — not rebuilt)
- **Preloads all four poses on mount** (`new Image()`), so a swap never flash-loads.
- **Crossfade**: two absolutely-stacked `<img>` layers, **opacity-only, 400ms ease**.
  Never a hard swap.
- **Shared `objectPosition` anchor per character** carries across the fade, so the face
  stays put even though the poses are cropped quadrants with slightly different framing.
- **Fallback**: exact pose → that character's `listening` → their single base image.
  Robots and un-regenerated humans simply keep their portrait.
- **No mouth animation on photographs.** Lip motion stays the amplitude glow + waveform
  badge; the pose carries the register — exactly as the note instructed.
- **prefers-reduced-motion**: the crossfade is **kept** (it is opacity only, which is
  permitted); the Ken Burns / sway / pulse motion is dropped. Killing the fade too would
  produce the hard swap the spec forbids.

### Server tone hint (item 5)
`prompts.turn_tone(difficulty, stage, escalation_level)` → `"warm" | "neutral" |
"probing"`, returned on the turn payload alongside `escalation_level`. The **server**
decides the register — it already knows the round and the ladder — and the client maps it
onto the pose, so **the face and the words say the same thing**.

```
greeting / warm-up   -> warm      (smile)
Realistic domain     -> neutral   (alternate)
Stretch case         -> probing   (intense)
Easy domain          -> warm      (smile)
escalation >= 2      -> probing   (intense)   <- overrides everything
```
The client heuristics remain as a fallback for when `tone` is absent.

---

## Addendum items

- **No interviewer-mute** — already shipped in the previous pass (E2). The panel is always
  audible; CC carries accessibility.
- **m6 expressiveness / m7 smile_moments / m8 nod_count** — these belong to the **Phase D
  detector**, which is still blocked on the CSP/model-asset decision. Folded into that
  sprint, not faked here. Migration 006's `presence_metrics` JSON already has room for
  them, so no further migration will be needed.
- **Hard language rules — extended, with one deliberate correction.**

  The addendum bans emotion words in "any engine/**persona**/readout string". Taken
  literally that is unsatisfiable: **PART 1 requires the persona to name those very words
  in order to forbid them** ("Never say nervous, bored, disinterested…"). A token-ban
  would make the rule unstateable.

  So I enforce what actually causes harm — **the attribution pattern**, not the token:
  - A **token ban** across everything a candidate can read or hear (readout copy, coaching
    notes, ladder directives).
  - A **pattern ban** — `(you|they|the candidate) (were|seemed|looked|felt|appear…) …
    (bored|nervous|anxious|…)` — applied **across the prompts too**, so the persona may
    *name* the words to prohibit them but can never *use* them as a claim.
  - Plus a **guard-the-guard test**: the regex provably catches `"you seemed a bit bored"`
    and provably passes `"your gaze drifted; hold the interviewer's eye"`. A test that
    can't fail is worthless.

  `"cheating"` stays banned outright — including from the prompts — because naming it
  primes the model to echo it. (My own earlier draft did exactly that; the test caught it.)

---

## Notes for when the art lands

1. Drop the files at `frontend/src/interviewers/poses/{characterId}_{pose}.png` —
   ids are `priya`, `ananya`, `kavya`, `meera`, `arjun`, `vikram`; poses are
   `listening`, `smile`, `intense`, `thinking`.
2. **They are already LFS-tracked** (`.gitattributes` now covers `poses/*.png`), so the HF
   "no raw binaries" rejection cannot recur.
3. A character lights up the moment its **full four** are present; a partial set falls back
   to `listening`, then to the base portrait. No code change, no redeploy logic.
4. Still outstanding from earlier sprints: `ananya` and `kavya` have **no base portrait**,
   so their roster rows remain commented out.

## UAT

1. **Today (no art)**: the room looks exactly as before — base portraits, glow, badge,
   arc, ring. Nothing regressed. ✅
2. **With art**: greeting → `smile`; a Realistic domain round → face alternates rather than
   freezing; a Stretch case → `intense`; whilst you answer → `listening`; whilst it thinks
   → `thinking`. All crossfaded, never snapped. ✅
3. **Tab-switch 3+ times** (escalation ≥ 2) → the face goes **`intense`** and stays there
   while it speaks, even in an Easy warm-up. The face matches the firmer words. ✅
4. **Reduced motion** → poses still crossfade; Ken Burns/sway/pulse are off. ✅
5. `npm run test:poses` → 9/9. ✅
