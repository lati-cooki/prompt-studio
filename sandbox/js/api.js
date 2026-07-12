function getApiBase() {
  if (typeof window !== "undefined" && window.PROMPT_STUDIO_API_BASE) {
    return window.PROMPT_STUDIO_API_BASE;
  }
  return "http://localhost:8000/api";
}

// Builds an Error for a non-OK response, enriched with the server's JSON
// `error`/`use` fields when present (e.g. the promotion-flow guard's 409
// bodies) instead of swallowing them behind a generic message.
async function httpError(res, fallbackMsg) {
  let detail = "";
  try {
    const body = await res.json();
    const parts = [body?.error, body?.use].filter(Boolean);
    if (parts.length) detail = `: ${parts.join(" — ")}`;
  } catch {
    // response body wasn't JSON (or was empty) — fall back to the plain message
  }
  return new Error(`${fallbackMsg}${detail}`);
}

export async function fetchSessions() {
  const res = await fetch(`${getApiBase()}/sessions`);
  if (!res.ok) throw await httpError(res, "Failed to fetch sessions");
  return res.json();
}

export async function saveSession(sessionData) {
  const res = await fetch(`${getApiBase()}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sessionData)
  });
  if (!res.ok) throw await httpError(res, "Failed to save session");
  return res.json();
}

export async function renameSession(id, name) {
  const res = await fetch(`${getApiBase()}/sessions/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  if (!res.ok) throw await httpError(res, "Failed to rename session");
  return res.json();
}

export async function deleteSession(id) {
  const res = await fetch(`${getApiBase()}/sessions/${id}`, {
    method: "DELETE"
  });
  if (!res.ok) throw await httpError(res, "Failed to delete session");
  return res.json();
}

export async function fetchPrompts() {
  const res = await fetch(`${getApiBase()}/prompts`);
  if (!res.ok) throw await httpError(res, "Failed to fetch prompts");
  return res.json();
}

export async function savePrompt(promptData) {
  const res = await fetch(`${getApiBase()}/prompts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(promptData),
  });
  if (!res.ok) throw await httpError(res, "Failed to save prompt");
  return res.json();
}

export async function updatePrompt(id, fields) {
  const res = await fetch(`${getApiBase()}/prompts/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!res.ok) throw await httpError(res, "Failed to update prompt");
  return res.json();
}

export async function deletePrompt(id) {
  const res = await fetch(`${getApiBase()}/prompts/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await httpError(res, "Failed to delete prompt");
  return res.json();
}

export async function saveDraftPrompt(id, body) {
  const res = await fetch(`${getApiBase()}/prompts/${id}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw await httpError(res, "Failed to save draft");
  return res.json();
}
