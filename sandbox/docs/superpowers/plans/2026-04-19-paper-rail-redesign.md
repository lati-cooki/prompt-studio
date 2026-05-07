# Paper + Rail UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current dark near-black UI with the "Warm Paper + Rail" aesthetic: Geist typography, warm paper palette, left sessions rail, redesigned prompt strip, new composer, and compare-mode per-pane colored headers.

**Architecture:** Replace `index.html`'s `<style>` block and top-level markup entirely; rewrite `pane.js` DOM structure with single/compare CSS toggling via the `.compare` class; create `js/session-rail.js` to render the persistent sessions rail; lightly update `js/app.js` to wire the rail, remove the old dropdown, and add keyboard shortcuts; restyle `js/meter.js` internals. All state management, streaming, and logic modules are untouched.

**Tech Stack:** Vanilla HTML/CSS/ES modules (no build step, no framework); Geist + Geist Mono from Google Fonts.

**Design reference files (read-only, do not copy directly into production):**
- `/Users/troylatimer/Downloads/design_handoff_prompt_sandbox/README.md` — tokens, layout spec, interaction rules
- `/Users/troylatimer/Downloads/design_handoff_prompt_sandbox/mockups/paper-rail.jsx` — C1 single mode
- `/Users/troylatimer/Downloads/design_handoff_prompt_sandbox/mockups/paper-rail-compare.jsx` — C2 compare mode

---

## File Map

| File | Action | Notes |
|---|---|---|
| `index.html` | **rewrite** `<style>` + HTML body | Keep `<script type="module" src="./js/app.js">` exactly |
| `js/pane.js` | **rewrite** | New DOM structure; keep all exported method contracts |
| `js/session-rail.js` | **create** | Replaces session-panel.js for rail rendering |
| `js/meter.js` | **edit** | New threshold colors + appends to `.pane-meta-row` |
| `js/app.js` | **edit lightly** | Remove old sessions panel, wire rail, add shortcuts |
| `js/session-panel.js` | **keep** (unused) | App.js import replaced by session-rail.js |
| Everything else | **untouched** | |

---

## Task 1: CSS Design Tokens + Geist Fonts + Base Layout

**Files:**
- Modify: `index.html` (entire `<style>` block + `<head>` + `<body>` skeleton)

Replace the current `<style>` block and body markup with the new structure. This task creates the skeleton only — no pane content, no rail content yet.

- [ ] **Step 1: Replace `<head>` to add Geist fonts + new `<style>` block**

