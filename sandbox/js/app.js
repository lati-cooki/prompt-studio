import { createPaneState }                      from "./state.js";
import { createPane }                           from "./pane.js";
import { sendToPanes }                          from "./send.js";
import { pingVaultHealth, reindexVault }        from "./vault.js";
import { DEFAULT_SYSTEM_PROMPT, MODELS, getActiveModelKey } from "./config.js";
import { renderSaveSlot, renderSessionList }    from "./session-rail.js";
import { buildMarkdown, triggerMarkdownDownload, slugify } from "./export.js";
import { createSessionsStore, resolveModelKey } from "./sessions.js";
import { createMeter }                          from "./meter.js";
import {
  fetchRegistryIndex,
  loadRegistryPromptBody,
  listLoadablePrompts,
} from "./registry.js";

const paneContainer = document.getElementById("pane-container");
const stateA = createPaneState(DEFAULT_SYSTEM_PROMPT);
let   stateB = null;
let   paneB  = null;

let modelKeyA = getActiveModelKey();
let modelKeyB = null;

const paneA = createPane({
  id:              "A",
  container:       paneContainer,
  initialPrompt:   DEFAULT_SYSTEM_PROMPT,
  modelKeys:       Object.keys(MODELS),
  initialModelKey: modelKeyA,
});

const activePanes = () => paneB
  ? [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] },
     { state: stateB, pane: paneB, model: MODELS[modelKeyB] }]
  : [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] }];

paneA.applyReset.addEventListener("click", () => {
  stateA.applyPrompt(paneA.textarea.value);
  paneA.clearLog();
  paneA.refreshPreview();
});

let meterA = null;
let meterB = null;

function attachMeter(pane, state, modelKey) {
  const meter = createMeter({
    pane,
    state,
    contextWindow: MODELS[modelKey].contextWindow,
    getDraftText: () => $input.value,
  });
  pane.onUsage = (usage) => {
    if (typeof usage.prompt_tokens === "number") {
      meter.setExactPromptTokens(usage.prompt_tokens);
    }
  };
  return meter;
}

// Shared controls
const $input        = document.getElementById("input");
const $send         = document.getElementById("send");
const $newSession   = document.getElementById("new-session");
const $useVault     = document.getElementById("use-vault");
const $topK         = document.getElementById("top-k");
const $reindex      = document.getElementById("reindex");
const $vaultStatus  = document.getElementById("vault-status");
const $vaultHealth  = document.getElementById("vault-health");

let activeSessionId = null;

meterA = attachMeter(paneA, stateA, modelKeyA);

paneA.onModelChange((newKey) => {
  modelKeyA = newKey;
  meterA.updateContextWindow(MODELS[newKey].contextWindow);
  try {
    localStorage.setItem("promptSandbox.modelKey", newKey);
  } catch { /* storage disabled — in-session change still works */ }
});

// ── New UI refs ──────────────────────────────────────────
const $segSingle     = document.getElementById("seg-single");
const $segCompare    = document.getElementById("seg-compare");
const $stopBoth      = document.getElementById("stop-both");
const $exportBtn     = document.getElementById("export-btn");
const $registrySelect = document.getElementById("registry-prompt-select");
const $registryLoadBtn = document.getElementById("registry-load-btn");
const $registryStatus  = document.getElementById("registry-status");
const $composerLabel = document.getElementById("composer-label");
const $sendHint      = document.getElementById("send-hint");
const $topbarSession = document.getElementById("topbar-session");
const $topbarSubtitle = document.getElementById("topbar-subtitle");
const $topbarDots    = document.getElementById("topbar-dots");
const $railModeTag   = document.getElementById("rail-mode-tag");
const $sessionsList  = document.getElementById("sessions-list");
const $vaultCardSub  = document.getElementById("vault-card-sub");
const $vaultCheckVisual = document.getElementById("vault-checkbox-visual");

