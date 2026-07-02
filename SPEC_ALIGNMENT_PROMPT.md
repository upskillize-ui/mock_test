\# InterviewIQ Spec Alignment — Four-Ticket Sprint



You are implementing four spec-alignment tickets in the InterviewIQ codebase (Upskillize EcoPro LMS's AI mock interview agent — FastAPI backend + React/Vite frontend on HuggingFace Spaces). The July 2026 audit found the live product does not match its own product definition. This sprint closes that gap.



Tickets in this sprint, in build order:

\- INT-04 — Canonical seven-round session structure (with the minimal server-side stage tracking needed to enforce it)

\- INT-01 — Confidence rating (1–5) captured after every answer

\- INT-03 — Readiness bands replace percentages in the readout

\- INT-02 — Calibration delta scoring and readout block



NOT in this sprint (do not touch):

\- INT-05 full state-machine refactor beyond what INT-04 needs

\- INT-06 session-refresh persistence

\- INT-07 DPDPA compliance

\- Any voice or STT/TTS work



Work through six phases. Do NOT skip phases. After each phase, print a one-line status.



═══════════════════════════════════════════════

PHASE 1 — DISCOVERY \& PLAN

═══════════════════════════════════════════════

1\. Read the current backend session flow — main.py, the session endpoints, the scoring path, the vyom\_debriefs table schema.

2\. Read the current frontend App.jsx — locate the session component, the round advancement logic, the readout render.

3\. Identify exactly where each of the four tickets plugs in — file, line range, function name.

4\. Print a short plan (max 15 lines) showing: which files change, which tables/columns get added, which endpoints get added or modified.

5\. Legacy naming rule from the audit — vyom\_debriefs and other DB table names STAY (safe-to-leave). All new code, docs, config, and UI copy use "InterviewIQ". Do not rename DB tables in this sprint.



═══════════════════════════════════════════════

PHASE 2 — INT-04 · Canonical seven-round session structure

═══════════════════════════════════════════════

Ship the exact InterviewIQ flow: Setup → Warm-up (2 questions) → Domain (4-6 questions) → Behavioural (3-4 questions) → Case (1 short for fresher, 1 long for 2+ yrs) → Reverse (learner asks 2 questions) → Readout.



Backend deliverables:

\- New column session\_state.current\_stage on the session table (or new table if cleaner), enum: SETUP, WARMUP, DOMAIN, BEHAVIOURAL, CASE, REVERSE, READOUT, DONE.

\- New column session\_state.round\_index tracking which question within the round.

\- Round question counts vary by level — accept a level field on session start: fresher / 0-2 / 2-5 / 5+. Fresher gets 4 domain + 3 behavioural + short case. 5+ gets 6 domain + 4 behavioural + long case + notice-period question at session end.

\- New endpoint GET /session/{id}/state returning the current stage and next expected action.

\- /session/turn validates that the submitted answer matches the current stage — invalid transitions return HTTP 409 with a clear message.

\- /session/turn increments round\_index and advances current\_stage automatically when the round completes.

\- Reverse round accepts learner-asked questions (not answers) and scores them on quality — structure, curiosity, role-appropriateness. Use the existing Claude Sonnet call with a new prompt template.

\- Server-side answer cap enforced: max 20 answers per session (matches the spec math + buffer).



Frontend deliverables:

\- Session component fetches /session/{id}/state before rendering each question.

\- Round header shows current stage name and progress: "Behavioural · Question 2 of 4".

\- Reverse round UI switches the flow — learner types a question, not an answer. Copy: "Your turn to interview us. Ask us two questions."

\- Do NOT keep the current frontend-computed stage logic. Backend is source of truth.



Acceptance criteria:

\- Session runs through all seven stages in order for a fresher-level test session.

\- POSTing an answer to /session/turn when the state is READOUT returns 409.

\- Skipping a stage (e.g. POSTing behavioural answer while state is WARMUP) returns 409.

\- Reverse-round questions receive a quality score in the debrief JSON.



═══════════════════════════════════════════════

PHASE 3 — INT-01 · Confidence rating (1–5) per answer

═══════════════════════════════════════════════

After every scored answer, prompt the learner: "How confident are you in that answer?" with a 1-5 tap or keyboard input.



Backend deliverables:

\- New column vyom\_debriefs.answers\[].confidence\_rating (integer 1-5, nullable to allow "prefer not to say").

\- New endpoint POST /session/turn/rating with body { session\_id, answer\_id, rating } — rating validated server-side as 1-5.

\- Double-submit for the same answer\_id is rejected with HTTP 409.

\- The session state machine (from INT-04) knows: after a scored answer, next expected action is a rating, not the next question. Enforce this.



Frontend deliverables:

\- After each answer scores, show a 1-5 rating widget. Minimal UI: five tappable pills labelled 1 through 2 3 4 5 with tiny helper text "1 = not confident, 5 = very confident".

\- Keyboard shortcut 1-5 also works on desktop.

\- Rating cannot be skipped, but "prefer not to say" is a soft option that sets rating to null and advances.

\- Widget disappears from the readout — the calibration output (INT-02) shows there instead.



Upskillize UI rules for the rating widget:

\- No emojis. Use inline SVG line icons only if any icon is used, Lucide-style, 1.6px stroke.

\- Palette: navy #0B1628 for text, gold #C8992A for the selected pill background, teal #00C4A0 for the confirmed state.

\- Plus Jakarta Sans for the widget text, DM Mono for the numerals.



Acceptance criteria:

\- Cannot advance to next question without submitting a rating (or explicitly choosing "prefer not to say").

\- Rating persists in the DB and appears in the debrief JSON.

\- Double-submit blocked.



═══════════════════════════════════════════════

PHASE 4 — INT-03 · Readiness bands replace percentages

═══════════════════════════════════════════════

Remove "Selection chances" and percentage displays from the readout. Replace with the four canonical InterviewIQ bands.



Backend deliverables:

\- Configurable thresholds in backend settings (not hardcoded): Not Ready < 50, Building 50-69, Interview-Ready 70-84, Offer-Ready 85+.

\- Compute overall band per session and per-round band per round.

\- Store band values in vyom\_debriefs.overall\_band and vyom\_debriefs.round\_bands.

\- The raw percentage is still computed and stored internally for later analysis, but never returned to the frontend in the readout payload.

\- Global search-and-remove any user-facing "Selection chances" copy from backend response templates.



Frontend deliverables:

\- Readout displays the band as a pill component using the Upskillize palette:

&#x20; - Offer-Ready → Gold #C8992A background, cream text

&#x20; - Interview-Ready → Teal #00C4A0 background, cream text

&#x20; - Building → Navy #1a2744 background, cream text

&#x20; - Not Ready → Orange #E8521A background, cream text (warning, not failure — do not use red)

\- Band label typeface: Playfair Display, 700 weight, letter-spacing -0.01em.

\- Per-round bands shown alongside overall band.

\- Remove every "%" symbol and every "Selection chances" string from the readout component.

\- Global search across the codebase for "Selection chances" and "%" in copy — remove all instances.



Acceptance criteria:

\- Readout shows a band, not a percentage.

\- Grep the codebase for "Selection chances" returns zero user-facing hits.

\- Colours match the spec above exactly.



═══════════════════════════════════════════════

PHASE 5 — INT-02 · Calibration delta scoring and readout block

═══════════════════════════════════════════════

This is the InterviewIQ differentiator. Compare each learner rating against the LLM's independent quality score and produce a calibration profile.



Backend deliverables:

\- New scoring function per answer:

&#x20; - Well-calibrated: absolute delta between rating and normalised score ≤ 1

&#x20; - Over-confident: rating ≥ 4 AND normalised score ≤ 2

&#x20; - Under-confident: rating ≤ 2 AND normalised score ≥ 4

&#x20; - (Answers with null rating are excluded from the calibration profile.)

\- Session-level calibration\_profile computed as the modal category across all answers with ratings. If a tie, prefer over-confident (it's the pattern we care about flagging).

\- Store per\_answer\_calibration array and session calibration\_profile in vyom\_debriefs.

\- Compute three summary numbers: avg\_confidence (1-5), avg\_score (1-5 normalised), calibration\_delta (avg\_confidence - avg\_score, one decimal).



Frontend deliverables:

\- New readout block below the band section: "Calibration Profile".

\- Show three tiles: Your Average Confidence, Your Average Score, Your Calibration Delta.

\- Below the tiles, show the calibration profile category as a pill:

&#x20; - Well-calibrated → Teal #00C4A0 pill, copy: "Your confidence matches your quality. Keep it."

&#x20; - Over-confident → Orange #E8521A pill, copy: "This is the pattern panels reject. Your confidence outran your answers."

&#x20; - Under-confident → Gold #C8992A pill, copy: "Your answers were stronger than you thought. This is coachable."

\- Never use punitive copy. Coach, don't grade down.

\- Typography rules from INT-03 apply. DM Mono for the three summary numbers.



Acceptance criteria:

\- Calibration Profile block renders in the readout beneath the band.

\- Over-confident sessions get the orange pill and the specific copy.

\- Sessions with all null ratings show the calibration block gracefully as "Not enough data" — do not crash.



═══════════════════════════════════════════════

PHASE 6 — VERIFY \& REPORT

═══════════════════════════════════════════════

Verification:

\- Run through the complete happy path manually against a running dev server: create a session as fresher, answer 15 questions with mixed confidence ratings, complete the reverse round, view the readout.

\- Confirm: band renders, calibration block renders with correct pill, stage transitions blocked when out of order, rating widget appears after every answer.

\- Try to break the flow: POST answer directly when stage is REVERSE, POST rating twice for same answer, POST answer when session is DONE. Each must return 409.

\- Grep the codebase for "Selection chances" — must be zero user-facing hits.



Create SPEC\_ALIGNMENT\_REPORT.md in the project root, plain English (business analyst reader, not engineer). Structure:



1\. What shipped — the four tickets, one line each, files touched

2\. What did NOT ship — items deferred (INT-05 full FSM refactor, INT-06 refresh, INT-07 DPDPA) and why

3\. New database columns and tables — plain description of what got added

4\. New API endpoints — one line each

5\. UI changes visible to learners — the four things a learner will see differently

6\. Manual test log — what I tested, what passed, what needs UAT from Haritha

7\. Known gaps — any place where the implementation differs from the spec, why, and how to close it

8\. Deploy checklist — steps to safely roll this out on HuggingFace Spaces



At the end, print the file path to SPEC\_ALIGNMENT\_REPORT.md.



Rules for all phases:

\- If a fix would take more than 40 lines and involves a product decision, STOP and list it in the report under "Needs Haritha's decision" — do not guess.

\- After each ticket, run any tests that exist and print pass/fail. If no tests exist for that area (likely), note it.

\- Never touch the DPDPA area, never add STT/TTS code, never rename vyom\_ tables.

\- Every UI string must use the Upskillize brand voice: direct, coaching, never punitive, no emojis.



Begin Phase 1 now.

