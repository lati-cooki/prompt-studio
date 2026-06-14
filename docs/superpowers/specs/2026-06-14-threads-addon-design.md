# Threads Add-on — Phase 1 (Read-Only Viewer) — Design

**Date:** 2026-06-14
**Status:** Approved (brainstorm), pending implementation plan
**Component:** Prompt Studio (`~/DevSwarmProjects/Clista`)

## Context

Prompt Studio is the workbench where the "Rational Partner" deliberation happens
(sandbox chat + prompt registry + eval pipeline). Two sibling projects complete a
three-layer decision stack:

| Layer | Project | Role | Remote |
| --- | --- | --- | --- |
| Format/engine | ClisTa Protocol | Produces & validates decision event logs | `lati-club/ClisTa-Protocol` |
| Store/hub | ThreadHub | Signs, hash-chains, content-addresses, hosts & verifies threads | `lati-club/ThreadHub` |
| Workbench | Prompt Studio | Where deliberation happens | `lati-cooki/prompt-studio` |

> Note: ClisTa and ThreadHub are standardized on the `lati-club` org; `prompt-studio`
> currently still lives under `lati-cooki`. Reconciling that is out of scope for this spec.

The relationship ThreadHub states for itself: **git : GitHub :: ClisTa Protocol : Thread Hub.**

The full integration vision ("C") is the closed loop **deliberate → shape → notarize**,
decomposed into four sub-projects built left to right:

