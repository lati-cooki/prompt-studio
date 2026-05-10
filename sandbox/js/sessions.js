import * as api from "./api.js";

export function createSessionsStore() {
  function nowIso() {
    return new Date().toISOString();
  }

  function newId() {
    const rand = Math.random().toString(36).slice(2, 8).padEnd(6, "0");
    return `sess-${Date.now()}-${rand}`;
  }

  return {
    async load() {
      try {
        return await api.fetchSessions();
      } catch (err) {
        console.warn("Failed to load sessions from API:", err);
        return [];
      }
    },

    async save({ name, panes, vaultConfig }) {
      const now = nowIso();
      const entry = {
        id:        newId(),
        name,
        createdAt: now,
        updatedAt: now,
        panes,
        vaultConfig,
      };

      try {
        await api.saveSession(entry);
        return entry;
      } catch (err) {
        console.warn("Failed to save session to API:", err);
        throw err;
      }
    },

    async rename(id, newName) {
      try {
        return await api.renameSession(id, newName);
      } catch (err) {
        console.warn("Failed to rename session via API:", err);
        return null;
      }
    },

    async delete(id) {
      try {
        await api.deleteSession(id);
        return true;
      } catch (err) {
        console.warn("Failed to delete session via API:", err);
        return false;
      }
    },
  };
}

export function resolveModelKey(saved, modelKeys, fallbackKey) {
  if (saved && modelKeys.includes(saved)) return saved;
  if (saved) {
    console.warn(`Unknown modelKey "${saved}" in saved session; falling back to "${fallbackKey}"`);
  }
  return fallbackKey;
}

export function exportToRegistryDraft(session) {
  if (!session?.panes?.length) {
    throw new Error("exportToRegistryDraft: session has no panes");
  }
  const primaryPane = session.panes[0];
  return {
    id:                session.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || "draft",
    version:           "0.1.0",
    status:            "draft",
    tier:              "audit",
    owner:             "unknown",
    body:              primaryPane.systemPrompt,
    use_case:          "Draft exported from sandbox",
    default_model:     primaryPane.modelKey ?? null,
    cost_per_run_usd:  null,
    tokens_prompt_body: null,
    tested_on:         primaryPane.modelKey ? [primaryPane.modelKey] : [],
    eval_status:       "unevaluated",
    composes:          [],
    file:              null,
    notes:             "",
  };
}
