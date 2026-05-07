# Prompt Sandbox — Phase 1: A/B Compare + UI Refresh

**Date:** 2026-04-18
**Status:** Approved design, awaiting implementation plan.
**Parent project:** `prompt-sandbox` (see `docs/superpowers/specs/2026-04-14-prompt-sandbox-design.md` for the original design).

## Context

The sandbox today is a single-pane chat UI. A "prompt sandbox" should let you directly compare system-prompt variants; today that requires manually remembering prior outputs, which defeats the purpose. Simultaneously, the current layout feels cramped — the 90px+ system-prompt textarea always dominates the top, and the vault-controls row competes with it for attention.

This phase delivers two coupled changes: an A/B compare mode, and a UI refresh that makes room for it. The two are bundled because the layout rework only makes sense once we know it has to host two panes, not one.

This is **Phase 1 of 3**. Phase 2 adds persistence (prompt presets, conversation history, export). Phase 3 adds a token/context meter. Phase 1 is foundational — everything later sits inside the shell it establishes.

## Goals

- Compare two system prompts against the same user input, same retrieval context, same model, in parallel.
- Cleaner visual hierarchy: conversation takes primary screen space, controls get out of the way.
- Preserve the "one HTML file, no build, no framework" constraint. Split logic into `<script type="module">` files if needed, but no npm.

## Non-goals

- Persistence of any kind (Phase 2).
- Model switcher (out of scope; MLX serves one model per process).
- Per-pane vault settings — vault is always shared across panes.
- Responsive / mobile layout. Desktop dev tool.
- More than two panes. A/B only.

## Design

### 1. Mode model + layout

- **Default: single pane.** Current behavior preserved when A/B is off.
- **Compare toggle** in the top controls strip enters A/B mode. Icon button labeled "Compare" (or "A/B").
- **In A/B mode**: two chat columns side by side, equal width. Each column has:
  - Its own system-prompt area (collapsible, shared visual style).
  - Its own message log.
  - Its own "Apply & Reset" button.
  - A small header badge: "A" or "B" with a subtle accent color (e.g., `--accent-a`, `--accent-b`).
- **Shared at the top of the page**: compare toggle, new session (affects both panes), vault toggle, top-K, reindex button, vault-health dot.
- **Shared at the bottom**: single input textarea and Send button.
- **Exiting A/B**: discards Pane B (confirm prompt if B has non-empty history); Pane A becomes the single pane. When re-entering, Pane B starts fresh.

### 2. State + send behavior

- Two pane objects: `paneA = { systemPrompt, messages, $log, $systemPrompt, $applyReset }`, same for `paneB`. In single-pane mode, only `paneA` is active.
- `send()` fires one `fetchVaultContext` (if vault toggle is on), then makes one `/v1/chat/completions` request per active pane, in parallel. Each streams into its own pane independently.
- **Error isolation**: a failure in one pane shows an error bubble in that pane only; the other continues.
- **Shared retrieval guarantee**: the single retrieved-notes system message is spliced into both panes' `turnMessages`. Any difference in output between panes is attributable to the system prompt.
- The shared input clears immediately on send; both pending bubbles appear simultaneously.
- `Apply & Reset` is per-pane — changes only that pane's `systemPrompt` and clears only that pane's log.
- "New session" clears both panes' logs, keeps both system prompts.

### 3. Visual refresh

Addressing the "clunky" feel. Ordered by impact:

- **Collapsible system-prompt area**. Default view: a one-line preview with the first ~60 chars + an edit affordance. Click/tap to expand the full textarea inline. Recovers roughly 100px of vertical space per pane and stops the prompt from visually competing with the conversation.
- **Merged controls strip** — one slim top row with: compare toggle, new session, vault toggle, top-K, reindex, vault-health dot. Replaces today's two separate headers.
- **Typographic hierarchy**: slightly larger message text, tighter bubble padding, muted role tags ("You" / "Assistant") above bubbles. Clearer scan path.
- **Pane identity in A/B mode**: subtle color accent on each pane's header strip (badge + border-top). No accent on bubbles — keeps the message content clean. Labels "A" and "B."
- Keep unchanged: dark palette, pulse-while-thinking animation, keyboard shortcuts (Enter send / Shift+Enter newline), vault-source chips.

