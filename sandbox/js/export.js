export function buildMarkdown(snapshot, exportedName) {
  const { panes, vaultConfig } = snapshot;
  const safeName = exportedName.replace(/"/g, '\\"');
  const modelLines = panes.length === 1
    ? [`model: "${panes[0].modelKey}"`]
    : ["models:", `  A: "${panes[0].modelKey}"`, `  B: "${panes[1].modelKey}"`];
  const frontmatter = [
    "---",
    `name: "${safeName}"`,
    `exported: ${new Date().toISOString()}`,
    ...modelLines,
    "vault:",
    `  enabled: ${vaultConfig.enabled}`,
    `  topK: ${vaultConfig.topK}`,
    "---",
    "",
  ].join("\n");

  const sections = panes.map((pane, idx) => {
    const header = panes.length > 1 ? `## Pane ${idx === 0 ? "A" : "B"}\n\n` : "";
    const prompt = pane.systemPrompt
      .split("\n")
      .map(line => `> ${line}`)
      .join("\n");
    const turns = pane.messages
      .filter(m => m.role !== "system")
      .map(m => {
        const label = m.role === "user" ? "**You:**" : "**Assistant:**";
        return `${label}\n\n${m.content}\n`;
      })
      .join("\n");
    return `${header}${prompt}\n\n${turns}`;
  });

  return frontmatter + sections.join("\n");
}

export function buildRegistryDraft(snapshot, paneIndex = 0) {
  const { panes } = snapshot;
  const pane = panes[paneIndex];
  if (!pane) return null;
  const name = snapshot.name || "untitled";
  return {
    id:       slugify(name),
    version:  "1.0.0",
    status:   "draft",
    tier:     "audit",
    body:     pane.systemPrompt,
    use_case: `Draft exported from Sandbox session: ${name}`,
    metadata: {
      exported_at:           new Date().toISOString(),
      original_session_name: name,
      model_key:             pane.modelKey,
    },
  };
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function triggerMarkdownDownload({ filename, markdown }) {
  downloadBlob(new Blob([markdown], { type: "text/markdown;charset=utf-8" }), filename);
}

export function triggerJsonDownload({ filename, json }) {
  downloadBlob(new Blob([JSON.stringify(json, null, 2)], { type: "application/json;charset=utf-8" }), filename);
}

export function renderExportSlot(slot, { onExport }) {
  slot.innerHTML = "";
  const button = document.createElement("button");
  button.textContent = "Export current as Markdown";
  button.className   = "secondary";
  button.style.width = "100%";
  button.addEventListener("click", onExport);
  slot.appendChild(button);
}

export function slugify(name) {
  if (typeof name !== "string") return "prompt-sandbox";
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40) || "prompt-sandbox";
}
