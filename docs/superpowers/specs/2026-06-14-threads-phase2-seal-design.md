# Threads Add-on — Phase 2 ("Seal as Decision") — Design

**Date:** 2026-06-14
**Status:** Approved (brainstorm), pending implementation plan
**Component:** Prompt Studio (`~/DevSwarmProjects/Clista`)
**Builds on:** Phase 1 (`docs/superpowers/specs/2026-06-14-threads-addon-design.md`) — the read-only Threads tab + ThreadHub sidecar.

## Context

Phase 1 shipped the read path: a Threads tab that proxies a ThreadHub sidecar to list, open, and
verify decision records. Phase 2 adds the **write path** — turning a Rational-Partner deliberation
in the sandbox into a signed, accountable decision record. This is the "shape → notarize" half of
the deliberate → shape → notarize loop.

The three-layer stack (see the Phase 1 spec / `project_decision_stack` memory):
- **Prompt Studio** — workbench (`lati-cooki/prompt-studio`), Python stdlib `http.server` on :8000.
- **ClisTa Protocol** — `~/ClisTa-Protocol` (`lati-club/ClisTa-Protocol`), Node CLI engine that
  authors and validates decision event logs.
- **ThreadHub** — `~/threadhub` (`lati-club/ThreadHub`), signed hash-chained store, sidecar on :8110.

## Goal

A **"Seal as decision"** action in the sandbox that captures the minimal accountable structure of a
decision via a manual form, authors a ClisTa-validated event log from it, and ingests that log into
ThreadHub as a new signed thread — which then appears in the Phase 1 Threads tab with a permanent
citation hash.

## Decisions locked in brainstorming

- **Capture depth: minimal "accountable yes" (~5 fields).** Not the full ClisTa structure — every
  field is hand-typed, and rich capture is Phase 3's job (Gemma-assisted extraction). v1 captures the
  irreducible core: a yes that carries its evidence, a surviving objection, and authority.
- **Identity: custodial.** ThreadHub holds the key; Studio declares a `Troy` identity once and POSTs
  unsigned payloads / ingests; the server signs. This is ThreadHub's documented v1 human-writer path
  ("human writers never touch key material"). Non-custodial is deferred.
- **Build approach: ClisTa CLI orchestration → ThreadHub ingest.** ClisTa authors and validates the
  log (it owns the schema); we never hand-craft ClisTa JSON or modify ClisTa/ThreadHub.
- **No prefill.** v1 form is fully manual (no auto-extraction from the session); that is Phase 3.

## Constraints & principles

- **Run the engines, don't reimplement them.** Zero changes to ClisTa or ThreadHub. Studio shells out
  to the `clista` and `threadhub` (node) CLIs.
- **`trusted: false` holds.** A sealed decision being well-formed is not a claim that it is correct.
- **No new runtime dependencies** in Studio (stdlib + subprocess to node, consistent with Phase 1).
- **Atomicity:** author into a fresh temp events file and `validate` it BEFORE any ThreadHub write.
  `threadhub ingest` is the single ThreadHub mutation, so a failure upstream leaves no partial thread.
- **Isolation:** the orchestration lives in a dedicated, unit-testable `seal.py` module; `server.py`
  stays a thin route.

## Architecture

```
Sandbox topbar "Seal as decision" button
  └─ opens modal form (5 fields)
       └─ POST /api/threads/seal  { title, question, decision, evidence[], objections[], decidedBy }
            └─ server.py  → seal.py.seal_decision(payload)
                 1. ensure custodial identity (declare "Troy" once, reuse id)
                 2. author ClisTa log into a fresh temp events file (CLI sequence)
                 3. clista validate <tmp>          (gate — abort on failure, nothing written)
                 4. threadhub ingest --events <tmp> --author <id> --title <title>
                 5. return { slug, citationHash }
       └─ result UI: "✓ Sealed · <slug> · sha256:… · Open in Threads ↗"
```

Viewing the sealed decision reuses the Phase 1 Threads tab (`/threads`) and its proxy routes.

## Components

### 1. Seal form (frontend)
- A modal added to `sandbox/index.html`, opened by a new topbar button "Seal as decision" placed
  beside the existing Registry / Threads links (topbar-actions region, ~line 698).
- Fields: **Title** (text, defaults to current session name), **Question** (text), **Decision** (text),
  **Evidence** (repeatable rows of `source` + `finding`, at least one), **Surviving objection**
  (repeatable rows of `text`, zero or more), **Decided by** (text, defaults to "Troy").