In `index.html`, replace everything from `<head>` through `</style>` with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Prompt Sandbox</title>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  /* ── Design tokens ─────────────────────────────────── */
  :root {
    /* surfaces */
    --bg:         #f6f3ee;
    --rail:       #eee8dd;
    --panel-alt:  #faf7f1;
    --panel:      #efeae1;

    /* ink */
    --ink:        #1f2529;
    --ink-dim:    #4a5056;
    --muted:      #6b7278;
    --faint:      #a8ada8;

    /* rules */
    --hair:       #d9d4c8;
    --hair-soft:  #e4dfd3;

    /* accents */
    --accent:       #3f7a7a;
    --accent-b:     #8a6a9c;
    --accent-ok:    #6a9c6a;
    --accent-warn:  #c89a3a;
    --accent-err:   #b85450;
  }

  /* ── Reset ─────────────────────────────────────────── */
  *, *::before, *::after { box-sizing: border-box; }
  html, body {
    margin: 0; height: 100%;
    background: var(--bg); color: var(--ink);
    font-family: "Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 13px; line-height: 1.55; letter-spacing: -0.003em;
  }
  body { display: flex; flex-direction: row; overflow: hidden; }

  /* ── Mono utility ───────────────────────────────────── */
  .mono {
    font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  }

  /* ── Layout ─────────────────────────────────────────── */
  .main-wrap {
    flex: 1; display: flex; flex-direction: column;
    min-width: 0; min-height: 0;
  }

  /* ── Rail (left sessions sidebar) ───────────────────── */
  .rail {
    width: 232px; flex-shrink: 0;
    background: var(--rail);
    border-right: 1px solid var(--hair);
    display: flex; flex-direction: column;
    padding: 16px 0;
    overflow: hidden;
  }
  .rail-header {
    display: flex; align-items: center; gap: 10px;
    padding: 0 18px 16px;
  }
  .rail-logo {
    width: 22px; height: 22px; border-radius: 4px;
    background: var(--ink); color: var(--bg);
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; flex-shrink: 0;
  }
  .rail-title { font-size: 13px; font-weight: 600; letter-spacing: -0.01em; }
  .rail-header-spacer { flex: 1; }
  .rail-mode-tag {
    font-family: "Geist Mono", monospace;
    font-size: 10px; color: var(--faint);
  }
  .rail-new-wrap { padding: 0 12px 12px; }
  .rail-new-btn {
    width: 100%; background: var(--bg); color: var(--ink);
    border: 1px solid var(--hair); padding: 8px 10px;
    border-radius: 3px; display: flex; align-items: center; gap: 8px;
    font-family: inherit; font-size: 12.5px; cursor: pointer;
  }
  .rail-new-btn:hover { background: var(--panel-alt); }
  .rail-new-plus { color: var(--accent); font-size: 14px; line-height: 1; }
  .rail-new-spacer { flex: 1; }
  .rail-new-kbd {
    font-family: "Geist Mono", monospace;
    font-size: 10px; color: var(--faint);
  }
  .rail-saved-label {
    padding: 12px 18px 6px;
    font-family: "Geist Mono", monospace;
    font-size: 10px; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--faint);
  }
  .rail-list { flex: 1; overflow-y: auto; }
  .rail-session-row {
    padding: 7px 18px; display: flex; align-items: center; gap: 10px;
    font-size: 12.5px; color: var(--ink-dim); cursor: pointer;
    border-left: 2px solid transparent;
    position: relative;
  }
  .rail-session-row:hover { background: var(--panel-alt); }
  .rail-session-row.active {
    background: var(--bg); color: var(--ink);
    border-left: 2px solid var(--accent);
    margin-left: -1px;
  }
  .rail-session-dots {
    font-family: "Geist Mono", monospace;
    font-size: 10px; color: var(--faint);
    width: 16px; letter-spacing: 1px; flex-shrink: 0;
  }
  .rail-session-name {
    flex: 1; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }
  .rail-session-age {
    font-family: "Geist Mono", monospace;
    font-size: 10px; color: var(--faint); flex-shrink: 0;
  }
  .rail-session-del {
    display: none; position: absolute; right: 10px;
    background: transparent; border: none;
    color: var(--muted); font-size: 11px; cursor: pointer;
    padding: 2px 4px; line-height: 1;
  }
  .rail-session-row:hover .rail-session-del { display: block; }
  .rail-session-row:hover .rail-session-age { display: none; }
  .rail-empty {
    padding: 14px 18px; color: var(--muted);
    font-size: 12px; font-style: italic;
  }
  .rail-save-slot { padding: 0 12px 8px; }
  .rail-save-btn {
    width: 100%; background: transparent; color: var(--muted);
    border: 1px solid var(--hair); padding: 6px 10px;
    border-radius: 3px; font-family: inherit; font-size: 12px;
    cursor: pointer; text-align: left;
  }
  .rail-save-btn:hover { color: var(--ink); border-color: var(--ink-dim); }
  .rail-save-form {
    display: flex; gap: 6px; align-items: center;
  }
  .rail-save-form[hidden] { display: none; }
  .rail-save-input {
    flex: 1; background: var(--bg); color: var(--ink);
    border: 1px solid var(--hair); border-radius: 2px;
    padding: 5px 8px; font-family: inherit; font-size: 12px;
  }
  .rail-save-input:focus { outline: none; border-color: var(--accent); }
  .rail-save-confirm {
    background: var(--ink); color: var(--bg); border: none;
    padding: 5px 10px; border-radius: 2px;
    font-family: "Geist Mono", monospace; font-size: 10px;
    letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer;
  }
  .rail-save-cancel {
    background: transparent; color: var(--muted);
    border: 1px solid var(--hair); padding: 5px 8px;
    border-radius: 2px; font-family: inherit; font-size: 12px; cursor: pointer;
  }
  .rail-vault {
    margin: 10px 12px 4px;
    padding: 12px; border-radius: 3px;
    background: var(--bg); border: 1px solid var(--hair);
    font-family: "Geist Mono", monospace; font-size: 11px;
  }
  .rail-vault-row {
    display: flex; align-items: center; gap: 8px;
    color: var(--ink); margin-bottom: 6px;
  }
  .health-dot {
    display: inline-block; width: 7px; height: 7px;
    border-radius: 50%; background: var(--faint); flex-shrink: 0;
  }
  .health-dot.ok   { background: var(--accent-ok); }
  .health-dot.down { background: var(--accent-err); }
  .rail-vault-port { color: var(--faint); margin-left: auto; }
  .rail-vault-sub { color: var(--muted); font-size: 10.5px; line-height: 1.5; }

  /* ── Top bar ─────────────────────────────────────────── */
  .topbar {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 22px;
    border-bottom: 1px solid var(--hair-soft);
    background: var(--bg); flex-shrink: 0;
  }
  .topbar-crumb {
    display: flex; align-items: baseline; gap: 8px;
    min-width: 0; flex: 1;
  }
  .topbar-session {
    font-family: "Geist Mono", monospace;
    font-size: 11px; color: var(--faint);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .topbar-sep { color: var(--faint); flex-shrink: 0; }
  .topbar-subtitle { font-size: 13px; font-weight: 500; white-space: nowrap; }
  .topbar-dots {
    display: inline-flex; gap: 2px; align-items: center; margin-left: 4px;
  }
  .topbar-dots span {
    width: 4px; height: 4px; border-radius: 50%; background: var(--accent);
  }
  .topbar-dots span:nth-child(1) { opacity: 0.4; }
  .topbar-dots span:nth-child(2) { opacity: 0.6; }
  .topbar-dots span:nth-child(3) { opacity: 0.8; animation: dot-pulse 1.2s ease-in-out infinite; }
  @keyframes dot-pulse { 0%,100%{opacity:.8} 50%{opacity:.3} }
  .topbar-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

  /* Mode toggle */
  .seg-toggle {
    display: inline-flex;
    border: 1px solid var(--hair); border-radius: 3px;
    background: var(--panel-alt); overflow: hidden;
    font-family: "Geist Mono", monospace; font-size: 11px;
  }
  .seg-btn {
    padding: 5px 11px;
    background: transparent; border: none; cursor: pointer;
    color: var(--muted); font-family: inherit; font-size: inherit;
    display: inline-flex; align-items: center; gap: 5px;
    white-space: nowrap;
  }
  .seg-btn.seg-active { background: var(--ink); color: var(--bg); }
  .seg-dot {
    width: 4px; height: 4px; border-radius: 50%; background: var(--accent);
  }
  .seg-dot-a { width: 4px; height: 4px; border-radius: 50%; background: var(--accent); }
  .seg-dot-b { width: 4px; height: 4px; border-radius: 50%; background: var(--accent-b); }

  /* Ghost / stop buttons */
  .ghost-btn {
    background: transparent; border: 1px solid var(--hair); color: var(--muted);
    padding: 5px 10px; border-radius: 3px;
    font-family: "Geist Mono", monospace; font-size: 11px; cursor: pointer;
    white-space: nowrap;
  }
  .ghost-btn:hover { color: var(--ink); }
  .stop-btn {
    background: var(--bg); border: 1px solid var(--accent-err);
    color: var(--accent-err); padding: 5px 10px; border-radius: 3px;
    font-family: "Geist Mono", monospace; font-size: 11px; cursor: pointer;
    white-space: nowrap;
  }

  /* ── Pane container ──────────────────────────────────── */
  .pane-container {
    flex: 1; display: flex; min-height: 0; overflow: hidden;
  }
  .pane {
    flex: 1; display: flex; flex-direction: column;
    min-height: 0; min-width: 0; background: var(--bg);
  }
  .pane + .pane { border-left: 1px solid var(--hair-soft); }

  /* ── Pane prompt header (single mode default) ─────────── */
  .pane-prompt {
    background: var(--panel-alt);
    border-bottom: 1px solid var(--hair-soft);
    flex-shrink: 0;
  }
  /* Compare mode: 2px accent stripe at top */
  .compare .pane[data-pane-id="A"] .pane-prompt {
    border-top: 2px solid var(--accent);
  }
  .compare .pane[data-pane-id="B"] .pane-prompt {
    border-top: 2px solid var(--accent-b);
  }

  /* Label row (single mode only) */
  .pane-label-row {
    display: flex; align-items: baseline; justify-content: space-between;
    padding: 16px 22px 8px;
  }
  .compare .pane .pane-label-row { display: none; }
  .pane-prompt-label {
    font-family: "Geist Mono", monospace;
    font-size: 10px; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--faint);
  }

  /* Meta row (model select + meter) — visible in both modes */
  .pane-meta-row {
    display: flex; align-items: center; gap: 10px;
    padding: 0 22px 0;
  }
  /* In compare mode, padding adjusts and badge shows */
  .compare .pane .pane-meta-row { padding: 12px 18px 8px; }

  /* Badge (compare only) */
  .pane-badge {
    display: none;
    font-family: "Geist Mono", monospace;
    font-size: 11px; font-weight: 600;
    padding: 2px 8px; border-radius: 2px;
    color: #fff; letter-spacing: 0.04em;
    flex-shrink: 0;
  }
  .compare .pane .pane-badge { display: inline-flex; }
  .compare .pane[data-pane-id="A"] .pane-badge { background: var(--accent); }
  .compare .pane[data-pane-id="B"] .pane-badge { background: var(--accent-b); }

  /* Model select */
  .pane-model-select {
    background: transparent; color: var(--muted);
    border: none; outline: none; cursor: pointer;
    font-family: "Geist Mono", monospace; font-size: 11px;
    padding: 0; appearance: none; -webkit-appearance: none;
  }
  /* Styled wrapper for the model select in single mode */
  .pane-model-wrap {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 5px 10px; border: 1px solid var(--hair);
    border-radius: 3px; background: var(--panel-alt);
    font-family: "Geist Mono", monospace; font-size: 11px;
    cursor: pointer; position: relative;
  }
  .pane-model-dot {
    width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
  }
  .pane-meta-spacer { flex: 1; }

  /* Meter — injected by meter.js into .pane-meta-row */
  .meter {
    display: flex; align-items: center; gap: 8px;
    font-family: "Geist Mono", monospace;
    font-size: 10.5px; color: var(--muted);
  }
  .meter-numbers { white-space: nowrap; }
  .meter-used { color: var(--muted); }
  .meter-bar {
    width: 140px; height: 3px;
    background: var(--hair); border-radius: 2px; overflow: hidden;
    flex-shrink: 0;
  }
  .compare .pane .meter-bar { width: 90px; }
  .meter-fill {
    height: 100%; background: var(--accent);
    transition: width 0.1s linear, background 0.2s;
    width: 0%;
  }
  .meter.amber .meter-fill { background: var(--accent-warn); }
  .meter.red   .meter-fill { background: var(--accent-err); }
  /* In compare mode, meter fill color is pane-specific */
  .compare .pane[data-pane-id="B"] .meter-fill { background: var(--accent-b); }
  .compare .pane[data-pane-id="B"] .meter.amber .meter-fill { background: var(--accent-warn); }
  .compare .pane[data-pane-id="B"] .meter.red   .meter-fill { background: var(--accent-err); }

  /* Prompt body (read-only preview, shown when not editing/collapsed) */
  .pane-prompt-body {
    margin: 8px 22px 0;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--hair);
    border-left: 2px solid var(--accent);
    border-radius: 2px;
    font-family: "Geist Mono", monospace;
    font-size: 12.5px; line-height: 1.65; color: var(--ink);
    cursor: pointer; user-select: none;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .compare .pane[data-pane-id="B"] .pane-prompt-body {
    border-left: 2px solid var(--accent-b);
  }
  .pane-prompt-gt { color: var(--muted); }

  /* Collapsed: hide body and hint, just show meta rows */
  .pane-prompt.collapsed .pane-prompt-body { display: none; }
  .pane-prompt.collapsed .pane-prompt-hint { display: none; }
  .pane-prompt.collapsed .pane-label-row { padding-bottom: 10px; }

  /* Editing: swap body for textarea */
  .pane-prompt.editing .pane-prompt-body { display: none; }
  .pane-prompt-expanded {
    display: none;
    flex-direction: column; gap: 8px;
    padding: 8px 22px 0;
  }
  .pane-prompt.editing .pane-prompt-expanded { display: flex; }
  .pane-prompt-textarea {
    min-height: 90px;
    background: var(--bg); color: var(--ink);
    border: 1px solid var(--hair);
    border-left: 2px solid var(--accent);
    border-radius: 2px;
    padding: 10px 12px;
    font-family: "Geist Mono", monospace;
    font-size: 12.5px; line-height: 1.65;
    resize: vertical; outline: none;
  }
  .compare .pane[data-pane-id="B"] .pane-prompt-textarea {
    border-left: 2px solid var(--accent-b);
  }
  .pane-prompt-textarea:focus { border-color: var(--accent); }
  .compare .pane[data-pane-id="B"] .pane-prompt-textarea:focus {
    border-color: var(--accent-b);
  }
  .pane-apply-reset {
    align-self: flex-end;
    background: var(--ink); color: var(--bg); border: none;
    padding: 6px 14px; border-radius: 2px;
    font-family: "Geist Mono", monospace; font-size: 10px;
    letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer;
  }

  /* Prompt hint */
  .pane-prompt-hint {
    margin: 8px 22px 14px;
    font-family: "Geist Mono", monospace;
    font-size: 11px; color: var(--faint);
  }
  /* In compare mode with collapsed (default), show a smaller version */
  .compare .pane .pane-prompt-hint { margin: 0 18px 10px; }

  /* ── Compare mode: compact header for pane-meta-row ─────── */
  /* In compare mode, reduce vertical spacing for compact look */
  .compare .pane .pane-label-row { display: none; }
  .compare .pane .pane-prompt-body {
    margin: 0 18px 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    font-size: 11.5px;
  }
  .compare .pane .pane-prompt-hint { display: none; }
  .compare .pane .pane-meta-row { margin-bottom: 8px; }

  /* ── Log ─────────────────────────────────────────────── */
  .pane-log {
    flex: 1; overflow-y: auto;
    padding: 18px 22px 24px;
    display: flex; flex-direction: column; gap: 14px;
    position: relative;
  }
  /* Baseline rule grid */
  .pane-log::before {
    content: '';
    position: absolute; inset: 0;
    pointer-events: none; opacity: 0.3;
    background-image: repeating-linear-gradient(
      to bottom,
      transparent 0, transparent 27px,
      var(--hair-soft) 27px, var(--hair-soft) 28px
    );
  }
  .compare .pane .pane-log { padding: 18px 20px 24px; }

  /* ── Bubbles ─────────────────────────────────────────── */
  .bubble-wrap {
    display: flex; flex-direction: column;
    max-width: 86%; position: relative; z-index: 1;
  }
  .bubble-wrap.user { align-self: flex-end; align-items: flex-end; }
  .bubble-wrap.assistant { align-self: flex-start; align-items: flex-start; }
  .bubble-role {
    font-family: "Geist Mono", monospace;
    font-size: 10px; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--faint);
    margin-bottom: 4px;
  }
  .bubble-wrap.user .bubble-role { padding-right: 2px; }
  .bubble-wrap.assistant .bubble-role { padding-left: 2px; }
  .bubble {
    font-size: 13.5px; line-height: 1.6; color: var(--ink);
    padding: 10px 14px; border-radius: 3px;
    max-width: 100%; white-space: pre-wrap; word-wrap: break-word;
  }
  .bubble.user {
    background: var(--bg);
    border: 1px solid var(--hair);
  }
  .bubble.assistant {
    background: var(--panel-alt);
    border: 1px solid var(--hair-soft);
    border-left: 2px solid var(--accent);
  }
  /* Pane B assistant bubbles use plum */
  .compare .pane[data-pane-id="B"] .bubble.assistant {
    border-left: 2px solid var(--accent-b);
  }
  .bubble.error { color: var(--accent-err); border-color: var(--accent-err); }
  .bubble.pending {
    color: var(--muted);
    animation: pulse 1.2s ease-in-out infinite;
  }
  /* Streaming caret on last pending bubble */
  .bubble.assistant.pending::after {
    content: '';
    display: inline-block;
    width: 6px; height: 14px;
    background: var(--accent);
    vertical-align: text-bottom;
    margin-left: 3px; opacity: 0.8;
  }
  .compare .pane[data-pane-id="B"] .bubble.assistant.pending::after {
    background: var(--accent-b);
  }
  @keyframes pulse { 0%,100%{opacity:.9} 50%{opacity:.4} }

  /* Reasoning tokens */
  .bubble.assistant .reasoning {
    display: block;
    color: var(--muted); font-style: italic;
    font-size: 12.5px; line-height: 1.5;
  }
  .bubble.assistant .reasoning:not(:empty) { margin-bottom: 6px; }
  .bubble.assistant .content { display: block; }

  /* Sources chips */
  .bubble.assistant .sources {
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    margin-top: 8px;
    font-family: "Geist Mono", monospace; font-size: 10.5px; color: var(--muted);
  }
  .bubble.assistant .sources .source-label { color: var(--faint); }
  .bubble.assistant .sources span:not(.source-label) {
    padding: 1px 6px;
    border: 1px solid var(--hair);
    border-radius: 2px;
    background: var(--panel-alt);
    color: var(--ink-dim);
    text-decoration: underline dotted;
    cursor: help;
  }

  /* Log notes */
  .log-note {
    align-self: center;
    color: var(--muted); font-size: 12px; font-style: italic;
    padding: 2px 8px; position: relative; z-index: 1;
  }

  /* ── Empty state ─────────────────────────────────────── */
  .empty-state {
    display: flex; align-items: center; justify-content: center;
    flex: 1; padding: 64px 22px;
  }
  .empty-state-inner {
    max-width: 440px; text-align: center;
    position: relative; z-index: 1;
  }
  .empty-tag {
    font-family: "Geist Mono", monospace;
    font-size: 10px; letter-spacing: 0.18em;
    text-transform: uppercase; color: var(--faint);
    margin-bottom: 24px;
  }
  .empty-hero {
    font-size: 26px; font-weight: 500;
    letter-spacing: -0.015em; line-height: 1.2;
    margin-bottom: 14px;
  }
  .empty-body {
    font-size: 13px; color: var(--muted);
    margin-bottom: 28px; line-height: 1.55;
  }
  .empty-body em {
    color: var(--ink); font-style: normal;
    border-bottom: 1px dotted var(--muted);
  }
  .empty-shortcuts {
    display: inline-flex; gap: 6px;
    font-family: "Geist Mono", monospace; font-size: 11px; color: var(--muted);
  }
  .kbd-chip {
    padding: 3px 8px;
    border: 1px solid var(--hair);
    border-radius: 2px;
  }

  /* ── Composer ────────────────────────────────────────── */
  .composer {
    border-top: 1px solid var(--hair-soft);
    background: var(--panel-alt);
    padding: 14px 22px 18px;
    flex-shrink: 0;
  }
  .composer-field {
    display: flex; align-items: stretch; gap: 12px;
    background: var(--bg);
    border: 1px solid var(--hair);
    border-radius: 3px; padding: 12px 14px;
  }
  .composer-label {
    font-family: "Geist Mono", monospace;
    font-size: 11px; color: var(--faint);
    padding-top: 3px; min-width: 44px; flex-shrink: 0;
    white-space: nowrap;
  }
  .composer-field textarea {
    flex: 1; min-height: 54px; max-height: 200px;
    background: transparent; color: var(--ink);
    border: none; outline: none;
    font-family: inherit; font-size: 13.5px; line-height: 1.55;
    resize: vertical;
  }
  .composer-field textarea::placeholder { color: var(--faint); }
  .composer-send-col {
    display: flex; flex-direction: column;
    align-items: flex-end; gap: 6px; flex-shrink: 0;
  }
  #send {
    background: var(--ink); color: var(--bg); border: none;
    padding: 6px 16px; border-radius: 2px;
    font-family: "Geist Mono", monospace; font-size: 11px;
    letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer;
  }
  #send:disabled {
    background: var(--faint); cursor: not-allowed;
  }
  .composer-hint {
    font-family: "Geist Mono", monospace;
    font-size: 10px; color: var(--faint);
    white-space: nowrap;
  }
  .composer-controls {
    margin-top: 8px; display: flex; align-items: center; gap: 14px;
    font-family: "Geist Mono", monospace; font-size: 11px; color: var(--muted);
  }
  .vault-label {
    display: flex; align-items: center; gap: 6px; cursor: pointer;
  }
  .vault-checkbox-box {
    width: 14px; height: 14px;
    border: 1px solid var(--ink); background: transparent;
    display: inline-flex; align-items: center; justify-content: center;
    color: transparent; font-size: 10px; border-radius: 2px;
    flex-shrink: 0;
  }
  .vault-checkbox-box.checked {
    background: var(--ink); color: var(--bg);
  }
  .top-k-input {
    width: 40px; background: var(--bg); color: var(--ink);
    border: 1px solid var(--hair); border-radius: 2px;
    padding: 1px 4px; font-family: inherit; font-size: inherit;
    outline: none; text-align: center;
  }
  .composer-spacer { flex: 1; }
  .vault-inline-status {
    color: var(--faint); font-size: 10.5px;
    max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .compare .composer-label::after { content: ''; }
</style>
```

- [ ] **Step 2: Replace `<body>` markup with new layout skeleton**

Replace everything after `</style>` and before `</html>` with:

```html
</head>
<body>

<!-- ── Left sessions rail ───────────────────────────── -->
<aside class="rail" id="sessions-rail">
  <div class="rail-header">
    <div class="rail-logo">◐</div>
    <span class="rail-title">Sandbox</span>
    <span class="rail-header-spacer"></span>
    <span class="rail-mode-tag" id="rail-mode-tag">v2</span>
  </div>

  <div class="rail-new-wrap">
    <button class="rail-new-btn" id="new-session">
      <span class="rail-new-plus">＋</span>
      New session
      <span class="rail-new-spacer"></span>
      <span class="rail-new-kbd">⌘N</span>
    </button>
  </div>

  <div class="rail-saved-label">Saved</div>
  <div class="rail-list" id="sessions-list"></div>

  <div class="rail-save-slot" id="sessions-save-slot"></div>

  <div class="rail-vault" id="vault-card">
    <div class="rail-vault-row">
      <span class="health-dot" id="vault-health" title="Vault search: checking…"></span>
      <span>vault-search</span>
      <span class="rail-vault-port">:8100</span>
    </div>
    <div class="rail-vault-sub" id="vault-card-sub">checking…</div>
  </div>
</aside>

<!-- ── Main area ─────────────────────────────────────── -->
<div class="main-wrap">

  <header class="topbar">
    <div class="topbar-crumb">
      <span class="topbar-session" id="topbar-session">untitled</span>
      <span class="topbar-sep">/</span>
      <span class="topbar-subtitle" id="topbar-subtitle">empty conversation</span>
      <span class="topbar-dots" id="topbar-dots" hidden>
        <span></span><span></span><span></span>
      </span>
    </div>
    <div class="topbar-actions">
      <div class="seg-toggle" id="mode-toggle">
        <button class="seg-btn seg-active" id="seg-single">
          <span class="seg-dot"></span>Single
        </button>
        <button class="seg-btn" id="seg-compare">
          <span class="seg-dot-a"></span><span class="seg-dot-b"></span>Compare A / B
        </button>
      </div>
      <button class="ghost-btn" id="export-btn">Export .md</button>
      <button class="stop-btn" id="stop-both" hidden>⏹ Stop both</button>
    </div>
  </header>

  <main class="pane-container" id="pane-container"></main>

  <footer class="composer">
    <div class="composer-field">
      <span class="composer-label" id="composer-label">you</span>
      <textarea id="input" placeholder="Message…" rows="2"></textarea>
      <div class="composer-send-col">
        <button id="send">SEND ↵</button>
        <span class="composer-hint" id="send-hint">shift+↵ newline</span>
      </div>
    </div>
    <div class="composer-controls">
      <label class="vault-label" id="vault-label-wrap">
        <span class="vault-checkbox-box" id="vault-checkbox-visual"></span>
        <input type="checkbox" id="use-vault"
               style="position:absolute;opacity:0;pointer-events:none;width:0;height:0">
        use vault
      </label>
      <span>top-K <input type="number" id="top-k" min="1" max="20" value="5"
                         class="top-k-input"></span>
      <button class="ghost-btn" id="reindex">Reindex</button>
      <span class="composer-spacer"></span>
      <span class="vault-inline-status" id="vault-status"></span>
    </div>
  </footer>

</div>

<script type="module" src="./js/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Run tests to confirm logic modules unaffected**

```bash
cd /Users/troylatimer/prompt-sandbox
node --test js/*.test.js
```
Expected: all tests pass (no DOM modules tested).

- [ ] **Step 4: Open in browser and verify skeleton**

```bash
python3 -m http.server 7777
```
Open `http://localhost:7777`. Expected: warm beige page, left rail visible (empty), topbar visible, composer at bottom. No functionality yet — pane-container is empty because app.js still references removed elements.

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/prompt-sandbox
git add index.html
git commit -m "feat: add CSS design tokens, Geist fonts, and HTML layout skeleton for Paper+Rail redesign"
```

---

## Task 2: Rewrite `js/pane.js` — New DOM Structure

**Files:**
- Modify: `js/pane.js`

Update `createPane` to emit the new markup. Keep all exported method contracts: `id`, `section`, `textarea`, `applyReset`, `log`, `refreshPreview`, `modelSelect`, `setModelKey`, `onModelChange`, `addBubble`, `addLogNote`, `clearLog`, `renderFromMessages`, `onUsage`.

- [ ] **Step 1: Replace `js/pane.js` entirely**

```js
function oneLinePreview(text) {
  const firstLine = text.split("\n", 1)[0].trim();
  if (firstLine.length <= 80) return firstLine || "(empty prompt)";
  return firstLine.slice(0, 77) + "…";
}

export function createPane({ id, container, initialPrompt, modelKeys = [], initialModelKey = null }) {
  // ── Section ──────────────────────────────────────────
  const section = document.createElement("section");
  section.className      = "pane";
  section.dataset.paneId = id;

  // ── Prompt header ────────────────────────────────────
  const header = document.createElement("header");
  // In compare mode start collapsed; single mode starts expanded (CSS handles via no .collapsed class).
  header.className = "pane-prompt";

  // Label row (single-mode only — compare hides it via CSS)
  const labelRow = document.createElement("div");
  labelRow.className = "pane-label-row";

  const promptLabel = document.createElement("span");
  promptLabel.className   = "pane-prompt-label";
  promptLabel.textContent = "SYSTEM PROMPT";

  // Token meta label (right side — meter.js overwrites this)
  labelRow.appendChild(promptLabel);

  // Meta row (badge + model select + spacer + meter slot)
  const metaRow = document.createElement("div");
  metaRow.className = "pane-meta-row";

  const badge = document.createElement("span");
  badge.className   = "pane-badge";
  badge.textContent = id;

  const modelSelect = document.createElement("select");
  modelSelect.className = "pane-model-select";
  for (const key of modelKeys) {
    const opt = document.createElement("option");
    opt.value       = key;
    opt.textContent = key;
    if (key === initialModelKey) opt.selected = true;
    modelSelect.appendChild(opt);
  }

  const metaSpacer = document.createElement("span");
  metaSpacer.className = "pane-meta-spacer";

  metaRow.appendChild(badge);
  metaRow.appendChild(modelSelect);
  metaRow.appendChild(metaSpacer);
  // meter.js appends its element to metaRow after this

  // Prompt body (read-only preview, click-to-edit)
  const promptBody = document.createElement("div");
  promptBody.className = "pane-prompt-body";

  const promptGt = document.createElement("span");
  promptGt.className   = "pane-prompt-gt";
  promptGt.textContent = "> ";

  const promptPreviewText = document.createElement("span");
  promptPreviewText.textContent = oneLinePreview(initialPrompt);

  promptBody.appendChild(promptGt);
  promptBody.appendChild(promptPreviewText);

  // Expanded area (textarea + Apply button)
  const expandedArea = document.createElement("div");
  expandedArea.className = "pane-prompt-expanded";
  expandedArea.hidden    = true;

  const textarea = document.createElement("textarea");
  textarea.className  = "pane-prompt-textarea";
  textarea.spellcheck = false;
  textarea.value      = initialPrompt;

  const applyReset = document.createElement("button");
  applyReset.className   = "pane-apply-reset";
  applyReset.textContent = "Apply & Reset";

  expandedArea.appendChild(textarea);
  expandedArea.appendChild(applyReset);

  // Hint line
  const hint = document.createElement("div");
  hint.className = "pane-prompt-hint";
  hint.textContent = "click to collapse · ⌘↵ to apply & reset";

  // Assemble header
  header.appendChild(labelRow);
  header.appendChild(metaRow);
  header.appendChild(promptBody);
  header.appendChild(expandedArea);
  header.appendChild(hint);

  // ── Toggle logic ─────────────────────────────────────
  // Clicking the label row or prompt body enters editing mode.
  // Clicking the hint text (or label row when editing) collapses/expands.
  // Apply & Reset exits editing.

  function enterEditing() {
    header.classList.remove("collapsed");
    header.classList.add("editing");
    expandedArea.hidden = false;
    hint.textContent = "⌘↵ to apply & reset";
    textarea.focus();
  }

  function exitEditing() {
    header.classList.remove("editing");
    expandedArea.hidden = true;
    hint.textContent = "click to collapse · ⌘↵ to apply & reset";
  }

  function toggleCollapsed() {
    if (header.classList.contains("editing")) {
      exitEditing();
    } else {
      header.classList.toggle("collapsed");
    }
  }

  promptBody.addEventListener("click", enterEditing);

  labelRow.addEventListener("click", toggleCollapsed);

  // Keyboard: ⌘↵ applies; Esc exits editing without applying
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      applyReset.click();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      exitEditing();
    }
  });

  applyReset.addEventListener("click", exitEditing);

  // ── Log ──────────────────────────────────────────────
  const log = document.createElement("main");
  log.className = "pane-log";

  // ── Empty state (only in single mode, removed on first message) ──
  const emptyState = document.createElement("div");
  emptyState.className = "empty-state";
  emptyState.innerHTML = `
    <div class="empty-state-inner">
      <div class="empty-tag">— New conversation —</div>
      <div class="empty-hero">A quiet place to<br>iterate on your prompt.</div>
      <div class="empty-body">
        Write a message below to start, or edit the system prompt above.
        Turn on <em>use context</em> to ground responses in notes from your vault.
      </div>
      <div class="empty-shortcuts">
        <span class="kbd-chip">⌘↵ send</span>
        <span class="kbd-chip">⌘K sessions</span>
        <span class="kbd-chip">⌘\\ compare</span>
      </div>
    </div>
  `;
  log.appendChild(emptyState);

  // ── Assemble section ─────────────────────────────────
  section.appendChild(header);
  section.appendChild(log);
  container.appendChild(section);

  // ── Exported API ─────────────────────────────────────
  const refreshPreview = () => {
    promptPreviewText.textContent = oneLinePreview(textarea.value);
  };

  function addBubble(role, text = "") {
    // Remove empty state on first bubble
    if (emptyState.parentNode === log) log.removeChild(emptyState);

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap " + role;

    const tag = document.createElement("div");
    tag.className   = "bubble-role";
    tag.textContent = role === "user" ? "you" : "assistant";
    wrap.appendChild(tag);

    const el = document.createElement("div");
    el.className  = "bubble " + role;
    el.textContent = text;
    wrap.appendChild(el);

    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    return el;  // send.js appends .reasoning / .content / .sources to this
  }

  return {
    id,
    section,
    textarea,
    applyReset,
    log,
    refreshPreview,
    modelSelect,

    setModelKey(key) {
      modelSelect.value = key;
    },

    onModelChange(fn) {
      modelSelect.addEventListener("change", () => fn(modelSelect.value));
    },

    addBubble,

    addLogNote(text) {
      const note = document.createElement("div");
      note.className   = "log-note";
      note.textContent = text;
      log.appendChild(note);
    },

    clearLog() {
      log.innerHTML = "";
      log.appendChild(emptyState);
    },

    renderFromMessages(messages) {
      log.innerHTML = "";
      const nonSystem = messages.filter(m => m.role !== "system");
      if (nonSystem.length === 0) {
        log.appendChild(emptyState);
        return;
      }
      for (const msg of nonSystem) {
        addBubble(msg.role, msg.content);
      }
    },

    // onUsage is set externally by app.js (via meter.js)
    onUsage: null,
  };
}
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/troylatimer/prompt-sandbox && node --test js/*.test.js
```
Expected: all pass (pane.js has no unit tests — verified by browser later).

- [ ] **Step 3: Commit**

```bash
git add js/pane.js
git commit -m "feat: rewrite pane.js DOM structure for Paper+Rail design (single/compare CSS toggle)"
```

---

## Task 3: Restyle `js/meter.js`

**Files:**
- Modify: `js/meter.js`

Change (1) the append target from `.pane-prompt` to `.pane-meta-row`, (2) the inline HTML to match new design (horizontal layout), and (3) threshold class logic to 75%/90%.

- [ ] **Step 1: Replace `js/meter.js`**

```js
import { breakdown, computeUsed } from "./tokens.js";

export function createMeter({ pane, state, contextWindow: initialContextWindow, getDraftText }) {
  let contextWindow = initialContextWindow;

  // Append meter into .pane-meta-row (new layout — sits inline with model select)
  const metaRow = pane.section.querySelector(".pane-meta-row");
  const el = document.createElement("div");
  el.className = "meter";
  el.innerHTML = `
    <div class="meter-numbers">
      <span class="meter-used">0</span>
      <span style="color:var(--faint)"> / </span>
      <span class="meter-max"></span>
    </div>
    <div class="meter-bar"><div class="meter-fill"></div></div>
  `;
  metaRow.appendChild(el);

  const maxEl  = el.querySelector(".meter-max");
  const usedEl = el.querySelector(".meter-used");
  const fillEl = el.querySelector(".meter-fill");
  maxEl.textContent = formatCtx(contextWindow);

  let exactPromptTokens  = 0;
  let anchorMessageCount = 0;
  let anchorSystemPrompt = null;

  function invalidateAnchor() {
    exactPromptTokens  = 0;
    anchorMessageCount = 0;
    anchorSystemPrompt = null;
  }

  function render() {
    const draftText = typeof getDraftText === "function" ? getDraftText() : "";

    const { used, anchorValid } = computeUsed({
      exactPromptTokens,
      anchorMessageCount,
      anchorSystemPrompt,
      messages:     state.messages,
      systemPrompt: state.systemPrompt,
      draftText,
    });

    if (exactPromptTokens > 0 && !anchorValid) {
      invalidateAnchor();
    }

    usedEl.textContent = used.toLocaleString();

    const pct = Math.min(100, (used / contextWindow) * 100);
    fillEl.style.width = `${pct.toFixed(1)}%`;

    // New thresholds: amber 75-89%, red 90%+
    el.classList.toggle("amber", pct >= 75 && pct < 90);
    el.classList.toggle("red",   pct >= 90);

    const b = breakdown({ messages: state.messages, draftText, exactPromptTokens });
    el.title = `system ≈ ${b.system.toLocaleString()}, history ≈ ${b.history.toLocaleString()}, draft ≈ ${b.draft.toLocaleString()}`;
  }

  const unsubState = state.subscribe(render);
  render();

  return {
    setExactPromptTokens(n) {
      exactPromptTokens  = n;
      anchorMessageCount = state.messages.length;
      anchorSystemPrompt = state.systemPrompt;
      render();
    },
    updateContextWindow(newMax) {
      contextWindow = newMax;
      maxEl.textContent = formatCtx(newMax);
      render();
    },
    render,
    destroy() {
      unsubState();
      el.remove();
    },
  };
}

function formatCtx(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(0)}M`;
  if (n >= 1000)    return `${Math.round(n / 1000)}K`;
  return String(n);
}
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/troylatimer/prompt-sandbox && node --test js/*.test.js
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add js/meter.js
git commit -m "feat: restyle meter.js for inline pane-meta-row layout with new threshold colors"
```

---

## Task 4: Create `js/session-rail.js`

**Files:**
- Create: `js/session-rail.js`

This module renders session rows directly into the rail's `#sessions-list` div and the `#sessions-save-slot`. It replaces `session-panel.js` for the app's session UI. The store API (`sessionsStore`) is unchanged.

- [ ] **Step 1: Create `js/session-rail.js`**

```js
/**
 * session-rail.js — renders sessions into the persistent left rail.
 * Replaces the floating sessions-panel for the Paper+Rail redesign.
 *
 * Exported API (compatible with what app.js needs):
 *   renderSessionList(slot, entries, { onClick, onDelete, activeId })
 *   renderSaveSlot(slot, { defaultName, onSave })
 */