function syncVaultCheckbox() {
  $vaultCheckVisual.classList.toggle("checked", $useVault.checked);
}
$useVault.addEventListener("change", syncVaultCheckbox);
document.getElementById("vault-label-wrap").addEventListener("click", () => {
  $useVault.checked = !$useVault.checked;
  syncVaultCheckbox();
});
syncVaultCheckbox();

async function handleSend() {
  if ($send.disabled) return;
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";

  $send.disabled        = true;
  $send.textContent     = "Streaming…";
  $sendHint.textContent = "esc to cancel";
  $topbarDots.hidden    = false;
  $topbarSubtitle.textContent = "streaming";
  if (paneB) $stopBoth.hidden = false;

  try {
    await sendToPanes({
      panes:    activePanes(),
      userText: text,
      useVault: $useVault.checked,
      topK:     $topK.value,
    });
  } finally {
    $send.disabled        = false;
    $send.textContent     = "SEND ↵";
    $sendHint.textContent = "shift+↵ newline";
    $topbarDots.hidden    = true;
    $topbarSubtitle.textContent = "conversation";
    $stopBoth.hidden      = true;
  }
}

$send.addEventListener("click", handleSend);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

$input.addEventListener("input", () => {
  meterA?.render();
  meterB?.render();
});

function resetToNewSession() {
  for (const { state, pane } of activePanes()) {
    state.reset();
    pane.clearLog();
  }
  $topbarSubtitle.textContent = "empty conversation";
  $topbarSession.textContent  = "untitled";
  activeSessionId = null;
  refreshSessionList();
}

$newSession.addEventListener("click", resetToNewSession);

$reindex.addEventListener("click", async () => {
  $reindex.disabled = true;
  $vaultStatus.textContent = "Reindexing…";
  try {
    const data = await reindexVault();
    $vaultStatus.textContent =
      `Indexed: +${data.added} new, ${data.updated} updated, ${data.deleted} deleted (${data.unchanged} unchanged)`;
  } catch (err) {
    $vaultStatus.textContent = `Reindex failed: ${err.message}`;
  } finally {
    $reindex.disabled = false;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 6000);
  }
});

async function tickVaultHealth() {
  const state = await pingVaultHealth();
  $vaultHealth.className = `health-dot ${state}`;
  $vaultHealth.title = state === "ok" ? "Vault search: online" : "Vault search: unreachable";
  $vaultCardSub.textContent = state === "ok" ? "online" : "unreachable";
}
tickVaultHealth();
setInterval(tickVaultHealth, 10000);

function enterCompare() {
  if (paneB) return;
  modelKeyB = modelKeyA;
  stateB = createPaneState(DEFAULT_SYSTEM_PROMPT);
  paneB  = createPane({
    id:              "B",
    container:       paneContainer,
    initialPrompt:   DEFAULT_SYSTEM_PROMPT,
    modelKeys:       Object.keys(MODELS),
    initialModelKey: modelKeyB,
  });
  paneB.applyReset.addEventListener("click", () => {
    stateB.applyPrompt(paneB.textarea.value);
    paneB.clearLog();
    paneB.refreshPreview();
  });
  paneContainer.classList.add("compare");

  $segSingle.classList.remove("seg-active");
  $segCompare.classList.add("seg-active");
  $railModeTag.textContent = "compare";
  $composerLabel.textContent = "both ⇢";

  meterB = attachMeter(paneB, stateB, modelKeyB);
  paneB.onModelChange((newKey) => {
    modelKeyB = newKey;
    meterB.updateContextWindow(MODELS[newKey].contextWindow);
  });
}

function exitCompare() {
  if (!paneB) return;
  if (stateB.messages.length > 1) {
    const ok = confirm("Exit compare mode? Pane B's conversation will be discarded.");
    if (!ok) return;
  }
  paneB.section.remove();
  meterB?.destroy();
  meterB    = null;
  paneB     = null;
  stateB    = null;
  modelKeyB = null;
  paneContainer.classList.remove("compare");

  $segCompare.classList.remove("seg-active");
  $segSingle.classList.add("seg-active");
  $railModeTag.textContent = "v2";
  $composerLabel.textContent = "you";
}

