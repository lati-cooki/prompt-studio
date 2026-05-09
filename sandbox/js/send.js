import { parseSSEBuffer, extractSSEDelta } from "./stream.js";
import { fetchVaultContext }                from "./vault.js";
import { renderSources }                    from "./ui.js";

export async function sendToPanes({ panes, userText, useVault, topK }) {
  // Echo the user bubble immediately so it paints before any network I/O —
  // vault retrieval can take up to 5s and we don't want to hide the user's
  // own message behind that latency.
  for (const { state, pane } of panes) {
    state.addUser(userText);
    pane.addBubble("user", userText);
  }

  // One shared vault retrieval per send. Panes see the same injected message.
  let vaultMessage  = null;
  let vaultResults  = null;
  if (useVault) {
    const k   = Math.max(1, Math.min(20, parseInt(topK, 10) || 5));
    const got = await fetchVaultContext(userText, k);
    if (got && got.message) {
      vaultMessage = got.message;
      vaultResults = got.results;
    } else if (got && got.error) {
      for (const p of panes) p.pane.addLogNote("Vault search unavailable; sending without context.");
    }
  }

  // Fire one request per pane in parallel.
  await Promise.all(panes.map(({ state, pane, model }) =>
    streamOnePane({ state, pane, model, vaultMessage, vaultResults })));
}

async function streamOnePane({ state, pane, model, vaultMessage, vaultResults }) {
  const turnMessages = state.buildTurnMessages(vaultMessage);

  const bubble = pane.addBubble("assistant", "Thinking…");
  bubble.classList.add("pending");

  try {
    const res = await fetch(model.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model.id,
        messages: turnMessages,
        stream: true,
        max_tokens: 4096,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer      = "";
    let reasoning   = "";
    let content     = "";
    let reasoningEl = null;
    let contentEl   = null;
    let capturedUsage = null;

    const initSpans = () => {
      if (reasoningEl) return;
      bubble.textContent = "";
      bubble.classList.remove("pending");
      reasoningEl = document.createElement("span");
      reasoningEl.className = "reasoning";
      contentEl = document.createElement("span");
      contentEl.className = "content";
      bubble.appendChild(reasoningEl);
      bubble.appendChild(contentEl);
    };

    const applyEvents = (events) => {
      let needsScroll = false;
      for (const event of events) {
        const delta = extractSSEDelta(event);
        if (!delta || delta.done) continue;
        if (delta.usage) capturedUsage = delta.usage;
        const { reasoning: r, content: c } = delta;
        if (r || c) initSpans();
        if (r) { reasoning += r; reasoningEl.textContent = reasoning; }
        if (c) { content   += c; contentEl.textContent   = content;   }
        if (r || c) needsScroll = true;
      }
      if (needsScroll) pane.log.scrollTop = pane.log.scrollHeight;
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSSEBuffer(buffer);
      buffer = remainder;
      applyEvents(events);
    }
    // Flush the decoder's internal state and any residual event.
    buffer += decoder.decode();
    if (buffer.trim()) {
      const { events } = parseSSEBuffer(buffer + "\n\n");
      applyEvents(events);
    }

    // Fire onUsage BEFORE addAssistant so the meter's anchor is set against
    // the same message-count the server tokenized (prompt_tokens does NOT
    // include the assistant reply that we're about to append).
    if (capturedUsage && typeof pane.onUsage === "function") {
      pane.onUsage(capturedUsage);
    }
    state.addAssistant(content || reasoning);
    if (!reasoningEl) {
      // [DONE] arrived with zero deltas — keep the bubble visible but not spinning.
      bubble.classList.remove("pending");
      bubble.textContent = "(empty response)";
    }
    if (vaultResults) renderSources(bubble, vaultResults);
  } catch (err) {
    bubble.classList.add("error");
    bubble.textContent = `⚠ ${err.message}`;
    state.popLastUser();
  }
}
