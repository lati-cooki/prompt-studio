# Prompt Sandbox — Design

**Date:** 2026-04-14
**Status:** Approved (pending user review of written spec)

## Purpose

A minimal, standalone browser UI for iterating on system prompts against a
locally-running Gemma model served by `mlx_lm.server`. Separate from the
Animus RPG project; used purely to test and refine prompts before taking
them into any downstream application.

## Scope

**In scope:**
- Editable system prompt with "Apply & Reset" (rebuilds conversation)
- Streaming assistant responses (token-by-token)
- "New session" button that clears the conversation while preserving the
  current system prompt
- Single HTML page, vanilla JS, served locally via `python3 -m http.server`

**Out of scope (YAGNI):**
- Sampling controls (temperature, top-p, max tokens)
- Saving/loading named prompts
- Side-by-side prompt comparison
- Token counts, latency display
- Persistence across reloads
- Automated tests

## Architecture

```
~/prompt-sandbox/
├── index.html    # entire app: HTML + CSS + JS inline
├── README.md     # launch instructions and config notes
└── docs/superpowers/specs/2026-04-14-prompt-sandbox-design.md
```

No build step, no frameworks, no backend. The page talks directly to the
MLX server's OpenAI-compatible endpoint.

### Runtime topology

```
browser (localhost:7000)  →  MLX server (localhost:8080)
        index.html                mlx_lm.server --cors-allow-origins "*"
```

MLX must be started with `--cors-allow-origins "*"` so the browser is
permitted to call it from a different origin.

## UI Layout

Top to bottom:

1. **System prompt area** — ~6-row monospace textarea with an
   "Apply & Reset" button to its right.
2. **Conversation log** — scrolling area. User turns right-aligned,
   assistant turns left-aligned. Streaming tokens append in place into
   the active assistant bubble.
3. **Input row** — textarea + "Send" button + "New session" button.
   Enter sends, Shift+Enter inserts a newline.

## State

In-memory only. Nothing persists across page reloads.

- `systemPrompt: string` — seeded from the textarea on Apply & Reset
- `messages: Array<{role, content}>` — always starts with one system
  message derived from `systemPrompt`

## Data Flow

### Send

1. Append `{role: "user", content: input}` to `messages` and render it.
2. Create an empty assistant bubble.
3. `POST` to `API_URL` with body:
   ```json
   { "model": MODEL, "messages": messages, "stream": true }
   ```
4. Read the response as an SSE stream (MLX returns OpenAI-compatible
   `text/event-stream`). Split incoming chunks by `\n\n`, strip the
   `data: ` prefix, and stop on the `[DONE]` sentinel. For each JSON
   payload, append `choices[0].delta.content` (when present) to the
   active bubble.
5. On stream end, push the completed `{role: "assistant", content}` onto
   `messages`.

### Apply & Reset

Re-read the system prompt textarea into `systemPrompt`, rebuild
`messages` as `[{role: "system", content: systemPrompt}]`, clear the
conversation log.

### New session

Keep the current `systemPrompt`, rebuild `messages` as
`[{role: "system", content: systemPrompt}]`, clear the conversation log.
(Differs from Apply & Reset only in that the textarea is NOT re-read —
useful when the user wants to start fresh without committing in-flight
edits to the prompt box.)

## Error Handling

If `fetch` rejects or the stream aborts mid-response, render the error
inline in the active assistant bubble (red text). No retries, no
reconnect logic. The next Send starts cleanly.

## Configuration

Two constants at the top of the inline `<script>` in `index.html`:

```js
const API_URL = "http://localhost:8080/v1/chat/completions";
const MODEL   = "mlx-community/gemma-4-26B-A4B-it-4bit";
```

Edit these directly to swap models or ports. No env vars, no config
file.

### Default system prompt

The system prompt textarea is prefilled with the "Rational Partner"
prime on page load. The user can overwrite it freely; there is no UI
to restore the default (if they want it back, re-open the page in a
fresh tab, or copy it from this spec).

```
Role: You are my Lead Strategic Advisor and Decision Scientist.
Objective: Help me reach better conclusions by identifying my blind spots and logical fallacies.
Protocol:
Steel-manning: Before critiquing, summarize my argument back to me to prove you understand it perfectly.
Pre-Mortem: If I propose a plan, tell me three specific ways it could realistically fail in 12 months.
Inversion: Ask me, "What would I have to do to ensure this project fails?" to help me avoid those pitfalls.
Occam's Razor: Challenge me to find the simplest possible version of my idea.
Second-Order Effects: Always ask "And then what?" to explore the long-term consequences of my choice.
Tone: Brutally honest, intellectually rigorous, and concise. No fluff.
```

Stored as a JS string constant (`DEFAULT_SYSTEM_PROMPT`) next to
`API_URL` and `MODEL`, and assigned to the textarea's `value` on load.

## Out of Scope: RAG / Document Grounding

Pointing the model at local documents (notes, PDFs, etc.) is deferred.
If that becomes useful, use AnythingLLM separately — it already handles
vector DB + Ollama/MLX integration. This sandbox stays a plain
prompt-iteration tool.

## Launch

### MLX server (update existing command)

```bash
mlx_lm.server \
  --model mlx-community/gemma-4-26B-A4B-it-4bit \
  --port 8080 \
  --cors-allow-origins "*"
```

### Sandbox

```bash
cd ~/prompt-sandbox && python3 -m http.server 7000
# open http://localhost:7000
```

## Testing

Manual smoke test only:

1. Launch MLX with the CORS flag.
2. Launch the static server, open the page.
3. Send "hello" — verify tokens stream in.
4. Edit the system prompt, click Apply & Reset, send another message —
   verify the assistant's behavior reflects the new prompt.
5. Click New session — verify the log clears but the prompt textarea is
   untouched.

No automated tests. This is a personal prompt-iteration tool.
