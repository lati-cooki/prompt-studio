import { createPaneState }     from "./state.js";
import { createPane }          from "./pane.js";
import { sendToPanes }         from "./send.js";
import { pingVaultHealth, reindexVault } from "./vault.js";
import { ALL_MODELS, FRONTIER_MODELS, LM_STUDIO_URL, getActiveModelKey, DEFAULT_SYSTEM_PROMPT } from "./config.js";
import { renderSaveSlot, renderSessionList } from "./session-rail.js";
import { buildMarkdown, triggerMarkdownDownload, slugify } from "./export.js";
import { createSessionsStore, resolveModelKey, resolveSession } from "./sessions.js";
import { createMeter }                          from "./meter.js";
import {
  fetchRegistryIndex,
  loadRegistryPromptBody,
  listLoadablePrompts,
} from "./registry.js";
import { paneContext } from './seal-extract.js';
import { createRegistryPanel } from './registry-panel.js';
import { createModelSelector } from './model-selector.js';
import * as api from './api.js';
import { resolveView, homeState } from './view.js';

// ── App state ──────────────────────────────────────────
const activePaneMap      = {};
const liveModels         = {};
let   selectedModelKeys  = new Set(Object.keys(FRONTIER_MODELS).slice(0, 1));
let   activeSessionId    = null;
let   activePrompt       = null;
let   promptIndex        = [];
const registryPromptsMap = new Map();

window.sealActivePane = () => paneContext(activePaneMap, ALL_MODELS);

const sessionsStore = createSessionsStore();

// ── DOM refs ───────────────────────────────────────────
const $paneContainer     = document.getElementById("pane-container");
const $input             = document.getElementById("input");
const $send              = document.getElementById("send");
const $newSession        = document.getElementById("new-session");
const $saveSessionBtn    = document.getElementById("save-session-btn");
const $exportBtn         = document.getElementById("export-btn");
const $stopBtn           = document.getElementById("stop-btn");
const $useVault          = document.getElementById("use-vault");
const $topK              = document.getElementById("top-k");
const $reindex           = document.getElementById("reindex");
const $vaultStatus       = document.getElementById("vault-status");
const $vaultHealth       = document.getElementById("vault-health");
const $vaultCardSub      = document.getElementById("vault-card-sub");
const $vaultCheckVisual  = document.getElementById("vault-checkbox-visual");
const $topbarSession     = document.getElementById("topbar-session");
const $topbarSubtitle    = document.getElementById("topbar-subtitle");
const $topbarDots        = document.getElementById("topbar-dots");
const $sessionsList      = document.getElementById("sessions-list");
const $promptPicker      = document.getElementById("prompt-picker");
const $includeDrafts     = document.getElementById("include-drafts");
const $promptBadges      = document.getElementById("prompt-badges");
const $modelChecklist    = document.getElementById("model-checklist");
const $registryPanelMount = document.getElementById("registry-panel-mount");
const $tabEval           = document.getElementById("tab-eval");
const $tabRegistry       = document.getElementById("tab-registry");
const $registryFrame     = document.getElementById("registry-frame");
const $decisionsFrame    = document.getElementById('decisions-frame');
const $composer          = document.getElementById("composer");

// ── Registry panel ─────────────────────────────────────
const registryPanel = createRegistryPanel({
  container:      $registryPanelMount,
  onSaveDraft:    handleSaveDraft,
  onViewRegistry: () => switchTab("registry"),
  onSessionClick: (entry) => {
    activeSessionId = entry.id;
    $topbarSession.textContent = entry.name;
    loadEntry(entry);
    refreshSessionList();
  },
});

// ── Model selector ─────────────────────────────────────
function buildModelSelector(initialKeys) {
  $modelChecklist.innerHTML = "";
  createModelSelector({
    container:   $modelChecklist,
    models:      { ...FRONTIER_MODELS, ...liveModels },
    initialKeys: initialKeys ?? [...selectedModelKeys],
    onChange(keys) {
      selectedModelKeys = keys;
      syncPanes();
    },
  });
}

