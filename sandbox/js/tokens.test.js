import { test } from "node:test";
import assert from "node:assert/strict";
import { approxTokens, sumMessages, breakdown, computeUsed } from "./tokens.js";

test("approxTokens: empty string is 0", () => {
  assert.equal(approxTokens(""), 0);
});

test("approxTokens: short string rounds up via /4", () => {
  assert.equal(approxTokens("hi"),   1);   // 2 / 4 = 0.5 → 1
  assert.equal(approxTokens("hello"), 2);  // 5 / 4 = 1.25 → 2
  assert.equal(approxTokens("a".repeat(8)), 2);  // 8 / 4 = 2
});

test("approxTokens: long string", () => {
  assert.equal(approxTokens("a".repeat(401)), 101);  // 401 / 4 = 100.25 → 101
});

test("approxTokens: handles non-string input as 0", () => {
  assert.equal(approxTokens(null),      0);
  assert.equal(approxTokens(undefined), 0);
});

test("sumMessages: empty array is 0", () => {
  assert.equal(sumMessages([]), 0);
});

test("sumMessages: sums content + fixed overhead per message", () => {
  const msgs = [
    { role: "system",    content: "a".repeat(8) },   // 2 tokens + 3 overhead = 5
    { role: "user",      content: "b".repeat(8) },   // 2 + 3 = 5
    { role: "assistant", content: "c".repeat(8) },   // 2 + 3 = 5
  ];
  assert.equal(sumMessages(msgs), 15);
});

test("sumMessages: skips falsy content but still counts overhead", () => {
  const msgs = [
    { role: "assistant", content: "" },
    { role: "user",      content: null },
  ];
  assert.equal(sumMessages(msgs), 6);   // 0 + 3 + 0 + 3
});

test("breakdown: returns system, history, draft, totalExact, totalApprox", () => {
  const messages = [
    { role: "system",    content: "a".repeat(40) },  // system: 10 + 3 = 13
    { role: "user",      content: "b".repeat(40) },  // history: 10 + 3 = 13
    { role: "assistant", content: "c".repeat(40) },  // history: 10 + 3 = 13
  ];
  const out = breakdown({ messages, draftText: "d".repeat(20), exactPromptTokens: 42 });
  assert.equal(out.system,       13);
  assert.equal(out.history,      26);   // two non-system messages
  assert.equal(out.draft,        5);    // 20 / 4
  assert.equal(out.totalExact,   42);
  assert.equal(out.totalApprox,  13 + 26 + 5);   // full approximate path
});

test("breakdown: messages with no system prefix returns system: 0", () => {
  const messages = [
    { role: "user", content: "x".repeat(8) },
  ];
  const out = breakdown({ messages, draftText: "", exactPromptTokens: 0 });
  assert.equal(out.system,       0);
  assert.equal(out.history,      5);    // 2 + 3
  assert.equal(out.draft,        0);
  assert.equal(out.totalApprox,  5);
});

test("computeUsed: no anchor → pure approx path", () => {
  const messages = [
    { role: "system", content: "a".repeat(40) },   // 10 + 3 = 13
    { role: "user",   content: "b".repeat(40) },   // 10 + 3 = 13
  ];
  const out = computeUsed({
    exactPromptTokens: 0,
    anchorMessageCount: 0,
    anchorSystemPrompt: null,
    messages,
    systemPrompt: "a".repeat(40),
    draftText: "d".repeat(20),     // 5
  });
  assert.equal(out.used, 13 + 13 + 5);
  assert.equal(out.anchorValid, false);
});

test("computeUsed: anchored and still valid → exact + slice-post-anchor + draft", () => {
  const messages = [
    { role: "system",    content: "sys" },
    { role: "user",      content: "u1" },
    { role: "assistant", content: "a1" },
    { role: "user",      content: "u2".repeat(4) },   // 8 chars → 2 + 3 = 5
  ];
  const out = computeUsed({
    exactPromptTokens: 100,
    anchorMessageCount: 3,          // anchor was set at end of turn 1
    anchorSystemPrompt: "sys",
    messages,
    systemPrompt: "sys",
    draftText: "",
  });
  // 100 (exact) + sumMessages(messages.slice(3)) + 0 draft
  assert.equal(out.used, 100 + 5);
  assert.equal(out.anchorValid, true);
});

test("computeUsed: anchor invalidated when messages shrink below anchor count", () => {
  const messages = [
    { role: "system", content: "sys" },
    { role: "user",   content: "u" },
  ];
  const out = computeUsed({
    exactPromptTokens: 50,
    anchorMessageCount: 4,          // was set when history was longer
    anchorSystemPrompt: "sys",
    messages,
    systemPrompt: "sys",
    draftText: "",
  });
  assert.equal(out.anchorValid, false);
  // Falls back to approx: sumMessages([sys, u]) = (1+3) + (1+3) = 8
  assert.equal(out.used, 8);
});

test("computeUsed: anchor invalidated when systemPrompt changed", () => {
  const messages = [
    { role: "system", content: "new-sys" },
    { role: "user",   content: "u" },
    { role: "assistant", content: "a" },
  ];
  const out = computeUsed({
    exactPromptTokens: 50,
    anchorMessageCount: 2,
    anchorSystemPrompt: "old-sys",
    messages,
    systemPrompt: "new-sys",
    draftText: "",
  });
  assert.equal(out.anchorValid, false);
  assert.equal(out.used, (2+3) + (1+3) + (1+3));   // 12, approx full
});

test("computeUsed: includes draftText in both paths", () => {
  const base = {
    messages: [{ role: "system", content: "sys" }],
    systemPrompt: "sys",
    draftText: "d".repeat(40),      // 10 tokens
  };
  const approx = computeUsed({ ...base, exactPromptTokens: 0, anchorMessageCount: 0, anchorSystemPrompt: null });
  const exact  = computeUsed({ ...base, exactPromptTokens: 100, anchorMessageCount: 1, anchorSystemPrompt: "sys" });
  assert.equal(approx.used, (1+3) + 10);
  assert.equal(exact.used,  100 + 0 + 10);   // nothing after anchor, + draft
});
