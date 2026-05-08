function oneLinePreview(text) {
  const firstLine = text.split("\n", 1)[0].trim();
  if (firstLine.length <= 80) return firstLine || "(empty prompt)";
  return firstLine.slice(0, 77) + "…";
}

export function createPane({ id, container, initialPrompt, modelKeys = [], initialModelKey = null, registryPrompts = [] }) {
  // ── Section ──────────────────────────────────────────
  const section = document.createElement("section");
  section.className      = "pane";
  section.dataset.paneId = id;

  // ── Prompt header ────────────────────────────────────
  const header = document.createElement("header");
  header.className = "pane-prompt";

  // Label row (single-mode only — compare hides it via CSS)
  const labelRow = document.createElement("div");
  labelRow.className = "pane-label-row";

  const promptLabel = document.createElement("span");
  promptLabel.className   = "pane-prompt-label";
  promptLabel.textContent = "SYSTEM PROMPT";

  // Registry Dropdown
  const regLabel = document.createElement("span");
  regLabel.className = "pane-prompt-label";
  regLabel.style.marginLeft = "auto";
  regLabel.style.marginRight = "8px";
  regLabel.style.opacity = "0.5";
  regLabel.textContent = "Registry:";

  const regSelect = document.createElement("select");
  regSelect.className = "pane-model-select";
  regSelect.style.border = "1px solid var(--hair)";
  regSelect.style.padding = "2px 6px";
  regSelect.style.borderRadius = "3px";
  regSelect.style.maxWidth = "160px";
  
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "— Select —";
  regSelect.appendChild(defaultOpt);

  for (const p of registryPrompts) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `${p.id} v${p.version}`;
    regSelect.appendChild(opt);
  }

  labelRow.appendChild(promptLabel);
  labelRow.appendChild(regLabel);
  labelRow.appendChild(regSelect);

  // Meta row (badge + model select + spacer + meter slot)
  const metaRow = document.createElement("div");
  metaRow.className = "pane-meta-row";

  const badge = document.createElement("span");
  badge.className   = "pane-badge";
  badge.textContent = id;

  const modelSelect = document.createElement("select");
  modelSelect.className = "pane-model-select";
  for (const key of modelKeys) {
    const opt = document.createElement("option");
    opt.value       = key;
    opt.textContent = key;
    if (key === initialModelKey) opt.selected = true;
    modelSelect.appendChild(opt);
  }

  const metaSpacer = document.createElement("span");
  metaSpacer.className = "pane-meta-spacer";

  metaRow.appendChild(badge);
  metaRow.appendChild(modelSelect);
  metaRow.appendChild(metaSpacer);
  // meter.js appends its element to metaRow after this

  // Prompt body (read-only preview, click-to-edit)
  const promptBody = document.createElement("div");
  promptBody.className = "pane-prompt-body";

  const promptGt = document.createElement("span");
  promptGt.className   = "pane-prompt-gt";
  promptGt.textContent = "> ";

  const promptPreviewText = document.createElement("span");
  promptPreviewText.textContent = oneLinePreview(initialPrompt);

  promptBody.appendChild(promptGt);
  promptBody.appendChild(promptPreviewText);

  // Expanded area (textarea + Apply button)
  const expandedArea = document.createElement("div");
  expandedArea.className = "pane-prompt-expanded";
  expandedArea.hidden    = true;

  const textarea = document.createElement("textarea");
  textarea.className  = "pane-prompt-textarea";
  textarea.spellcheck = false;
  textarea.value      = initialPrompt;

  const applyReset = document.createElement("button");
  applyReset.className   = "pane-apply-reset";
  applyReset.textContent = "Apply & Reset";

  expandedArea.appendChild(textarea);
  expandedArea.appendChild(applyReset);

  // Hint line
  const hint = document.createElement("div");
  hint.className = "pane-prompt-hint";
  hint.textContent = "click to collapse · ⌘↵ to apply & reset";

  // Assemble header
  header.appendChild(labelRow);
  header.appendChild(metaRow);
  header.appendChild(promptBody);
  header.appendChild(expandedArea);
  header.appendChild(hint);

  // ── Toggle logic ─────────────────────────────────────
  function enterEditing() {
    header.classList.remove("collapsed");
    header.classList.add("editing");
    expandedArea.hidden = false;
    hint.textContent = "⌘↵ to apply & reset";
    textarea.focus();
  }

  function exitEditing() {
    header.classList.remove("editing");
    expandedArea.hidden = true;
    hint.textContent = "click to collapse · ⌘↵ to apply & reset";
  }

  function toggleCollapsed() {
    if (header.classList.contains("editing")) {
      exitEditing();
    } else {
      header.classList.toggle("collapsed");
    }
  }

  promptBody.addEventListener("click", enterEditing);
  labelRow.addEventListener("click", toggleCollapsed);

  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      applyReset.click();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      exitEditing();
    }
  });

  applyReset.addEventListener("click", exitEditing);

  regSelect.addEventListener("change", () => {
    const selected = registryPrompts.find(p => p.id === regSelect.value);
    if (selected) {
      // Strip markdown headers if they exist (Registry stores them as MD files)
      let body = selected.body;
      if (body.includes("---")) {
         body = body.split("---").pop().trim();
      }
      // Also strip common "## The prompt body" or similar headers
      body = body.replace(/^# .*\n+/gm, "").trim();

      textarea.value = body;
      refreshPreview();
      applyReset.click();
      // Reset dropdown to default
      regSelect.value = "";
    }
  });

  // ── Log ──────────────────────────────────────────────
  const log = document.createElement("main");
  log.className = "pane-log";

  // ── Empty state ───────────────────────────────────────
  const emptyState = document.createElement("div");
  emptyState.className = "empty-state";
  emptyState.innerHTML = `
    <div class="empty-state-inner">
      <div class="empty-tag">— New conversation —</div>
      <div class="empty-hero">A quiet place to<br>iterate on your prompt.</div>
      <div class="empty-body">
        Write a message below to start, or edit the system prompt above.
        Turn on <em>use context</em> to ground responses in notes from your vault.
      </div>
      <div class="empty-shortcuts">
        <span class="kbd-chip">⌘↵ send</span>
        <span class="kbd-chip">⌘K sessions</span>
        <span class="kbd-chip">⌘\\ compare</span>
      </div>
    </div>
  `;
  log.appendChild(emptyState);

  // ── Assemble section ─────────────────────────────────
  section.appendChild(header);
  section.appendChild(log);
  container.appendChild(section);

  // ── Exported API ─────────────────────────────────────
  const refreshPreview = () => {
    promptPreviewText.textContent = oneLinePreview(textarea.value);
  };

  function addBubble(role, text = "") {
    if (emptyState.parentNode === log) log.removeChild(emptyState);

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap " + role;

    const tag = document.createElement("div");
    tag.className   = "bubble-role";
    tag.textContent = role === "user" ? "you" : "assistant";
    wrap.appendChild(tag);

    const el = document.createElement("div");
    el.className  = "bubble " + role;
    el.textContent = text;
    wrap.appendChild(el);

    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  return {
    id,
    section,
    textarea,
    applyReset,
    log,
    refreshPreview,
    modelSelect,

    setModelKey(key) {
      modelSelect.value = key;
    },

    onModelChange(fn) {
      modelSelect.addEventListener("change", () => fn(modelSelect.value));
    },

    addBubble,

    addLogNote(text) {
      const note = document.createElement("div");
      note.className   = "log-note";
      note.textContent = text;
      log.appendChild(note);
    },

    clearLog() {
      log.innerHTML = "";
      log.appendChild(emptyState);
    },

    renderFromMessages(messages) {
      log.innerHTML = "";
      const nonSystem = messages.filter(m => m.role !== "system");
      if (nonSystem.length === 0) {
        log.appendChild(emptyState);
        return;
      }
      for (const msg of nonSystem) {
        addBubble(msg.role, msg.content);
      }
    },

    onUsage: null,
  };
}
