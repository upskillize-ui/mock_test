/**
 * presenceMetrics.test.mjs — the pure fold from per-frame observations to m1–m8.
 *
 * Runs under `node --test` with zero deps, like posePolicy / roomPolicy / roomLayout.
 * These tests pin the two things that matter most for a report-only, privacy-first
 * feature: the numbers are computed HONESTLY from the observations, and nothing here can
 * emit an emotion word (the labels/behaviour live server-side, but the frame SHAPE this
 * client produces must stay behavioural — booleans and small numbers, never a feeling).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createPresenceAccumulator } from "./presenceMetrics.js";

const frame = (o = {}) => ({ hasFace: true, ...o });

test("no face ever seen -> null (nothing measured, never a penalty)", () => {
  const acc = createPresenceAccumulator();
  acc.addFrame({ hasFace: false });
  acc.addFrame({ hasFace: false, gesturing: true });
  assert.equal(acc.result(60000), null);
});

test("m1 gaze-on-screen is the ratio over frames WITH a face", () => {
  const acc = createPresenceAccumulator();
  for (let i = 0; i < 8; i++) acc.addFrame(frame({ gazeOnScreen: true }));
  for (let i = 0; i < 2; i++) acc.addFrame(frame({ gazeOnScreen: false }));
  // A frame with no face must not dilute the denominator.
  acc.addFrame({ hasFace: false });
  assert.equal(acc.result(60000).m1, 0.8);
});

test("m5 smile balance and m8 framing are face-frame ratios", () => {
  const acc = createPresenceAccumulator();
  for (let i = 0; i < 4; i++) acc.addFrame(frame({ smiling: true, centered: true }));
  for (let i = 0; i < 4; i++) acc.addFrame(frame({ smiling: false, centered: false }));
  const r = acc.result(60000);
  assert.equal(r.m5, 0.5);
  assert.equal(r.m8, 0.5);
});

test("m3 posture events count edge-triggered events, not per frame", () => {
  const acc = createPresenceAccumulator();
  for (let i = 0; i < 100; i++) acc.addFrame(frame());
  acc.addPostureEvent();
  acc.addPostureEvent();
  assert.equal(acc.result(60000).m3, 2);
});

test("m2 steadiness: a still head reads high, a swinging head reads lower", () => {
  const still = createPresenceAccumulator();
  for (let i = 0; i < 20; i++) still.addFrame(frame({ headYaw: 0, headPitch: 0 }));
  assert.equal(still.result(60000).m2, 1);

  const swinging = createPresenceAccumulator();
  for (let i = 0; i < 20; i++) swinging.addFrame(frame({ headYaw: i % 2 ? 20 : -20, headPitch: i % 2 ? 15 : -15 }));
  assert.ok(swinging.result(60000).m2 < 0.5);
});

test("m4 range: a flat face reads low, an animated face reads higher", () => {
  const flat = createPresenceAccumulator();
  for (let i = 0; i < 20; i++) flat.addFrame(frame({ expression: 0.2 }));
  assert.equal(flat.result(60000).m4, 0);

  const animated = createPresenceAccumulator();
  for (let i = 0; i < 20; i++) animated.addFrame(frame({ expression: i % 2 ? 0.05 : 0.35 }));
  assert.ok(animated.result(60000).m4 > 0.5);
});

test("m6 blink rate: a natural rate reads steady, a frozen stare reads lower", () => {
  const natural = createPresenceAccumulator();
  for (let i = 0; i < 100; i++) natural.addFrame(frame({ blink: i % 5 === 0 })); // 20 blinks
  assert.equal(natural.result(60000).m6, 1); // 20/min is inside the natural band

  const frozen = createPresenceAccumulator();
  for (let i = 0; i < 100; i++) frozen.addFrame(frame({ blink: false }));
  assert.equal(frozen.result(60000).m6, 0); // 0/min reads as not-steady
});

test("m7 gesture presence is over ALL frames (hands are visible without a face)", () => {
  const acc = createPresenceAccumulator();
  for (let i = 0; i < 5; i++) acc.addFrame(frame({ gesturing: true }));
  for (let i = 0; i < 5; i++) acc.addFrame(frame({ gesturing: false }));
  assert.equal(acc.result(60000).m7, 0.5);
});

test("all ratios are clamped to [0,1] and rounded", () => {
  const acc = createPresenceAccumulator();
  acc.addFrame(frame({ gazeOnScreen: true, smiling: true, centered: true, gesturing: true }));
  const r = acc.result(60000);
  for (const k of ["m1", "m2", "m4", "m5", "m6", "m7", "m8"]) {
    assert.ok(r[k] >= 0 && r[k] <= 1, `${k}=${r[k]} out of range`);
  }
});

test("the result is ONLY the eight numeric keys — no frame, no landmark, no label", () => {
  const acc = createPresenceAccumulator();
  for (let i = 0; i < 10; i++) acc.addFrame(frame({ gazeOnScreen: true, gesturing: true, headYaw: 1, headPitch: 1, expression: 0.2 }));
  acc.addPostureEvent();
  const r = acc.result(60000);
  assert.deepEqual(Object.keys(r).sort(), ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]);
  for (const k of Object.keys(r)) assert.equal(typeof r[k], "number");
});

test("the accumulator retains no per-frame array (privacy by construction)", () => {
  const acc = createPresenceAccumulator();
  for (let i = 0; i < 50; i++) acc.addFrame(frame({ gazeOnScreen: true }));
  // The public surface is the fold + the two counters — there is no frames list to leak.
  const surface = Object.keys(acc);
  assert.ok(!surface.some((k) => /frame(s)?$/i.test(k) && Array.isArray(acc[k])));
  assert.equal(acc.frameCount, 50);
});
