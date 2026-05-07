import { breakdown, computeUsed } from "./tokens.js";

export function createMeter({ pane, state, contextWindow: initialContextWindow, getDraftText }) {
  let contextWindow = initialContextWindow;

  // Append meter into .pane-meta-row (new layout — sits inline with model select)
  const metaRow = pane.section.querySelector(".pane-meta-row");
  const el = document.createElement("div");
  el.className = "meter";
  el.innerHTML = `
    <div class="meter-numbers">
      <span class="meter-used">0</span>
      <span style="color:var(--faint)"> / </span>
      <span class="meter-max"></span>
    </div>
    <div class="meter-bar"><div class="meter-fill"></div></div>
  `;
  metaRow.appendChild(el);

  const maxEl  = el.querySelector(".meter-max");
  const usedEl = el.querySelector(".meter-used");
  const fillEl = el.querySelector(".meter-fill");
  maxEl.textContent = formatCtx(contextWindow);

  let exactPromptTokens  = 0;
  let anchorMessageCount = 0;
  let anchorSystemPrompt = null;

  function invalidateAnchor() {
    exactPromptTokens  = 0;
    anchorMessageCount = 0;
    anchorSystemPrompt = null;
  }

  function render() {
    const draftText = typeof getDraftText === "function" ? getDraftText() : "";

    const { used, anchorValid } = computeUsed({
      exactPromptTokens,
      anchorMessageCount,
      anchorSystemPrompt,
      messages:     state.messages,
      systemPrompt: state.systemPrompt,
      draftText,
    });

    if (exactPromptTokens > 0 && !anchorValid) {
      invalidateAnchor();
    }

    usedEl.textContent = used.toLocaleString();

    const pct = Math.min(100, (used / contextWindow) * 100);
    fillEl.style.width = `${pct.toFixed(1)}%`;

    // New thresholds: amber 75-89%, red 90%+
    el.classList.toggle("amber", pct >= 75 && pct < 90);
    el.classList.toggle("red",   pct >= 90);

    const b = breakdown({ messages: state.messages, draftText, exactPromptTokens });
    el.title = `system ≈ ${b.system.toLocaleString()}, history ≈ ${b.history.toLocaleString()}, draft ≈ ${b.draft.toLocaleString()}`;
  }

  const unsubState = state.subscribe(render);
  render();

  return {
    setExactPromptTokens(n) {
      exactPromptTokens  = n;
      anchorMessageCount = state.messages.length;
      anchorSystemPrompt = state.systemPrompt;
      render();
    },
    updateContextWindow(newMax) {
      contextWindow = newMax;
      maxEl.textContent = formatCtx(newMax);
      render();
    },
    render,
    destroy() {
      unsubState();
      el.remove();
    },
  };
}

function formatCtx(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(0)}M`;
  if (n >= 1000)    return `${Math.round(n / 1000)}K`;
  return String(n);
}
