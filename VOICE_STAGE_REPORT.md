# InterviewIQ — Voice Stage + Conversation Realism v2

A call-like presentation mode over the existing state machine, now with a **dynamically
improvised interviewer**, an **instant hands-free two-way flow**, and an **illustrated
character** whose mouth is driven by the real TTS audio.

Backend suite **86/86 green**; `vite build` passes.

---

## 1. What shipped

### Part A — Truly dynamic openings & voice
- **No fixed greeting, no persona templates, no archetype list.** At session start the
  model improvises a distinct professional interviewer (tone, pacing, warmth, phrasing
  habits) fitted to the role/level/company/JD/focus/duration, returns a one-line
  **identity summary**, and is held to it on every later turn.
- The identity is persisted (`vyom_sessions.interviewer_identity`, **migration 005**,
  additive) and replayed into the system prompt each turn: *"STAY IN IT … identity
  governs tone, pacing and phrasing only — never difficulty, rigor, Indian-hiring norms,
  or round structure."*
- Opening **constraints, not templates**: 2–4 sentences, at most one reassurance line and
  **only for freshers**, must end in a real first question already shaped by the role.
- Flavor examples are included but marked *"for flavor — never copy or template these."*

**The hard part, and what actually made it work.** Improvisation alone does **not**
diverge. Measured against the live model: three fresh sessions for the same role produced
the *same* interviewer — all "pragmatic fintech backend lead", all named **Vikram**, all
"building payment systems for five years". Lexically different, semantically identical —
exactly the failure the spec names. Two causes, both fixed:
1. **The flavor example matched the sector.** Given a fintech company, the model grabbed
   the "brisk fintech panel lead" example. The prompt now says explicitly that reaching
   for the sector-matching example *is* the copying failure.
2. **Diversity the model cannot observe cannot be requested.** Asking it for "a name you
   haven't defaulted to" is meaningless — it has no memory of prior sessions. So we now
   **supply** the variation: a set of per-session **dials** (warmth / pace / register /
   opening move / phrasing habit, drawn at random — broad axes, *not* archetypes) and a
   **drawn interviewer name**, gender-matched to the TTS voice so name + voice + character
   are one coherent person.

**After the fix**, the same three-session probe produced *Lakshmi* (forensic, brisk),
*Sneha* (measured, unhurried, comfortable with silence), and *Ishita* (wry, deliberate
pauses) — three genuinely different interviewers, 3/3 unique openings.

### Part B — Instant two-way flow
- **No review card, no Send in voice mode.** Stop → THINKING → **auto-submit** → IQ speaks
  the reply. A **"Heard: …" caption flashes for 3s**; the answer lands in the drawer via
  the normal message flow.
- **The last answer is editable in the transcript drawer** ("Correct this") →
  `PATCH /session/turn/last`, **idempotent**. **No schema change** — it rewrites
  `vyom_messages.content` in place. Behind `EDIT_LAST_ANSWER_ENABLED` (default on).
- **Null STT → IQ speaks a natural, in-character re-ask** (`POST /session/reask`) and the
  mic reopens. That endpoint **inserts no message and changes no state**, so a failed
  transcription **never consumes a question slot**. Typed fallback engages only after
  **two consecutive** failures.
- **Spoken confidence rating.** IQ **asks aloud** (text + audio ride on the turn response);
  the mic opens and we parse **digits / English words / "prefer not to say" / Hinglish
  (ek, do, teen, char/chaar, panch/paanch)**. The **pills appear only** on a parse failure,
  after **8s of silence**, or when voice can't carry it (auto-listen off / no consent /
  typed mode). **Typed mode is untouched.**

### Part C — The interviewer character (replaces the orb)
- **`frontend/src/InterviewerCharacter.jsx`** — isolated so the dual-theme redesign or a
  vendor avatar can swap it wholesale. Layered inline SVG, no new deps, no external assets.
- Two characters matched to the voice picker: **female (ritu)** and **male (shubh)** —
  Indian professional business attire, head-and-shoulders, flat premium-editorial on the
  brand palette (navy suit, teal accent, gold detail). Realistic proportions; deliberately
  not cartoonish.
- Rigged in layers: shoulders (breathing) → head group (tilt/nod) → brows, eyes + lids,
  nose, **mouth (5 shapes: closed / small / mid / wide / smile)**.
- **SPEAKING: the mouth follows the ACTUAL TTS audio** — an `AnalyserNode` is attached to
  the `<audio>` element and its live RMS selects the mouth shape (not a fake loop). Brow
  lifts on amplitude **onsets** (sentence starts); blinks every 3–6s.
- **LISTENING:** attentive tilt toward the candidate, randomized nods every 4–7s, steady
  eyes with blinks, occasional "mm-hm" mouth twitch — never a talking mouth.
- **THINKING:** gaze shifts up-and-aside, brows draw in, stillness + breathing.
- **IDLE:** relaxed neutral, breathing + blinks.
- Persistent text state label remains; captions render beneath the character; the learner
  strip (live waveform, timer, orange ring) is unchanged.
- **prefers-reduced-motion:** freezes to a neutral portrait, state label only.

