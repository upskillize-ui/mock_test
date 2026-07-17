# CONSENT_COPY_FOR_REVIEW.md — every consent notice a student reads, verbatim

**For:** Legal review. **Prepared:** 2026-07-17.
**Current version:** `CONSENT_COPY_VERSION = "v0-draft"` (`frontend/src/App.jsx:181`).
**Status:** every block below is marked `[PENDING LEGAL REVIEW]` in source and is
**live in production today** under the draft wording. This is the last launch-blocker for
all three modes (QA-06 in `docs/QA_BUG_REGISTER.md`).

Each block is reproduced **exactly as a student reads it** — same words, same order, same
punctuation. Headings and button labels are included where the student sees them, because
what a button says is part of what they agreed to.

---

## ⚠️ There are FIVE blocks, not four

The brief asked for four (setup, mic, camera/attention-cue, TEXT). There is a fifth: the
**voice-recording consent modal**, which the source itself labels *"production gate #1"*.
It is the notice attached to the most sensitive grant we record — recording someone's
voice — so it is included below as **Block 5**. Reviewing four of five would leave the
riskiest one unapproved.

**Two blocks record the same consent type from different wordings** (see the ledger table
at the end): a student who allows the mic in the pre-flight grants `voice_recording` after
reading **Block 2**; a student who joins muted and later taps the mic grants the *same*
`voice_recording` after reading **Block 5**. The two wordings differ. If they must agree,
they need to be reconciled as one text — that is a legal call, not an engineering one.

**Nothing else needs reviewing.** These five are the complete set: a sweep of every
`[PENDING LEGAL REVIEW]` marker in the frontend found one more, in `SelfView.jsx` — but
that file is **dead code**, imported by nothing and rendered to no one, so its copy has
never reached a student and is not reproduced here. Flagging it so it doesn't surface
later as an unreviewed sixth block, and so nobody spends time reviewing text the product
does not show.

---

## Block 1 — Setup consent (the checkbox)

**Where:** the setup screen, in a gold-bordered panel headed **"Before you begin"**.
**Mode:** all three (TEXT, AUDIO, VIDEO).
**Moment:** before the interview can be started at all — the "Start Interview" button is
gated on it, and an unticked box shows *"Please accept the notice above to begin."*
**Records:** `consent_type: "data_processing"` (written on join).
**Source:** `frontend/src/App.jsx:1321-1323`.

> **Before you begin**
>
> ☐ I agree that InterviewIQ may process my interview responses to generate my practice
> feedback and scorecard. My transcript and report are retained for a limited period and I
> can download or delete my data any time from Settings.

*Note for review: "a limited period" is the only retention statement a student ever sees,
and it names no duration. The source comment says the retention windows are Legal's to set.*

---

## Block 2 — Microphone copy (AUDIO pre-flight)

**Where:** the pre-flight ("Ready to join?") screen, in a panel headed **"Before you join"**.
**Mode:** AUDIO only.
**Moment:** after choosing the mode, before granting any device — it sits directly above
the **"Allow mic"** button that raises the browser's microphone prompt.
**Records:** `consent_type: "voice_recording"` (written on join, if the mic was allowed).
**Source:** `frontend/src/Lobby.jsx:66-67` (`CONSENT_COPY_MIC`).

> **Before you join**
>
> Your mic converts answers to text — audio is never stored. You can type instead at any
> time.

*Buttons on this screen: **Allow mic** · **Type instead**.*

---

## Block 3 — Camera and attention-cue copy (VIDEO pre-flight)

**Where:** the pre-flight ("Ready to join?") screen, same **"Before you join"** panel, as
two consecutive paragraphs.
**Mode:** VIDEO only.
**Moment:** before granting any device — directly above the **"Allow mic & camera"**
button that raises the browser's microphone *and* camera prompt.
**Records:** `consent_type: "voice_recording"` and `consent_type: "camera_selfview"`
(written on join, per device actually allowed).
**Source:** `frontend/src/Lobby.jsx:68-70` (`CONSENT_COPY_MIC_CAMERA`) and
`Lobby.jsx:72-74` (`CONSENT_COPY_CAMERA`).

> **Before you join**
>
> Your mic converts answers to text — audio is never stored. Your camera stays on your
> device — never recorded or uploaded. You can type instead at any time.
>
> During the interview, InterviewIQ notices attention cues (like looking away) on your
> device to coach your interview presence. No video is recorded.

*Buttons on this screen: **Allow mic & camera** · **Continue without camera** ·
**Type instead**.*

*Note for review: the second paragraph is the only place we disclose on-device attention
monitoring. The grant it produces is named `camera_selfview` in the ledger, which is a
narrower word than what the paragraph describes.*

---

## Block 4 — TEXT copy (TEXT pre-flight) — **new, never reviewed**

**Where:** the pre-flight ("Ready to join?") screen, in a panel headed **"Before you join"**.
**Mode:** TEXT only.
**Moment:** before joining — directly above the **"Join interview"** button.
**Records:** `consent_type: "data_processing"` only (TEXT grants no device consent).
**Source:** `frontend/src/Lobby.jsx:80-83` (`CONSENT_COPY_TEXT`).

> **Before you join**
>
> Your typed answers are processed to generate your feedback and scorecard. Your
> transcript and report are retained for a limited period, and you can download or delete
> your data any time from Settings.

