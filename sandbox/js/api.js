function getApiBase() {
  if (typeof window !== "undefined" && window.PROMPT_STUDIO_API_BASE) {
    return window.PROMPT_STUDIO_API_BASE;
  }
  return "http://localhost:8000/api";
}

export async function fetchSessions() {
  const res = await fetch(`${getApiBase()}/sessions`);
  if (!res.ok) throw new Error("Failed to fetch sessions");
  return res.json();
}

export async function saveSession(sessionData) {
  const res = await fetch(`${getApiBase()}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sessionData)
  });
  if (!res.ok) throw new Error("Failed to save session");
  return res.json();
}

export async function renameSession(id, name) {
  const res = await fetch(`${getApiBase()}/sessions/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  if (!res.ok) throw new Error("Failed to rename session");
  return res.json();
}

export async function deleteSession(id) {
  const res = await fetch(`${getApiBase()}/sessions/${id}`, {
    method: "DELETE"
  });
  if (!res.ok) throw new Error("Failed to delete session");
  return res.json();
}