**Audio safety note.** `createMediaElementSource()` may be called only once per element,
and from then on the element's audio flows *only* through the graph — so the analyser is
wired **inside the Start-button gesture** (context starts "running") and connected to
`destination`, and we `resume()` defensively on every play. If any of it throws, the
element is left completely untouched: **audio still plays**, only the lip-sync degrades.

---

## 2. Manual UAT script

Pre-req: `TTS_ENABLED`, `STT_ENABLED`, `VOICE_ENABLED` on; **migration 005 applied**;
mic-equipped device. Open `http://localhost:8000/dev/login` to land logged in.

1. **Three different interviewers** — start three fresh sessions with the *same* role and
   company. The dev console logs `[interviewer identity] …` each time. Confirm three
   **clearly different** interviewers: different name, different energy, different opening
   move — not the same person in different words. Confirm no opening is a stock pleasantry
   and each ends in a real, role-shaped question. ✅
2. **Fresher vs non-fresher** — a Fresher session may contain at most one reassurance line;
   a senior session should contain **none** and get to substance immediately. ✅
3. **Full no-hands loop** — the character speaks the opening (SPEAKING). Accept the consent
   modal on first mic use. Then: IQ finishes → mic opens automatically → you answer → pause
   → auto-stops → THINKING → **"Heard: …"** flashes → the answer submits **with no Send** →
   IQ replies and speaks. **Repeat with zero clicks.** ✅
4. **Spoken confidence rating** — after a scored answer, IQ **asks aloud** for a 1–5. Say
   *"four"* (or *"chaar"*, or *"4"*, or *"prefer not to say"*). It is accepted and the round
   advances **without touching the pills**. ✅
5. **Rating fallbacks** — say something unparseable ("um, maybe-ish") → the pills appear.
   Separately, say nothing for 8s → the pills appear. ✅
6. **Mouth syncs to the audio** — ask for a long question (or replay one) and watch the
   mouth: it should open/close **in time with the voice**, not on a loop. Mute the audio and
   confirm the mouth goes still. ✅
7. **Listening nods** — give a ~60s spoken answer and watch the character: attentive tilt,
   periodic nods (every 4–7s, not metronomic), blinks, and **no talking mouth**. ✅
8. **STT failure → re-ask, no slot lost** — force one STT failure (invalid `SARVAM_API_KEY`,
   or record silence). IQ **says in character** that it didn't catch it and the mic reopens.
   Confirm the round counter did **not** advance. Force a **second** consecutive failure →
   the typed composer swaps in. ✅
9. **Correct a mis-transcription** — open the transcript drawer, hit **"Correct this"** on
   your last answer, fix the text, Save. Re-saving the same text is a no-op (idempotent).
   Note: IQ does **not** re-answer — the correction is what gets **scored**. ✅
10. **Hinglish answer** — speak a code-mixed answer; confirm the transcript is sensible and
    the flow continues hands-free. ✅
11. **Captions / drawer / voice picker** — settings menu: captions off hides the caption
    line; the drawer shows the full conversation; switching the voice swaps **both** the TTS
    voice and the on-screen character (female ↔ male). ✅
12. **Reduced motion** — enable OS "reduce motion": the character freezes to a neutral
    portrait, and the state is carried entirely by the text label. ✅
13. **360px mobile** — the character scales and stays above the captions; nothing clips or
    scrolls sideways. ✅
14. **Toggle OFF** — settings → Voice mode off: exactly the classic chat + composer UI, with
    the rating pills and typed review as before. ✅

---

## 3. Activation

1. **Apply migration 005** (`db/migration_005_interviewer_identity.sql`) — additive, with a
   rollback file. *Without it the interview still runs* (the write is caught and logged),
   but the interviewer **loses cross-turn identity continuity**.
2. Flags: `TTS_ENABLED`, `STT_ENABLED`, `VOICE_ENABLED` on; `EDIT_LAST_ANSWER_ENABLED`
   defaults on (set false to remove the PATCH endpoint entirely).
3. Migration 004 (delivery metrics) remains optional and independent.

---

## 4. Known gaps / decisions

- **The identity's variety is engineered, not emergent.** Diversity comes from
  server-drawn dials + name. This is deliberate and *necessary* (see §1), but it means the
  space of interviewers is bounded by those axes rather than being open-ended. Worth
  revisiting if openings start to feel systematic.
- **One in three openings may still start with a mild pleasantry** despite the explicit ban
  ("Hey, thanks for joining"). The identity underneath is genuinely different; only the
  first few words occasionally regress. Tunable in the prompt if it grates in UAT.
- **`PATCH /session/turn/last` does not re-run the interviewer's reply.** IQ has already
  responded to the original wording; regenerating would rewrite history and re-bill the
  model. The corrected text is what the **debrief scores** — the follow-up you already
  heard was based on the original. Flagged as a product call.
- **The re-ask costs a small model call** (max 60 tokens) plus TTS, and falls back to a
  varied canned line if the model is unavailable.
- **Spoken rating consumes an STT call** (well within the per-session cap).
- **Lip-sync needs Web Audio.** If `createMediaElementSource` is unavailable the mouth stays
  neutral rather than faking a talk loop — audio is never put at risk.
- The character is CSS/SVG-only by design (no canvas/WebGL), per the no-new-deps and
  reskin-without-relayout constraints.
