# QA_SWEEP_PHASE_PROMPT.md — full audit, TEST-ONLY, no fixes
# Mission: drive the ENTIRE product and produce a complete defect register.
# DO NOT FIX ANYTHING in this sprint — find, document, prove. Harness code
# may be committed under tests/; product code untouched. No screenshots in
# git. No hf push.

1. THE MODE CONTRACT MATRIX — test every cell and assert it. For each mode:
   TEXT:  pre-flight has NO device UI/copy; zero getUserMedia calls; TTS
          OFF (zero /session/speech audio, zero clip fetches, zero Sarvam
          TTS spend); typing drawer primary; no mic/camera buttons; persona
          never says mute/mic; nudges patient per typing (see item 3);
          scored on content only, no Delivery metrics.
   AUDIO: pre-flight asks MIC ONLY (no camera request, no camera copy);
          TTS ON (audio bytes returned + played); STT captures speech;
          self-captions from Saarika; no camera button; Delivery metrics
          from voice.
   VIDEO: pre-flight asks mic+camera; self-view renders; everything AUDIO
          has; presence NOT computed (Phase D dark).
   Record every deviation as a defect with evidence.

2. AUDIO PIPELINE END-TO-END (her #1 complaint): separate the layers with
   evidence — (a) does /session/speech return real audio bytes (server/
   Sarvam layer)? (b) does the client create and play the audio element
   (app layer)? (c) is playback blocked (autoplay/permission layer — the
   "Tap to enable audio" path)? Same three layers for input: getUserMedia
   granted? bytes captured (RMS>0)? STT returns transcript? For each layer:
   PASS/FAIL with log evidence, so "audio not working" becomes a named
   layer, not a mystery.

3. CONVERSATION PACING: in each mode, measure — time from question to
   first nudge with an idle student; nudge frequency; whether typing
   suppresses nudges; whether the open question ever gets replaced while
   the student's turn is open; escalation triggers. Compare against: voice
   nudges follow silence rules; TEXT nudges only after 60-90s true idle,
   max one per question, never escalation from slow typing.

4. FULL-SESSION COMPLETION per mode: complete one full session in each
   mode through /session/end → verify readout renders as ONE document,
   debrief row has non-null benchmark + weights_version + mode recorded,
   history row correct.

5. KNOWN-SUSPECT LIST — verify each and include in the register with
   status (confirmed/fixed/not-reproducible): stale role on pre-flight;
   pre-flight top gap; "you're on mute" in TEXT; DRAFT NOTICE visible;
   engagement rebuke fired by typing speed; per-question timer visible
   while student engaged; cold-start lobby delay.

6. DELIVERABLE — docs/QA_BUG_REGISTER.md: every defect as
   ID | severity (LAUNCH-BLOCKER / MAJOR / MINOR / COSMETIC) | mode(s) |
   what happens | what should happen | repro steps | evidence file |
   suspected layer (frontend/backend/vendor/browser-setting).
   Ranked launch-blockers first. End with a one-page summary: is each mode
   shippable to 2,500 students next week, yes/no, and what must be fixed
   first.