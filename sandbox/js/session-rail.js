export function renderSessionList(slot, entries, { onClick, onDelete, activeId = null }) {
  slot.innerHTML = "";

  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className   = "rail-empty";
    empty.textContent = "No saved sessions yet.";
    slot.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "rail-session-row" + (entry.id === activeId ? " active" : "");

    const dots = document.createElement("span");
    dots.className   = "rail-session-dots";
    dots.textContent = entry.panes
      .map(p => p.messages.length > 1 ? "●" : "○")
      .join("");

    const name = document.createElement("span");
    name.className   = "rail-session-name";
    name.textContent = entry.name;

    const age = document.createElement("span");
    age.className   = "rail-session-age";
    age.textContent = formatAge(entry.createdAt);

    const del = document.createElement("button");
    del.className   = "rail-session-del";
    del.textContent = "✕";
    del.title       = "Delete session";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      onDelete(entry);
    });

    row.append(dots, name, age, del);
    row.addEventListener("click", () => onClick(entry));
    slot.appendChild(row);
  }
}

export function renderSaveSlot(slot, { defaultName, onSave }) {
  slot.innerHTML = "";

  const button = document.createElement("button");
  button.className   = "rail-save-btn";
  button.textContent = "Save current…";

  const form = document.createElement("div");
  form.className = "rail-save-form";
  form.hidden    = true;

  const input = document.createElement("input");
  input.type        = "text";
  input.className   = "rail-save-input";
  input.placeholder = "Session name";

  const confirmBtn = document.createElement("button");
  confirmBtn.className   = "rail-save-confirm";
  confirmBtn.textContent = "Save";

  const cancelBtn = document.createElement("button");
  cancelBtn.className   = "rail-save-cancel";
  cancelBtn.textContent = "✕";

  form.append(input, confirmBtn, cancelBtn);
  slot.append(button, form);

  function openForm() {
    input.value   = defaultName();
    button.hidden = true;
    form.hidden   = false;
    input.focus();
    input.select();
  }
  function closeForm() {
    button.hidden = false;
    form.hidden   = true;
  }
  function commit() {
    const name = input.value.trim();
    if (!name) return;
    onSave(name);
    closeForm();
  }

  button.addEventListener("click", openForm);
  confirmBtn.addEventListener("click", commit);
  cancelBtn.addEventListener("click", closeForm);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter")  { e.preventDefault(); commit(); }
    if (e.key === "Escape") { e.preventDefault(); closeForm(); }
  });
}

function formatAge(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const day = 86400000;
  const days = Math.floor(diffMs / day);
  if (days < 1) return "today";
  if (days < 2) return "1d";
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}
