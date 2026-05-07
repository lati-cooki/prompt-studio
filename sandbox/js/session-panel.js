export function createSessionPanel({ panelEl, anchor }) {
  const saveSlot   = panelEl.querySelector(".sessions-panel-save");
  const listSlot   = panelEl.querySelector(".sessions-panel-list");
  const exportSlot = panelEl.querySelector(".sessions-panel-export");

  let onDocClick = null;
  let onEscKey   = null;

  function positionBelowAnchor() {
    const rect = anchor.getBoundingClientRect();
    panelEl.style.left = `${rect.left}px`;
    panelEl.style.top  = `${rect.bottom + 4}px`;
  }

  function open() {
    if (!panelEl.hidden) return;
    positionBelowAnchor();
    panelEl.hidden = false;
    anchor.setAttribute("aria-expanded", "true");
    // Close on outside click. Defer until the current event settles so the
    // click that opened the panel doesn't immediately close it.
    setTimeout(() => {
      onDocClick = (e) => {
        if (panelEl.contains(e.target) || anchor.contains(e.target)) return;
        close();
      };
      document.addEventListener("click", onDocClick);
    }, 0);
    onEscKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onEscKey);
  }

  function close() {
    if (panelEl.hidden) return;
    panelEl.hidden = true;
    anchor.setAttribute("aria-expanded", "false");
    if (onDocClick) { document.removeEventListener("click",   onDocClick); onDocClick = null; }
    if (onEscKey)   { document.removeEventListener("keydown", onEscKey);   onEscKey   = null; }
  }

  function toggle() { panelEl.hidden ? open() : close(); }

  anchor.addEventListener("click", toggle);

  return { open, close, toggle, saveSlot, listSlot, exportSlot, isOpen: () => !panelEl.hidden };
}

export function renderSaveSlot(slot, { defaultName, onSave }) {
  slot.innerHTML = "";

  const button = document.createElement("button");
  button.textContent = "Save current…";
  button.className   = "secondary sessions-save-button";
  button.style.width = "100%";

  const form = document.createElement("div");
  form.className = "sessions-save-form";
  form.hidden = true;
  form.style.display = "flex";
  form.style.gap = "6px";

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Name this session";
  input.style.flex = "1";
  input.style.background = "#111";
  input.style.color = "var(--fg)";
  input.style.border = "1px solid var(--border)";
  input.style.borderRadius = "4px";
  input.style.padding = "6px 8px";

  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save";

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Cancel";
  cancelBtn.className = "secondary";

  form.append(input, saveBtn, cancelBtn);
  slot.append(button, form);

  function openForm() {
    input.value = defaultName();
    button.hidden = true;
    form.hidden   = false;
    form.style.display = "flex";
    input.focus();
    input.select();
  }
  function closeForm() {
    button.hidden = false;
    form.hidden   = true;
    form.style.display = "none";
  }
  function commit() {
    const name = input.value.trim();
    if (!name) return;        // require non-empty
    onSave(name);
    closeForm();
  }

  button.addEventListener("click", openForm);
  saveBtn.addEventListener("click", commit);
  cancelBtn.addEventListener("click", closeForm);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter")  { e.preventDefault(); commit();    }
    if (e.key === "Escape") { e.preventDefault(); closeForm(); }
  });
}

export function renderSessionList(slot, entries, { onClick, onDelete }) {
  slot.innerHTML = "";
  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "sessions-empty";
    empty.textContent = "No saved sessions yet.";
    slot.appendChild(empty);
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "sessions-row";
    row.style.padding = "8px 10px";
    row.style.cursor  = "pointer";
    row.style.display = "flex";
    row.style.gap     = "8px";
    row.style.alignItems = "center";
    row.style.borderBottom = "1px solid var(--border)";

    const dots = document.createElement("span");
    dots.textContent = entry.panes
      .map(p => p.messages.length > 1 ? "●" : "○")
      .join("");
    dots.style.color = "var(--muted)";
    dots.style.fontSize = "11px";
    dots.style.width = "22px";

    const name = document.createElement("span");
    name.textContent = entry.name;
    name.style.flex = "1";
    name.style.overflow = "hidden";
    name.style.textOverflow = "ellipsis";
    name.style.whiteSpace = "nowrap";

    const age = document.createElement("span");
    age.textContent = formatAge(entry.createdAt);
    age.style.color = "var(--muted)";
    age.style.fontSize = "11px";

    const del = document.createElement("button");
    del.textContent = "✕";
    del.className   = "secondary";
    del.style.padding = "2px 6px";
    del.style.fontSize = "11px";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      onDelete(entry);
    });

    row.append(dots, name, age, del);
    row.addEventListener("click", () => onClick(entry));
    slot.appendChild(row);
  }
}

function formatAge(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const day    = 86400000;
  const days   = Math.floor(diffMs / day);
  if (days < 1) return "today";
  if (days < 2) return "1d";
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}
