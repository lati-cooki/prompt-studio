// LM Studio serves all local models on a single endpoint.
// Models are discovered at runtime via GET /v1/models.
export const LM_STUDIO_URL = "http://localhost:1234";

export const FRONTIER_MODELS = {
  // Anthropic
  "claude-haiku-4-5": {
    id:            "claude-haiku-4-5-20251001",
    endpoint:      "/api/chat",
    contextWindow: 200000,
    group:         "frontier",
    provider:      "anthropic",
  },
  "claude-sonnet-4-6": {
    id:            "claude-sonnet-4-6",
    endpoint:      "/api/chat",
    contextWindow: 200000,
    group:         "frontier",
    provider:      "anthropic",
  },
  // OpenAI
  "gpt-4o": {
    id:            "gpt-4o",
    endpoint:      "/api/chat",
    contextWindow: 128000,
    group:         "frontier",
    provider:      "openai",
  },
  "gpt-4o-mini": {
    id:            "gpt-4o-mini",
    endpoint:      "/api/chat",
    contextWindow: 128000,
    group:         "frontier",
    provider:      "openai",
  },
  // xAI Grok
  "grok-3": {
    id:            "grok-3",
    endpoint:      "/api/chat",
    contextWindow: 131072,
    group:         "frontier",
    provider:      "xai",
  },
  // Google Gemini
  "gemini-2.5-pro": {
    id:            "gemini-2.5-pro-preview-05-06",
    endpoint:      "/api/chat",
    contextWindow: 1000000,
    group:         "frontier",
    provider:      "google",
  },
  "gemini-2.5-flash": {
    id:            "gemini-2.5-flash-preview-04-17",
    endpoint:      "/api/chat",
    contextWindow: 1000000,
    group:         "frontier",
    provider:      "google",
  },
};

// ALL_MODELS starts frontier-only; local models are added at runtime by app.js
// after querying LM Studio's /v1/models endpoint.
export const ALL_MODELS = { ...FRONTIER_MODELS };

export const DEFAULT_MODEL_KEY = "claude-sonnet-4-6";

export function getActiveModelKey() {
  try {
    const saved = localStorage.getItem("promptSandbox.modelKey");
    if (saved && Object.prototype.hasOwnProperty.call(ALL_MODELS, saved)) {
      return saved;
    }
    return DEFAULT_MODEL_KEY;
  } catch {
    return DEFAULT_MODEL_KEY;
  }
}

export const VAULT_URL   = "http://localhost:8100";
export const STORAGE_KEY = "promptSandbox.sessions";

export const DEFAULT_SYSTEM_PROMPT = `Role: You are my Lead Strategic Advisor and Decision Scientist.
Objective: Help me reach better conclusions by identifying my blind spots and logical fallacies.
Protocol:
Steel-manning: Before critiquing, summarize my argument back to me to prove you understand it perfectly.
Pre-Mortem: If I propose a plan, tell me three specific ways it could realistically fail in 12 months.
Inversion: Ask me, "What would I have to do to ensure this project fails?" to help me avoid those pitfalls.
Occam's Razor: Challenge me to find the simplest possible version of my idea.
Second-Order Effects: Always ask "And then what?" to explore the long-term consequences of my choice.
Tone: Brutally honest, intellectually rigorous, and concise. No fluff.`;
