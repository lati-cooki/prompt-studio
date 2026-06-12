export function createRegistryPanel({ container, onSaveDraft, onValidate, onViewRegistry, onSessionClick }) {
  const panel = document.createElement("aside");
  panel.className = "registry-panel";

  const title = document.createElement("div");
  title.className   = "rp-title";
  title.textContent = "Active Prompt";

  const idEl = document.createElement("div");
  idEl.className   = "rp-id";
  idEl.textContent = "—";

  const metaEl = document.createElement("div");
  metaEl.className = "rp-meta";

  const divider1 = document.createElement("hr");
  divider1.className = "rp-divider";

  const statsEl = document.createElement("div");
  statsEl.className = "rp-stats";

  const divider2 = document.createElement("hr");
  divider2.className = "rp-divider";

  const draftBtn = document.createElement("button");
  draftBtn.className   = "rp-action save-version";
  draftBtn.textContent = "Save as next draft";
  draftBtn.addEventListener("click", () => onSaveDraft && onSaveDraft());

  const validateBtn = document.createElement("button");
  validateBtn.className   = "rp-action promote";
  validateBtn.textContent = "Mark eval: validated ✓";
  validateBtn.addEventListener("click", () => onValidate && onValidate());

  const viewBtn = document.createElement("button");
  viewBtn.className   = "rp-action open-reg";
  viewBtn.textContent = "View full registry →";
  viewBtn.addEventListener("click", () => onViewRegistry && onViewRegistry());

  const divider3 = document.createElement("hr");
  divider3.className = "rp-divider";

  const sessionsTitle = document.createElement("div");
  sessionsTitle.className   = "rp-title";
  sessionsTitle.textContent = "Recent Sessions";

  const sessionsEl = document.createElement("div");
  sessionsEl.className = "rp-sessions";

  panel.append(title, idEl, metaEl, divider1, statsEl, divider2, draftBtn, validateBtn, viewBtn, divider3, sessionsTitle, sessionsEl);
  container.appendChild(panel);

  function stat(label, value) {
    const row = document.createElement("div");
    row.className = "rp-stat";
    const span = document.createElement("span");
    span.textContent = value ?? "—";
    row.append(`${label} `, span);
    return row;
  }

  function relativeTime(isoStr) {
    if (!isoStr) return "";
    const diff = Date.now() - new Date(isoStr).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1)  return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  return {
    element: panel,

    setPrompt(p) {
      if (!p) {
        idEl.textContent     = "—";
        metaEl.textContent   = "";
        statsEl.innerHTML    = "";
        draftBtn.disabled    = true;
        validateBtn.disabled = true;
        sessionsEl.innerHTML = "";
        return;
      }
      idEl.textContent   = p.id;
      metaEl.textContent = `v${p.version} · ${p.status ?? "draft"}`;
      statsEl.innerHTML  = "";
      statsEl.append(
        stat("eval status", p.eval_status ?? "pending"),
        stat("tokens",      p.tokens_prompt_body ?? "—"),
        stat("cost/run",    p.cost_per_run_usd != null ? `$${p.cost_per_run_usd.toFixed(4)}` : "—"),
      );
      draftBtn.disabled    = false;
      validateBtn.disabled = (p.eval_status === "validated");
    },

    setSessions(sessions, activePromptId) {
      sessionsEl.innerHTML = "";
      const relevant = sessions.filter(s => {
        const raw = s.panes;
        const ref = Array.isArray(raw) ? null : raw?.promptRef;
        return ref?.id === activePromptId;
      });
      if (!relevant.length) {
        const empty = document.createElement("div");
        empty.className   = "rp-sessions-empty";
        empty.textContent = "No sessions yet";
        sessionsEl.appendChild(empty);
        return;
      }
      for (const s of relevant.slice(0, 8)) {
        const row = document.createElement("div");
        row.className = "rp-session-row";
        row.title     = s.name;

        const name = document.createElement("span");
        name.className   = "rp-session-name";
        name.textContent = s.name;

        const age = document.createElement("span");
        age.className   = "rp-session-age";
        age.textContent = relativeTime(s.updatedAt || s.createdAt);

        row.append(name, age);
        row.addEventListener("click", () => onSessionClick && onSessionClick(s));
        sessionsEl.appendChild(row);
      }
    },
  };
}