async function loadLMStudioModels() {
  try {
    const ctl   = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 2000);
    const res   = await fetch(`${LM_STUDIO_URL}/v1/models`, { signal: ctl.signal });
    clearTimeout(timer);
    if (!res.ok) return;
    const { data = [] } = await res.json();
    for (const m of data) {
      liveModels[m.id] = {
        id:            m.id,
        endpoint:      `${LM_STUDIO_URL}/v1/chat/completions`,
        contextWindow: m.context_length || 32768,
        group:         "local",
        provider:      "lmstudio",
      };
      // Keep ALL_MODELS in sync so pane creation can look up contextWindow
      ALL_MODELS[m.id] = liveModels[m.id];
    }
  } catch { /* LM Studio not running — degrade gracefully */ }
}

// ── Pane management ─────────────────────────────────────
function getSystemPromptBody() {
  return activePrompt?.body ?? "";
}

function createOrUpdatePane(modelKey) {
  if (activePaneMap[modelKey]) return;
  const state = createPaneState(getSystemPromptBody());
  const pane  = createPane({
    id:              modelKey,
    container:       $paneContainer,
    initialPrompt:   getSystemPromptBody(),
    modelKeys:       [modelKey],
    initialModelKey: modelKey,
  });
  pane.applyReset.addEventListener("click", () => {
    state.applyPrompt(pane.getSystemPrompt());
    pane.clearLog();
    pane.refreshPreview();
  });
  const meter = createMeter({
    pane,
    state,
    contextWindow: ALL_MODELS[modelKey]?.contextWindow ?? 32768,
    getDraftText:  () => $input.value,
  });
  pane.onUsage = (usage) => {
    if (typeof usage.prompt_tokens === "number") meter.setExactPromptTokens(usage.prompt_tokens);
  };
  activePaneMap[modelKey] = { state, pane, meter };
}

function removePane(modelKey) {
  const entry = activePaneMap[modelKey];
  if (!entry) return;
  entry.pane.section.remove();
  entry.meter?.destroy();
  delete activePaneMap[modelKey];
}

function syncPanes() {
  const desired = new Set(selectedModelKeys);
  for (const key of Object.keys(activePaneMap)) {
    if (!desired.has(key)) removePane(key);
  }
  for (const key of desired) {
    createOrUpdatePane(key);
  }
}

function activePanes() {
  return Object.entries(activePaneMap).map(([modelKey, { state, pane }]) => ({
    state,
    pane,
    model: ALL_MODELS[modelKey],
  }));
}

// ── Prompt picker ───────────────────────────────────────
function populatePromptPicker(prompts) {
  $promptPicker.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "— no prompt selected —";
  $promptPicker.appendChild(none);
  for (const p of prompts) {
    const opt = document.createElement("option");
    opt.value       = `${p.id}|${p.version}`;
    opt.textContent = `${p.id}  v${p.version}`;
    $promptPicker.appendChild(opt);
  }
}

// Monotonic guard against overlapping picker refreshes (e.g. rapid toggling
// of "include drafts"): only the most recently started refresh is allowed
// to mutate shared state or repopulate the picker.
let pickerLoadSeq = 0;

/** Re-filter promptIndex against the current toggle state, fetching only
 *  bodies not already cached in registryPromptsMap, then repopulate the
 *  picker in the filtered/sorted order. */
async function refreshPromptPicker() {
  const seq = ++pickerLoadSeq;
  const prompts = listLoadablePrompts(promptIndex, $includeDrafts?.checked);
  const loaded = [];
  for (const p of prompts) {
    const key = `${p.id}|${p.version}`;
    let entry = registryPromptsMap.get(key);
    if (!entry) {
      try {
        const body = await loadRegistryPromptBody(p.file);
        if (seq !== pickerLoadSeq) return; // superseded mid-fetch
        entry = { ...p, body };
        registryPromptsMap.set(key, entry);
      } catch {
        continue; // skip unparseable prompt
      }
    }
    loaded.push(entry);
  }
  if (seq !== pickerLoadSeq) return; // superseded
  populatePromptPicker(loaded);
}

