export function createRegistryPanel({ container, onSaveDraft, onValidate, onViewRegistry }) {
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

  panel.append(title, idEl, metaEl, divider1, statsEl, divider2, draftBtn, validateBtn, viewBtn);
  container.appendChild(panel);

  function stat(label, value) {
    const row = document.createElement("div");
    row.className = "rp-stat";
    row.innerHTML = `${label} <span>${value ?? "—"}</span>`;
    return row;
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
  };
}