*This block is **new this sprint** and has never been reviewed in any form. Until now TEXT
showed **no consent copy at all** — the whole panel sat inside the non-TEXT branch, so a
typing student was told nothing about what happens to what they write. The wording
deliberately mirrors Block 1's retention and deletion sentence, minus the devices this
mode does not have. It is a placeholder in exactly the way the others are.*

*The student also reads this, immediately above, which is product copy rather than a
consent notice but sets the same expectation:* "No microphone needed, so we won't ask for
one. Your interviewer's questions appear as text, and you'll type your answers. Take the
time you need to think and type — your session length is the only clock. You're scored on
what you say, not how you said it."

---

## Block 5 — Voice-recording modal (**the one the brief missed**)

**Where:** a modal dialog over the interview room, titled **"Use your voice to answer"**.
**Mode:** AUDIO and VIDEO.
**Moment:** the first time a student taps the microphone having joined without granting it
— i.e. the point of capture, not the point of setup. It blocks the mic until answered.
**Records:** `consent_type: "voice_recording"`.
**Source:** `frontend/src/App.jsx:1390` (`VOICE_CONSENT_SHORT`) and `App.jsx:1391-1394`
(`VOICE_CONSENT_FULL`). Source comment: *"[PENDING LEGAL REVIEW] … awaiting legal sign-off
(production gate #1)"*.

The student reads this:

> ### Use your voice to answer
>
> Your answer is saved as text — audio is never stored.
>
> **[ Allow & record ]**  **[ Not now ]**
>
> *How voice answers work* ▾

…and this only if they tap **"How voice answers work"**:

> InterviewIQ converts your spoken answer to text. Your audio is transcribed and
> immediately discarded — it is never stored. Only the text of your answer is saved,
> exactly as if you had typed it. You can switch to typing at any time.

*Note for review: the full disclosure is **one tap away**, not on the face of the dialog —
the student can grant recording having read only the single line. The button says
**"Allow & record"** while the copy says audio is never stored; whether those two read
consistently to a student is a review question.*

---

## What the ledger stores

Every grant writes one row to `vyom_consents` (`db/migration_003_dpdpa_foundation.sql`):

| Column | Value |
|---|---|
| `consent_type` | `data_processing` \| `voice_recording` \| `camera_selfview` |
| `copy_version` | **`v0-draft`** — pins exactly which wording they agreed to |
| `granted_at` | timestamp |
| `user_id`, `session_id` | who, and in which session (nullable: voice consent is user-scoped) |

| Consent type | Produced by | Modes |
|---|---|---|
| `data_processing` | Block 1 (and Block 4's context in TEXT) | all |
| `voice_recording` | **Block 2** (allowed at pre-flight) **or Block 5** (allowed at the mic) | AUDIO, VIDEO |
| `camera_selfview` | Block 3 | VIDEO |

**`voice_recording` is per-user and durable, not per-session.** Once granted it persists
across every later session. This is not a footnote: it is what made QA-07 exploitable (a
TEXT session could reach the speech-to-text vendor because the consent wall was already
down from an earlier AUDIO session). It also means a student consents to voice recording
**once, forever**, under whichever wording they happened to see that day.

---

## What happens once approved wording arrives

Small and mechanical — the copy lives in five named constants and nothing computes it.

1. **Swap the strings.** `CONSENT_COPY_MIC`, `CONSENT_COPY_MIC_CAMERA`,
   `CONSENT_COPY_CAMERA`, `CONSENT_COPY_TEXT` (`frontend/src/Lobby.jsx:66-83`);
   `VOICE_CONSENT_SHORT`, `VOICE_CONSENT_FULL` (`frontend/src/App.jsx:1390-1394`); and the
   checkbox sentence (`App.jsx:1321-1323`).
2. **Bump `CONSENT_COPY_VERSION`** (`App.jsx:181`) from `"v0-draft"` to the approved
   version. Every `recordConsent` call already passes it, so from that deploy on, each row
   in `vyom_consents` is stamped with the wording that produced it — old rows keep saying
   `v0-draft`, which is the whole point of the column: what was shown stays traceable.
3. **Bump `CONSENT_KEY`** (`App.jsx:180`, currently `"interviewiq_consent_v0-draft"`).
   ⚠️ **This is the deliberate side effect worth deciding on:** the key embeds the version
   and remembers acceptance in the student's browser, so changing it makes **everyone
   re-accept under the new wording**. That is almost certainly what you want for materially
   changed terms, and almost certainly not for a typo fix. It is a choice, not an
   automatic consequence — leaving the key alone silently keeps prior acceptances.
4. **Delete the `[PENDING LEGAL REVIEW]` source comments** and the dev-only draft markers
   they document (`Lobby.jsx`, `App.jsx`). The markers are already invisible to students —
   Vite strips them from the production bundle (verified: 0 hits in `dist`) — but the
   comments should not outlive the review.

No schema change, no migration, no backfill. `copy_version` is already `VARCHAR(40)` and
already written on every grant.

---

## Open questions for review

1. **Retention.** "a limited period" (Blocks 1 and 4) names no duration. Every other
   sentence here is specific; this one is not.
2. **Blocks 2 and 5 record the same `voice_recording` grant from different wordings.**
   Should they be one text?
3. **Block 5's full disclosure is behind a tap.** The student can grant recording having
   read one line.
4. **Block 3's attention-cue paragraph** is the only disclosure of on-device attention
   monitoring, and the grant is filed under the narrower name `camera_selfview`.
5. **`voice_recording` is durable and user-scoped** — consented once, applies forever,
   under whichever version was live that day.
6. **Block 4 is new** and has never been reviewed in any form.
