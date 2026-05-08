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
  const { name, panes } = snapshot;
  const pane = panes[paneIndex];
  if (!pane) return null;

  return {
    id: slugify(name),
    version: "1.0.0",
    status: "draft",
    tier: "audit",
    owner: "troy_builds", // Default owner per Registry INDEX.json
    body: pane.systemPrompt,
    use_case: `Draft exported from Sandbox session: ${name}`,
    metadata: {
      exported_at: new Date().toISOString(),
      original_session_name: name,
      model_key: pane.modelKey
    }
  };
}

export function triggerMarkdownDownload({ filename, markdown }) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  downloadBlob(blob, filename);
}

export function triggerJsonDownload({ filename, json }) {
  const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json;charset=utf-8" });
  downloadBlob(blob, filename);
}

function downloadBlob(blob, filename) {
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function renderExportSlot(slot, { onExportMarkdown, onExportRegistry }) {
  slot.innerHTML = "";
  slot.style.display = "flex";
  slot.style.flexDirection = "column";
  slot.style.gap = "4px";

  const mdBtn = document.createElement("button");
  mdBtn.textContent = "Export as Markdown";
  mdBtn.className   = "secondary";
  mdBtn.style.width = "100%";
  mdBtn.addEventListener("click", onExportMarkdown);

  const regBtn = document.createElement("button");
  regBtn.textContent = "Export as Registry Draft (JSON)";
  regBtn.className   = "secondary";
  regBtn.style.width = "100%";
  regBtn.addEventListener("click", onExportRegistry);

  slot.append(mdBtn, regBtn);
}

export function slugify(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40) || "prompt-sandbox";
}
