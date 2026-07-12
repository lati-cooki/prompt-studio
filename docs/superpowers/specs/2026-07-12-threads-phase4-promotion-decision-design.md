# Threads Phase 4 — Registry promotion recorded as a ClisTa decision (FCP-shaped)

**Date:** 2026-07-12
**Status:** Implemented
**Repo:** `lati-cooki/prompt-studio` (this repo), branch `threads-phase4`
**Predecessors:** Phase 1 (Threads tab, read-only), Phase 2 (seal-as-decision write path), Phase 3 (assisted extraction) — all shipped 2026-06-14. See `2026-06-14-threads-addon-design.md` and the phase plans beside it.

## Purpose

Registry promotion today is `POST /api/prompts/<id>/validate/<version>` (`handle_post_prompt_validate`, `server.py`) — a single unguarded SQL UPDATE that sets `status='production', eval_status='validated'`. Nothing records *why*, on what evidence, or who could have objected.

Phase 4 makes promotion a **recorded ClisTa decision**, borrowing two mechanisms from Rust's stabilization process (chosen via analogical transfer during design):

1. **Final comment period (FCP):** promotion opens a time-boxed objection window; status flips only when the window closes clean or is explicitly waived — and a waiver is *disclosed in the record*, never silent.
2. **Executable evidence (playground-permalink model):** the decision's evidence is a pinned eval run — dataset, model, params, scores, content-hashed — attached so anyone can re-run it, not prose assertion.

The single-author self-review problem ("vibes with hashes", deliberately dodged in Phase 2) is addressed structurally: "no objections during a declared 24h window" and "window waived, disclosed" are both auditable facts, not claimed virtues.

## Non-goals

- **No formal `DecisionRequested → ReviewSubmitted → DecisionRecorded` upgrade.** Owner signed off (2026-07-12): sealing stays on Phase 2's validated **decision-as-claim** event sequence. Formal-decision enrichment (authority/assumptions/review) remains the separate, later option it already was.
- No changes to ThreadHub itself (rule stands: sidecar + proxy, never reimplement).
- No multi-user identity work; the custodial author model from Phase 2 stays.
- No auto-deprecation rules (still excluded as premature, per registry design notes).

## Data model

New SQLite table `promotions` (created in `migrate_db`, `server.py`):

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `prompt_id` | TEXT | FK-by-convention to `prompts.id` |
| `version` | TEXT | the version being promoted |
| `state` | TEXT | `open` \| `waived` \| `closed` \| `aborted` |
| `opened_at` | TEXT | ISO-8601 UTC |
| `window_hours` | REAL | default 24 |
| `closes_at` | TEXT | derived at open: `opened_at + window_hours` |
| `resolved_at` | TEXT | when state left `open` |
| `evidence_json` | TEXT | pinned eval run: `{dataset, model, params, scores, content_hash, run_at}` |
| `thread_slug` | TEXT | ThreadHub slug of the sealed record (set at seal time) |
| `waive_reason` | TEXT | required when waived |

New table `promotion_objections`:

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `promotion_id` | INTEGER | FK to `promotions.id` |
| `raised_at` | TEXT | |
| `body` | TEXT | objection text (required, non-empty) |
| `resolution` | TEXT | NULL while open; `responded` \| `upheld` |
| `resolution_body` | TEXT | response text, required on resolve |

**Invariant:** at most one promotion in state `open` per (`prompt_id`, `version`). A second open attempt → 409.

## FCP state machine

```
open ──window elapses, no unresolved objections──▶ closed   → status flips, seal
open ──explicit waive (reason required)──────────▶ waived   → status flips, seal (fcp_waived: true)
open ──abort────────────────────────────────────▶ aborted  → status unchanged, seal abort record
open + unresolved objection: window elapse does NOT close — stays open until every
objection is resolved (responded/upheld) or the promotion is aborted.
```

- An objection with `resolution='upheld'` forces `aborted` (an upheld objection and a completed promotion cannot coexist).
- There is no background scheduler: window elapse is evaluated lazily — a close attempt (or any read of the promotion) checks `now >= closes_at`. Closing is an explicit `POST .../close` call that succeeds only when the window has elapsed and no objection is unresolved.

## API routes (all in `server.py`, same stdlib-http style as existing handlers)

| route | behavior |
|---|---|
| `POST /api/prompts/<id>/promote/<version>` | Opens a promotion. Body: `{window_hours?, evidence?}`. Runs/attaches evidence (see Evidence). Returns the promotion row. 409 if one is already open, 404 if prompt/version unknown. Does **not** touch `prompts.status`. |
| `GET /api/promotions` / `GET /api/promotions/<pid>` | List / detail (detail includes objections; state reflects lazy window check). |
| `POST /api/promotions/<pid>/object` | Body: `{body}`. 422 if empty; 409 if promotion not `open`. |
| `POST /api/promotions/<pid>/objections/<oid>/resolve` | Body: `{resolution: responded\|upheld, body}`. `upheld` → promotion aborts (and seals the abort). |
| `POST /api/promotions/<pid>/close` | Succeeds iff window elapsed AND no unresolved objections → state `closed`, flip `prompts.status='production', eval_status='validated'`, seal. 409 otherwise with reason. |
| `POST /api/promotions/<pid>/waive` | Body: `{reason}` (required). State `waived`, flip status, seal with `fcp_waived: true`. |
| `POST /api/promotions/<pid>/abort` | State `aborted`, status untouched, seal an abort record. |
| `POST /api/prompts/<id>/demote/<version>` | Body: `{reason}`. Sets `status='deprecated'` and seals a superseding claim referencing the promotion's `thread_slug` (if any). |

