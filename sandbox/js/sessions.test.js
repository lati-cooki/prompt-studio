import { test } from "node:test";
import assert from "node:assert/strict";
import { createSessionsStore, resolveModelKey } from "./sessions.js";

class FakeStorage {
  constructor(seed = {}) { this.data = { ...seed }; }
  getItem(k)       { return Object.prototype.hasOwnProperty.call(this.data, k) ? this.data[k] : null; }
  setItem(k, v)    { this.data[k] = String(v); }
  removeItem(k)    { delete this.data[k]; }
}

const samplePane = { systemPrompt: "sp", messages: [{ role: "system", content: "sp" }] };
const sampleVault = { enabled: false, topK: 5 };

test("load: empty storage returns []", () => {
  const store = createSessionsStore(new FakeStorage());
  assert.deepEqual(store.load(), []);
});

test("load: corrupt JSON returns [] and does not throw", (t) => {
  t.mock.method(console, "warn", () => {});
  const fake = new FakeStorage({ "promptSandbox.sessions": "{not json" });
  const store = createSessionsStore(fake);
  assert.deepEqual(store.load(), []);
  assert.equal(console.warn.mock.callCount(), 1);
});

test("save: prepends new entry with id + timestamps", () => {
  const store = createSessionsStore(new FakeStorage());
  const entry = store.save({ name: "first", panes: [samplePane], vaultConfig: sampleVault });
  assert.match(entry.id, /^sess-\d+-[a-z0-9]{6}$/);
  assert.equal(entry.name, "first");
  assert.match(entry.createdAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(entry.createdAt, entry.updatedAt);
  assert.deepEqual(store.load()[0], entry);
});

test("save: newest entries come first", () => {
  const store = createSessionsStore(new FakeStorage());
  store.save({ name: "one",   panes: [samplePane], vaultConfig: sampleVault });
  store.save({ name: "two",   panes: [samplePane], vaultConfig: sampleVault });
  store.save({ name: "three", panes: [samplePane], vaultConfig: sampleVault });
  const all = store.load();
  assert.deepEqual(all.map(e => e.name), ["three", "two", "one"]);
});

test("save: trims to cap of 100 on overflow", () => {
  const store = createSessionsStore(new FakeStorage());
  for (let i = 0; i < 105; i++) {
    store.save({ name: `n${i}`, panes: [samplePane], vaultConfig: sampleVault });
  }
  const all = store.load();
  assert.equal(all.length, 100);
  // Newest first; oldest 5 dropped.
  assert.equal(all[0].name,  "n104");
  assert.equal(all[99].name, "n5");
});

test("rename: updates name + updatedAt, leaves createdAt alone", async () => {
  const store = createSessionsStore(new FakeStorage());
  const created = store.save({ name: "before", panes: [samplePane], vaultConfig: sampleVault });
  await new Promise(r => setTimeout(r, 10));   // ensure timestamp advances
  const updated = store.rename(created.id, "after");
  assert.equal(updated.name, "after");
  assert.equal(updated.createdAt, created.createdAt);
  assert.notEqual(updated.updatedAt, created.createdAt);
});

test("rename: unknown id returns null", () => {
  const store = createSessionsStore(new FakeStorage());
  assert.equal(store.rename("sess-missing", "x"), null);
});

test("delete: removes by id and returns true", () => {
  const store = createSessionsStore(new FakeStorage());
  const a = store.save({ name: "a", panes: [samplePane], vaultConfig: sampleVault });
  const b = store.save({ name: "b", panes: [samplePane], vaultConfig: sampleVault });
  assert.equal(store.delete(a.id), true);
  assert.deepEqual(store.load().map(e => e.id), [b.id]);
});

test("delete: unknown id returns false", () => {
  const store = createSessionsStore(new FakeStorage());
  assert.equal(store.delete("sess-missing"), false);
});

class QuotaLimitedStorage {
  constructor(maxBytes) { this.data = {}; this.max = maxBytes; }
  getItem(k) { return Object.prototype.hasOwnProperty.call(this.data, k) ? this.data[k] : null; }
  setItem(k, v) {
    const candidate = { ...this.data, [k]: String(v) };
    const size = Object.values(candidate).reduce((n, s) => n + s.length, 0);
    if (size > this.max) {
      const err = new Error("quota");
      err.name = "QuotaExceededError";
      throw err;
    }
    this.data = candidate;
  }
  removeItem(k) { delete this.data[k]; }
}

test("save: on quota error, progressively drops oldest and retries", () => {
  const bigPane = { systemPrompt: "x".repeat(200), messages: [{ role: "system", content: "x".repeat(200) }] };
  const storage = new QuotaLimitedStorage(700);
  const store = createSessionsStore(storage);
  store.save({ name: "one",   panes: [bigPane], vaultConfig: { enabled: false, topK: 5 } });
  store.save({ name: "two",   panes: [bigPane], vaultConfig: { enabled: false, topK: 5 } });
  store.save({ name: "three", panes: [bigPane], vaultConfig: { enabled: false, topK: 5 } });
  const all = store.load();
  assert.ok(all.length >= 1 && all.length <= 2, `expected 1-2 entries after trim, got ${all.length}`);
  assert.equal(all[0].name, "three");
});

test("save: rethrows non-quota errors", () => {
  const storage = {
    getItem: () => null,
    setItem: () => { const e = new Error("disk on fire"); e.name = "IOError"; throw e; },
    removeItem: () => {},
  };
  const store = createSessionsStore(storage);
  assert.throws(
    () => store.save({ name: "x", panes: [{ systemPrompt: "s", messages: [] }], vaultConfig: { enabled: false, topK: 5 } }),
    /disk on fire/,
  );
});

test("resolveModelKey: known key passes through", () => {
  const out = resolveModelKey("gemma-4-26b", ["gemma-4-26b", "llama-3-local"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
});

test("resolveModelKey: missing key returns fallback without warn", (t) => {
  t.mock.method(console, "warn", () => {});
  const out = resolveModelKey(undefined, ["gemma-4-26b"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
  assert.equal(console.warn.mock.callCount(), 0);
});

test("resolveModelKey: unknown key returns fallback and warns", (t) => {
  t.mock.method(console, "warn", () => {});
  const out = resolveModelKey("llama-3-local", ["gemma-4-26b"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
  assert.equal(console.warn.mock.callCount(), 1);
});
