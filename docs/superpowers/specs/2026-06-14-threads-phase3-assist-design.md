# Threads Add-on — Phase 3 (Assisted Extraction — "✨ Suggest") — Design

**Date:** 2026-06-14
**Status:** Approved (brainstorm), pending implementation plan
**Component:** Prompt Studio (`~/DevSwarmProjects/Clista`)
**Builds on:** Phase 2 (`docs/superpowers/specs/2026-06-14-threads-phase2-seal-design.md`) — the seal modal + `POST /api/threads/seal`.

## Context

Phase 2 captures a decision via a manual 5-field form. Phase 3 makes that capture cheap: a model
reads the current sandbox conversation and proposes the content fields, which the user reviews and
edits before sealing. This is the "assist" that the Phase 2 minimal-form scope was deliberately
betting on.

## Goal

A **"✨ Suggest from conversation"** button in the seal modal that calls the active pane's model to
draft the seal's content fields (question, decision, evidence, objections) from the conversation
transcript, fills them into the existing editable form, and flags them as drafted. The user always
reviews/edits before sealing — never auto-seal.

## Decisions locked in brainstorming

- **Interaction: Suggest button fills the form in place** (not a separate review step). One modal;
  the existing Phase 2 fields fill, editable, then Seal.
- **Trust: assist proposes, the user always edits, then seals.** A visible "drafted — review & edit"
  note keeps the human-in-the-loop framing. No auto-seal.
- **Architecture: fully client-side**, reusing the sandbox's existing model-call path. The browser
  already calls local models directly (LM Studio at `LM_STUDIO_URL`); frontier models go through
  `/api/chat`. No new backend route.
- **Model: the active pane's model.** Whatever the user is conversing with. If local (Gemma), the
  step stays local; if the user deliberately picked a frontier model, it uses that. User stays in
  control of local-vs-cloud by their model choice.
- **Fills content fields only:** question, decision, evidence, objections. Title (session name) and
  Decided-by ("Troy") are left as-is.

## Constraints & principles

- **Reuse existing model infrastructure**; add no backend. Stays consistent with the sandbox's
  local-first, browser-addresses-the-model design.
- **Separate the pure from the impure.** The extraction prompt and the response parser are pure
  functions in their own module, unit-tested with `node --test` (the project's JS-test convention).
  The model call (`runExtraction`) is the only impure part and is covered by manual acceptance.
- **Robust parsing.** The active model may be a reasoning model (Gemma emits a reasoning section
  before content) and may wrap JSON in markdown fences or prose. The parser must recover the JSON
  object regardless, and fail cleanly (graceful error state) when it cannot.

## Architecture

```
Seal modal "✨ Suggest from conversation" button
  └─ window.sealActivePane()            → { model, messages }  (focused pane; pane A in compare mode)
  └─ empty messages? → error state ("start a conversation first")
  └─ working state (disable button, spinner)
  └─ runExtraction(model, buildExtractionMessages(messages))   → raw model text
  └─ parseExtraction(text)              → { question, decision, evidence[], objections[] }
  └─ fill Question/Decision, rebuild evidence + objection rows, show amber "drafted" note
  └─ (any failure) → error state; button always re-enabled
  └─ user edits → existing Phase 2 "Seal →"
```

## Components

### 1. `sandbox/js/seal-extract.js` (new — pure functions)
- `EXTRACTION_PROMPT` (string): a system instruction telling the model to read a decision
  conversation and output ONLY a JSON object with keys `question` (string), `decision` (string),
  `evidence` (array of `{source, finding}`), `objections` (array of `{text}`); no prose, no fences.
- `buildExtractionMessages(transcript)` → `[{role:"system", content: EXTRACTION_PROMPT},
  {role:"user", content: <rendered transcript>}]`. `transcript` is the pane's `messages`
  (`[{role, content}]`); render to a readable "role: content" block.
- `parseExtraction(text)` → `{question, decision, evidence, objections}`. Strips reasoning/markdown
  fences, locates the first balanced `{…}` object, `JSON.parse`s it, and coerces the shape:
  `question`/`decision` → strings (default `""`); `evidence` → array of `{source, finding}` strings,
  dropping malformed items; `objections` → array of `{text}` strings. Throws a clear error when no
  JSON object can be recovered.
- These are `export`ed and unit-tested.

### 2. Suggest wiring (in `sandbox/index.html` seal script)
- A `<button id="seal-suggest-btn">✨ Suggest from conversation</button>` in the modal header.
- On click: call `window.sealActivePane()`; if no messages, show the empty-conversation error and
  return. Otherwise set the working state (disable button, label "Reading conversation…"), call
  `runExtraction`, then `parseExtraction`, then populate the fields (set Question/Decision inputs;
  clear and rebuild evidence rows from `evidence[]`; clear and rebuild objection rows from
  `objections[]`), and show the amber "✨ Drafted from conversation — review & edit before sealing"
  note. On any error, show the error message. Always re-enable the button.
- `runExtraction(model, messages)` (impure helper, in the same script): for `model.provider ===
  "lmstudio"`, `POST {model.endpoint}` with `{model: model.id, messages, stream: false}` and read
  `choices[0].message.content` (falling back to `.reasoning` only if `content` is empty); for other
  providers, POST `/api/chat` with `{provider, model, messages}` and accumulate the streamed text to
  completion. Returns the full response string.

### 3. Bridge (`sandbox/js/app.js`)
- Expose `window.sealActivePane = () => ({ model, messages })` for the focused pane (pane A when in
  A/B compare mode), sourced from the existing pane state (`state.messages` + the pane's model
  config). One small, explicit global so the modal script can read pane context without coupling to
  module internals.

## Data flow

Suggest click → `sealActivePane()` → `buildExtractionMessages(messages)` → `runExtraction` (active
model) → response text → `parseExtraction` → fill fields → user edits → Phase 2 seal POST.

## Error handling

- **Empty transcript** (no messages) → inline notice "Start a conversation first," no model call.
- **Model unreachable / fetch error** → "Model unreachable — is it running?" error state.
- **Non-JSON / unparseable response** → "Couldn't draft from this conversation. Fill manually or try
  again." (`parseExtraction` throws → caught).
- The Suggest button is re-enabled after every outcome; partial fills are never committed silently —
  on parse failure no fields are changed.

## Testing

- **`node --test` for `sandbox/js/seal-extract.js`:** `parseExtraction` on (a) clean JSON, (b) JSON
  in a ```json fence, (c) JSON after a reasoning preamble, (d) missing keys → defaulted shape,
  (e) garbage → throws; `buildExtractionMessages` returns the system+user shape with the transcript
  rendered. Run with `node --test sandbox/js/*.test.js` (existing convention).
- **Manual browser acceptance:** have a short decision conversation with the local model, open the
  seal modal, click ✨ Suggest, confirm the content fields fill with the amber note, edit a field,
  and Seal — confirming the sealed thread appears in the Threads tab.

## Non-goals (deferred)

- No streaming the draft token-by-token into the fields (one-shot fill once the response is complete).
- No extraction of Title or Decided-by.
- No auto-seal — the user always edits and clicks Seal.
- No multi-pane merge — compare mode uses the focused pane (pane A) only.
- No server-side extraction route.
- No formal-decision enrichment (authority/assumptions/review) — that remains a separate later step.

## Open items for the implementation plan

- Confirm the exact shape the active model returns for the `lmstudio` non-streaming call (whether
  Gemma's reasoning lands in a separate `reasoning` field vs inline in `content`) and that
  `parseExtraction` handles both — verify against the running model when writing task code.
- Confirm the `/api/chat` streamed-accumulation path's chunk format for the frontier fallback.
