# ROOM_UI_REPORT.md — meet-room layout, captions, chat panel

Phase: ROOM_UI_PHASE_PROMPT.md. Frontend only — **no backend changes, so nothing is
pending an hf push.** All suites green: 100 frontend tests (29 of them new), 22 Critical
guardrails, capture-gate mutation test.

The room's presentation decisions now live in a pure, tested module (`roomLayout.js`,
alongside `roomPolicy.js`) rather than being re-derived by each floating overlay. That is
the through-line of this sprint: the old room answered "what is happening right now?" in
three places at once, and they could disagree.

---

## The one-line summary

The room was an interviewer on a stage with the student watching from a corner PiP. It is
now a two-person call: **two equal tiles, one status strip, one caption area that scrolls
instead of clipping, one chat panel that is both the transcript and the composer.** Nothing
floats over the stage any more.

---

## Item 1 — TWO EQUAL TILES + active-speaker glow

**Before** (`before-room-1280.png`): the interviewer sat centre-stage at a hard-coded 220px
and the student was a 168px PiP pinned bottom-right. Roughly half the room was empty navy.

**After** (`after-room-1280.png`): a CSS grid of `1fr 1fr` — equal *by construction*, not by
eye — with the chat panel taking its own third track when open, so opening it can never make
the call lopsided. The teal ring follows whoever is talking.

- `activeSpeaker()` returns **at most one** tile, tested across the whole input space. Two
  lit tiles carry the same information as none.
- **Barge-in gets the ring right**: while her clip ducks out (~200ms) the recorder is already
  open, so for that beat `speaking` and `recording` are *both* true. The student wins — they
  are the one talking. Deferring to `speaking` would light her tile while she is being
  interrupted.
- Camera-off shows the initial avatar; `connecting` counts as her floor (FAST START: she is
  about to speak into a room already listening for her).
- The portrait is **measured, not guessed**. `InterviewerCharacter` is a fixed-aspect card
  (`size × size*1.25`), so a ResizeObserver sizes it to the tile. It is clamped on **both**
  axes: height alone is the tempting version and it is wrong — at 1100 with the panel open
  the tile is ~350px wide, and a size picked off a 460px-tall body would push a 368px-wide
  portrait out through the sides of its own tile.

## Item 2 — ONE STATUS STRIP

`before-room-1280.png` shows the bug precisely: **the word "SPEAKING" rendering behind the
"Nia · InterviewIQ" name tag**, sliced in half by it. The label was a child of the character
column; the name chip was absolutely positioned over the same space.

Now there is one strip under both tiles — SPEAKING / LISTENING (with the rec counter) /
THINKING — and the name tag has its corner to itself.

**The muted chip is folded into it too.** It used to float at `right:16px; bottom:150px` —
a magic number chosen to clear the self-view, which held exactly until the thing below it
changed height. Item 2 asks for *one* status surface; a strip plus a floating orange chip is
two. The voice sprint's promise is kept: muted-with-an-answer-due still reads
"You're muted / Tap the mic to answer" and still pulses toward the mic button.

**The parity rule.** The strip, the lit tile and her face are three renderings of one state,
so they are derived from one state. `roomLayout.test.mjs` walks all 128 reachable
combinations asserting `STRIP_TO_FACE[strip.key] === orbState`. If the strip could ever say
"Speaking" while her face said "listening", the room would be lying to somebody and the
candidate would have no way to know which half.

Precedence worth noting: `listening` outranks `speaking` (barge-in again), and **muted never
shouts over her** — while she is still speaking, the strip says Speaking, not "You're muted".

## Item 3 — CAPTION AREA FIXED

**Before**: `-webkit-line-clamp:2` plus `max-height`, i.e. a hard clip with an ellipsis. On
a three-sentence case prompt the question was literally unreadable — and worse, it *looked*
like it had worked.

**After**: a fixed-height area (104px desktop / 92 / 86) that **scrolls**. Height is reserved
whether or not there is a caption in it, so the room does not jump as she starts and stops.
Progressive reveal: each sentence she reaches scrolls into view; when she finishes, the area
holds the whole question and can be scrolled back through.

Verified in the real DOM: `overflow-y=auto, height=104px, line-clamp=none`, and
`after-room-1280.png` / `state-listening.png` show a full three-line question rendering
complete where the old room would have ellipsed it.

The area is **hers alone** now — the student's running transcript moved to their own tile
(item 4), which is where their words belong.

## Item 4 — STUDENT INPUT SURFACE

Speaking an answer had no surface of its own: the waveform floated 16px off the stage bottom
and the running transcript borrowed *the interviewer's* caption band. An answer in progress
looked like a thing happening **to** the room rather than a thing the student was **doing**.

Now a surface opens inside their own tile — as a **sibling** of the tile body, not an overlay
on it, so it cannot collide with the name tag however long the transcript runs. Structure,
not magic numbers.