## Key invariants

- Vault retrieval always runs once per send (not once per pane).
- The retrieved-text system message is byte-identical across panes within a send.
- Streaming parsers run independently per pane — neither pane can stall the other.
- Single-pane mode is the default on page load; A/B is opt-in.

## File layout (constraint: no build, no framework)

The logic grows beyond the current ~460 LOC. Keep it vanilla but split into ES modules loaded via `<script type="module">`:

- `index.html` — markup + styles only (plus a tiny entry-point script block).
- `js/state.js` — pane factory, state types, shared app state.
- `js/send.js` — vault retrieval + parallel fan-out to both panes.
- `js/stream.js` — SSE parsing (extracted from today's inline implementation).
- `js/ui.js` — DOM wiring, collapsible prompt, pane rendering helpers.
- `js/vault.js` — `pingVaultHealth`, `fetchVaultContext`, reindex.

This scales from single-pane → dual-pane cleanly and gives Phase 2/3 a place to add code without inflating one file. No build step — browser-native ES modules served by `python3 -m http.server 7777` work today.

## Acceptance criteria

- Single-pane mode behaves identically to the current tool: same default prompt, same send behavior, same vault integration, same streaming.
- Compare toggle enters A/B mode with Pane A carrying over.
- One send in A/B mode produces two streaming responses in parallel; a kill of one backend connection (simulated) does not block the other.
- Retrieved vault context (when enabled) is identical across panes for any given send.
- System-prompt area is collapsed by default; the one-line preview updates when the prompt changes.
- Vault-health dot behaves unchanged.
- No console errors on mode transitions.
- Page still launches via `./launch.command` with no added setup steps.

## Open follow-ups (not blocking Phase 1)

- What should A/B mode do when the user edits one pane's prompt mid-conversation? (Current answer: that pane's `Apply & Reset` resets only that pane; other pane is untouched. Matches single-pane behavior.)
- Should Pane B default to a copy of Pane A's prompt or to the repo default? (Leaning: repo default, to make the comparison meaningful out of the gate.)
- When entering A/B mode, should Pane A's existing conversation be preserved or cleared? (Leaning: preserved; user opted into compare, not into reset.)

These are minor and can be resolved in the implementation plan.

## Risks

- **Parallel streams compete for the network**: MLX serves one model, one generation at a time per process. Two simultaneous requests may serialize at the MLX layer regardless of what the browser does. Verify during implementation; if so, it's still the correct client behavior and surfaces the real backend constraint instead of hiding it.
- **Module split churn**: refactoring to ES modules touches every line of the current JS. Mitigation: do the split as a no-behavior-change first pass, verified against current single-pane behavior, before adding A/B logic.
- **System-prompt collapse hides state**: users may edit a prompt they can't see. Mitigation: the one-line preview reflects the current `systemPrompt` value, not the textarea — so users always see what the *applied* prompt is, and expansion shows the textarea for edits.

## Verification

- Start the stack: `./launch.command`.
- **Single-pane regression**: default view behaves as before; send + receive + vault toggle + reindex + health dot all work.
- **A/B enter**: click Compare. Pane A unchanged; Pane B empty with repo-default prompt.
- **A/B send**: type one message, send; both panes stream independently.
- **A/B isolation**: kill MLX mid-stream (`lsof -ti :8080 | xargs kill`) during a send; both panes error, but the error bubbles are scoped per pane. Restart MLX; next send works.
- **A/B retrieval parity**: with vault on and top-K=3, send a message; inspect DevTools network → both `/v1/chat/completions` requests carry an identical retrieved-notes system message.
- **Exit A/B**: click Compare off; confirm dialog if Pane B has content; Pane A preserved.
- **Collapse behavior**: preview line matches the applied prompt; edit + Apply updates the preview.
