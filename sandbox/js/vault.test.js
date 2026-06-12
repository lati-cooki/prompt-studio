import { test, describe, it, mock, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { pingVaultHealth, fetchVaultContext, reindexVault } from "./vault.js";

describe("Vault API wrappers", () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    mock.restoreAll();
  });

  describe("pingVaultHealth", () => {
    it("returns 'ok' on successful response", async () => {
      global.fetch = mock.fn(() => Promise.resolve({ ok: true }));
      const result = await pingVaultHealth();
      assert.equal(result, "ok");
    });

    it("returns 'down' on non-ok HTTP response", async () => {
      global.fetch = mock.fn(() => Promise.resolve({ ok: false }));
      const result = await pingVaultHealth();
      assert.equal(result, "down");
    });

    it("returns 'down' on fetch error", async () => {
      global.fetch = mock.fn(() => Promise.reject(new Error("Network Error")));
      const result = await pingVaultHealth();
      assert.equal(result, "down");
    });
  });

  describe("fetchVaultContext", () => {
    it("returns formatted system message and results array on success", async () => {
      const mockResults = [
        { text: "Note 1", score: 0.9 },
        { text: "Note 2", score: 0.8 }
      ];
      global.fetch = mock.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ results: mockResults })
      }));

      const result = await fetchVaultContext("test query", 2);

      assert.ok(result);
      assert.deepEqual(result.results, mockResults);
      assert.equal(result.message.role, "system");
      assert.ok(result.message.content.includes("Note 1\n---\nNote 2"));
    });

    it("returns null if results array is empty", async () => {
      global.fetch = mock.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ results: [] })
      }));

      const result = await fetchVaultContext("test query", 2);
      assert.equal(result, null);
    });

    it("returns an error object on non-ok HTTP response", async () => {
      global.fetch = mock.fn(() => Promise.resolve({
        ok: false,
        status: 404
      }));

      const result = await fetchVaultContext("test query", 2);
      assert.deepEqual(result, { error: "HTTP 404" });
    });

    it("returns a 'timeout' error when an AbortError occurs", async () => {
      const abortError = new Error("Abort");
      abortError.name = "AbortError";
      global.fetch = mock.fn(() => Promise.reject(abortError));

      const result = await fetchVaultContext("test query", 2);
      assert.deepEqual(result, { error: "timeout" });
    });

    it("returns the error message for other exceptions", async () => {
      global.fetch = mock.fn(() => Promise.reject(new Error("Network Error")));

      const result = await fetchVaultContext("test query", 2);
      assert.deepEqual(result, { error: "Network Error" });
    });
  });

  describe("reindexVault", () => {
    it("returns JSON payload on successful reindex", async () => {
      const mockData = { status: "success", count: 10 };
      global.fetch = mock.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockData)
      }));

      const result = await reindexVault();
      assert.deepEqual(result, mockData);
    });

    it("throws an Error on non-ok HTTP response", async () => {
      global.fetch = mock.fn(() => Promise.resolve({
        ok: false,
        status: 500
      }));

      await assert.rejects(
        async () => await reindexVault(),
        /HTTP 500/
      );
    });
  });
});