export function renderSessionList(slot, entries, { onClick, onDelete, activeId = null }) {
  slot.innerHTML = "";

  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className   = "rail-empty";
    empty.textContent = "No saved sessions yet.";
    slot.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "rail-session-row" + (entry.id === activeId ? " active" : "");

    const dots = document.createElement("span");
    dots.className   = "rail-session-dots";
    dots.textContent = entry.panes
      .map(p => p.messages.length > 1 ? "●" : "○")
      .join("");

    const name = document.createElement("span");
    name.className   = "rail-session-name";
    name.textContent = entry.name;

    const age = document.createElement("span");
    age.className   = "rail-session-age";
    age.textContent = formatAge(entry.createdAt);

    const del = document.createElement("button");
    del.className   = "rail-session-del";
    del.textContent = "✕";
    del.title       = "Delete session";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      onDelete(entry);
    });

    row.append(dots, name, age, del);
    row.addEventListener("click", () => onClick(entry));
    slot.appendChild(row);
  }
}

export function renderSaveSlot(slot, { defaultName, onSave }) {
  slot.innerHTML = "";

  const button = document.createElement("button");
  button.className   = "rail-save-btn";
  button.textContent = "Save current…";

  const form = document.createElement("div");
  form.className = "rail-save-form";
  form.hidden    = true;

  const input = document.createElement("input");
  input.type        = "text";
  input.className   = "rail-save-input";
  input.placeholder = "Session name";

  const confirmBtn = document.createElement("button");
  confirmBtn.className   = "rail-save-confirm";
  confirmBtn.textContent = "Save";

  const cancelBtn = document.createElement("button");
  cancelBtn.className   = "rail-save-cancel";
  cancelBtn.textContent = "✕";

  form.append(input, confirmBtn, cancelBtn);
  slot.append(button, form);

  function openForm() {
    input.value   = defaultName();
    button.hidden = true;
    form.hidden   = false;
    input.focus();
    input.select();
  }
  function closeForm() {
    button.hidden = false;
    form.hidden   = true;
  }
  function commit() {
    const name = input.value.trim();
    if (!name) return;
    onSave(name);
    closeForm();
  }

  button.addEventListener("click", openForm);
  confirmBtn.addEventListener("click", commit);
  cancelBtn.addEventListener("click", closeForm);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter")  { e.preventDefault(); commit(); }
    if (e.key === "Escape") { e.preventDefault(); closeForm(); }
  });
}

