/**
 * Room-clock tests. Run with:  npm run test:room   (node --test, no new deps)
 *
 * These pin the promise the E7.7 fix exists to keep: an expired clock never strands the
 * candidate. Whatever they managed to get out is submitted; if they got nothing out, the
 * interview moves on anyway; and only a genuinely dead room wraps the session.
 */
import test from "node:test";
import assert from "node:assert/strict";
import {
  questionSeconds, expiryAction, shouldArmAbandon,
  QUESTION_SECONDS, DEFAULT_QUESTION_SECONDS,
  CAMERA_GRACE_MS, SILENT_ABANDON_MS,
} from "./roomPolicy.js";

// ── The per-question budget ────────────────────────────────────────────────

test("each round gets its own budget; an unknown round falls back, never to zero", () => {
  assert.equal(questionSeconds("CASE"), QUESTION_SECONDS.CASE);
  assert.equal(questionSeconds("warmup"), QUESTION_SECONDS.WARMUP);   // case-insensitive
  assert.equal(questionSeconds("READOUT"), DEFAULT_QUESTION_SECONDS);
  assert.equal(questionSeconds(""), DEFAULT_QUESTION_SECONDS);
  assert.equal(questionSeconds(undefined), DEFAULT_QUESTION_SECONDS);
  // A zero budget would expire every question the instant it was asked.
  for (const v of Object.values(QUESTION_SECONDS)) assert.ok(v > 0);
});

// ── Expiry with something captured -> submit it ────────────────────────────

test("a partial transcript is submitted as the answer, not thrown away", () => {
  const a = expiryAction({ partial: "We'd cap exposure per borrower and re-price the" });
  assert.equal(a.timeout, "partial");
  assert.equal(a.text, "We'd cap exposure per borrower and re-price the");
});

test("a typed draft counts just as much as speech", () => {
  const a = expiryAction({ draft: "  I'd start by segmenting the book  " });
  assert.equal(a.timeout, "partial");
  assert.equal(a.text, "I'd start by segmenting the book");     // trimmed
});

test("speech wins over a stale draft — it is the more recent act", () => {
  const a = expiryAction({ partial: "spoken words", draft: "abandoned draft" });
  assert.equal(a.text, "spoken words");
});

test("a long partial is clamped to the field limit", () => {
  const a = expiryAction({ partial: "x".repeat(5000) });
  assert.equal(a.text.length, 4000);
});

// ── Expiry with nothing captured -> a skip, and the interview moves on ─────

test("nothing captured is a skip, and a skip sends no text", () => {
  for (const input of [{}, { partial: "", draft: "" }, { partial: "   ", draft: "\n" }, undefined]) {
    const a = expiryAction(input);
    assert.equal(a.timeout, "skip", `for ${JSON.stringify(input)}`);
    assert.equal(a.text, "");
  }
});

test("the two outcomes are the only two outcomes", () => {
  // There is no third branch where nothing is posted and the mic sits in "Waiting…".
  // That state was the dead end; it does not exist here.
  for (const a of [expiryAction({ partial: "something" }), expiryAction({})]) {
    assert.ok(["partial", "skip"].includes(a.timeout));
  }
});

// ── Abandonment: only a genuinely dead room wraps ──────────────────────────

const DEAD = { inRoom: true, answerDue: true, micOn: false, typedChars: 0 };

test("mic muted, nothing typed, answer due — that is abandonment", () => {
  assert.equal(shouldArmAbandon(DEAD), true);
});

test("an unmuted mic is never abandonment — silence there is thinking", () => {
  assert.equal(shouldArmAbandon({ ...DEAD, micOn: true }), false);
});

test("typing keeps the interview alive — typed answers are first-class", () => {
  assert.equal(shouldArmAbandon({ ...DEAD, typedChars: 1 }), false);
});

test("no clock runs when no answer is due, or outside the room", () => {
  assert.equal(shouldArmAbandon({ ...DEAD, answerDue: false }), false);   // e.g. rating due
  assert.equal(shouldArmAbandon({ ...DEAD, inRoom: false }), false);      // typed-only mode
  assert.equal(shouldArmAbandon(), false);
});

// ── The numbers the spec fixed ────────────────────────────────────────────

test("the device-policy clocks are the ones the policy promised", () => {
  assert.equal(CAMERA_GRACE_MS, 60_000);      // 60s camera grace
  assert.equal(SILENT_ABANDON_MS, 90_000);    // 90s both-channels-silent
});
