# Prompt Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone single-page browser UI at `~/prompt-sandbox/` that streams completions from a local MLX server running Gemma, for iterating on system prompts.

**Architecture:** One `index.html` file containing inline HTML/CSS/JS. No frameworks, no build step, no backend. The page is served by `python3 -m http.server` on port 7000 and talks directly to MLX's OpenAI-compatible `/v1/chat/completions` endpoint on port 8080. MLX must be launched with `--cors-allow-origins "*"`.

**Tech Stack:** Plain HTML5 + vanilla JavaScript (ES2020+, `fetch` with streaming `ReadableStream`). Python 3 built-in `http.server` to serve the file. No npm, no bundler, no dependencies.

**Spec:** `docs/superpowers/specs/2026-04-14-prompt-sandbox-design.md`

**Testing note:** Per the spec, this is a personal tool with manual smoke testing only — no automated test suite. Each task still includes an explicit manual verification step with expected outcome.

---

## File Structure

Files created in this plan:

- `~/prompt-sandbox/index.html` — the entire app (HTML skeleton, CSS, JS)
- `~/prompt-sandbox/README.md` — launch instructions, config notes, default prompt reference

No other files. No backend, no tests, no config files.

---

## Task 1: Create HTML skeleton and static layout

Establish the page structure and CSS. No JavaScript behavior yet — verify the layout renders correctly in the browser before wiring up any logic.

**Files:**
- Create: `~/prompt-sandbox/index.html`

- [ ] **Step 1: Create `index.html` with skeleton and styles**

