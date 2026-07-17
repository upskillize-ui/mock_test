/**
 * Item 7 — the noise/silence answer gate. Run with:  node src/answerGate.test.mjs
 *
 * Pins the promise the fix exists to keep: background noise or a lone stray token never
 * counts as a spoken answer, so nothing is captured or submitted until the student has
 * actually said something. A real answer still passes untouched.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { isSubstantiveAnswer, ANSWER_MIN_WORDS, ANSWER_MIN_CHARS, ANSWER_MIN_MS } from "./roomPolicy.js";

test("a real spoken answer passes", () => {
  assert.equal(isSubstantiveAnswer("I led the migration and it took three weeks.", 8000), true);
  assert.equal(isSubstantiveAnswer("Yes, I did that last year.", 3000), true);
});

test("noise/silence tokens do NOT pass", () => {
  for (const junk of ["", "  ", ".", "...", "um", "you", "okay", "-", "\n", "a"]) {
    assert.equal(isSubstantiveAnswer(junk, 5000), false, `"${junk}" must not count as an answer`);
  }
});

test("punctuation and symbols don't count toward the word floor", () => {
  assert.equal(isSubstantiveAnswer(". . .", 5000), false);
  assert.equal(isSubstantiveAnswer("um , .", 5000), false);   // one real word + punctuation
});

test("a too-brief recording never counts, even with words", () => {
  // A sub-ANSWER_MIN_MS blip that STT still produced text for is not a real answer.
  assert.equal(isSubstantiveAnswer("yes I did", ANSWER_MIN_MS - 1), false);
  assert.equal(isSubstantiveAnswer("yes I did", ANSWER_MIN_MS + 1), true);
});

test("duration defaults to accepted when unknown (classic/partial paths pass their own gate)", () => {
  assert.equal(isSubstantiveAnswer("a full sentence here"), true);   // durationMs defaults to Infinity
});

test("the floors are sane", () => {
  assert.ok(ANSWER_MIN_WORDS >= 2);
  assert.ok(ANSWER_MIN_CHARS >= 4);
  assert.ok(ANSWER_MIN_MS >= 500);
});