$segSingle.addEventListener("click",  () => { if (paneB)  exitCompare(); });
$segCompare.addEventListener("click", () => { if (!paneB) enterCompare(); });

const sessionsStore = createSessionsStore();

function autoName() {
  for (const { state } of activePanes()) {
    const firstUser = state.messages.find(m => m.role === "user");
    if (firstUser) {
      const raw = firstUser.content.trim().split("\n", 1)[0];
      if (raw.length <= 40) return raw;
      const cut = raw.slice(0, 40);
      const lastSpace = cut.lastIndexOf(" ");
      return lastSpace > 10 ? cut.slice(0, lastSpace) : cut;
    }
  }
  return `Untitled ${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
}

function currentSnapshot() {
  const perPaneKey = [modelKeyA, modelKeyB];
  const panes = activePanes().map(({ state }, idx) => ({
    systemPrompt: state.systemPrompt,
    messages:     [...state.messages],
    modelKey:     perPaneKey[idx],
  }));
  const vaultConfig = {
    enabled: $useVault.checked,
    topK:    Math.max(1, Math.min(20, parseInt($topK.value, 10) || 5)),
  };
  return { panes, vaultConfig };
}

function loadEntry(entry) {
  const paneCount = entry.panes.length;
  const modelKeys = Object.keys(MODELS);
  const fallback  = getActiveModelKey();

  const keyA = resolveModelKey(entry.panes[0].modelKey, modelKeys, fallback);
  const keyB = paneCount > 1
    ? resolveModelKey(entry.panes[1].modelKey, modelKeys, fallback)
    : null;

  if (paneCount === 1) {
    if (paneB && stateB && stateB.messages.length > 1) {
      const ok = confirm("Loading this session will exit compare mode and discard Pane B's conversation. Continue?");
      if (!ok) return;
    }
    if (paneB) {
      stateB.loadSnapshot({
        systemPrompt: stateB.systemPrompt,
        messages: [{ role: "system", content: stateB.systemPrompt }],
      });
      exitCompare();
    }
    stateA.loadSnapshot({
      systemPrompt: entry.panes[0].systemPrompt,
      messages: [...entry.panes[0].messages],
    });
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);

    modelKeyA = keyA;
    paneA.setModelKey(keyA);
    meterA.updateContextWindow(MODELS[keyA].contextWindow);
    try { localStorage.setItem("promptSandbox.modelKey", keyA); } catch { /* ignore */ }
  } else {
    if (!paneB) enterCompare();
    stateA.loadSnapshot({
      systemPrompt: entry.panes[0].systemPrompt,
      messages: [...entry.panes[0].messages],
    });
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);

    stateB.loadSnapshot({
      systemPrompt: entry.panes[1].systemPrompt,
      messages: [...entry.panes[1].messages],
    });
    paneB.textarea.value = entry.panes[1].systemPrompt;
    paneB.refreshPreview();
    paneB.renderFromMessages(stateB.messages);

    modelKeyA = keyA;
    paneA.setModelKey(keyA);
    meterA.updateContextWindow(MODELS[keyA].contextWindow);
    try { localStorage.setItem("promptSandbox.modelKey", keyA); } catch { /* ignore */ }

    modelKeyB = keyB;
    paneB.setModelKey(keyB);
    meterB.updateContextWindow(MODELS[keyB].contextWindow);
  }

  $useVault.checked = !!entry.vaultConfig?.enabled;
  $topK.value       = String(entry.vaultConfig?.topK ?? 5);
  syncVaultCheckbox();
}

async function refreshSessionList() {
  renderSessionList($sessionsList, await sessionsStore.load(), {
    activeId: activeSessionId,
    onClick: async (entry) => {
      activeSessionId = entry.id;
      loadEntry(entry);
      refreshSessionList();
    },
    onDelete: async (entry) => {
      const ok = confirm(`Delete '${entry.name}'? This cannot be undone.`);
      if (!ok) return;
      await sessionsStore.delete(entry.id);
      if (activeSessionId === entry.id) activeSessionId = null;
      refreshSessionList();
    },
  });
}

renderSaveSlot(document.getElementById("sessions-save-slot"), {
  defaultName: autoName,
  onSave: async (name) => {
    try {
      const { panes, vaultConfig } = currentSnapshot();
      const entry = await sessionsStore.save({ name, panes, vaultConfig });
      activeSessionId = entry.id;
      refreshSessionList();
    } catch (err) {
      $vaultStatus.textContent = `Save failed: ${err.message}`;
      setTimeout(() => { $vaultStatus.textContent = ""; }, 6000);
    }
  },
});

$exportBtn.addEventListener("click", () => {
  const snapshot = currentSnapshot();
  const name     = autoName();
  const markdown = buildMarkdown(snapshot, name);
  const date     = new Date().toISOString().slice(0, 10);
  triggerMarkdownDownload({
    filename: `${slugify(name)}-${date}.md`,
    markdown,
  });
});

function showRegistryStatus(msg, isError = false) {
  $registryStatus.hidden = false;
  $registryStatus.textContent = msg;
  $registryStatus.style.color = isError ? "var(--red)" : "";
  if (!isError) {
    setTimeout(() => { $registryStatus.hidden = true; }, 5000);
  }
}

function paneHasConversation(state) {
  return state.messages.some((m) => m.role === "user" || m.role === "assistant");
}

function applyRegistryPromptToPane(state, pane, body) {
  state.applyPrompt(body);
  pane.textarea.value = body;
  pane.refreshPreview();
  pane.clearLog();
}

async function populateRegistrySelect() {
  try {
    const prompts = listLoadablePrompts(await fetchRegistryIndex());
    $registrySelect.innerHTML = '<option value="">Load from registry…</option>';
    for (const p of prompts) {
      const opt = document.createElement("option");
      opt.value = p.file;
      opt.textContent = `${p.id}@${p.version}`;
      if (p.use_case) opt.title = p.use_case;
      $registrySelect.appendChild(opt);
    }
  } catch (err) {
    $registrySelect.innerHTML =
      '<option value="">Registry unavailable</option>';
    showRegistryStatus(err.message, true);
  }
}

async function handleRegistryLoad() {
  const file = $registrySelect.value;
  if (!file) return;

  const label = $registrySelect.selectedOptions[0]?.textContent ?? file;
  const hasChat =
    paneHasConversation(stateA) || (stateB && paneHasConversation(stateB));
  if (hasChat) {
    const ok = confirm(
      `Load ${label} into pane A? The current conversation will be cleared.`
    );
    if (!ok) return;
  }

  $registryLoadBtn.disabled = true;
  showRegistryStatus("Loading…");
  try {
    const body = await loadRegistryPromptBody(file);
    applyRegistryPromptToPane(stateA, paneA, body);
    $topbarSubtitle.textContent = `registry · ${label}`;
    meterA?.render();
    showRegistryStatus(`Loaded ${label}`);
  } catch (err) {
    showRegistryStatus(err.message, true);
  } finally {
    $registryLoadBtn.disabled = false;
  }
}

$registryLoadBtn.addEventListener("click", handleRegistryLoad);
populateRegistrySelect();

refreshSessionList();

// ── Keyboard shortcuts ───────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "n" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
    e.preventDefault();
    resetToNewSession();
  }

  if ((e.key === "\\" || (e.key === "c" && e.shiftKey)) && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    if (paneB) exitCompare(); else enterCompare();
  }

  if (e.key === "k" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
    e.preventDefault();
    const firstRow = $sessionsList.querySelector(".rail-session-row");
    if (firstRow) firstRow.focus();
  }

  if (e.key === "v" && (e.metaKey || e.ctrlKey) && e.shiftKey) {
    e.preventDefault();
    $useVault.checked = !$useVault.checked;
    syncVaultCheckbox();
  }
});
