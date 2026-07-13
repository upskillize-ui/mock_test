# InterviewIQ — The Interviewer & The Experience

Against `INTERVIEW_EXPERIENCE_MASTER_PROMPT.md`. Backend suite **121/121 green**;
`vite build` passes. Not pushed to HF.

---

## 0. Two blockers — stated plainly, not worked around

**E3 (four-pose crossfade) is blocked on art, not code.**
It needs **listening / smile / intense / thinking** per character — **4 poses × 6
characters = 24 images**. The repo has **4 images**: one pose each, for four of the six
roster characters (`ananya` and `kavya` have no art at all). You cannot crossfade between
poses that don't exist, and I'm not going to fake it with CSS filters and call it a pose
system. What *is* already in place from the v4.2 roster: amplitude glow + waveform badge
while speaking, listening pulse ring, thinking arc, reduced-motion honoured. The
crossfade, Ken Burns idle and the shared object-position anchor land the moment the 24
images do — it's then a contained change to one file.

**E4 (the eyes) is still the CSP/model-asset blocker** you deferred last sprint.
MediaPipe/tfjs fetch WASM + weights from a CDN at runtime; production CSP
(`script-src 'self'; connect-src 'self'`) blocks that, and it would **pass in `vite dev`
and silently do nothing in production**. Unchanged until model assets are self-hosted.
The `tab_hidden` / `window_blur` signals that need no camera **are already live**.

---

## 1. PART 1 — The persona (the "soul") ✅

`prompts.build_persona(cfg)` is now the interviewer. It is split so cost stays sane:
- **Stable half → the CACHED system prompt**: who you are (`YOU ARE PRIYA — a senior
  professional running a real {role} panel in India`), how you speak, register,
  difficulty, device moments, what you never do.
- **Per-turn half → the small un-cached directive**: current round + **what that round is
  FOR**, the escalation/presence note, and **their last answer verbatim** — so the
  follow-up can pick up a *specific detail* instead of acknowledging generically.

Enforced and tested:
- **2–3 short sentences per turn, one question at a time.** No monologues.
- **Generic acknowledgements are FORBIDDEN** ("Great answer, next question").
- **Hinglish is never commented on.** Reply in English, move on.
- **`tone_hint` derives from difficulty** — Easy → *warm*, Realistic → *neutral*,
  Stretch → *probing* ("pressure through precision, not through tone").
- **Never comments on accent, appearance, or anything they can't fix in this room.**
- **The improvised identity (migration 005) is retained** *inside* the persona: it still
  supplies the individual's phrasing habits, and the roster's name is adopted, so the
  face, the voice and the words are one person.

**One deliberate deviation, and why.** The spec's `{presence_hint}` prose lists emotion
words to forbid ("nervous", "bored"…). I kept that list — the spec is explicit and the
rule needs to be concrete — **but I removed the word "cheating" entirely, even from the
prohibition.** My first draft of the level-2 directive said *"no accusation of cheating"*
and my own test caught it: **naming a word in a prompt primes the model to echo it.** A
test now asserts `"cheat"` appears in *no* prompt, directive, or user-facing string.
Flagging the same theoretical risk for the emotion list — it's a weaker effect and the
spec asked for it by name, but if reactions ever start leaking those words, that list is
the first place to look.

## 2. E2 — Voice & pacing ✅

**The reply is now synthesised ONE CLIP PER SENTENCE.** This is what buys human pacing:
- `tts.split_sentences()` → `_try_tts_segments()` returns
  `[{text, audio_url, pause_before_ms}]`, synthesised **in parallel**.
- Pauses per spec: **380ms between sentences**, **700ms before the question lands**
  (the last sentence usually *is* the question).
- The client **sequences explicitly** (`playSegments`). This mattered: with per-sentence
  clips, the old shared `'ended'` listener would have fired **once per sentence** and
  opened the mic **before the question was even asked**. The sequencer now owns the
  hand-off and fires it once, when the whole reply is done.
- **Captions are in true lockstep** — the caption *is* the sentence currently in the air.
  The old progress-bar interpolation is gone. Max 2 lines, `'Noto Sans Devanagari'` in
  the stack. Idle → the whole question, so it can always be read.
- **The interviewer is ALWAYS audible: the mute control is removed.** Replay stays; CC
  carries accessibility. *(Noted: this deliberately removes an affordance for anyone who
  needs silence — CC is the substitute. Flagging in case that trade is contested.)*
- A sentence whose synth fails shows its caption for a beat and moves on. Never stalls.

> **COST — read this.** TTS is now **N calls per turn instead of 1** (a 3-sentence turn =
> 3 calls). The content-addressed cache absorbs repeats, but questions are mostly unique,
> so budget roughly **2–3× the previous TTS spend**. The per-session cap still bounds the
> worst case. If that's unacceptable, the lever is to synthesise the *question* sentence
> separately and the lead-in as one clip (2 calls, most of the pacing benefit).

## 3. E5 — Fairness spine ✅ (already held, now pinned)

- **Skipped ≠ failed** — non-substantive answers are excluded from quality scoring and
  don't consume a question slot (the `substantive` flag, FIX 1/2).
- **Early wrap scores completed rounds; nothing is zeroed** (tested).
- **Typed and spoken answers are scored identically** — same message row, same debrief.
- **Presence coaching never gates content scoring** — the ladder is *prepended* to the
  turn directive, so the round plan underneath is byte-identical (tested).
- **Escalation is persisted server-side; a refresh changes nothing.**

## 4. Not done

- **E3** — blocked on 24 images (§0).
- **E4** — blocked on model assets (§0).
- **E6 readout re-order** (what-went-well → Delivery → Presence → fixes → band with the
  calibration delta explained) — **not done this pass.** The Presence Profile data and the
  Delivery Profile both exist; this is a readout-composition change plus a debrief-prompt
  change, and I'd rather do it properly than rush it into a turn that's already large.
- **Per-question timer** (E7.7: expiry auto-submits a half-answer, empty = skip) — not
  built. The 60s camera grace / 90s abandonment timers from the last sprint are also
  still open.

## 5. UAT (what you can check today)

1. **Greeting** uses their name, ≤4 sentences, and you can **hear the pauses** — a beat
   between sentences, a longer one before the question. ✅
2. **Captions advance sentence by sentence, in time with the voice** (not sliding on a
   progress bar). ✅
3. **A rambling answer gets a specific follow-up** quoting a detail from it — generic
   "great answer, next question" should never appear. ✅
4. **Stretch** session reads as *probing*; **Easy** reads as *warm*. ✅
5. **No mute button** anywhere; **CC toggle** works. ✅
6. **Tab-switch twice** → one gentle in-persona line; keep going → firmer. The question
   plan doesn't change. ✅
7. **Nothing in any transcript** contains an emotion attribution or the word "cheating". ✅
8. Migration 006 (now also carrying `interviewer_name`) must be applied for the name,
   the ladder and the early-wrap to persist. Un-migrated, everything degrades safely.
