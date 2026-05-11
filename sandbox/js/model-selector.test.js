import { test } from "node:test";
import assert from "node:assert/strict";
import { createModelSelectorState } from "./model-selector.js";

test("initial selected keys match initialKeys", () => {
  const state = createModelSelectorState({
    allKeys: ["a", "b", "c"],
    initialKeys: ["a", "b"],
    onChange: () => {},
  });
  assert.deepEqual([...state.selectedKeys()].sort(), ["a", "b"]);
});

test("toggle adds a deselected key", () => {
  const changes = [];
  const state = createModelSelectorState({
    allKeys: ["a", "b"],
    initialKeys: ["a"],
    onChange: (keys) => changes.push([...keys]),
  });
  state.toggle("b");
  assert.ok([...state.selectedKeys()].includes("b"));
  assert.equal(changes.length, 1);
  assert.ok(changes[0].includes("b"));
});

test("toggle removes a selected key", () => {
  const state = createModelSelectorState({
    allKeys: ["a", "b"],
    initialKeys: ["a", "b"],
    onChange: () => {},
  });
  state.toggle("a");
  assert.ok(![...state.selectedKeys()].includes("a"));
});

test("cannot deselect last key — minimum 1 enforced", () => {
  const state = createModelSelectorState({
    allKeys: ["a"],
    initialKeys: ["a"],
    onChange: () => {},
  });
  state.toggle("a");
  assert.ok([...state.selectedKeys()].includes("a"));
});

test("unknown key toggle is a no-op", () => {
  const state = createModelSelectorState({
    allKeys: ["a"],
    initialKeys: ["a"],
    onChange: () => {},
  });
  state.toggle("z");
  assert.deepEqual([...state.selectedKeys()], ["a"]);
});
