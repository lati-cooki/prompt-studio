import { VAULT_URL } from "./config.js";

export async function pingVaultHealth() {
  const ctrl    = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 2000);
  try {
    const res = await fetch(`${VAULT_URL}/health`, { signal: ctrl.signal });
    return res.ok ? "ok" : "down";
  } catch {
    return "down";
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchVaultContext(query, k) {
  const ctrl    = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 5000);
  try {
    const res = await fetch(`${VAULT_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, k }),
      signal: ctrl.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return { error: `HTTP ${res.status}` };
    const data    = await res.json();
    const results = data.results || [];
    if (results.length === 0) return null;
    const body    = results.map(r => r.text).join("\n---\n");
    const message = {
      role: "system",
      content: `Relevant notes from your vault:\n---\n${body}\n---`,
    };
    return { message, results };
  } catch (err) {
    clearTimeout(timeout);
    return { error: err.name === "AbortError" ? "timeout" : err.message };
  }
}

export async function reindexVault() {
  const res = await fetch(`${VAULT_URL}/reindex`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