async function loadRegistryPrompts() {
  try {
    const index = await fetchRegistryIndex();
    promptIndex = index;
    await refreshPromptPicker();
  } catch (err) {
    console.warn("Registry unavailable:", err.message);
  }
}

function applyPromptToAllPanes(prompt) {
  activePrompt = prompt;
  const body = prompt?.body ?? "";
  for (const { pane } of Object.values(activePaneMap)) {
    pane.setSystemPrompt(body);
    pane.applyReset.click();
  }
  updatePromptBadges(prompt);
  registryPanel.setPrompt(prompt);
  refreshSessionList();
}

function updatePromptBadges(prompt) {
  $promptBadges.innerHTML = "";
  if (!prompt) return;
  const vBadge = document.createElement("span");
  vBadge.className   = "rail-prompt-badge version";
  vBadge.textContent = `v${prompt.version}`;
  const eBadge = document.createElement("span");
  eBadge.className   = `rail-prompt-badge eval ${prompt.eval_status === "validated" ? "validated" : ""}`;
  eBadge.textContent = `eval: ${prompt.eval_status ?? "pending"}`;
  $promptBadges.append(vBadge, eBadge);
}

$promptPicker.addEventListener("change", () => {
  const val = $promptPicker.value;
  if (!val) { applyPromptToAllPanes(null); return; }
  const [id, version] = val.split("|");
  const prompt = registryPromptsMap.get(`${id}|${version}`);
  if (prompt) applyPromptToAllPanes(prompt);
});

$includeDrafts?.addEventListener("change", () => {
  refreshPromptPicker();
});

// ── New UI refs ──────────────────────────────────────────
const $composerLabel = document.getElementById("composer-label");
const $sendHint      = document.getElementById("send-hint");
const $railModeTag   = document.getElementById("rail-mode-tag");
const $sessionsRail  = document.getElementById("sessions-rail");
const $topbar        = document.querySelector(".topbar");
const $sessionsViewList = document.getElementById('sessions-view-list');

// ── Home hub renderer ────────────────────────────────────
async function renderHome() {
  let sessionCount = 0, decisions = [];
  try { sessionCount = document.querySelectorAll('#sessions-list > *').length; } catch (e) {}
  try {
    const r = await fetch('/api/threads');
    if (r.ok) decisions = await r.json();
  } catch (e) { decisions = []; }
  const state = homeState(sessionCount, Array.isArray(decisions) ? decisions.length : 0);
  const emptyEl = document.getElementById('home-empty');
  const hubEl = document.getElementById('home-hub');
  if (emptyEl) emptyEl.style.display = state === 'empty' ? '' : 'none';
  if (hubEl) hubEl.style.display = state === 'hub' ? '' : 'none';
  const recent = document.getElementById('home-recent');
  if (recent && state === 'hub') {
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const items = (Array.isArray(decisions) ? decisions : []).slice(0, 5)
      .map((t) => `<div style="padding:4px 0;font-size:12px">✓ ${esc(t.slug)} <span style="color:var(--ink-4)">· ${esc(t.title || '')}</span></div>`).join('');
    recent.innerHTML = `<div class="sidebar-group-label" style="padding-left:0">Recent decisions <a href="javascript:void(0)" id="home-see-decisions" style="text-transform:none">→ all</a></div>${items || '<div style="color:var(--ink-4);font-size:12px">none yet</div>'}`;
    document.getElementById('home-see-decisions')?.addEventListener('click', () => showView('decisions'));
  }
}

// ── Sessions view renderer ───────────────────────────────
async function renderSessions() {
  if (!$sessionsViewList) return;
  let sessions = [];
  try { sessions = await sessionsStore.load(); } catch (e) { sessions = []; }
  if (!sessions.length) {
    $sessionsViewList.innerHTML = '<div class="sessions-view-empty">No saved sessions yet.</div>';
    return;
  }
  renderSessionList($sessionsViewList, sessions, {
    activeId: activeSessionId,
    onClick: (entry) => {
      activeSessionId = entry.id;
      $topbarSession.textContent = entry.name;
      loadEntry(entry);
      refreshSessionList();
      showView('deliberate');
    },
    onDelete: async (entry) => {
      await sessionsStore.delete(entry.id);
      renderSessions();
      refreshSessionList();
    },
  });
}

