// challenge-panel.js — the "Challenge Run" card in the Deliberate view
// (Phase 5 Wave 3 / Slice 7).
//
// The server (challenge.py) owns every protocol step: gate appends, precedent
// citations, verify, hub anchor. This panel only (1) builds the POST
// /api/challenge body from form state, (2) polls GET /api/challenge/<job_id>
// (the vault-health setInterval pattern), and (3) renders the live event
// stream and the three verdicts. All rendering goes through
// createElement/textContent — user- and model-derived strings are never
// concatenated into markup.
//
// Eligibility is a server-side 409 (only production prompts with a sealed
// promotion thread); the picker mirrors that by offering production prompts
// only, so the refusal is rare rather than surprising.

const DEFAULT_PROVIDER = "anthropic";
const DEFAULT_MODEL = "claude-sonnet-5"; // owner decision: frontier default
const DEFAULT_ROUNDS = 2;
const MAX_ROUNDS = 4;
const POLL_MS = 1500;

// ── pure helpers (unit-tested in challenge-panel.test.js) ────────────

export function productionPrompts(prompts) {
  return (prompts || []).filter((p) => p && p.status === "production");
}

export function challengeModelOptions(frontierModels) {
  // The owner-default first; the rest derived from config.js FRONTIER_MODELS
  // (provider + real model id). Values are "provider|model".
  const options = [{
    value: `${DEFAULT_PROVIDER}|${DEFAULT_MODEL}`,
    label: `${DEFAULT_MODEL} (${DEFAULT_PROVIDER}, default)`,
  }];
  const seen = new Set(options.map((o) => o.value));
  for (const [key, entry] of Object.entries(frontierModels || {})) {
    const value = `${entry.provider}|${entry.id}`;
    if (seen.has(value)) continue;
    seen.add(value);
    options.push({ value, label: `${key} (${entry.provider})` });
  }
  return options;
}

function splitPair(value) {
  const idx = (value || "").indexOf("|");
  return idx < 0 ? null : [value.slice(0, idx), value.slice(idx + 1)];
}

export function buildChallengeRequest({ scenario, rounds, maker, checker }) {
  const text = (scenario || "").trim();
  if (!text) return { error: "scenario is required" };
  const roles = {};
  for (const [role, picked] of [["maker", maker], ["checker", checker]]) {
    const prompt = splitPair(picked && picked.prompt);
    if (!prompt) return { error: `${role}: pick a production prompt` };
    const model = splitPair(picked && picked.model) ||
      [DEFAULT_PROVIDER, DEFAULT_MODEL];
    roles[role] = {
      prompt_id: prompt[0], version: prompt[1],
      provider: model[0], model: model[1],
    };
  }
  let n = parseInt(rounds, 10);
  if (Number.isNaN(n)) n = DEFAULT_ROUNDS;
  n = Math.max(1, Math.min(MAX_ROUNDS, n));
  return { body: { scenario: text, rounds: n, roles } };
}

export function summarizeEvent(ev) {
  const hash = ev.hash && ev.hash.startsWith("sha256:")
    ? ` [${ev.hash.slice(7, 19)}]` : "";
  return `${ev.type} · ${ev.actor} — ${ev.summary || ""}${hash}`;
}

export function verdictBadge(verdict) {
  if (verdict === "PASS") return { label: "PASS", cls: "challenge-verdict-pass" };
  if (verdict === "FAIL") return { label: "FAIL", cls: "challenge-verdict-fail" };
  return { label: "—", cls: "challenge-verdict-none" };
}

// ── the card ─────────────────────────────────────────────────────────

async function getJson(url, options) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `${url} returned ${res.status}`);
  }
  return body;
}

