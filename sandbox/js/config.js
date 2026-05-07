export const MODELS = {
  "gemma-4-26b": {
    id:            "mlx-community/gemma-4-26B-A4B-it-4bit",
    endpoint:      "http://localhost:8080/v1/chat/completions",
    contextWindow: 128000,
  },
  "qwen3-4b": {
    id:            "mlx-community/Qwen3-4B-Instruct-2507-4bit",
    endpoint:      "http://localhost:8091/v1/chat/completions",
    contextWindow: 262144,
  },
  "qwen3-27b": {
    id:            "Jackrong/MLX-Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-4bit",
    endpoint:      "http://localhost:8092/v1/chat/completions",
    contextWindow: 262144,
  },
};

export const DEFAULT_MODEL_KEY = "gemma-4-26b";

export function getActiveModelKey() {
  try {
    const saved = localStorage.getItem("promptSandbox.modelKey");
    if (saved && Object.prototype.hasOwnProperty.call(MODELS, saved)) {
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