// ── View router ─────────────────────────────────────────
function showView(raw) {
  const view = resolveView(raw);
  const isDeliberate = view === 'deliberate';
  const isRegistry = view === 'registry';
  const isDecisions = view === 'decisions';
  const isHome = view === 'home';
  // Deliberate-only chrome. The Setup rail is a drawer — hidden until the
  // ⚙ Setup toggle opens it, so the default Deliberate is just the conversation.
  if ($sessionsRail) $sessionsRail.style.display = (isDeliberate && document.body.classList.contains('setup-open')) ? "" : "none";
  if ($topbar) $topbar.style.display = isDeliberate ? "" : "none";
  // Deliberate (sandbox) surfaces
  $paneContainer.style.display      = isDeliberate ? "" : "none";
  $composer.style.display           = isDeliberate ? "" : "none";
  $registryPanelMount.style.display = isDeliberate ? "" : "none";
  // Embedded views (lazy src on first show)
  $registryFrame.style.display  = isRegistry  ? "block" : "none";
  $decisionsFrame.style.display = isDecisions ? "block" : "none";
  if (isDecisions && !$decisionsFrame.src && $decisionsFrame.dataset.src) {
    $decisionsFrame.src = $decisionsFrame.dataset.src;
  }
  // Home view section (added next task; guard for absence)
  const homeEl = document.getElementById('view-home');
  if (homeEl) homeEl.style.display = isHome ? "" : "none";
  // Sessions view section
  const sessionsEl = document.getElementById('view-sessions');
  if (sessionsEl) sessionsEl.style.display = view === 'sessions' ? "" : "none";
  // Sidebar active state (added next task; guard for absence)
  document.querySelectorAll('[data-view]').forEach((el) =>
    el.classList.toggle('nav-active', el.dataset.view === view));
  if (location.hash.replace(/^#/, '') !== view) location.hash = view;
  if (view === 'home') renderHome();
  if (view === 'sessions') renderSessions();
}

document.querySelectorAll('.nav-item[data-view]').forEach((el) =>
  el.addEventListener('click', () => showView(el.dataset.view)));
const $homeStart = document.getElementById('home-start-btn');
if ($homeStart) $homeStart.addEventListener('click', () => showView('deliberate'));
const $homeNew = document.getElementById('home-new-btn');
if ($homeNew) $homeNew.addEventListener('click', () => { document.getElementById('new-session')?.click(); showView('deliberate'); });
const $sessionsViewNew = document.getElementById('sessions-view-new');
if ($sessionsViewNew) $sessionsViewNew.addEventListener('click', () => { document.getElementById('new-session')?.click(); showView('deliberate'); });
// ⚙ Setup drawer toggle (reveals the prompt/model/vault rail on demand)
const $setupToggle = document.getElementById('setup-toggle');
if ($setupToggle) $setupToggle.addEventListener('click', () => {
  const open = document.body.classList.toggle('setup-open');
  $setupToggle.classList.toggle('seg-active', open);
  if ($sessionsRail) $sessionsRail.style.display = open ? "" : "none";
});

// ── Tab switching ───────────────────────────────────────
function switchTab(tab) {
  showView(tab === 'registry' ? 'registry' : 'deliberate');
}

$tabEval?.addEventListener("click", () => switchTab("eval"));
$tabRegistry?.addEventListener("click", () => switchTab("registry"));

window.addEventListener("message", (e) => {
  if (e.data?.type !== "loadPrompt") return;
  const { id, version } = e.data;
  const prompt = registryPromptsMap.get(`${id}|${version}`);
  if (prompt) {
    switchTab("eval");
    $promptPicker.value = `${id}|${version}`;
    applyPromptToAllPanes(prompt);
  }
});

// ── Registry actions ────────────────────────────────────
async function handleSaveDraft() {
  if (!activePrompt) { alert("Select a registry prompt first."); return; }
  const body = Object.values(activePaneMap)[0]?.pane.getSystemPrompt() ?? activePrompt.body;
  try {
    const result = await api.saveDraftPrompt(activePrompt.id, body);
    $vaultStatus.textContent = `Draft saved as v${result.version}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 4000);
    await loadRegistryPrompts();
  } catch (err) {
    $vaultStatus.textContent = `Draft save failed: ${err.message}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
  }
}

// ── Send / stream ───────────────────────────────────────
async function handleSend() {
  if ($send.disabled) return;
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";
  $send.disabled        = true;
  $send.textContent     = "Streaming…";
  $topbarDots.hidden    = false;
  $topbarSubtitle.textContent = "streaming";
  $stopBtn.hidden       = false;

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
    $topbarDots.hidden    = true;
    $topbarSubtitle.textContent = "conversation";
    $stopBtn.hidden       = true;
  }
}

$send.addEventListener("click", handleSend);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
});
$input.addEventListener("input", () => {
  for (const { meter } of Object.values(activePaneMap)) meter?.render();
});

