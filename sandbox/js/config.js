export const MODELS = {
  "gemma-4-26b": {
    id:            "mlx-community/gemma-4-26b-a4b-it-4bit",
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

export const DEFAULT_MODEL_KEY = "qwen3-4b";

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

export const DEFAULT_SYSTEM_PROMPT = `— Select a prompt from the Registry above or type your protocol here —`;
