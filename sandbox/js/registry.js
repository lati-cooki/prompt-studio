/** Registry helpers — load prompt catalog and bodies from Prompt Studio server. */

export function appUrl(path) {
  const origin =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : "http://localhost:8000";
  return `${origin}${path.startsWith("/") ? path : `/${path}`}`;
}

export function extractPromptBody(markdown) {
  const marker = "## The prompt body";
  const idx = markdown.indexOf(marker);
  if (idx >= 0) {
    let body = markdown.slice(idx + marker.length).trim();
    if (body.startsWith("---")) {
      body = body.replace(/^---\s*\n?/, "").trim();
    }
    return body;
  }
  const parts = markdown.split(/\n---\n/);
  if (parts.length >= 2) {
    return parts[parts.length - 1].trim();
  }
  return markdown.trim();
}

export async function fetchRegistryIndex() {
  const res = await fetch(appUrl("/api/registry"));
  if (!res.ok) {
    throw new Error(`Registry unavailable (HTTP ${res.status}). Run python3 server.py on port 8000.`);
  }
  const data = await res.json();
  return Array.isArray(data.prompts) ? data.prompts : [];
}

export async function fetchRegistryPromptFile(filePath) {
  const res = await fetch(appUrl(`/registry-asset/${filePath}`));
  if (!res.ok) {
    throw new Error(`Prompt file not found: ${filePath}`);
  }
  return res.text();
}

export async function loadRegistryPromptBody(filePath) {
  const markdown = await fetchRegistryPromptFile(filePath);
  return extractPromptBody(markdown);
}

/** Prompts with archived .md files, newest version first per id.
 *  Production-only by default (Rust-channel model); includeDrafts = "nightly". */
export function listLoadablePrompts(prompts, includeDrafts = false) {
  const withFile = prompts.filter(
    (p) => p.file && (includeDrafts || p.status === "production"));
  return withFile.sort((a, b) => {
    const idCmp = a.id.localeCompare(b.id);
    if (idCmp !== 0) return idCmp;
    return b.version.localeCompare(a.version, undefined, { numeric: true });
  });
}