- **live** — the real waveform (heights from the AnalyserNode, not an animation) + the "You:"
  running transcript, DM Mono, verbatim, never beautified, scrolling inside a fixed height.
- **captured** — a Lucide check-circle and "Answer captured". No emoji.
- `captured` deliberately spans **both** `transcribing` and the `heard` flash, so the tick
  does not blink out and back between them.
- Self-captions off → the waveform and counter still say "we can hear you", and the caption
  never leaks (tested: `caption === ""`, not merely hidden).

The old centre-stage `Heard:` flash is **gone**. It quoted their transcript back for 3
seconds in the middle of the screen; it now lands in their own tile as the captured state,
where it can actually be read.

See `state-listening.png` (ring + surface + counter) and `state-muted.png` (the tick).

## Item 5 — CHAT PANEL

One `ChatPanel` component replaced three surfaces that were really one thing — the
conversation:

| was | now |
|---|---|
| `TranscriptDrawer`, a modal you open/read/dismiss | the panel's body |
| `iq-typebar`, a slide-out composer | the panel's footer |
| "Correct this" edit-last, inside the drawer | on the last bubble, unchanged |

Collapsible third column ≥1000px; below that the CSS floats it over the grid (same component).
Typed = spoken: `onSend` is the same `send()` a spoken answer takes. Captured voice answers
carry a subtle **"heard you"** tick — a spoken answer is the only one with no receipt (they
typed nothing, they just talked at a laptop), which is why `bubbleMeta` gives the tick to
`SPOKEN` and not to `TYPED` or `SKIPPED`.

Mode-agnostic, as asked: `chatSlot()` puts it in the **student tile's slot** when
`config.mode === "text"` and in the side column otherwise. The room is two tiles in both
modes; only the occupant changes. Nothing inside the panel asks which mode it is in. (Text
mode itself lands with INTAKE/MODES — this is the surface waiting for it, and it is tested:
in text mode the panel can never be collapsed away, because that would leave a room with no
way to answer in it.)

The control bar's two buttons (keyboard + transcript) collapse to one Chat toggle. In text
mode there is nothing to toggle, so the button is not rendered.

### ⚠️ The one that would have bitten us: **reading is not typing**

`canArmCapture({typing})` suppresses the mic when the student has chosen the composer — right
rule. But `typing` was wired to **"the typing drawer is open"**, which was only ever a decent
proxy because that drawer did nothing else.

The panel does something else: **it is where you re-read an earlier question** (item 5's own
requirement). Inheriting the old proxy would have meant that opening the transcript to check
what was asked *silently disarmed the microphone* — hands-free dying from an act of reading.

So the signal is now the composer itself (`composerIntent`: focused, or holding a draft) and
never the panel's visibility. Consequently the two entry points differ on purpose: the HUD
transcript button opens the panel **without** focusing (a request to read); the control-bar
Chat button focuses the composer (a request to type). The capture invariant and its mutation
test are untouched — only the honesty of what feeds it improved.

## Item 6 — every screen, 1100 / 1280 / 1920

Driven with Playwright against the real backend and a real session (fake mic/cam), asserting
the global layout rule rather than eyeballing it: for every element, `right <= clientWidth`
and `left >= 0`, plus `scrollWidth <= clientWidth`.

**21/21 pass** — 7 screens × 3 widths:

| screen | 1100 | 1280 | 1920 |
|---|---|---|---|
| Setup | ✅ | ✅ | ✅ |
| History | ✅ | ✅ | ✅ |
| Settings | ✅ | ✅ | ✅ |
| Pre-flight | ✅ *(was ❌)* | ✅ *(was ❌)* | ✅ *(was ❌)* |
| Pre-flight (mic check) | ✅ *(was ❌)* | ✅ *(was ❌)* | ✅ *(was ❌)* |
| Room | ✅ | ✅ | ✅ |
| Room + chat panel | ✅ | ✅ | ✅ |

At 1100 with the panel open — the tightest case — the tiles are ~341px each and still equal,
with a 340px panel. Below the embed's floor the layout degrades rather than breaking: the
panel becomes an overlay <1000px, the tiles stack <820px.

---

## Two real bugs found by the verification, and fixed

**1. Pre-flight overflowed horizontally at every width** (pre-existing — reproduced on
`main` with the changes stashed; see the `before-preflight-*` shots, `scrollW = clientW+28`).
`Lobby.jsx` carried `margin: "-24px -28px"` to bleed the navy out through a padded app shell.
The shell's padding is long gone; the lobby renders straight into the page, so those numbers
were pulling the whole screen 28px off **both** edges and putting a scrollbar on the
pre-flight. Full bleed is what a plain 100%-wide block already does there.

