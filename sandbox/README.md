# Prompt Sandbox

A small browser UI for iterating on system prompts against any local
OpenAI-compatible chat endpoint (Gemma on MLX by default, but any
server speaking `/v1/chat/completions` works), with optional RAG from a
local Obsidian-style vault. Vanilla HTML/CSS + ES modules served by
`python3 -m http.server` — no build step, no npm, no framework.

## Features

- **Live prompt iteration**: streaming chat with the system prompt
  visible at the top of each pane; apply edits and reset with one
  button.
- **A/B compare**: two panes side by side, one shared input fires
  parallel requests to each so you can directly compare prompt
  variants. Vault retrieval runs once and is spliced into both panes
  identically.
- **Saved sessions**: explicit save/load/delete of prompt + conversation
  to `localStorage`. Unified list handles prompt-only snapshots and
  full session snapshots.
- **Markdown export**: dump the active pane(s) as a file with YAML
  frontmatter, blockquoted system prompt, and labeled turns.
- **Token/context meter**: per-pane running count with live draft
  preview and an exact anchor from each stream's `usage.prompt_tokens`.
  Color-coded at 75% and 90% of the model's context window.
- **Model-portable**: each pane has a dropdown to pick any entry from
  the `MODELS` registry in `js/config.js`; no other code path
  hard-codes a model name. Pane A's choice persists across reloads.

## Quick launch

Double-click `~/Desktop/prompt-sandbox.command` (symlinked to
`./launch.command`). It opens four Terminal windows (Gemma MLX on 8080,
Qwen3 MLX on 8091, static web server on 7777, vault-search on 8100),
polls each health endpoint, and opens the sandbox in your browser.
Close the Terminal windows when you're done.

## Run (manual)

### 1. Start MLX with CORS enabled

```bash
source ~/mlx-env/bin/activate
mlx_lm.server \
  --model mlx-community/gemma-4-26B-A4B-it-4bit \
  --port 8080 \
  --allowed-origins "*"
```

The `--allowed-origins "*"` flag is required — the browser refuses
cross-origin requests to MLX without it.

### 2. Serve the page

```bash
cd ~/prompt-sandbox
python3 -m http.server 7777
```

### 3. (Optional) Start vault-search

The sandbox works without vault-search — the "Use vault context" toggle
simply does nothing. To enable RAG, start the sibling service at
`~/vault-search/`:

```bash
source ~/vault-env/bin/activate
cd ~/vault-search && python server.py
```

### 4. Open it

http://localhost:7777

## Use

### One pane (default)

- The pane shows a **one-line preview** of the current system prompt at
  the top. Click it to expand the full textarea + **Apply & Reset**
  button; click again to collapse. Edit the prompt and hit Apply & Reset
  to apply it and clear the conversation. Typing alone doesn't take
  effect — Apply & Reset is what commits the change.
- Type in the bottom input. Enter sends; Shift+Enter inserts a newline.
- Messages render with muted **YOU** / **ASSISTANT** labels above each
  bubble.
- The **controls strip** at the top carries, left to right:
  Compare | New session | Sessions ▾ | health-dot | Use vault context |
  top-K | Reindex | (status).
- **New session** clears the conversation but keeps the current system
  prompt.
- **Use vault context**: when on, your next send is augmented with
  top-K semantically similar notes from `~/vault/` (served by
  vault-search on port 8100). Retrieved source filenames appear under
  the assistant bubble. If vault-search is down, the send proceeds
  without context and a log note is shown.
- **Reindex**: rebuilds the vault embedding index after you add or
  change markdown files in `~/vault/`.
- **Health dot**: green when vault-search responds on `/health`, red
  when unreachable, polled every 10s.
- **Token/context meter**: a small `<current> / <context-window>` bar
  appears under the prompt preview. Updates live as you type
  (approximate) and snaps to the model-reported exact count after each
  send. Bar goes amber above 75%, red above 90%. Hover for the
  breakdown (system / history / draft). Independent per pane in A/B
  mode.

### A/B compare (two panes)

Click **Compare** to open a second pane side by side. Pane A keeps its
current prompt and conversation; Pane B starts fresh with the default
prompt. In compare mode each pane gets a small colored badge — blue
**A**, purple **B** — and a matching top-accent on the prompt area, so
you can tell the panes apart at a glance. The bubbles themselves stay
uniform.

- Each pane has its own collapsible prompt preview and its own
  conversation.
- One send fires requests to both panes **in parallel** — you see two
  streaming responses at once.
- Vault retrieval runs **once per send** and the retrieved notes are
  spliced into both panes' prompts identically, so output differences
  are attributable to the system prompt.
- **Apply & Reset** is per pane. **New session** clears both.
- Click **Single** (same button) to exit compare mode. If Pane B has
  any conversation, you'll be asked to confirm before it's discarded.

### Saved sessions + Markdown export

Click **Sessions ▾** in the controls strip to open the sessions panel.

- **Save current…** captures the active pane(s): system prompt,
  conversation history, vault toggle, and top-K. Name it and press
  Enter. Saves go to `localStorage` under the key
  `promptSandbox.sessions`. Soft cap: 100 entries (FIFO trim on
  overflow; on quota-exceeded, the store also drops oldest and retries).
- **Session list**: each row shows pane-count dots (`●` = has
  conversation, `○` = prompt only), the name, and relative age. Click
  to restore; the panel exits / enters compare mode as needed to match
  the saved layout. `✕` deletes with a native confirm.
