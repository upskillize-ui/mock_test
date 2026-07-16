# ROOM_UI_PHASE_PROMPT.md — meet-room layout, captions, chat panel
# Rules header: same as VOICE_CAPTURE. Runs in the LMS embed. Copy + layout
# global rules apply with force here: decent spacing and gaps, consistent
# rhythm, ZERO overflow — no clipped text or cut-off elements at any width.

1. TWO EQUAL TILES: interviewer and student side by side like a real video
   call; active-speaker glow (teal ring) follows whoever is talking. Camera
   -off student tile shows initial avatar. Layout holds 1100→1920px.
2. ONE STATUS STRIP: a single SPEAKING / LISTENING (with rec counter) /
   THINKING strip under the tiles replaces the floating state text that
   currently overlaps the name tag.
3. CAPTION AREA FIXED: interviewer captions in a fixed-height, comfortably
   padded area that handles long questions (progressive reveal or inner
   scroll) — never overflows, never clips mid-sentence.
4. STUDENT INPUT SURFACE: when the student speaks, an input surface opens —
   live waveform + running "You:" transcript (from the voice sprint's
   self-captions) → clean "captured ✓-style" state (Lucide-style icon, no
   emoji) before the interviewer responds.
5. CHAT PANEL: collapsible side panel = the full session transcript —
   interviewer questions and student answers as chat bubbles, student can
   type there anytime (typed = spoken). Captured voice answers appear as
   bubbles with a subtle "heard you" tick. Students can re-read any earlier
   question. This panel IS the primary surface for Text mode later — build
   it mode-agnostic. In Text mode the layout stays two-tile: interviewer
   tile + chat panel in the student tile's place.
6. Verify every screen (room, pre-flight, Setup, History, Settings) against
   the global layout rule at 1100/1280/1920 — screenshot each for the
   report.

Report to docs/ROOM_UI_REPORT.md with before/after screenshots list.