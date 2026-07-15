# AVATAR_PHASE_PROMPT.md — InterviewIQ Premium "Video Interviewer" (LiveAvatar Lite)
# Run in Claude Code AFTER the go-live sprint. LIVEAVATAR_API_KEY is in backend/.env.

## What we're building
A premium interviewer tier: a real-time streaming avatar (LiveAvatar by
HeyGen, Lite mode) whose lips speak the ACTUAL Bulbul audio, live. The
existing pose-based interviewer (Riya) remains the free tier and the
automatic fallback. Nothing about the interview brain changes — LiveAvatar
renders a face; our stage machine, persona, Bulbul TTS, and Saarika STT
stay exactly in charge (that is what Lite mode means — do NOT use Full
mode; it would replace our TTS/ASR with theirs).

## Hard rules
1. The API key lives server-side only. The browser NEVER sees it. The
   backend creates the avatar session and hands the client only the
   short-lived session credentials/stream token LiveAvatar returns.
2. Fallback is sacred: ANY avatar failure (session create fails, WebRTC
   drops, quota exhausted, >3s stream stall) silently switches the tile
   to the Riya pose engine mid-interview and the interview continues.
   Log the event; never surface an error wall to the student.
3. Cost discipline: the stream starts at the FIRST QUESTION (lobby and
   pre-join burn zero avatar minutes) and stops at the courteous close
   (the readout page has no face). Track streamed seconds per session in
   the DB for cost reporting.
4. Testing reality: free-tier/entry sessions cap at ~5 minutes. Build a
   dev config (AVATAR_MAX_MINUTES) so pilots run 4-minute mini-interviews
   without hitting the cap mid-question; production tier (1,000-credit
   plan) lifts it to 20.

## Backend
- New module avatar.py: create_avatar_session(session_id) → calls
  LiveAvatar API (Lite mode, chosen avatar_id from env
  LIVEAVATAR_AVATAR_ID) and returns client join info; end_avatar_session;
  both defensive — a LiveAvatar outage must never 500 our own endpoints.
- Audio pipe: wherever Bulbul TTS audio is produced per turn, when the
  session has avatar_mode=true, ALSO forward the audio to the LiveAvatar
  session per their Lite-mode audio-input API (chunked/streamed per their
  docs — read them; do not guess the transport). The room keeps receiving
  our audio events for captions/timing as today.
- Session flag: /session/start accepts avatar_mode; persists on the
  session row with streamed_seconds. Server refuses avatar_mode when the
  feature flag AVATAR_TIER_ENABLED=false or (later) credit balance is
  insufficient — return a clean "tier unavailable" the lobby understands.

## Frontend
- Lobby: when AVATAR_TIER_ENABLED and eligibility passes, show an
  "Interviewer style" choice: Riya (Standard) | Video Interviewer
  (Premium). Default Standard. Persist choice into /session/start.
- Room tile: avatar_mode renders the LiveAvatar WebRTC <video> stream in
  the SAME tile chrome (glow, name chip, thinking arc, listening ring all
  unchanged — they wrap the tile, not the face). Riya poses component
  stays mounted-but-hidden as the hot fallback; rule 2 swap is a state
  flip, not a remount.
- Captions, mic semantics, typing drawer, self-view, device policy:
  untouched. The avatar is a face, not a new room.

## Tests
- avatar session create failure → session starts in pose mode, flagged.
- mid-interview stream drop simulation → tile swaps to poses, interview
  state uninterrupted, event logged.
- avatar_mode=false path is byte-identical to current behavior.
- streamed_seconds accounting matches start-at-first-question /
  stop-at-close rule.

## Report
AVATAR_PHASE_REPORT.md: which LiveAvatar APIs used, avatar_id chosen,
measured added latency (question spoken → lips moving) on a real session,
streamed seconds for one full pilot interview, and the observed per-
interview cost at current pricing.