- **Export current as Markdown**: dumps the active pane(s) as a
  downloaded `.md` file with YAML-ish frontmatter, a blockquoted system
  prompt, and `**You:**` / `**Assistant:**` turn labels. Works in
  compare mode too (two `## Pane A` / `## Pane B` sections).
- Everything else lives in memory — a page reload restores the default
  prompt and empties the conversation. Only saved sessions survive.

## Config

All shared constants live in `js/config.js`:

- `MODELS` — registry keyed by short model name. Each entry has
  `id` (model string for `/v1/chat/completions`), `endpoint`, and
  `contextWindow`.
- `DEFAULT_MODEL_KEY` / `getActiveModelKey()` — resolves the active
  entry (falls back to `DEFAULT_MODEL_KEY` if nothing is saved to
  `localStorage`).
- `VAULT_URL` — vault-search endpoint.
- `STORAGE_KEY` — `localStorage` key for saved sessions.
- `DEFAULT_SYSTEM_PROMPT` — starting prompt.

## Adding providers

The UI speaks **only** OpenAI-compatible `/v1/chat/completions` with SSE streaming over HTTP to a local endpoint. Any provider you want to use has to fit that shape and has to be reachable from the browser with permissive CORS.

Three patterns:

### 1. Local OpenAI-compatible server (MLX, llama.cpp, vLLM)

Drop a new entry into `MODELS` in `js/config.js` pointing at the server's port. Example for llama.cpp running on 8091:

```js
"llama-3-local": {
  id:            "meta-llama/Meta-Llama-3-8B-Instruct",
  endpoint:      "http://localhost:8091/v1/chat/completions",
  contextWindow: 8192,
},
```

The server must run with permissive CORS. For `llama-server`:

```bash
llama-server --model path/to/model.gguf --port 8091 --host 127.0.0.1
```

(llama-server allows all origins by default. For `mlx_lm.server` use `--allowed-origins "*"`, already set in `_run-mlx.sh`.)

### 2. Cloud via local proxy (OpenAI, Anthropic, any API key)

The browser can't talk to `api.openai.com` directly — API keys don't belong in a browser, and CORS would block it anyway. Run a small local proxy that holds the key and speaks OpenAI shape to `localhost`. [LiteLLM](https://github.com/BerriAI/litellm) is the simplest option:

```bash
pip install 'litellm[proxy]'
litellm --model openai/gpt-4o --port 8090
```

Then in `MODELS`:

```js
"gpt-4o-via-litellm": {
  id:            "openai/gpt-4o",
  endpoint:      "http://localhost:8090/v1/chat/completions",
  contextWindow: 128000,
},
```

If your proxy blocks browser CORS, add `--config` with an allow-origins setting or front it with a tiny CORS-adding shim.

### 3. Native Anthropic via proxy

Same as (2). LiteLLM translates Anthropic's API to OpenAI shape so the browser sees a consistent contract:

```bash
litellm --model claude-opus-4-7 --port 8092
```

```js
"claude-opus-4-7-via-litellm": {
  id:            "claude-opus-4-7",
  endpoint:      "http://localhost:8092/v1/chat/completions",
  contextWindow: 200000,
},
```

### Switching at runtime

Each pane's header has a dropdown listing every `MODELS` key. Pane A's choice is persisted to `localStorage` across reloads. Pane B (Compare mode) defaults to Pane A's current choice and is transient.

## File layout

```
prompt-sandbox/
├── index.html              ← markup + styles + <script src="./js/app.js">
├── launch.command          ← three-terminal launcher
├── _run-{mlx,web,vault}.sh ← individual process scripts
└── js/
    ├── config.js           ← MODELS map + constants
    ├── app.js              ← entry wiring (DOM refs + event handlers + meters)
    ├── stream.js           ← pure SSE parser (tests: stream.test.js)
    ├── state.js            ← pane state factory + subscribe (tests: state.test.js)
    ├── vault.js            ← vault-search HTTP wrappers
    ├── pane.js             ← createPane DOM factory + oneLinePreview + renderFromMessages
    ├── ui.js               ← renderSources (vault sources chips)
    ├── session-panel.js    ← createSessionPanel + save/list rendering
    ├── export.js           ← buildMarkdown + download + slugify
    ├── sessions.js         ← createSessionsStore (localStorage CRUD; tests: sessions.test.js)
    ├── tokens.js           ← pure token-counting helpers (tests: tokens.test.js)
    ├── meter.js            ← per-pane token/context meter factory
    └── send.js             ← streaming orchestrator (vault retrieve + parallel fan-out)
```

## Tests

Zero-dependency Node-native tests cover the pure-logic modules:

```bash
node --test js/*.test.js
```

- `stream.test.js` — SSE parsing + delta extraction + `usage` chunk.
- `state.test.js` — pane state factory, `loadSnapshot`, `subscribe`.
- `sessions.test.js` — localStorage CRUD + quota-aware trim.
- `tokens.test.js` — `approxTokens` / `sumMessages` / `breakdown`.

DOM-facing modules (`pane.js`, `session-panel.js`, `export.js`,
`meter.js`, `app.js`) are verified by manual browser acceptance — no
jsdom, no test harness to maintain.

## Doc grounding / RAG

Handled by the sibling **vault-search** project at `~/vault-search/`.
Flip **Use vault context** in the controls row to inject semantically
similar notes from `~/vault/` into the next prompt. See
`~/vault-search/README.md` for setup and endpoints.
