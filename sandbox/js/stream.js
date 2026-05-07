export function parseSSEBuffer(buffer) {
  if (buffer === "") return { events: [], remainder: "" };
  const parts = buffer.split("\n\n");
  const remainder = parts.pop();
  return { events: parts, remainder };
}

export function extractSSEDelta(event) {
  for (const line of event.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (payload === "[DONE]") return { done: true };
    try {
      const json  = JSON.parse(payload);
      const delta = json.choices?.[0]?.delta;
      const usage = json.usage;
      if (!delta && !usage) return null;
      return {
        reasoning: delta?.reasoning,
        content:   delta?.content,
        done:      false,
        usage,
      };
    } catch (err) {
      console.warn("Failed to parse SSE payload:", payload, err);
      return null;
    }
  }
  return null;
}
