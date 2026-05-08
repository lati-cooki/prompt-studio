import { createPaneState }                      from "./state.js";
import { createPane }                           from "./pane.js";
import { sendToPanes }                          from "./send.js";
import { pingVaultHealth, reindexVault }        from "./vault.js";
import { DEFAULT_SYSTEM_PROMPT, MODELS, getActiveModelKey } from "./config.js";
import { renderSaveSlot, renderSessionList }    from "./session-rail.js";
import { buildMarkdown, buildRegistryDraft, triggerMarkdownDownload, triggerJsonDownload, slugify } from "./export.js";
import { createSessionsStore, resolveModelKey } from "./sessions.js";
import { createMeter }                          from "./meter.js";

// ── State ──────────────────────────────────────────────
const paneContainer = document.getElementById("pane-container");
const stateA = createPaneState(DEFAULT_SYSTEM_PROMPT);
let   stateB = null;
let   paneB  = null;

let modelKeyA = getActiveModelKey();
let modelKeyB = null;

let registryPrompts = [];
let paneA = null;
let meterA = null;
let meterB = null;
let activeSessionId = null;

const sessionsStore = createSessionsStore("");

// ── Helpers ────────────────────────────────────────────
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

const activePanes = () => paneB
  ? [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] },
     { state: stateB, pane: paneB, model: MODELS[modelKeyB] }]
  : [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] }];

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

// ── UI refs ──────────────────────────────────────────
const $input        = document.getElementById("input");
const $send         = document.getElementById("send");
const $newSession   = document.getElementById("new-session");
const $useVault     = document.getElementById("use-vault");
const $topK         = document.getElementById("top-k");
const $reindex      = document.getElementById("reindex");
const $vaultStatus  = document.getElementById("vault-status");
const $vaultCheckVisual = document.getElementById("vault-checkbox-visual");
const $segSingle     = document.getElementById("seg-single");
const $segCompare    = document.getElementById("seg-compare");
const $stopBoth      = document.getElementById("stop-both");
const $exportMdBtn   = document.getElementById("export-md-btn");
const $exportRegBtn  = document.getElementById("export-reg-btn");
const $promoteBtn    = document.getElementById("promote-btn");
const $composerLabel = document.getElementById("composer-label");
const $sendHint      = document.getElementById("send-hint");
const $topbarSession = document.getElementById("topbar-session");
const $topbarSubtitle = document.getElementById("topbar-subtitle");
const $topbarDots    = document.getElementById("topbar-dots");
const $railModeTag   = document.getElementById("rail-mode-tag");
const $sessionsList  = document.getElementById("sessions-list");

// ── Logic ──────────────────────────────────────────────
async function handleSend() {
  console.log("[app] handleSend triggered");
  if ($send.disabled || !paneA) return;
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
  } catch (err) {
    console.error("[app] send failed:", err);
  } finally {
    $send.disabled        = false;
    $send.textContent     = "SEND ↵";
    $sendHint.textContent = "shift+↵ newline";
    $topbarDots.hidden    = true;
    $topbarSubtitle.textContent = "conversation";
    $stopBoth.hidden      = true;
  }
}

function resetToNewSession() {
  if (!paneA) return;
  for (const { state, pane } of activePanes()) {
    state.reset();
    pane.clearLog();
  }
  $topbarSubtitle.textContent = "empty conversation";
  $topbarSession.textContent  = "untitled";
  activeSessionId = null;
  refreshSessionList();
}