- Submit → `POST /api/threads/seal`; on success show the result line with the citation hash and an
  "Open in Threads" link to `/threads`; on error show the message inline (field-level for 400).
- Vanilla JS, no build step; all interpolation HTML-escaped (reuse the Phase 1 widget's `esc()` style).

### 2. `seal.py` (backend orchestrator)
A dedicated module with a primary entry `seal_decision(payload) -> {slug, citationHash}` and small
helpers. Responsibilities:
- **Validate payload** (raises a typed error → 400): require non-empty `question`, `decision`,
  `decidedBy`, and `evidence` with ≥1 item each having `source` + `finding`. `objections` optional.
- **Ensure identity:** look up / create the custodial ThreadHub identity for the author (declare once,
  cache the id; idempotent).
- **Author the ClisTa log** into a fresh temp events file via the CLI sequence (exact flags verified at
  plan time — see Open Items): `thread create --title --question` → `participant declare --name` →
  for each evidence `evidence commit --source --finding` (collect evidence ids) → `claim create --text
  <decision> --evidence <evidenceIds>` → `decision open --proposal <decision>` → for each objection
  `objection raise --target <id> --text` → `decision merge --decider <participant>`.
- **Validate:** `clista validate --events <tmp>`; abort (no ThreadHub write) on non-zero.
- **Ingest:** `threadhub ingest --events <tmp> --author <id> --title <title>`; parse the returned
  thread slug + head/citation hash.
- **Return** `{slug, citationHash}`. Clean up the temp file.

### 3. `server.py` route
`POST /api/threads/seal`: read+size-limit the JSON body (existing `read_json_body`), call
`seal.seal_decision`, and map the outcome: success → `200 {slug, citationHash}`; validation error →
`400 {error, fields}`; ThreadHub unreachable → `502 {code: "threadhub_unreachable"}`; other
orchestration failure → `500 {error}`.

## Form → ClisTa mapping

| Form field | ClisTa authoring |
| --- | --- |
| Title | thread title (also passed to `threadhub ingest --title`) |
| Question | `thread create --question` |
| Evidence[] (source, finding) | `evidence commit --source --finding` (one per item; collect ids) |
| Decision | `claim create --text <decision> --evidence <ids>` + `decision open --proposal <decision>` |
| Objection[] | `objection raise --target <claim/decision id> --text` (one per item) |
| Decided by | `participant declare --name` + `decision merge --decider <participant>` |

## Error handling

- Missing/empty required field → `400` with a `fields` map; the form highlights offending fields.
- ClisTa authoring or `validate` failure → `500 {error}`; **no ThreadHub write occurs** (temp-then-ingest).
- ThreadHub unreachable / ingest connection failure → `502 {code: "threadhub_unreachable"}`; form offers retry.
- ThreadHub rate-limited → pass through `429`.
- Temp file always cleaned up (success or failure).

## Testing

- **`seal.py` unit tests** (mock `subprocess`): payload validation (each missing required field →
  error), correct command sequence and argument wiring (assert the ordered `clista`/`threadhub` calls
  and that evidence ids thread into `claim create`), validate-failure aborts before ingest, error
  mapping (ThreadHub-down → unreachable). Follows the existing `unittest` + mocked-I/O convention.
- **`server.py` route test**: `/api/threads/seal` with a valid mocked `seal_decision` → 200 with
  `{slug, citationHash}`; missing-field payload → 400.
- **Manual integration:** with ClisTa + ThreadHub running, seal a sample decision; confirm the new
  thread appears in the Threads tab, `verify`s valid, and `clista state show` projects the decision.

## Non-goals (deferred)

- No prefill / auto-extraction from the session transcript (Phase 3).
- No richer structure: assumptions, per-participant positions, minority reports, provenance traces
  (beyond the minimal 5 fields).
- No non-custodial / client-side signing.
- No editing or re-sealing of an existing thread; no deletion.
- No registry-promotion-as-decision (Phase 4).

## Open items for the implementation plan

- Verify the exact `clista` CLI mechanics for authoring a single event log: how each command targets
  one events file (a `--events <path>` flag vs a `.clista/` working-dir convention), and the exact
  flag names/output formats for `evidence commit` (id capture), `claim create`, `decision open`,
  `objection raise`, and `decision merge`. Confirm against the live CLI before writing task code.
- Confirm `threadhub ingest` output format for reliably parsing the new slug + citation hash.
- Confirm how `participant declare` / identity is represented in a from-scratch authored log and how it
  maps onto the custodial ThreadHub `--author` identity.
