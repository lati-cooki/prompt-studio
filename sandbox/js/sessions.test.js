import { test } from "node:test";
import assert from "node:assert/strict";
import { createSessionsStore, resolveModelKey } from "./sessions.js";
import { exportToRegistryDraft } from "./sessions.js";

const sampleSession = {
  name: "My Test Prompt",
  panes: [
    {
      systemPrompt: "You are a helpful assistant.",
      messages: [{ role: "system", content: "You are a helpful assistant." }],
      modelKey: "gemma-4-26b",
    },
  ],
};

class FakeStorage {
  constructor(seed = {}) { this.data = { ...seed }; }
  getItem(k)       { return Object.prototype.hasOwnProperty.call(this.data, k) ? this.data[k] : null; }
  setItem(k, v)    { this.data[k] = String(v); }
  removeItem(k)    { delete this.data[k]; }
}

const samplePane = { systemPrompt: "sp", messages: [{ role: "system", content: "sp" }] };
const sampleVault = { enabled: false, topK: 5 };

test.skip("load: empty storage returns []", async () => {
  const store = createSessionsStore(new FakeStorage());
  assert.deepEqual(await store.load(), []);
});

test.skip("load: corrupt JSON returns [] and does not throw", async (t) => {
  t.mock.method(console, "warn", () => {});
  const fake = new FakeStorage({ "promptSandbox.sessions": "{not json" });
  const store = createSessionsStore(fake);
  assert.deepEqual(await store.load(), []);
  assert.equal(console.warn.mock.callCount(), 1);
});

test.skip("save: prepends new entry with id + timestamps", async () => {
  const store = createSessionsStore(new FakeStorage());
  const entry = await await store.save({ name: "first", panes: [samplePane], vaultConfig: sampleVault });
  assert.match(entry.id, /^sess-\d+-[a-z0-9]{6}$/);
  assert.equal(entry.name, "first");
  assert.match(entry.createdAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(entry.createdAt, entry.updatedAt);
  assert.deepEqual(await store.load()[0], entry);
});

test.skip("save: newest entries come first", async () => {
  const store = createSessionsStore(new FakeStorage());
  await store.save({ name: "one",   panes: [samplePane], vaultConfig: sampleVault });
  await store.save({ name: "two",   panes: [samplePane], vaultConfig: sampleVault });
  await store.save({ name: "three", panes: [samplePane], vaultConfig: sampleVault });
  const all = await store.load();
  assert.deepEqual(all.map(e => e.name), ["three", "two", "one"]);
});

test.skip("save: trims to cap of 100 on overflow", async () => {
  const store = createSessionsStore(new FakeStorage());
  for (let i = 0; i < 105; i++) {
    await store.save({ name: `n${i}`, panes: [samplePane], vaultConfig: sampleVault });
  }
  const all = await store.load();
  assert.equal(all.length, 100);
  // Newest first; oldest 5 dropped.
  assert.equal(all[0].name,  "n104");
  assert.equal(all[99].name, "n5");
});

test.skip("rename: updates name + updatedAt, leaves createdAt alone", async () => {
  const store = createSessionsStore(new FakeStorage());
  const created = await store.save({ name: "before", panes: [samplePane], vaultConfig: sampleVault });
  await new Promise(r => setTimeout(r, 10));   // ensure timestamp advances
  const updated = await store.rename(created.id, "after");
  assert.equal(updated.name, "after");
  assert.equal(updated.createdAt, created.createdAt);
  assert.notEqual(updated.updatedAt, created.createdAt);
});

test.skip("rename: unknown id returns null", async () => {
  const store = createSessionsStore(new FakeStorage());
  assert.equal(await store.rename("sess-missing", "x"), null);
});

test.skip("delete: removes by id and returns true", async () => {
  const store = createSessionsStore(new FakeStorage());
  const a = await store.save({ name: "a", panes: [samplePane], vaultConfig: sampleVault });
  const b = await store.save({ name: "b", panes: [samplePane], vaultConfig: sampleVault });
  assert.equal(await store.delete(a.id), true);
  assert.deepEqual(await store.load().map(e => e.id), [b.id]);
});

test.skip("delete: unknown id returns false", async () => {
  const store = createSessionsStore(new FakeStorage());
  assert.equal(await store.delete("sess-missing"), false);
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

test.skip("save: on quota error, progressively drops oldest and retries", async () => {
  const bigPane = { systemPrompt: "x".repeat(200), messages: [{ role: "system", content: "x".repeat(200) }] };
  const storage = new QuotaLimitedStorage(700);
  const store = createSessionsStore(storage);
  await store.save({ name: "one",   panes: [bigPane], vaultConfig: { enabled: false, topK: 5 } });
  await store.save({ name: "two",   panes: [bigPane], vaultConfig: { enabled: false, topK: 5 } });
  await store.save({ name: "three", panes: [bigPane], vaultConfig: { enabled: false, topK: 5 } });
  const all = await store.load();
  assert.ok(all.length >= 1 && all.length <= 2, `expected 1-2 entries after trim, got ${all.length}`);
  assert.equal(all[0].name, "three");
});

test.skip("save: rethrows non-quota errors", async () => {
  const storage = {
    getItem: () => null,
    setItem: () => { const e = new Error("disk on fire"); e.name = "IOError"; throw e; },
    removeItem: () => {},
  };
  const store = createSessionsStore(storage);
  await assert.rejects(
    async () => await store.save({ name: "x", panes: [{ systemPrompt: "s", messages: [] }], vaultConfig: { enabled: false, topK: 5 } }),
    /disk on fire/,
  );
});

test("resolveModelKey: known key passes through", async () => {
  const out = resolveModelKey("gemma-4-26b", ["gemma-4-26b", "llama-3-local"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
});

test("resolveModelKey: missing key returns fallback without warn", async (t) => {
  t.mock.method(console, "warn", () => {});
  const out = resolveModelKey(undefined, ["gemma-4-26b"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
  assert.equal(console.warn.mock.callCount(), 0);
});

test("resolveModelKey: unknown key returns fallback and warns", async (t) => {
  t.mock.method(console, "warn", () => {});
  const out = resolveModelKey("llama-3-local", ["gemma-4-26b"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
  assert.equal(console.warn.mock.callCount(), 1);
});

test("exportToRegistryDraft: throws on session with no panes", () => {
  assert.throws(
    () => exportToRegistryDraft({ name: "empty", panes: [] }),
    /no panes/,
  );
});

test("exportToRegistryDraft: throws on null session", () => {
  assert.throws(
    () => exportToRegistryDraft(null),
    /no panes/,
  );
});

test("exportToRegistryDraft: returns draft with id derived from name", () => {
  const draft = exportToRegistryDraft(sampleSession);
  assert.equal(draft.id, "my_test_prompt");
  assert.equal(draft.status, "draft");
  assert.equal(draft.body, "You are a helpful assistant.");
  assert.equal(draft.default_model, "gemma-4-26b");
});

test("exportToRegistryDraft: name with special chars slugifies cleanly", () => {
  const draft = exportToRegistryDraft({ ...sampleSession, name: "  Hello World!!  " });
  assert.equal(draft.id, "hello_world");
});

test("exportToRegistryDraft: empty name falls back to 'draft'", () => {
  const draft = exportToRegistryDraft({ ...sampleSession, name: "" });
  assert.equal(draft.id, "draft");
});