1. **Phase 1 — Threads tab (read).** Studio proxies ThreadHub: list / open / verify records. *(this spec)*
2. Phase 2 — Seal as decision (manual write): session → ClisTa log → ThreadHub.
3. Phase 3 — Assisted extraction: local Gemma proposes ClisTa structure from a transcript.
4. Phase 4 — Registry promotion recorded as a ClisTa decision (depends on Phase 2's write path).

This spec covers **Phase 1 only** — the foundation every later phase rides on.

## Goal

A native **Threads tab** in Prompt Studio that lists threads stored in ThreadHub, opens a
selected thread to show its signed record chain, and surfaces ThreadHub's chain-verification
status. Read-only. It proves the sidecar + proxy architecture for all later phases.

## Constraints & principles

- **Run ThreadHub, don't reimplement it.** ThreadHub's append-only signed store is the moat
  and a deliberately scope-frozen repo. Studio consumes its public JSON API and makes **zero
  changes to ThreadHub**. Records are never copied into `prompt_studio.db`.
- **`trusted: false` boundary holds.** Studio displays ThreadHub's verification result; it
  never asserts a decision is good/approved because a chain is valid.
- **No new runtime dependencies.** `server.py` proxies using the Python stdlib (`urllib`),
  consistent with Prompt Studio's zero-build / stdlib-`http.server` approach. ThreadHub itself
  is zero-dependency Node ≥ 22 (verified: local Node is v25.9.0).
- **Follow existing patterns.** Mirror the registry add-on: a tab route + a static HTML widget
  + read endpoints. Vanilla JS, minimal comments.

## Why proxy (not direct browser calls, not iframe)

- **Direct browser → ThreadHub is ruled out:** ThreadHub's server sends no CORS headers, so a
  cross-origin fetch from Studio's origin is blocked. We will not add CORS to the frozen repo.
- **Iframe of ThreadHub's built-in viewer** is technically possible (no `X-Frame-Options`) but
  rejected: it shows ThreadHub's look instead of Studio's, gives no control over the view, and
  requires exposing ThreadHub's port to the browser.
- **Chosen: proxy through `server.py`.** Single origin, ThreadHub port stays private, native
  Studio UI, mirrors the registry tab.

## Architecture

```
Browser (Studio origin :8000)
  └─ GET /threads                       → threads_widget.html (static)
  └─ GET /api/threads                   → server.py ─urllib→ ThreadHub GET /threads
  └─ GET /api/threads/<slug>            → server.py ─urllib→ ThreadHub GET /t/<slug>.json
  └─ GET /api/threads/<slug>/verify     → server.py ─urllib→ ThreadHub GET /t/<slug>/verify

ThreadHub sidecar (private :8110)  ← launched & health-checked by launch.command
```

## Components

### 1. ThreadHub sidecar
- New helper `sandbox/_run-threadhub.sh`: `cd ~/threadhub && node bin/cli.js serve --port 8110`.
- `sandbox/launch.command`: add `free_port 8110`, spawn the helper window, and add a health-wait
  loop polling `http://localhost:8110/` (ThreadHub's instance-summary route) before opening the
  browser — same shape as the existing MLX / vault waits.
- **Port: 8110** (next in the local-services 81xx band after vault's 8100). Overridable via the
  helper script. ThreadHub's documented default is 7777; 8110 is chosen to group local services
  and avoid the legacy sandbox-web 7777 association.

### 2. Proxy routes in `server.py`
Three read-only GET routes, added to `do_GET`:
- `/api/threads` → ThreadHub `GET /threads`
- `/api/threads/<slug>` → ThreadHub `GET /t/<slug>.json`
- `/api/threads/<slug>/verify` → ThreadHub `GET /t/<slug>/verify`

A small helper proxies a GET to `http://localhost:<THREADHUB_PORT><path>` via
`urllib.request`, streams back the status + JSON body, and maps failures to errors (below).
`THREADHUB_PORT` is a module constant (default 8110) alongside the existing `PORT`. Slugs are
path-segment validated (no `/`, no `..`) before forwarding.

### 3. Threads widget (frontend)
- `threads/interface/threads_widget.html` served at `/threads` (new route in `do_GET`,
  mirroring `/registry` → `registry/interface/registry_widget.html`).
- Vanilla JS, no build step. **List view:** calls `/api/threads`; renders one row per thread
  with title, question, record count, and a verification badge. **Detail view:** on row click,
  calls `/api/threads/<slug>` and `/api/threads/<slug>/verify`; renders the record chain — each
  envelope's `seq`, `kind`, `author`, short `record_hash`, signature indicator — and the overall
  chain-valid / broken badge.
- A link/tab entry into `/threads` is added wherever the registry link already lives in the
  Studio UI (Studio ↔ Registry nav).

## Data flow

1. User opens the **Threads** tab → browser GETs `/threads` (static widget).
2. Widget JS GETs `/api/threads` → `server.py` forwards to ThreadHub `/threads` → list rendered.
3. User clicks a thread → widget GETs `/api/threads/<slug>` and `/api/threads/<slug>/verify` →
   `server.py` forwards to ThreadHub `/t/<slug>.json` and `/t/<slug>/verify` → detail rendered.

## Error handling

- **ThreadHub unreachable** (connection refused / timeout): proxy responds
  `502 {"error": "...", "code": "threadhub_unreachable"}`. The widget shows a clear message
  ("ThreadHub sidecar not running — start it via the launcher"), not a hung spinner.
- **Unknown slug / not found:** ThreadHub's `404` is passed through; widget shows "thread not found".
- **Broken chain:** verify returns a non-valid result; the widget shows the ✗ badge prominently.
  This is tamper-evidence working as intended, not an application error.
- **Malformed slug** (contains `/` or `..`): `server.py` returns `400` without forwarding.

## Testing

- **`pytest`** (`tests/`) for the proxy routes, run against a **real ThreadHub instance** seeded
  with the bundled `threads/founding-architecture.ndjson` fixture (ingested via the ThreadHub
  CLI in test setup). Assertions: list returns the seeded thread; detail returns its record
  chain; verify reports a valid chain; ThreadHub-down yields `502 threadhub_unreachable`;
  malformed slug yields `400`.
- **Manual browser acceptance** for the widget (DOM module, per project convention): list renders,
  click opens detail with the chain + verified badge, and the down-state message appears when the
  sidecar is stopped.

## Non-goals (explicitly deferred)

- No writes of any kind — no "seal as decision" (Phase 2).
- No ClisTa projection / human-readable accountable-decision view (later phase).
- No registry integration / promotion-as-decision (Phase 4).
- No identity or key management (read-only needs none; Phase 2 introduces it).
- No federation, attestation, or single-record (`/r/:hash`) views.
- No editing, deleting, or re-ordering of threads or records.

## Open items for the implementation plan

- Exact placement of the Threads nav entry in the existing Studio header/markup.
- Whether the verify call is issued eagerly with the detail fetch or lazily on a "verify" action
  (default: eagerly, alongside detail load).