// ── Sidebar footer ──────────────────────────────────────
function updateSidebarFoot() {
  const foot = document.getElementById('sidebar-foot');
  if (!foot) return;
  const vault = (document.getElementById('vault-card-sub')?.textContent || '').trim();
  const model = (typeof getActiveModelKey === 'function') ? getActiveModelKey() : '';
  foot.textContent = `vault: ${vault || '—'}${model ? ' · ' + model : ''}`;
}

// ── Vault ───────────────────────────────────────────────
function syncVaultCheckbox() {
  $vaultCheckVisual.classList.toggle("checked", $useVault.checked);
}
$useVault.addEventListener("change", syncVaultCheckbox);
document.getElementById("vault-label-wrap").addEventListener("click", () => {
  $useVault.checked = !$useVault.checked;
  syncVaultCheckbox();
});
syncVaultCheckbox();

$reindex.addEventListener("click", async () => {
  $reindex.disabled = true;
  $vaultStatus.textContent = "Reindexing…";
  try {
    const data = await reindexVault();
    $vaultStatus.textContent = `+${data.added} new, ${data.updated} updated, ${data.deleted} deleted`;
  } catch (err) {
    $vaultStatus.textContent = `Reindex failed: ${err.message}`;
  } finally {
    $reindex.disabled = false;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 6000);
  }
});

async function tickVaultHealth() {
  const state = await pingVaultHealth();
  $vaultHealth.className    = `health-dot ${state}`;
  $vaultCardSub.textContent = state === "ok" ? "online" : "unreachable";
  updateSidebarFoot();
}
tickVaultHealth();
setInterval(tickVaultHealth, 10000);

// ── Sessions ─────────────────────────────────────────────
function currentSnapshot() {
  const panes = Object.entries(activePaneMap).map(([modelKey, { state }]) => ({
    systemPrompt: state.systemPrompt,
    messages:     [...state.messages],
    modelKey,
  }));
  const vaultConfig = {
    enabled: $useVault.checked,
    topK:    Math.max(1, Math.min(20, parseInt($topK.value, 10) || 5)),
  };
  return {
    panes,
    vaultConfig,
    promptRef: activePrompt ? { id: activePrompt.id, version: activePrompt.version } : null,
    models:    [...selectedModelKeys],
  };
}

