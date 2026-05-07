import { test } from "node:test";
import assert from "node:assert/strict";
import { createPaneState } from "./state.js";

test("createPaneState: initializes with system message", () => {
  const s = createPaneState("hello");
  assert.equal(s.systemPrompt, "hello");
  assert.deepEqual(s.messages, [{ role: "system", content: "hello" }]);
});

test("addUser appends a user message", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  assert.deepEqual(s.messages, [
    { role: "system", content: "sp" },
    { role: "user", content: "hi" },
  ]);
});

test("addAssistant appends an assistant message", () => {
  const s = createPaneState("sp");
  s.addAssistant("ok");
  assert.deepEqual(s.messages[1], { role: "assistant", content: "ok" });
});

test("reset clears back to just the system message", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  s.addAssistant("ok");
  s.reset();
  assert.deepEqual(s.messages, [{ role: "system", content: "sp" }]);
});

test("applyPrompt replaces the prompt and clears history", () => {
  const s = createPaneState("old");
  s.addUser("hi");
  s.applyPrompt("new");
  assert.equal(s.systemPrompt, "new");
  assert.deepEqual(s.messages, [{ role: "system", content: "new" }]);
});

test("buildTurnMessages with null returns a copy of messages, not the live array", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  const turn = s.buildTurnMessages(null);
  assert.deepEqual(turn, s.messages);
  assert.notStrictEqual(turn, s.messages);
});

test("buildTurnMessages splices the vault message after system", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  const vault = { role: "system", content: "vault" };
  const turn = s.buildTurnMessages(vault);
  assert.deepEqual(turn, [
    { role: "system", content: "sp" },
    { role: "system", content: "vault" },
    { role: "user", content: "hi" },
  ]);
  // Original messages must NOT be mutated — vault injection is ephemeral.
  assert.deepEqual(s.messages, [
    { role: "system", content: "sp" },
    { role: "user", content: "hi" },
  ]);
});

test("popLastUser removes only a trailing user message", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  s.addAssistant("ok");
  s.addUser("second");
  // Messages: [system, user, assistant, user]
  assert.equal(s.popLastUser(), true);
  assert.deepEqual(s.messages, [
    { role: "system", content: "sp" },
    { role: "user", content: "hi" },
    { role: "assistant", content: "ok" },
  ]);
  // Next pop should be a no-op (tail is assistant, not user).
  assert.equal(s.popLastUser(), false);
  assert.equal(s.messages.length, 3);
});

test("loadSnapshot replaces systemPrompt and messages atomically", () => {
  const s = createPaneState("old prompt");
  s.addUser("hi");
  s.addAssistant("there");
  s.loadSnapshot({
    systemPrompt: "new prompt",
    messages: [
      { role: "system", content: "new prompt" },
      { role: "user", content: "resumed" },
    ],
  });
  assert.equal(s.systemPrompt, "new prompt");
  assert.deepEqual(s.messages, [
    { role: "system", content: "new prompt" },
    { role: "user", content: "resumed" },
  ]);
});

test("subscribe fires after mutating methods; unsubscribe stops notifications", () => {
  const s = createPaneState("sp");
  let calls = 0;
  const unsub = s.subscribe(() => calls++);

  s.addUser("a");
  s.addAssistant("b");
  s.reset();
  s.applyPrompt("new");
  s.loadSnapshot({ systemPrompt: "x", messages: [{ role: "system", content: "x" }] });

  const beforeUnsub = calls;
  assert.ok(beforeUnsub >= 5, `expected ≥5 notifications before unsub, got ${beforeUnsub}`);

  unsub();
  s.addUser("after-unsub");
  assert.equal(calls, beforeUnsub, "post-unsubscribe mutations must not notify");
});
