import { STORAGE_KEY } from "./config.js";

const CAP = 100;

export function createSessionsStore(apiUrl = "") {
  return {
    async load() {
      try {
        const res = await fetch(`${apiUrl}/api/sessions`);
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const sessions = await res.json();
        // Map API format to Sandbox format
        return sessions.map(s => ({
          id: s.id,
          name: s.name,
          createdAt: s.created_at,
          updatedAt: s.updated_at,
          panes: s.data?.panes || [],
          vaultConfig: s.data?.vaultConfig || { enabled: false, topK: 5 }
        }));
      } catch (err) {
        console.error("Failed to load sessions from API:", err);
        return [];
      }
    },

    async save({ name, panes, vaultConfig }) {
      const data = { panes, vaultConfig };
      try {
        const res = await fetch(`${apiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            name, 
            pane_count: panes.length, 
            data 
          })
        });
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const result = await res.json();
        return { 
          id: result.id, 
          name, 
          panes, 
          vaultConfig,
          createdAt: new Date().toISOString()
        };
      } catch (err) {
        console.error("Failed to save session to API:", err);
        throw err;
      }
    },

    async rename(id, newName) {
      // Fetch the current session first to get the data blob
      // (Minimal API implementation doesn't support partial updates easily)
      try {
        const sessions = await this.load();
        const entry = sessions.find(s => s.id === id);
        if (!entry) return null;

        const res = await fetch(`${apiUrl}/api/sessions/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: newName,
            pane_count: entry.panes.length,
            data: { panes: entry.panes, vaultConfig: entry.vaultConfig }
          })
        });
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        return { ...entry, name: newName };
      } catch (err) {
        console.error("Failed to rename session in API:", err);
        return null;
      }
    },

    async delete(id) {
      try {
        const res = await fetch(`${apiUrl}/api/sessions/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        return true;
      } catch (err) {
        console.error("Failed to delete session in API:", err);
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