function autoName() {
  for (const { state } of Object.values(activePaneMap)) {
    const first = state.messages.find(m => m.role === "user");
    if (first) {
      const raw  = first.content.trim().split("\n", 1)[0];
      if (raw.length <= 40) return raw;
      const cut  = raw.slice(0, 40);
      const last = cut.lastIndexOf(" ");
      return last > 10 ? cut.slice(0, last) : cut;
    }
  }
  return `Untitled ${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
}

function resetToNewSession() {
  for (const { state, pane } of Object.values(activePaneMap)) {
    state.reset();
    pane.clearLog();
  }
  activeSessionId = null;
  $topbarSubtitle.textContent = "empty";
  $topbarSession.textContent  = "untitled";
  refreshSessionList();
}

function loadEntry(entry) {
  const { promptRef, models, panes, vaultConfig } = resolveSession(entry);

  if (models.length) {
    const valid = models.filter(k => ALL_MODELS[k]);
    if (valid.length) {
      selectedModelKeys = new Set(valid);
      buildModelSelector([...selectedModelKeys]);
      syncPanes();
    }
  }

  if (promptRef) {
    const prompt = registryPromptsMap.get(`${promptRef.id}|${promptRef.version}`);
    if (prompt) {
      $promptPicker.value = `${promptRef.id}|${promptRef.version}`;
      applyPromptToAllPanes(prompt);
    }
  }

  for (const saved of panes) {
    const modelKey = saved.modelKey;
    if (!modelKey || !activePaneMap[modelKey]) continue;
    const { state, pane } = activePaneMap[modelKey];
    state.loadSnapshot({
      systemPrompt: saved.systemPrompt ?? getSystemPromptBody(),
      messages:     [...saved.messages],
    });
    pane.textarea.value = saved.systemPrompt ?? getSystemPromptBody();
    pane.refreshPreview();
    pane.renderFromMessages(state.messages);
  }

  $useVault.checked = !!vaultConfig?.enabled;
  $topK.value       = String(vaultConfig?.topK ?? 5);
  syncVaultCheckbox();
}

async function refreshSessionList() {
  const sessions = await sessionsStore.load();
  renderSessionList($sessionsList, sessions, {
    activeId: activeSessionId,
    onClick: async (entry) => {
      activeSessionId = entry.id;
      $topbarSession.textContent = entry.name;
      loadEntry(entry);
      refreshSessionList();
    },
    onDelete: async (entry) => {
      const ok = confirm(`Delete '${entry.name}'?`);
      if (!ok) return;
      await sessionsStore.delete(entry.id);
      if (activeSessionId === entry.id) activeSessionId = null;
      refreshSessionList();
    },
  });
  registryPanel.setSessions(sessions, activePrompt?.id ?? null);
}

$newSession.addEventListener("click", resetToNewSession);

$saveSessionBtn.addEventListener("click", async () => {
  const name = autoName();
  try {
    const snap  = currentSnapshot();
    const entry = await sessionsStore.save({
      name,
      panes:      snap.panes,
      vaultConfig: snap.vaultConfig,
      promptRef:  snap.promptRef,
      models:     snap.models,
    });
    activeSessionId = entry.id;
    $topbarSession.textContent = name;
    refreshSessionList();
  } catch (err) {
    $vaultStatus.textContent = `Save failed: ${err.message}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
  }
});

renderSaveSlot(document.getElementById("sessions-save-slot"), {
  defaultName: autoName,
  onSave: async (name) => {
    try {
      const snap  = currentSnapshot();
      const entry = await sessionsStore.save({
        name,
        panes:      snap.panes,
        vaultConfig: snap.vaultConfig,
        promptRef:  snap.promptRef,
        models:     snap.models,
      });
      activeSessionId = entry.id;
      refreshSessionList();
    } catch (err) {
      $vaultStatus.textContent = `Save failed: ${err.message}`;
      setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
    }
  },
});

$exportBtn.addEventListener("click", () => {
  const snap = currentSnapshot();
  const name = autoName();
  const markdown = buildMarkdown({ panes: snap.panes, vaultConfig: snap.vaultConfig }, name);
  const date     = new Date().toISOString().slice(0, 10);
  triggerMarkdownDownload({ filename: `${slugify(name)}-${date}.md`, markdown });
});

refreshSessionList();

// ── Keyboard shortcuts ───────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "n" && (e.metaKey || e.ctrlKey) && !e.shiftKey) { e.preventDefault(); resetToNewSession(); }
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

// ── Boot ─────────────────────────────────────────────────
async function init() {
  await loadLMStudioModels();   // discover local models (2s timeout, non-blocking)
  buildModelSelector();         // build checklist with discovered models + frontier
  syncPanes();
  loadRegistryPrompts();
  refreshSessionList();
  updateSidebarFoot();
}
init();

window.addEventListener('hashchange', () => showView(location.hash));
showView(location.hash || 'home');
