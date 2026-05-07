import { STORAGE_KEY } from "./config.js";

const CAP = 100;

export function createSessionsStore(storage) {
  function readRaw() {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      console.warn("Failed to parse sessions from storage:", err);
      return [];
    }
  }

  function writeRaw(entries) {
    // On QuotaExceededError, progressively drop the oldest entry and retry
    // until it fits or the list is empty. Rethrow anything else.
    while (true) {
      try {
        storage.setItem(STORAGE_KEY, JSON.stringify(entries));
        return;
      } catch (err) {
        const isQuota = err && (
          err.name === "QuotaExceededError" ||
          err.name === "NS_ERROR_DOM_QUOTA_REACHED" ||
          err.code === 22 || err.code === 1014
        );
        if (!isQuota || entries.length === 0) throw err;
        entries.pop();
      }
    }
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function newId() {
    const rand = Math.random().toString(36).slice(2, 8).padEnd(6, "0");
    return `sess-${Date.now()}-${rand}`;
  }

  return {
    load() {
      return readRaw();
    },

    save({ name, panes, vaultConfig }) {
      const now = nowIso();
      const entry = {
        id:        newId(),
        name,
        createdAt: now,
        updatedAt: now,
        panes,
        vaultConfig,
      };
      const entries = readRaw();
      entries.unshift(entry);
      if (entries.length > CAP) entries.length = CAP;
      writeRaw(entries);
      return entry;
    },

    rename(id, newName) {
      const entries = readRaw();
      const entry = entries.find(e => e.id === id);
      if (!entry) return null;
      entry.name = newName;
      entry.updatedAt = nowIso();
      writeRaw(entries);
      return entry;
    },

    delete(id) {
      const entries = readRaw();
      const idx = entries.findIndex(e => e.id === id);
      if (idx === -1) return false;
      entries.splice(idx, 1);
      writeRaw(entries);
      return true;
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
