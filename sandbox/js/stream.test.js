import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSSEBuffer, extractSSEDelta } from "./stream.js";

test("parseSSEBuffer: complete events with trailing blank", () => {
  const buf = "data: 1\n\ndata: 2\n\n";
  const { events, remainder } = parseSSEBuffer(buf);
  assert.deepEqual(events, ["data: 1", "data: 2"]);
  assert.equal(remainder, "");
});

test("parseSSEBuffer: partial trailing event is returned as remainder", () => {
  const buf = "data: 1\n\ndata: par";
  const { events, remainder } = parseSSEBuffer(buf);
  assert.deepEqual(events, ["data: 1"]);
  assert.equal(remainder, "data: par");
});

test("parseSSEBuffer: empty buffer", () => {
  const { events, remainder } = parseSSEBuffer("");
  assert.deepEqual(events, []);
  assert.equal(remainder, "");
});

test("extractSSEDelta: content delta", () => {
  const event = `data: {"choices":[{"delta":{"content":"hello"}}]}`;
  assert.deepEqual(extractSSEDelta(event),
    { reasoning: undefined, content: "hello", done: false, usage: undefined });
});

test("extractSSEDelta: reasoning delta", () => {
  const event = `data: {"choices":[{"delta":{"reasoning":"because"}}]}`;
  assert.deepEqual(extractSSEDelta(event),
    { reasoning: "because", content: undefined, done: false, usage: undefined });
});

test("extractSSEDelta: [DONE] sentinel", () => {
  assert.deepEqual(extractSSEDelta("data: [DONE]"), { done: true });
});

test("extractSSEDelta: non-data line returns null", () => {
  assert.equal(extractSSEDelta("event: ping"), null);
});

test("extractSSEDelta: malformed JSON returns null (and warns)", (t) => {
  t.mock.method(console, "warn", () => {});
  assert.equal(extractSSEDelta("data: {not-json"), null);
  assert.equal(console.warn.mock.callCount(), 1);
});

test("extractSSEDelta: empty delta object yields undefined fields (not null)", () => {
  const event = `data: {"choices":[{"delta":{}}]}`;
  const d = extractSSEDelta(event);
  assert.deepEqual(d, { reasoning: undefined, content: undefined, done: false, usage: undefined });
});

test("extractSSEDelta: usage chunk returns { usage } without reasoning/content", () => {
  const event = `data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":42,"completion_tokens":7,"total_tokens":49}}`;
  const d = extractSSEDelta(event);
  assert.ok(d, "expected a non-null delta");
  assert.equal(d.usage.prompt_tokens,     42);
  assert.equal(d.usage.completion_tokens,  7);
  assert.equal(d.usage.total_tokens,       49);
});

test("extractSSEDelta: content chunk without usage has usage undefined", () => {
  const event = `data: {"choices":[{"delta":{"content":"hi"}}]}`;
  const d = extractSSEDelta(event);
  assert.equal(d.content, "hi");
  assert.equal(d.usage, undefined);
});