async function refreshSessionList() {
  const sessions = await sessionsStore.load();
  renderSessionList($sessionsList, sessions, {
    activeId: activeSessionId,
    onClick:  (entry) => {
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
    if (paneB) exitCompare();
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
    try { localStorage.setItem("promptSandbox.modelKey", keyA); } catch { }
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
    modelKeyB = keyB;
    paneA.setModelKey(keyA);
    paneB.setModelKey(keyB);
    meterA.updateContextWindow(MODELS[keyA].contextWindow);
    meterB.updateContextWindow(MODELS[keyB].contextWindow);
  }
  
  $topbarSession.textContent = entry.name;
  $topbarSubtitle.textContent = entry.panes[0].messages.length > 1 ? "conversation" : "empty conversation";
}

function enterCompare() {
  if (paneB) return;
  modelKeyB = modelKeyA;
  stateB = createPaneState(paneA.textarea.value);
  paneB = createPane({
    id:              "B",
    container:       paneContainer,
    initialPrompt:   stateB.systemPrompt,
    modelKeys:       Object.keys(MODELS),
    initialModelKey: modelKeyB,
    registryPrompts,
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

// ── Init ───────────────────────────────────────────────
async function init() {
  console.log("[app] initializing...");
  try {
    const res = await fetch("/api/prompts");
    registryPrompts = await res.json();
    console.log("[app] loaded registry prompts:", registryPrompts.length);
  } catch (err) {
    console.error("Failed to fetch registry prompts:", err);
  }

  paneA = createPane({
    id:              "A",
    container:       paneContainer,
    initialPrompt:   DEFAULT_SYSTEM_PROMPT,
    modelKeys:       Object.keys(MODELS),
    initialModelKey: modelKeyA,
    registryPrompts,
  });

  paneA.applyReset.addEventListener("click", () => {
    stateA.applyPrompt(paneA.textarea.value);
    paneA.clearLog();
    paneA.refreshPreview();
  });

  paneA.onModelChange((newKey) => {
    modelKeyA = newKey;
    if (meterA) meterA.updateContextWindow(MODELS[newKey].contextWindow);
    try { localStorage.setItem("promptSandbox.modelKey", newKey); } catch { }
  });

  meterA = attachMeter(paneA, stateA, modelKeyA);
  
  await refreshSessionList();
  console.log("[app] ready.");
}

// ── Events ─────────────────────────────────────────────
$send.addEventListener("click", handleSend);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});
$input.addEventListener("input", () => {
  if (paneA) meterA?.render();
  if (paneB) meterB?.render();
});
$newSession.addEventListener("click", resetToNewSession);
$segSingle.addEventListener("click",  () => { if (paneB)  exitCompare(); });
$segCompare.addEventListener("click", () => { if (!paneB) enterCompare(); });

$reindex.addEventListener("click", async () => {
  $reindex.disabled = true;
  $reindex.textContent = "Reindexing…";
  try {
    const res = await reindexVault();
    alert(`Reindex complete: ${res.added} added, ${res.updated} updated.`);
  } catch (err) {
    alert(`Reindex failed: ${err.message}`);
  } finally {
    $reindex.disabled = false;
    $reindex.textContent = "Reindex";
  }
});

$exportMdBtn.addEventListener("click", () => {
  const snapshot = currentSnapshot();
  const name     = autoName();
  const markdown = buildMarkdown(snapshot, name);
  const date     = new Date().toISOString().slice(0, 10);
  triggerMarkdownDownload({ filename: `${slugify(name)}-${date}.md`, markdown });
});

$exportRegBtn.addEventListener("click", () => {
  const snapshot = currentSnapshot();
  const name     = autoName();
  const draft    = buildRegistryDraft(snapshot, 0);
  const date     = new Date().toISOString().slice(0, 10);
  triggerJsonDownload({ filename: `${slugify(name)}-${date}.json`, json: draft });
});

$promoteBtn.addEventListener("click", async () => {
  if (!activeSessionId) {
    alert("Please save the session first before promoting to the registry.");
    return;
  }
  const ok = confirm("Promote this session to a Registry Draft?");
  if (!ok) return;
  try {
    const res = await fetch(`/api/sessions/${activeSessionId}/promote`, { method: 'POST' });
    const result = await res.json();
    if (res.ok) alert(`Successfully promoted! Prompt ID: ${result.prompt_id}.`);
    else alert(`Promotion failed: ${result.error}`);
  } catch (err) { alert(`Error: ${err.message}`); }
});

function syncVaultCheckbox() {
  $vaultCheckVisual.classList.toggle("checked", $useVault.checked);
}
$useVault.addEventListener("change", syncVaultCheckbox);
document.getElementById("vault-label-wrap").addEventListener("click", () => {
  $useVault.checked = !$useVault.checked;
  syncVaultCheckbox();
});
syncVaultCheckbox();

renderSaveSlot(document.getElementById("sessions-save-slot"), {
  defaultName: autoName,
  onSave: async (name) => {
    const { panes, vaultConfig } = currentSnapshot();
    const entry = await sessionsStore.save({ name, panes, vaultConfig });
    activeSessionId = entry.id;
    refreshSessionList();
  },
});

// Start the app
init();