**2. Dead CSS is not free — it collides.** The room used to be a glowing orb on a centred
stage (`.iq-stage` / `.iq-orb*` / `.iq-micpill` / `.iq-review` / `.iq-caption` / a bottom
`.iq-strip`). `InterviewerCharacter` replaced the orb and the tiles replaced the stage, but
~50 lines of CSS stayed. The retired bottom-strip rule set `flex-direction:column` and
`padding:16px 20px 20px` on `.iq-strip` — **and the new status strip is also `.iq-strip`**.
The corpse was reaching up and stacking the live strip's dot above its own label into a tall
rounded blob. Removed (keeping the three rules still load-bearing: `.iq-livewave`,
`.iq-livebar`, `.iq-ghostbtn`), along with the reduced-motion and 420px blocks that only
styled the orb. Every class removed was verified to have zero JSX references first.

---

## Tests added — `roomLayout.test.mjs` (29, `npm run test:layout`)

The ones that are load-bearing rather than decorative:

- **the strip and her face never disagree, in any reachable state** — the parity sweep.
- **exactly one tile is ever lit, across the whole input space.**
- **BARGE-IN: the interrupter gets the ring, not the interrupted.**
- **muted never shouts over her — she is still speaking.**
- **the strip names each state in words, never in colour alone** — every reachable state has
  a non-empty label. A strip that says a state only by going orange says nothing at all to
  somebody who cannot see orange.
- **READING THE TRANSCRIPT DOES NOT COST YOU THE MICROPHONE** — panel visibility is not an
  input to `composerIntent`, and that absence *is* the assertion.
- **text mode: the panel IS the second tile, and cannot be collapsed away.**
- **captured spans transcribing AND the flash — the tick does not blink out between.**
- **self-captions off: the caption never leaks** (`caption === ""`, not just hidden).

## Accessibility

Colour never carries meaning alone — every strip state has words, and that is now a test, not
a convention. Under `prefers-reduced-motion` the active-speaker **ring stays a ring** (it is
the thing saying who has the floor, so it must not be the thing that disappears); only its
breathing stops. Tiles are `<section>`s with `aria-label`; the strip is a single
`role="status" aria-live="polite"` region — previously the state was announced from two.

## Brand / copy

Navy/gold/teal, Plus Jakarta Sans, DM Mono for data (counters, the "You:" transcript, strip
labels). No emoji on the interview surface — the captured tick is a drawn Lucide check-circle
matching the existing icon set. The chat panel's subtitle was mono caps ("TYPE ANY ANSWER
HERE") and is now sentence case: a quiet aside telling them typing is always an option, and a
shouted one reads as a warning about something.

One spacing rhythm for the whole room, as four CSS variables (`--gap:16 --pad:20 --tile-pad:10
--radius:14 --radius-sm:8`). The old room had gaps of 8/10/12/16/20/22 and three radii.

---

## Flagged, NOT fixed — out of scope, needs your call

**The pre-flight ships `[PENDING LEGAL REVIEW]` copy to students.** `Lobby.jsx` renders
`CONSENT_COPY` / `CONSENT_COPY_CAMERA` under a "DRAFT NOTICE — PENDING LEGAL REVIEW" line —
visible to the student on every join (see `after-preflight-1280.png`). The INTAKE/MODES
prompt's rules say nothing student-visible ships with that copy. It is consent wording, so it
is not mine to rewrite. Flagging it here.

---

## Screenshots — `docs/screenshots/room-ui/`

**Before/after pairs** (`before-*` captured on `main` with these changes stashed):

| screen | before | after |
|---|---|---|
| Room | `before-room-{1100,1280,1920}.png` | `after-room-{1100,1280,1920}.png` |
| Pre-flight | `before-preflight-{1100,1280,1920}.png` | `after-preflight-{1100,1280,1920}.png` |
| Pre-flight (mic) | `before-preflight-mic-{1100,1280,1920}.png` | `after-preflight-mic-{1100,1280,1920}.png` |
| Setup | `before-setup-{1100,1280,1920}.png` | `after-setup-{1100,1280,1920}.png` |
| History | `before-history-{1100,1280,1920}.png` | `after-history-{1100,1280,1920}.png` |
| Settings | `before-settings-{1100,1280,1920}.png` | `after-settings-{1100,1280,1920}.png` |

**After only** (no before — these states had no equivalent surface):

- `after-room-chat-{1100,1280,1920}.png` — the chat panel open; 1100 is the tightest case.
- `state-interviewer.png` — her tile lit, strip "Speaking".
- `state-listening.png` — their tile lit, strip "Listening 0:01", the live surface, and a
  full three-line question rendering uncropped in the caption area.
- `state-muted.png` — the captured tick, strip "Thinking".

The two most worth opening side by side are `before-room-1280.png` (the "SPEAKING" label
sliced in half by the name tag, student in a corner) and `after-room-1280.png`.
