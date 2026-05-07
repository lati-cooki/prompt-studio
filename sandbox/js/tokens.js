// Approximate token count from characters. ~4 chars/token for English.
// Good enough for live "how close am I to the limit" feedback; the
// meter's exact anchor from usage.prompt_tokens corrects this on each send.

const PER_MESSAGE_OVERHEAD = 3;  // rough: role tag, separators

export function approxTokens(text) {
  if (typeof text !== "string" || text.length === 0) return 0;
  return Math.ceil(text.length / 4);
}

export function sumMessages(messages) {
  let total = 0;
  for (const msg of messages) {
    total += approxTokens(msg.content);
    total += PER_MESSAGE_OVERHEAD;
  }
  return total;
}

export function computeUsed({
  exactPromptTokens,
  anchorMessageCount,
  anchorSystemPrompt,
  messages,
  systemPrompt,
  draftText,
}) {
  const draft = approxTokens(draftText);
  if (exactPromptTokens > 0) {
    const stillAnchored =
      messages.length >= anchorMessageCount &&
      systemPrompt === anchorSystemPrompt;
    if (stillAnchored) {
      return {
        used: exactPromptTokens + sumMessages(messages.slice(anchorMessageCount)) + draft,
        anchorValid: true,
      };
    }
  }
  return {
    used: sumMessages(messages) + draft,
    anchorValid: false,
  };
}

export function breakdown({ messages, draftText, exactPromptTokens }) {
  let system  = 0;
  let history = 0;
  for (const msg of messages) {
    if (msg.role === "system" && system === 0) {
      system = approxTokens(msg.content) + PER_MESSAGE_OVERHEAD;
    } else {
      history += approxTokens(msg.content) + PER_MESSAGE_OVERHEAD;
    }
  }
  const draft       = approxTokens(draftText);
  const totalApprox = system + history + draft;
  return { system, history, draft, totalExact: exactPromptTokens, totalApprox };
}