Create `/Users/troylatimer/prompt-sandbox/index.html` with this exact content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Prompt Sandbox</title>
<style>
  :root {
    --bg: #1a1a1a;
    --panel: #242424;
    --fg: #e8e8e8;
    --muted: #888;
    --accent: #6ea8fe;
    --user-bubble: #2d4a6b;
    --assistant-bubble: #2a2a2a;
    --error: #ff6b6b;
    --border: #333;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    height: 100%;
    background: var(--bg);
    color: var(--fg);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  body {
    display: flex;
    flex-direction: column;
  }
  header.system-prompt {
    padding: 12px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 8px;
  }
  header.system-prompt textarea {
    flex: 1;
    min-height: 90px;
    background: #111;
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    resize: vertical;
  }
  button {
    background: var(--accent);
    color: #111;
    border: 0;
    border-radius: 4px;
    padding: 8px 14px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.secondary {
    background: transparent;
    color: var(--fg);
    border: 1px solid var(--border);
  }
  main.log {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .bubble {
    max-width: 80%;
    padding: 10px 12px;
    border-radius: 10px;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .bubble.user {
    align-self: flex-end;
    background: var(--user-bubble);
  }
  .bubble.assistant {
    align-self: flex-start;
    background: var(--assistant-bubble);
  }
  .bubble.error { color: var(--error); }
  footer.input-row {
    display: flex;
    gap: 8px;
    padding: 12px;
    background: var(--panel);
    border-top: 1px solid var(--border);
  }
  footer.input-row textarea {
    flex: 1;
    min-height: 52px;
    max-height: 200px;
    background: #111;
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font: 14px/1.5 inherit;
    resize: vertical;
  }
</style>
</head>
<body>

<header class="system-prompt">
  <textarea id="system-prompt" spellcheck="false"></textarea>
  <button id="apply-reset">Apply &amp; Reset</button>
</header>

<main class="log" id="log"></main>

<footer class="input-row">
  <textarea id="input" placeholder="Message (Enter to send, Shift+Enter for newline)"></textarea>
  <button id="send">Send</button>
  <button id="new-session" class="secondary">New session</button>
</footer>

<script>
// Task 2+: logic goes here
</script>

</body>
</html>
```

- [ ] **Step 2: Manually verify the layout**

Run:
```bash
cd /Users/troylatimer/prompt-sandbox && python3 -m http.server 7000
```

Open `http://localhost:7000` in a browser. Verify:
- Dark background, system prompt textarea at top with "Apply & Reset" button
- Empty middle area (conversation log)
- Bottom row with input textarea, "Send" button, "New session" button
- No console errors in DevTools

Stop the server with Ctrl+C when verified.

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/prompt-sandbox
git add index.html
git commit -m "Add prompt sandbox HTML skeleton and layout"
```

---

## Task 2: Wire up default system prompt and "Apply & Reset"

Add the `DEFAULT_SYSTEM_PROMPT` constant (Rational Partner prime), prefill the textarea on load, and implement the state model + Apply & Reset button. No network calls yet — we're just verifying state management and the reset behavior.

**Files:**
- Modify: `~/prompt-sandbox/index.html` (the `<script>` block)

- [ ] **Step 1: Replace the `<script>` block with config, state, and Apply & Reset**

In `/Users/troylatimer/prompt-sandbox/index.html`, replace the line `// Task 2+: logic goes here` (and the surrounding empty `<script>` body) with:

```javascript
const API_URL = "http://localhost:8080/v1/chat/completions";
const MODEL   = "mlx-community/gemma-4-26B-A4B-it-4bit";

const DEFAULT_SYSTEM_PROMPT = `Role: You are my Lead Strategic Advisor and Decision Scientist.
Objective: Help me reach better conclusions by identifying my blind spots and logical fallacies.
Protocol:
Steel-manning: Before critiquing, summarize my argument back to me to prove you understand it perfectly.
Pre-Mortem: If I propose a plan, tell me three specific ways it could realistically fail in 12 months.
Inversion: Ask me, "What would I have to do to ensure this project fails?" to help me avoid those pitfalls.
Occam's Razor: Challenge me to find the simplest possible version of my idea.
Second-Order Effects: Always ask "And then what?" to explore the long-term consequences of my choice.
Tone: Brutally honest, intellectually rigorous, and concise. No fluff.`;

// DOM refs
const $systemPrompt = document.getElementById("system-prompt");
const $log          = document.getElementById("log");
const $input        = document.getElementById("input");
const $send         = document.getElementById("send");
const $applyReset   = document.getElementById("apply-reset");
const $newSession   = document.getElementById("new-session");

// State
let systemPrompt = DEFAULT_SYSTEM_PROMPT;
let messages     = [{ role: "system", content: systemPrompt }];

// Init: prefill the system prompt textarea
$systemPrompt.value = DEFAULT_SYSTEM_PROMPT;

function resetConversation() {
  messages = [{ role: "system", content: systemPrompt }];
  $log.innerHTML = "";
}

function applyAndReset() {
  systemPrompt = $systemPrompt.value;
  resetConversation();
}

$applyReset.addEventListener("click", applyAndReset);

// Send + New session + streaming wired up in later tasks
```

- [ ] **Step 2: Manually verify default prompt + reset**

Run:
```bash
cd /Users/troylatimer/prompt-sandbox && python3 -m http.server 7000
```

Open `http://localhost:7000`. Verify:
- System prompt textarea is prefilled with the Rational Partner prompt (starts with "Role: You are my Lead Strategic Advisor...")
- Open DevTools console and run `messages` — should show a one-element array with role "system" and the Rational Partner content
- Edit the textarea (add "TEST" at the end), click "Apply & Reset"
- Run `messages` again — the system content should now include "TEST" at the end
- No console errors

Stop the server.

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/prompt-sandbox
git add index.html
git commit -m "Prefill default system prompt and wire Apply & Reset"
```

---

## Task 3: Render user/assistant bubbles and "New session"

Implement bubble rendering and the "New session" button. Still no network — we fake an assistant response by hardcoding one, to confirm rendering and the session-clearing behavior.

**Files:**
- Modify: `~/prompt-sandbox/index.html` (the `<script>` block)

- [ ] **Step 1: Add rendering helpers and wire New session + a temporary fake send**

In `/Users/troylatimer/prompt-sandbox/index.html`, append the following to the end of the existing `<script>` block (replacing the trailing comment `// Send + New session + streaming wired up in later tasks`):

```javascript
function addBubble(role, text = "") {
  const el = document.createElement("div");
  el.className = "bubble " + role;
  el.textContent = text;
  $log.appendChild(el);
  $log.scrollTop = $log.scrollHeight;
  return el;
}

function newSession() {
  resetConversation();
}

$newSession.addEventListener("click", newSession);

// TEMPORARY fake send — replaced with real streaming in Task 4
async function send() {
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";

  messages.push({ role: "user", content: text });
  addBubble("user", text);

  const fake = "This is a fake assistant response. Streaming wired up in Task 4.";
  addBubble("assistant", fake);
  messages.push({ role: "assistant", content: fake });
}

$send.addEventListener("click", send);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
```

- [ ] **Step 2: Manually verify bubbles and New session**

Run:
```bash
cd /Users/troylatimer/prompt-sandbox && python3 -m http.server 7000
```

Open `http://localhost:7000`. Verify:
- Type "hello" in the input, press Enter — a blue-ish bubble appears on the right, then a gray bubble appears on the left with the fake response
- `messages.length` in DevTools should be 3 (system, user, assistant)
- Shift+Enter inserts a newline in the input instead of sending
- Click "New session" — conversation log clears, `messages.length` returns to 1
- System prompt textarea is unchanged after New session
- Edit system prompt, click "Apply & Reset", send a new message — the system prompt in `messages[0]` reflects the edit
- No console errors

Stop the server.

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/prompt-sandbox
git add index.html
git commit -m "Render bubbles and wire New session with fake response"
```

---

## Task 4: Replace fake send with real streaming from MLX

Swap the placeholder response for a real `fetch` to MLX's `/v1/chat/completions` with `stream: true`, parsing the OpenAI-compatible SSE format token-by-token into the assistant bubble. Also disable the Send button while a response is in flight, and render errors inline in red.

**Files:**
- Modify: `~/prompt-sandbox/index.html` (the `<script>` block — replace the `send()` function)

- [ ] **Step 1: Replace the fake `send()` with the streaming implementation**

In `/Users/troylatimer/prompt-sandbox/index.html`, find the `// TEMPORARY fake send` comment and the `async function send()` below it. Replace that entire function (through its closing `}`) with:

```javascript
async function send() {
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";

  messages.push({ role: "user", content: text });
  addBubble("user", text);

  const bubble = addBubble("assistant", "");
  $send.disabled = true;

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL,
        messages: messages,
        stream: true,
      }),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = "";
    let   content = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by blank lines ("\n\n")
      const events = buffer.split("\n\n");
      buffer = events.pop(); // keep the last (possibly partial) event in the buffer

      for (const event of events) {
        // Each event is one or more lines; we only care about "data: ..." lines
        for (const line of event.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (payload === "[DONE]") continue;
          try {
            const json  = JSON.parse(payload);
            const delta = json.choices?.[0]?.delta?.content;
            if (delta) {
              content += delta;
              bubble.textContent = content;
              $log.scrollTop = $log.scrollHeight;
            }
          } catch (err) {
            console.warn("Failed to parse SSE payload:", payload, err);
          }
        }
      }
    }

    messages.push({ role: "assistant", content });
  } catch (err) {
    bubble.classList.add("error");
    bubble.textContent = `⚠ ${err.message}`;
  } finally {
    $send.disabled = false;
  }
}
```

- [ ] **Step 2: Start MLX with CORS enabled**

In a separate terminal:

```bash
source ~/mlx-env/bin/activate
mlx_lm.server \
  --model mlx-community/gemma-4-26B-A4B-it-4bit \
  --port 8080 \
  --cors-allow-origins "*"
```

Wait for the server to report it's listening on port 8080.

- [ ] **Step 3: Manually verify streaming against real MLX**

In another terminal:

```bash
cd /Users/troylatimer/prompt-sandbox && python3 -m http.server 7000
```

Open `http://localhost:7000`. Verify:
- Send "hello" — tokens stream into the assistant bubble (you should *see* them appear incrementally, not all at once)
- The Send button is disabled while the response is streaming, then re-enabled
- After streaming ends, `messages` in DevTools shows 3 entries (system, user, assistant) with the assistant content matching what's on screen
- Click "New session", then send a different message — it gets a fresh response with no memory of the previous turn
- Edit system prompt (e.g., add "Respond only in haiku."), Apply & Reset, send "tell me about the sea" — the response should be a haiku, proving the system prompt is being applied
- Stop MLX (Ctrl+C in its terminal), send a message — the assistant bubble should display a red error, and Send should re-enable
- No unexpected console errors (the `console.warn` for malformed SSE is fine if it appears — it's defensive)

Stop both servers.

- [ ] **Step 4: Commit**

```bash
cd /Users/troylatimer/prompt-sandbox
git add index.html
git commit -m "Stream completions from MLX and render errors inline"
```

---

## Task 5: Write the README

Document launch steps so the sandbox can be used a month from now without remembering the CORS flag or the port numbers.

**Files:**
- Create: `~/prompt-sandbox/README.md`

- [ ] **Step 1: Create `README.md`**

Create `/Users/troylatimer/prompt-sandbox/README.md` with this exact content:

````markdown
# Prompt Sandbox

A tiny browser UI for iterating on system prompts against a local Gemma
model served by `mlx_lm.server`. One HTML file, no build step, no
backend.

## Run

### 1. Start MLX with CORS enabled

```bash
source ~/mlx-env/bin/activate
mlx_lm.server \
  --model mlx-community/gemma-4-26B-A4B-it-4bit \
  --port 8080 \
  --cors-allow-origins "*"
```

The `--cors-allow-origins "*"` flag is required — the browser refuses
cross-origin requests to MLX without it.

### 2. Serve the page

```bash
cd ~/prompt-sandbox
python3 -m http.server 7000
```

### 3. Open it

http://localhost:7000

## Use

- Edit the system prompt at the top, click **Apply & Reset** to apply
  changes and clear the conversation.
- Type in the bottom box. Enter sends; Shift+Enter inserts a newline.
- **New session** clears the conversation but keeps the current system
  prompt in the textarea.

State lives in memory only — a page reload restores the default prompt
and empties the conversation.

## Config

Edit these constants at the top of the `<script>` block in `index.html`:

```js
const API_URL = "http://localhost:8080/v1/chat/completions";
const MODEL   = "mlx-community/gemma-4-26B-A4B-it-4bit";
```

The default system prompt (`DEFAULT_SYSTEM_PROMPT`) lives in the same
block and is the "Rational Partner" prime — override it in the textarea
or edit the constant to change the baseline.

## Doc grounding / RAG

Out of scope for this sandbox. Use AnythingLLM (points at Ollama/MLX,
handles vector DB and retrieval) if you need retrieval over local
documents.
````

- [ ] **Step 2: Manually verify the README renders**

Open the file in a Markdown viewer (or GitHub preview locally) and skim
for broken formatting. Verify:
- Code blocks render correctly
- The triple-backtick-fenced outer block and the inner `bash` / `js`
  blocks nest correctly (the outer uses `````markdown`, the inner use
  triple-backticks)

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/prompt-sandbox
git add README.md
git commit -m "Add README with launch instructions"
```

---

## Final Verification

After all tasks are complete, run one end-to-end smoke test:

- [ ] **Step 1: Start both servers**

Terminal 1:
```bash
source ~/mlx-env/bin/activate
mlx_lm.server --model mlx-community/gemma-4-26B-A4B-it-4bit --port 8080 --cors-allow-origins "*"
```

Terminal 2:
```bash
cd /Users/troylatimer/prompt-sandbox && python3 -m http.server 7000
```

- [ ] **Step 2: Walk the spec's test plan**

Open `http://localhost:7000` and execute the test plan from the spec:

1. Page loads with the Rational Partner prompt prefilled.
2. Send "hello" — tokens stream in.
3. Edit system prompt to "Respond only in haiku.", click **Apply & Reset**, send "tell me about the sea" — response is a haiku.
4. Click **New session** — log clears, textarea untouched, `messages.length === 1`.
5. Stop MLX, send a message — red error appears inline, Send re-enables.

- [ ] **Step 3: Verify git log**

```bash
cd /Users/troylatimer/prompt-sandbox
git log --oneline
```

Expected: commits for skeleton, default prompt + Apply & Reset, bubbles + New session, streaming + errors, README — plus the two earlier spec commits.