function formatAge(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const day = 86400000;
  const days = Math.floor(diffMs / day);
  if (days < 1) return "today";
  if (days < 2) return "1d";
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/troylatimer/prompt-sandbox && node --test js/*.test.js
```
Expected: all pass (new file has no test file — that's expected per project convention for DOM modules).

- [ ] **Step 3: Commit**

```bash
git add js/session-rail.js
git commit -m "feat: create session-rail.js for persistent left-rail session management"
```

---

## Task 5: Update `js/app.js` — Wire New UI

**Files:**
- Modify: `js/app.js`

Replace session-panel import with session-rail, remove old `$sessionsToggle` / `$sessionsPanel` / `$compareToggle` DOM refs, wire new rail, update compare toggle to use segmented buttons, add streaming state changes to Send button, add keyboard shortcuts, update vault UI.

- [ ] **Step 1: Replace the import block at top of `js/app.js`**

Change:
```js
import { createSessionPanel, renderSaveSlot, renderSessionList } from "./session-panel.js";
import { renderExportSlot, buildMarkdown, triggerMarkdownDownload, slugify } from "./export.js";
```
To:
```js
import { renderSaveSlot, renderSessionList } from "./session-rail.js";
import { buildMarkdown, triggerMarkdownDownload, slugify } from "./export.js";
```

- [ ] **Step 2: Remove the old `$sessionsToggle`, `$sessionsPanel`, and `sessionPanel` lines**

Remove these lines (around lines 58–67 in the current file):
```js
const $sessionsToggle = document.getElementById("sessions-toggle");
const $sessionsPanel  = document.getElementById("sessions-panel");
const sessionPanel    = createSessionPanel({ panelEl: $sessionsPanel, anchor: $sessionsToggle });
```

- [ ] **Step 3: Remove the old `$compareToggle` ref and its event listener**

Remove:
```js
const $compareToggle = document.getElementById("compare-toggle");
```
And later:
```js
$compareToggle.setAttribute("aria-pressed", "true");
$compareToggle.textContent = "Single";
```
```js
$compareToggle.setAttribute("aria-pressed", "false");
$compareToggle.textContent = "Compare";
```
```js
$compareToggle.addEventListener("click", () => {
  if (paneB) exitCompare(); else enterCompare();
});
```

- [ ] **Step 4: Add new DOM refs block after the existing shared controls block**

After the `const $reindex = ...` block, add:

```js
// ── New UI refs ──────────────────────────────────────────
const $segSingle    = document.getElementById("seg-single");
const $segCompare   = document.getElementById("seg-compare");
const $stopBoth     = document.getElementById("stop-both");
const $exportBtn    = document.getElementById("export-btn");
const $composerLabel = document.getElementById("composer-label");
const $sendHint     = document.getElementById("send-hint");
const $topbarSession = document.getElementById("topbar-session");
const $topbarSubtitle = document.getElementById("topbar-subtitle");
const $topbarDots   = document.getElementById("topbar-dots");
const $railModeTag  = document.getElementById("rail-mode-tag");
const $sessionsList = document.getElementById("sessions-list");
const $vaultCardSub = document.getElementById("vault-card-sub");
const $vaultCheckVisual = document.getElementById("vault-checkbox-visual");

// Sync vault checkbox visual state
function syncVaultCheckbox() {
  $vaultCheckVisual.classList.toggle("checked", $useVault.checked);
}
$useVault.addEventListener("change", syncVaultCheckbox);
document.getElementById("vault-label-wrap").addEventListener("click", () => {
  $useVault.checked = !$useVault.checked;
  syncVaultCheckbox();
});
syncVaultCheckbox();
```

- [ ] **Step 5: Update `enterCompare` and `exitCompare` to use segmented toggle UI**

Replace the `enterCompare` function body (keep the logic, update the UI calls):

```js
function enterCompare() {
  if (paneB) return;
  modelKeyB = modelKeyA;
  stateB = createPaneState(DEFAULT_SYSTEM_PROMPT);
  paneB  = createPane({
    id:              "B",
    container:       paneContainer,
    initialPrompt:   DEFAULT_SYSTEM_PROMPT,
    modelKeys:       Object.keys(MODELS),
    initialModelKey: modelKeyB,
  });
  paneB.applyReset.addEventListener("click", () => {
    stateB.applyPrompt(paneB.textarea.value);
    paneB.clearLog();
    paneB.refreshPreview();
  });
  paneContainer.classList.add("compare");

  // Update mode toggle UI
  $segSingle.classList.remove("seg-active");
  $segCompare.classList.add("seg-active");
  $railModeTag.textContent = "compare";
  $composerLabel.textContent = "both ⇢";

  meterB = attachMeter(paneB, stateB, modelKeyB);
  paneB.onModelChange((newKey) => {
    modelKeyB = newKey;
    meterB.updateContextWindow(MODELS[newKey].contextWindow);
  });
}

function exitCompare() {
  if (!paneB) return;
  if (stateB.messages.length > 1) {
    const ok = confirm("Exit compare mode? Pane B's conversation will be discarded.");
    if (!ok) return;
  }
  paneB.section.remove();
  meterB?.destroy();
  meterB    = null;
  paneB     = null;
  stateB    = null;
  modelKeyB = null;
  paneContainer.classList.remove("compare");

  // Update mode toggle UI
  $segCompare.classList.remove("seg-active");
  $segSingle.classList.add("seg-active");
  $railModeTag.textContent = "v2";
  $composerLabel.textContent = "you";
}
```

- [ ] **Step 6: Add segmented toggle click handlers**

After the `exitCompare` function definition, add:

```js
$segSingle.addEventListener("click",  () => { if (paneB)  exitCompare(); });
$segCompare.addEventListener("click", () => { if (!paneB) enterCompare(); });
```

- [ ] **Step 7: Update `handleSend` to show streaming state**

Replace `handleSend`:

```js
async function handleSend() {
  if ($send.disabled) return;
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";

  // Streaming state
  $send.disabled      = true;
  $send.textContent   = "Streaming…";
  $sendHint.textContent = "esc to cancel";
  $topbarDots.hidden  = false;
  $topbarSubtitle.textContent = "streaming";
  if (paneB) $stopBoth.hidden = false;

  try {
    await sendToPanes({
      panes:    activePanes(),
      userText: text,
      useVault: $useVault.checked,
      topK:     $topK.value,
    });
  } finally {
    $send.disabled     = false;
    $send.textContent  = "SEND ↵";
    $sendHint.textContent = "shift+↵ newline";
    $topbarDots.hidden = true;
    $topbarSubtitle.textContent = "conversation";
    $stopBoth.hidden   = true;
  }
}
```

- [ ] **Step 8: Update vault health watcher to populate rail card**

Replace `tickVaultHealth`:

```js
async function tickVaultHealth() {
  const state = await pingVaultHealth();
  $vaultHealth.className = `health-dot ${state}`;
  $vaultHealth.title = state === "ok" ? "Vault search: online" : "Vault search: unreachable";
  if (state === "ok") {
    $vaultCardSub.textContent = "online";
  } else {
    $vaultCardSub.textContent = "unreachable";
  }
}
```

- [ ] **Step 9: Update `refreshSessionList` to use new rail slot and pass `activeId`**

Replace the `refreshSessionList` function:

```js
let activeSessionId = null;

function refreshSessionList() {
  renderSessionList($sessionsList, sessionsStore.load(), {
    activeId: activeSessionId,
    onClick:  (entry) => {
      activeSessionId = entry.id;
      loadEntry(entry);
      refreshSessionList();
    },
    onDelete: (entry) => {
      const ok = confirm(`Delete '${entry.name}'? This cannot be undone.`);
      if (!ok) return;
      sessionsStore.delete(entry.id);
      if (activeSessionId === entry.id) activeSessionId = null;
      refreshSessionList();
    },
  });
}
```

- [ ] **Step 10: Wire `renderSaveSlot` to new rail save slot**

Replace the `renderSaveSlot` call to use `#sessions-save-slot`:

```js
renderSaveSlot(document.getElementById("sessions-save-slot"), {
  defaultName: autoName,
  onSave: (name) => {
    const { panes, vaultConfig } = currentSnapshot();
    const entry = sessionsStore.save({ name, panes, vaultConfig });
    activeSessionId = entry.id;
    refreshSessionList();
  },
});
```

Note: `sessionsStore.save` returns the saved entry — verify this in `sessions.js`. If it doesn't return, assign `activeSessionId` inside a subsequent `sessionsStore.load()` call to find the latest entry.

- [ ] **Step 11: Wire Export button**

Replace `renderExportSlot(sessionPanel.exportSlot, ...)` with:

```js
$exportBtn.addEventListener("click", () => {
  const snapshot = currentSnapshot();
  const name     = autoName();
  const markdown = buildMarkdown(snapshot, name);
  const date     = new Date().toISOString().slice(0, 10);
  triggerMarkdownDownload({
    filename: `${slugify(name)}-${date}.md`,
    markdown,
  });
});
```

- [ ] **Step 12: Remove the old `sessionPanel.close()` call in `loadEntry`**

In `loadEntry`, remove the line:
```js
sessionPanel.close();
```

- [ ] **Step 13: Add keyboard shortcuts**

Add after `$input.addEventListener("keydown", ...)`:

```js
// ── Keyboard shortcuts ───────────────────────────────────
document.addEventListener("keydown", (e) => {
  // ⌘N — New session
  if (e.key === "n" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
    e.preventDefault();
    for (const { state, pane } of activePanes()) {
      state.reset();
      pane.clearLog();
    }
    activeSessionId = null;
    refreshSessionList();
  }

  // ⌘\ — Toggle Compare mode  (fallback: ⌘⇧C)
  if ((e.key === "\\" || (e.key === "c" && e.shiftKey)) && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    if (paneB) exitCompare(); else enterCompare();
  }

  // ⌘K — Focus sessions list (rail)
  if (e.key === "k" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
    e.preventDefault();
    const firstRow = $sessionsList.querySelector(".rail-session-row");
    if (firstRow) firstRow.focus();
  }

  // ⌘⇧V — Toggle vault checkbox
  if (e.key === "v" && (e.metaKey || e.ctrlKey) && e.shiftKey) {
    e.preventDefault();
    $useVault.checked = !$useVault.checked;
    syncVaultCheckbox();
  }

  // Esc — Cancel in-flight stream (handled by AbortController in send.js — Esc propagates)
});
```

- [ ] **Step 14: Verify `sessions.js` `save()` return value**

Open `js/sessions.js` and check if `save()` returns the saved entry. If it does, Task 5 step 10's `entry.id` assignment works. If `save()` returns `void`, replace the `onSave` callback in step 10 with:

```js
onSave: (name) => {
  const { panes, vaultConfig } = currentSnapshot();
  sessionsStore.save({ name, panes, vaultConfig });
  const entries = sessionsStore.load();
  if (entries.length) activeSessionId = entries[0].id;
  refreshSessionList();
},
```

- [ ] **Step 15: Update topbar subtitle on New Session click**

In the `$newSession.addEventListener("click", ...)` handler, add:
```js
$topbarSubtitle.textContent = "empty conversation";
$topbarSession.textContent  = "untitled";
activeSessionId = null;
refreshSessionList();
```

- [ ] **Step 16: Run tests**

```bash
cd /Users/troylatimer/prompt-sandbox && node --test js/*.test.js
```
Expected: all pass.

- [ ] **Step 17: Commit**

```bash
git add js/app.js
git commit -m "feat: wire session rail, mode toggle, keyboard shortcuts, and streaming state in app.js"
```

---

## Task 6: Fix `js/ui.js` — Sources Chip Markup

**Files:**
- Modify: `js/ui.js`

The current `renderSources` outputs plain `<span>` items without a "sources:" label element. The new bubble CSS expects a `.source-label` span. Update `renderSources` to emit the correct structure.

- [ ] **Step 1: Replace `js/ui.js`**

```js
export function renderSources(bubble, results) {
  const line = document.createElement("div");
  line.className = "sources";

  const label = document.createElement("span");
  label.className   = "source-label";
  label.textContent = "sources: ";
  line.appendChild(label);

  results.forEach((r) => {
    const name = r.path.split("/").pop();
    const chip = document.createElement("span");
    chip.textContent = name;
    chip.title       = r.snippet;
    line.appendChild(chip);
  });

  bubble.appendChild(line);
}
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/troylatimer/prompt-sandbox && node --test js/*.test.js
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add js/ui.js
git commit -m "fix: update renderSources to emit source-label chip structure for new bubble CSS"
```

---

## Task 7: Browser Acceptance Testing

This is the manual verification pass. No automated tests exist for DOM-facing modules (per CLAUDE.md).

- [ ] **Step 1: Start the web server**

```bash
cd /Users/troylatimer/prompt-sandbox && python3 -m http.server 7777
```

Open `http://localhost:7777`.

- [ ] **Step 2: Verify initial state (C1 — single, empty)**

Check all of the following:
- [ ] Warm paper `#f6f3ee` background, no dark colors
- [ ] Left rail visible at 232px: `◐ Sandbox v2` header, `＋ New session ⌘N` button, `SAVED` label, empty list, `vault-search :8100` card at bottom
- [ ] Top bar: `untitled / empty conversation` breadcrumb; `Single` button active (dark fill); `Compare A / B` inactive; `Export .md` button
- [ ] Prompt strip: `SYSTEM PROMPT` label, model select, meter (0 / contextWindow), styled `> <prompt text>` preview box, hint text
- [ ] Log area: empty state centered: `— NEW CONVERSATION —`, hero text, shortcut chips
- [ ] Composer: `you` label, placeholder textarea, `SEND ↵` button, `shift+↵ newline` hint, vault controls row

- [ ] **Step 3: Verify prompt expand/collapse**

- Click the `>` prompt preview box → header enters editing mode, textarea visible, hint says `⌘↵ to apply & reset`
- Type something in textarea, press Esc → exits editing, preview text updates to draft (before apply)
- Click again, press `Apply & Reset` → log clears, hint restores
- Click the `SYSTEM PROMPT` label row → prompt body hides (collapsed); click again → restores

- [ ] **Step 4: Verify compare mode (C2)**

- Click `Compare A / B` button → Pane B appears, rail mode tag changes to `compare`, `both ⇢` label in composer
- Pane A header: teal 2px stripe at top, `A` badge (teal), model select, meter
- Pane B header: plum 2px stripe at top, `B` badge (plum), model select, meter

- [ ] **Step 5: Verify sessions save/load**

- Type a message and click Send (MLX must be running for full test; skip if offline)
- Click `Save current…` → inline input appears, type a name, press Enter → row appears in rail
- Click the row → conversation restored, row highlighted
- Hover row → `✕` appears, clicking it after confirm → row removed

- [ ] **Step 6: Verify keyboard shortcuts**

- `⌘N` → clears conversation (both panes in compare mode)
- `⌘\` → toggles compare mode
- `⌘⇧V` → toggles vault checkbox visual

- [ ] **Step 7: Verify streaming state (requires MLX)**

Send a message:
- [ ] Send button shows `Streaming…` (faint fill)
- [ ] Hint shows `esc to cancel`
- [ ] Topbar subtitle shows `streaming` with animated dots
- [ ] In compare mode, `⏹ Stop both` button appears in topbar
- [ ] On completion, all revert

- [ ] **Step 8: Verify vault health display**

With vault running:
- [ ] Green dot in rail vault card, sub-text `online`
Without vault:
- [ ] Red dot, sub-text `unreachable`

- [ ] **Step 9: Commit final**

```bash
cd /Users/troylatimer/prompt-sandbox
git add -A
git commit -m "feat: complete Paper+Rail UI redesign — warm paper palette, sessions rail, new composer"
```

---

## Self-Review: Spec Coverage Check

| Spec requirement | Covered in |
|---|---|
| Warm paper palette `--bg`, `--rail`, `--panel-alt`, etc. | Task 1 CSS tokens |
| Geist + Geist Mono fonts | Task 1 `<link>` |
| Rail: logo, app name, mode tag, New session button | Task 1 HTML + Task 5 |
| Rail: session rows with dots + age + active highlight | Task 4 session-rail.js |
| Rail: vault card with health dot | Task 1 HTML + Task 5 |
| Top bar: breadcrumb + streaming dots | Task 1 HTML + Task 5 |
| Top bar: segmented Single/Compare toggle | Task 1 HTML + Task 5 |
| Top bar: Export .md button | Task 1 HTML + Task 5 |
| Top bar: Stop both button (compare streaming) | Task 1 HTML + Task 5 |
| Prompt strip: single mode expanded/collapsed | Task 1 CSS + Task 2 pane.js |
| Prompt strip: hint line | Task 2 pane.js |
| Per-pane compare header: 2px color stripe | Task 1 CSS |
| Per-pane compare header: badge + model + meter | Task 1 CSS + Task 2 pane.js |
| Collapsed prompt preview in compare | Task 1 CSS + Task 2 pane.js |
| Bubble styling: user (bg/hair), assistant (panel-alt + 2px color left rule) | Task 1 CSS |
| Bubble role labels: mono uppercase | Task 1 CSS + Task 2 pane.js |
| Reasoning tokens: muted italic | Task 1 CSS (unchanged class) |
| Streaming caret via CSS `::after` | Task 1 CSS |
| Sources chips | Task 1 CSS + Task 6 ui.js |
| Empty state: hero text + shortcut chips | Task 2 pane.js |
| Baseline rule grid in log | Task 1 CSS `.pane-log::before` |
| Composer: `you`/`both ⇢` label | Task 1 HTML + Task 5 |
| Composer: `SEND ↵` → `Streaming…` disabled | Task 5 handleSend |
| Composer: vault checkbox custom visual | Task 1 CSS + Task 5 |
| Token meter: inline in pane-meta-row | Task 3 meter.js |
| Token meter: amber 75-89%, red 90%+ | Task 3 meter.js |
| Keyboard shortcuts: ⌘N, ⌘\, ⌘K, ⌘⇧V | Task 5 |
| Sessions dropdown → rail (no dropdown) | Task 5 (removed $sessionsToggle) |
| Sessions: click to load, active row | Task 4 session-rail.js + Task 5 |
| Sessions: hover delete | Task 4 session-rail.js CSS |
| Sessions: save current inline form | Task 4 session-rail.js |
| Vault health poll every 10s (unchanged) | Untouched in app.js |
| No shadows, radius 2-3px, 1px borders | Task 1 CSS throughout |
| Directions A and B NOT implemented | Only C styles in CSS |
| All `*.test.js` untouched | Verified throughout |
| `state.js`, `stream.js`, `tokens.js`, `sessions.js`, `config.js` untouched | Verified — not touched |

**Gaps / known omissions:**
1. **Model picker not in topbar** — kept in pane header for both modes (avoids DOM-shuffle complexity). The picker is functional in both modes via CSS styling.
2. **Topbar session name** — `$topbarSession` starts as `"untitled"` and updates on new session / load. It does NOT auto-update on every message — a future enhancement.
3. **Rail collapse at viewport < 960px** (open question #3 in README) — NOT implemented; mocked always-expanded.
4. **Vault "248 notes indexed · 12ms avg"** — vault card sub-text shows `online`/`unreachable` rather than parsed stats. This requires a new `/health` response parsing step (out of scope per handoff: existing `pingVaultHealth` in vault.js returns just `"ok"/"down"`).