**Guard:** `handle_post_prompt_validate` and `handle_put_prompt` reject direct transitions **to** `status='production'` with 409 + a body pointing at the promote flow. (Other status edits stay unrestricted.) The `validate` route is kept but returns the 409 — existing callers get a self-explaining error, not a silent 404.

## Evidence (executable, pinned)

- On promote, the server captures a **pinned eval run** for (`prompt_id`, `version`): invokes the existing pipeline (`scripts/evaluate_prompt.py`) or accepts a caller-supplied recent result in the request body. Recorded as `{dataset, model, params, scores, run_at}` plus `content_hash` = sha256 over the stable-serialized record.
- If the eval pipeline cannot run (no API key, no dataset), promotion may proceed with `evidence: null` — but the sealed record then explicitly contains `evidence_attached: false`. Absence is disclosed, never faked.
- **Honesty boundary (verbatim into the sealed claim):** inputs and scores are pinned and hash-verifiable; LLM outputs are nondeterministic, so a re-run is *fresh evidence*, not a replay. The chain proves what was recorded and when — not that the prompt is good.
- Re-run pointer: the sealed evidence includes the eval invocation (script + args) so anyone with the repo can reproduce the *procedure*.

## Sealing (reuses Phase 2 machinery — decision-as-claim)

On terminal state (`closed`/`waived`/`aborted`), the server seals via the existing `seal.py` orchestrator/custodial path (validate-first atomicity, custodial HTTP writes through the :8110 sidecar, temp-dir ClisTa authoring, `.seal_author_id` author):

- **Thread:** one per promotion event, slug like `promote-<prompt_id>-<version>` (abort: `promote-…-aborted-<pid>`).
- **Evidence:** the pinned eval record (or the disclosed absence).
- **Claim (the decision):** "`<prompt_id>` `<version>` promoted to production" (or aborted/deprecated), with FCP metadata in content: `{opened_at, closes_at, resolved_at, state, window_hours, fcp_waived, waive_reason?, objection_count, evidence_attached, content_hash?}`.
- **Objections:** every `promotion_objections` row seals as an objection event with its resolution — objections survive the yes.
- Demotion seals a claim whose content references the superseded promotion's `thread_slug`.

Seal failure does not un-flip status: the flip and the seal are reported separately, and a failed seal is surfaced loudly in the API response and UI (`sealed: false, seal_error`), retryable via `POST /api/promotions/<pid>/reseal`.

## UI (registry widget + sandbox)

- **Registry widget** (`registry/interface/registry_widget.html`): draft rows get a **Promote** button → modal (window hours, optional waive-with-reason, evidence status shown). Rows with an open promotion show a countdown badge + **Object** button (textarea). Open objections show resolve controls. Deprecate button on production rows (reason required).
- **Threads tab:** no changes needed — sealed promotion threads appear via the existing Phase 1 read path.
- **Sandbox Active Prompt picker** (Setup drawer): defaults to `status='production'` prompts; an "include drafts (nightly)" toggle reveals the rest. Pure filter change in the existing picker population code.

## Sidecar repoint

`sandbox/_run-threadhub.sh`: `cd ~/threadhub` → `cd ~/Projects/clista/packages/threadhub` (fall back to `~/threadhub` with a loud "STALE CHECKOUT" warning if the monorepo path is missing). Rationale: ThreadHub's canonical source moved to the `lati-cooki/clista` monorepo by subtree merge 2026-07-10; the old checkout will drift.

## Verification

- **Python tests** (beside `tests/test_seal.py`, same stdlib style): FCP state machine (all transitions incl. lazy window elapse, objection blocking close, upheld → abort, one-open invariant), route guards (409 on direct production flips), evidence hash determinism, demote supersession reference, seal payload shape (mock sidecar).
- **`node --test`** for any new widget JS extracted into `sandbox/js`/`registry` modules (match Phase 3's pure/impure split).
- **Real-browser check** of the registry widget flow (promote → object → resolve → close) — the Phase 1–3 lesson: node/curl-only verification let `app.js` stay silently broken; drive the actual UI.
- **End-to-end:** with sidecar running from the monorepo checkout, one full promotion seals; `GET /api/threads/<slug>/verify` passes on the sealed thread.

## Risks / notes

- Lazy window evaluation means a promotion can sit `open` past `closes_at` until someone calls close — acceptable for a single-operator tool; the sealed record carries both timestamps so the gap is visible.
- `evaluate_prompt.py` integration shape (invoke vs. attach-latest) is decided at plan time after reading that script; the spec's contract is only the pinned-record shape + disclosed absence.
- Monorepo ThreadHub checkout at `~/Projects/clista/packages/threadhub` must have its deps installed to serve; the repoint script should fail loudly, not silently skip (current script exits 0 when the dir is missing — fix that while touching it).
