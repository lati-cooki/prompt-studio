import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import * as api from "./api.js";

describe("api.js", () => {
  let fetchCalls = [];
  let mockResponseOk = true;
  let mockResponseData = { success: true };

  beforeEach(() => {
    fetchCalls = [];
    mockResponseOk = true;
    mockResponseData = { success: true };

    globalThis.fetch = async (url, options) => {
      fetchCalls.push({ url, options });
      return {
        ok: mockResponseOk,
        json: async () => mockResponseData,
      };
    };
  });

  afterEach(() => {
    delete globalThis.fetch;
    delete globalThis.window;
  });

  describe("getApiBase", () => {
    it("returns default url when window is not defined", async () => {
      await api.fetchSessions();
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/sessions");
    });

    it("returns PROMPT_STUDIO_API_BASE when defined", async () => {
      globalThis.window = { PROMPT_STUDIO_API_BASE: "https://custom.api/v1" };
      await api.fetchSessions();
      assert.equal(fetchCalls[0].url, "https://custom.api/v1/sessions");
    });
  });

  describe("API methods - success", () => {
    it("fetchSessions", async () => {
      const res = await api.fetchSessions();
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/sessions");
      assert.equal(fetchCalls[0].options, undefined);
    });

    it("saveSession", async () => {
      const sessionData = { name: "test" };
      const res = await api.saveSession(sessionData);
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/sessions");
      assert.equal(fetchCalls[0].options.method, "POST");
      assert.equal(fetchCalls[0].options.body, JSON.stringify(sessionData));
    });

    it("renameSession", async () => {
      const res = await api.renameSession("id-123", "new name");
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/sessions/id-123");
      assert.equal(fetchCalls[0].options.method, "PUT");
      assert.equal(fetchCalls[0].options.body, JSON.stringify({ name: "new name" }));
    });

    it("deleteSession", async () => {
      const res = await api.deleteSession("id-123");
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/sessions/id-123");
      assert.equal(fetchCalls[0].options.method, "DELETE");
    });

    it("fetchPrompts", async () => {
      const res = await api.fetchPrompts();
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/prompts");
      assert.equal(fetchCalls[0].options, undefined);
    });

    it("savePrompt", async () => {
      const promptData = { title: "prompt1" };
      const res = await api.savePrompt(promptData);
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/prompts");
      assert.equal(fetchCalls[0].options.method, "POST");
      assert.equal(fetchCalls[0].options.body, JSON.stringify(promptData));
    });

    it("updatePrompt", async () => {
      const fields = { title: "updated" };
      const res = await api.updatePrompt("id-456", fields);
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/prompts/id-456");
      assert.equal(fetchCalls[0].options.method, "PUT");
      assert.equal(fetchCalls[0].options.body, JSON.stringify(fields));
    });

    it("deletePrompt", async () => {
      const res = await api.deletePrompt("id-456");
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/prompts/id-456");
      assert.equal(fetchCalls[0].options.method, "DELETE");
    });

    it("saveDraftPrompt", async () => {
      const res = await api.saveDraftPrompt("id-456", "draft body");
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/prompts/id-456/draft");
      assert.equal(fetchCalls[0].options.method, "POST");
      assert.equal(fetchCalls[0].options.body, JSON.stringify({ body: "draft body" }));
    });

    it("validatePrompt", async () => {
      const res = await api.validatePrompt("id-456", "v1.0");
      assert.deepEqual(res, { success: true });
      assert.equal(fetchCalls[0].url, "http://localhost:8000/api/prompts/id-456/v1.0/validate");
      assert.equal(fetchCalls[0].options.method, "POST");
      assert.equal(fetchCalls[0].options.body, JSON.stringify({}));
    });
  });

  describe("API methods - failure", () => {
    beforeEach(() => {
      mockResponseOk = false;
    });

    it("fetchSessions throws error", async () => {
      await assert.rejects(() => api.fetchSessions(), /Failed to fetch sessions/);
    });

    it("saveSession throws error", async () => {
      await assert.rejects(() => api.saveSession({}), /Failed to save session/);
    });

    it("renameSession throws error", async () => {
      await assert.rejects(() => api.renameSession("id", "name"), /Failed to rename session/);
    });

    it("deleteSession throws error", async () => {
      await assert.rejects(() => api.deleteSession("id"), /Failed to delete session/);
    });

    it("fetchPrompts throws error", async () => {
      await assert.rejects(() => api.fetchPrompts(), /Failed to fetch prompts/);
    });

    it("savePrompt throws error", async () => {
      await assert.rejects(() => api.savePrompt({}), /Failed to save prompt/);
    });

    it("updatePrompt throws error", async () => {
      await assert.rejects(() => api.updatePrompt("id", {}), /Failed to update prompt/);
    });

    it("deletePrompt throws error", async () => {
      await assert.rejects(() => api.deletePrompt("id"), /Failed to delete prompt/);
    });

    it("saveDraftPrompt throws error", async () => {
      await assert.rejects(() => api.saveDraftPrompt("id", "body"), /Failed to save draft/);
    });

    it("validatePrompt throws error", async () => {
      await assert.rejects(() => api.validatePrompt("id", "v1"), /Failed to validate prompt/);
    });
  });
});
