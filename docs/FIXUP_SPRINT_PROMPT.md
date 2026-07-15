# FIXUP_SPRINT_PROMPT.md — close the gaps from the last two reports
# Run BEFORE or WITH the go-live sprint (fresh Claude Code session).
# Small, surgical; keep all suites green.

1. PER-QUESTION TIMER (E7.7 — the "Time is up, no answers given" dead-end):
   On question-timer expiry: partial transcript or typed draft → auto-submit
   as the answer, interviewer responds in persona to an incomplete answer
   ("We're out of time on that one — let's move on."); nothing captured →
   record a skip (non-substantive, no slot consumed), interviewer
   acknowledges neutrally, stage advances automatically. Session-timer
   expiry → EARLY_WRAP. Remove the dead-end UI state; the mic must never
   sit in "Waiting…" after expiry. Tests: expiry-with-partial → submitted;
   expiry-empty → skip+advance; session expiry → wrapped, scored readout.

2. DEVICE-POLICY TIMERS still open from the meetroom sprint: the 60s
   camera grace and the 90s both-channels-silent abandonment timer. Wire
   them to the existing ladder/EARLY_WRAP paths. Tests for both.

3. E6 READOUT RE-ORDER: what-went-well (specific, quoting their answers)
   → Delivery Profile → Presence Profile (when data exists) → the 2–3
   fixes that matter with "try this next time" lines → readiness band
   with the calibration delta explained in one sentence. Mentor voice.
   Debrief-prompt + composition change; take the care it needs.

4. RIYA JOINS THE ROSTER: pose assets arrive as
   frontend/src/interviewers/poses/riya_{listening|smile|intense|thinking}.png
   plus base portrait riya_asking.png (use as her single base image,
   renamed riya.png if the roster expects that convention). Add roster row:
   id "riya", female, temperaments ["Easy","Realistic"]. Her thinking and
   listening files are intentionally the same image (chin-on-hands).
   OPTIONAL ENHANCEMENT (do only if trivial): while speaking with tone
   warm/neutral, on sustained amplitude > 0.65 crossfade to `intense`
   (her emphatic-gesture frame) and revert under 0.4, min 1.5s between
   switches — gives the impression her hands move with her voice.

5. MISSING BASE PORTRAITS: ananya and kavya rows stay commented until the
   maintainer drops their portraits into frontend/src/interviewers/
   (human task — files exist in the design deliverables). When present,
   uncomment; the glob handles the rest.

6. TTS COST GUARD: add a per-session synthesized-seconds counter to the
   delivery metrics we already store, so the 2–3× sentence-split cost is
   MEASURED per session (feeds the Sarvam credits application and the
   fallback decision on the 2-call lever).

Report: FIXUP_SPRINT_REPORT.md — what closed, test deltas, measured TTS
seconds for one full session.