export function createChallengePanel({ container, frontierModels = {}, fetchJson = getJson }) {
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const details = el("details", "challenge-card-details");
  const summary = el("summary", "challenge-card-summary", "⚔ Challenge Run");
  const hint = el("span", "challenge-card-hint",
    "witnessed MAKER/CHECKER deliberation → verify → anchor");
  summary.appendChild(hint);

  const form = el("div", "challenge-form");
  const scenarioLabel = el("label", "challenge-label", "Scenario");
  const scenario = el("textarea", "challenge-scenario");
  scenario.rows = 5;

  const roleRow = el("div", "challenge-roles");
  const rolePickers = {};
  for (const role of ["maker", "checker"]) {
    const box = el("div", "challenge-role");
    box.appendChild(el("div", "challenge-role-title", role.toUpperCase()));
    const promptSel = el("select", "challenge-select");
    const modelSel = el("select", "challenge-select");
    box.appendChild(el("label", "challenge-label", "prompt (production only)"));
    box.appendChild(promptSel);
    box.appendChild(el("label", "challenge-label", "model"));
    box.appendChild(modelSel);
    roleRow.appendChild(box);
    rolePickers[role] = { promptSel, modelSel };
  }

  const runRow = el("div", "challenge-run-row");
  const roundsLabel = el("label", "challenge-label", "rounds");
  const rounds = el("input", "challenge-rounds");
  rounds.type = "number";
  rounds.min = "1";
  rounds.max = String(MAX_ROUNDS);
  rounds.value = String(DEFAULT_ROUNDS);
  const runBtn = el("button", "challenge-run-btn", "Run challenge");
  runBtn.type = "button";
  const status = el("span", "challenge-status", "");
  runRow.append(roundsLabel, rounds, runBtn, status);

  const eventsList = el("div", "challenge-events");
  const results = el("div", "challenge-results");

  form.append(scenarioLabel, scenario, roleRow, runRow, eventsList, results);
  details.append(summary, form);
  container.appendChild(details);

  for (const { modelSel } of Object.values(rolePickers)) {
    for (const option of challengeModelOptions(frontierModels)) {
      const opt = el("option", null, option.label);
      opt.value = option.value;
      modelSel.appendChild(opt);
    }
  }

  let pollTimer = null;

  function renderEvents(events) {
    eventsList.replaceChildren();
    for (const ev of events || []) {
      const cls = ev.type === "GateRejectionRecorded"
        ? "challenge-event challenge-event-rejected"
        : "challenge-event";
      eventsList.appendChild(el("div", cls, summarizeEvent(ev)));
    }
    eventsList.scrollTop = eventsList.scrollHeight;
  }

  function renderResult(job) {
    results.replaceChildren();
    const result = job.result || {};
    if (job.status === "failed" && job.error) {
      results.appendChild(el("div", "challenge-error",
        `failed at stage "${job.error.stage}": ${job.error.message}`));
      // fall through: partial result fields (run dir, hashes, verdicts…)
      // are still worth showing — the failure names the missing rest.
    }
    if (result.verdicts) {
      const row = el("div", "challenge-verdicts");
      for (const check of ["chain", "coverage", "curation"]) {
        const badge = verdictBadge(result.verdicts[check]);
        const cell = el("span", `challenge-verdict ${badge.cls}`);
        cell.append(el("span", "challenge-verdict-name", check + " "),
          el("strong", null, badge.label));
        row.appendChild(cell);
      }
      results.appendChild(row);
    }
    const fact = (label, value) => {
      if (value === undefined || value === null || value === "") return;
      const line = el("div", "challenge-fact");
      line.append(el("span", "challenge-fact-label", label + ": "),
        el("code", null, String(value)));
      results.appendChild(line);
    };
    fact("thread slug", result.hub && result.hub.slug);
    fact("head hash", result.hub && result.hub.head);
    fact("report hash", result.report_hash);
    if (result.anchor) {
      const a = result.anchor;
      const state = a.anchored
        ? (a.anchor_pushed ? "anchored + pushed" : `anchored, push failed: ${a.anchor_push_error || "?"}`)
        : `not anchored: ${a.anchor_error || "?"}`;
      fact("anchor", state);
      if (a.disclosure) {
        results.appendChild(el("div", "challenge-disclosure", a.disclosure));
      }
    }
    if (result.verify_raw) {
      const raw = el("details", "challenge-raw");
      raw.appendChild(el("summary", null, "raw verify output"));
      const pre = el("pre", null, result.verify_raw);
      raw.appendChild(pre);
      results.appendChild(raw);
    }
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    runBtn.disabled = false;
  }

  function poll(jobId) {
    // The vault-health pattern (app.js tickVaultHealth): a plain setInterval
    // against a cheap snapshot endpoint.
    pollTimer = setInterval(async () => {
      let job;
      try {
        job = await fetchJson(`/api/challenge/${encodeURIComponent(jobId)}`);
      } catch (err) {
        status.textContent = `poll failed: ${err.message}`;
        return; // transient — keep polling
      }
      status.textContent = `${job.status} · stage: ${job.stage}`;
      renderEvents(job.events);
      if (job.status === "done" || job.status === "failed") {
        stopPolling();
        renderResult(job);
      }
    }, POLL_MS);
  }

  runBtn.addEventListener("click", async () => {
    const { body, error } = buildChallengeRequest({
      scenario: scenario.value,
      rounds: rounds.value,
      maker: { prompt: rolePickers.maker.promptSel.value,
               model: rolePickers.maker.modelSel.value },
      checker: { prompt: rolePickers.checker.promptSel.value,
                 model: rolePickers.checker.modelSel.value },
    });
    if (error) {
      status.textContent = error;
      return;
    }
    stopPolling();
    results.replaceChildren();
    eventsList.replaceChildren();
    runBtn.disabled = true;
    status.textContent = "starting…";
    try {
      const res = await fetchJson("/api/challenge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      poll(res.job_id);
    } catch (err) {
      // e.g. the 409 for a non-promoted prompt — shown verbatim, never
      // worked around client-side.
      runBtn.disabled = false;
      status.textContent = err.message;
    }
  });

  (async () => {
    try {
      const demo = await fetchJson("/api/challenge/demo");
      if (!scenario.value) scenario.value = demo.scenario;
    } catch { /* demo prefill is a convenience, not a requirement */ }
    try {
      const registry = await fetchJson("/api/registry");
      const eligible = productionPrompts(registry.prompts);
      for (const { promptSel } of Object.values(rolePickers)) {
        promptSel.replaceChildren();
        if (!eligible.length) {
          const opt = el("option", null, "— no production prompts —");
          opt.value = "";
          promptSel.appendChild(opt);
          continue;
        }
        for (const p of eligible) {
          const opt = el("option", null, `${p.id}@${p.version}`);
          opt.value = `${p.id}|${p.version}`;
          promptSel.appendChild(opt);
        }
      }
    } catch (err) {
      status.textContent = `registry load failed: ${err.message}`;
    }
  })();

  return { element: details };
}
