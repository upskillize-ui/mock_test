/**
 * fetch_mediapipe_assets.mjs — populate frontend/public/mediapipe/ for Phase D.
 *
 * Self-hosting (D1): the WASM runtime and the two .task models must be served from our
 * own origin, never a CDN at session time. This script:
 *   1. copies the WASM runtime out of the INSTALLED @mediapipe/tasks-vision package, so
 *      the runtime version can never drift from the JS the bundle imports; and
 *   2. downloads the two pinned model files.
 *
 * It is a DEPLOY-TIME step, run once per build machine — never at session time. The app
 * ships dark, so it is fine for these assets to be absent until the feature is enabled;
 * the monitor silently no-ops without them.
 *
 * Usage:  (from frontend/, after `npm install`)
 *     node ../scripts/fetch_mediapipe_assets.mjs
 */
import { mkdir, copyFile, readdir, writeFile, access } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "..", "frontend");
const outDir = join(frontend, "public", "mediapipe");
const wasmOut = join(outDir, "wasm");
const wasmSrc = join(frontend, "node_modules", "@mediapipe", "tasks-vision", "wasm");

// Models pinned by URL. These are the Google-hosted model cards; we DOWNLOAD them once
// here and thereafter serve them ourselves. Update the version segment deliberately.
const MODELS = [
  {
    file: "face_landmarker.task",
    url: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
  },
  {
    file: "pose_landmarker_lite.task",
    url: "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
  },
];

async function exists(p) {
  try { await access(p); return true; } catch { return false; }
}

async function copyWasm() {
  if (!(await exists(wasmSrc))) {
    throw new Error(`WASM source not found at ${wasmSrc}. Run \`npm install\` in frontend/ first.`);
  }
  await mkdir(wasmOut, { recursive: true });
  const files = await readdir(wasmSrc);
  for (const f of files) {
    await copyFile(join(wasmSrc, f), join(wasmOut, f));
    console.log(`  wasm: ${f}`);
  }
}

async function downloadModel({ file, url }) {
  const dest = join(outDir, file);
  process.stdout.write(`  model: ${file} … `);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET ${url} -> ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  await writeFile(dest, buf);
  console.log(`${(buf.length / 1e6).toFixed(1)} MB`);
}

async function main() {
  await mkdir(outDir, { recursive: true });
  console.log("Populating self-hosted MediaPipe assets:");
  await copyWasm();
  for (const m of MODELS) await downloadModel(m);
  console.log("Done. These are gitignored (large binaries) — a deploy step, not a commit.");
}

main().catch((e) => { console.error("FAILED:", e.message); process.exit(1); });
