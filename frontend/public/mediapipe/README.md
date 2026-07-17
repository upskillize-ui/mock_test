# Self-hosted MediaPipe assets (Phase D presence metrics)

These files are served **same-origin** at `/mediapipe/…` so the strict production CSP
(`script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'`) never has to reach a CDN
(requirement D1). `presenceMonitor.js` loads them from here.

## What goes here (NOT committed — large binaries, like the UAT screenshots)

```
public/mediapipe/
  wasm/                         <- @mediapipe/tasks-vision WASM runtime
    vision_wasm_internal.js
    vision_wasm_internal.wasm
    vision_wasm_nosimd_internal.js
    vision_wasm_nosimd_internal.wasm
  face_landmarker.task          <- FaceLandmarker model (~3.8 MB)
  pose_landmarker_lite.task     <- PoseLandmarker (lite) model (~3.1 MB)
```

## How to populate them

From `frontend/`:

```
npm install                                   # brings in @mediapipe/tasks-vision
node ../scripts/fetch_mediapipe_assets.mjs     # copies WASM + downloads the two models
```

The WASM files are copied out of `node_modules/@mediapipe/tasks-vision/wasm` (so the
runtime version always matches the installed package). The two `.task` models are pinned
by URL in the script and land here.

## Deploy note

This is a **deploy step**, exactly like applying a migration: the app ships DARK
(`PRESENCE_METRICS_ENABLED=false`, `VITE_PRESENCE_METRICS` unset), so a build with these
assets absent is completely fine — the monitor silently no-ops. Populate them **before**
the flag is ever flipped on. Nothing student-facing depends on them while the feature is
dark.
