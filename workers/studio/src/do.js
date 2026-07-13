// do.js — StudioState: the single named Durable Object that IS the studio's
// cloud half. One instance (idFromName('studio')) reproduces the Python
// server's single-process serialized-write semantics.
//
// Ported here, faithfully:
//   - the FCP state machine (promotion_store.py — open → closed | waived |
//     aborted, lazy window elapse, unresolved-objection block,
//     upheld-forces-abort) and its metrics formulas VERBATIM
//     (DR-2026-07-12-fcp-metrics, sealed immutable);
//   - token mint/revoke and objection filing (objections.py) with the
//     hub-first ordering: the hub identity mint precedes every local write,
//     so a hub failure files NOTHING;
//   - the insert-only refusal audit (object_refusals + RAISE(ABORT)
//     triggers) whose writer NEVER raises;
//   - the per-IP sliding-window rate limiter over ALL three public
//     surfaces, with the fail-loud OBJECT_RATE parser.
//
// Deliberately NOT ported (they live on the laptop, split per the port
// plan): the prompts table and its production flip (close/waive here only
// move the promotion; the laptop flips prompts after the cloud acks — the
// known non-atomic seam), evidence pinning, sealing/anchoring subprocess
// tooling, and mint's operator-writer-provisioned 409 (the writers registry
// that guard consults is laptop state; the laptop seal path still enforces
// fail-closed attribution).
import { DurableObject } from 'cloudflare:workers';
import { Buffer } from 'node:buffer';
import {
  GENERIC_404_HTML,
  GENERIC_404_JSON,
  GENERIC_429_HTML,
  GENERIC_429_JSON,
  JSON_TYPE,
  HTML_TYPE,
  CUSTODY_DISCLOSURE_MINT,
} from './constants.js';
import {
  TokenInvalid,
  validateToken,
  objectionStatus,
  sha256hex,
  postureNote,
} from './objections.js';
import { renderObjectPage } from './page.js';
import { mintIdentity, isPublishedSafe } from './hub.js';

// ---------------------------------------------------------------------------
// promotion_store.py constants (verbatim)

export const OPEN = 'open';
export const CLOSED = 'closed';
export const WAIVED = 'waived';
export const ABORTED = 'aborted';
// Terminal FCP outcomes — every state a promotion can end in. OPEN is the
// only non-terminal state; there is no other. Sealed immutable by
// DR-2026-07-12-fcp-metrics: changing this tuple's meaning requires a NEW
// metric name by DR amendment, never a redefinition.
export const TERMINAL_STATES = [CLOSED, WAIVED, ABORTED];
export const CONTESTED_DATA_ABSENT =
  'no token table yet (pre-Slice-6); 0 invitations recorded';
export const CONTESTED_DATA_MEASURED =
  'fcp_tokens table present; invitations measured';

export class PromotionError extends Error {
  constructor(message, status = 400) {
    super(message);
    this.message = message;
    this.status = status;
  }
}

// server.py:55-56 is_safe_slug
export const isSafeSlug = (slug) =>
  typeof slug === 'string' && slug !== '' && /^[A-Za-z0-9_-]+$/.test(slug);

// Same body ceiling as the Python server (server.py MAX_BODY_BYTES).
export const MAX_BODY_BYTES = 10 * 1024 * 1024;

// ---------------------------------------------------------------------------
// time — promotion_store._TS format, UTC seconds precision

const isoOfMs = (ms) => new Date(ms).toISOString().slice(0, 19) + 'Z';

// ---------------------------------------------------------------------------
// OBJECT_RATE parser — objections.py:85-97 _parse_rate, fail-LOUD port:
// a malformed spec must throw at DO construction, not launch a front door
// with a limiter it didn't ask for.

export function parseRate(spec) {
  const s = spec ?? '';
  const slash = s.indexOf('/');
  const countStr = slash === -1 ? s : s.slice(0, slash);
  const windowStr = slash === -1 ? '' : s.slice(slash + 1);
  const malformed = () => {
    throw new Error(
      `OBJECT_RATE=${JSON.stringify(spec)} is malformed — expected 'N' or ` +
        "'N/seconds' (e.g. '10/60' for 10 requests per 60 seconds)",
    );
  };
  if (!/^\s*[+-]?\d+\s*$/.test(countStr)) malformed();
  const count = parseInt(countStr.trim(), 10);
  let windowSeconds = 60.0;
  if (windowStr !== '') {
    if (windowStr.trim() === '') malformed();
    const w = Number(windowStr.trim());
    if (Number.isNaN(w)) malformed();
    windowSeconds = w;
  }
  return [Math.max(1, count), windowSeconds];
}

// ---------------------------------------------------------------------------
// per-IP rate limit — objections.py:477-499 allow_request, as a class with
// an injectable clock (seconds, like Python's time.time()). In-memory,
// DOCUMENTED trade-off: state is per-DO-instance and resets on eviction —
// the same "per-process, resets on restart" semantics the Python original
// documents. Buckets whose entries have all aged out are EVICTED once per
// window (a full sweep, amortized), so a probe spread across many distinct
// IPs cannot grow the map unboundedly. The backwards-clock branch only
// matters for tests that pass explicit `now` values.

export class SlidingWindow {
  constructor(limit, windowSeconds) {
    this.limit = limit;
    this.windowSeconds = windowSeconds;
    this.buckets = new Map();
    this.lastSweep = 0;
  }

  allow(ip, now = Date.now() / 1000) {
    const cutoff = now - this.windowSeconds;
    if (now - this.lastSweep >= this.windowSeconds || now < this.lastSweep) {
      this.lastSweep = now;
      for (const [key, bucket] of this.buckets) {
        if (bucket.length === 0 || bucket[bucket.length - 1] <= cutoff) {
          this.buckets.delete(key);
        }
      }
    }
    let bucket = this.buckets.get(ip);
    if (bucket === undefined) {
      bucket = [];
      this.buckets.set(ip, bucket);
    }
    const kept = bucket.filter((t) => t > cutoff);
    bucket.length = 0;
    bucket.push(...kept);
    if (bucket.length >= this.limit) return false;
    bucket.push(now);
    return true;
  }
}

// ---------------------------------------------------------------------------
// schema — table shapes from schema.sql (promotions FCP slice,
// promotion_objections), objections.py ensure_tokens_table (fcp_tokens —
// minted_at, NOT created_at: the sealed DR names it) and
// ensure_refusals_table (object_refusals + append-only triggers), and
// writers.py ensure_table (objector_writers: same shape, renamed — this DO
// registers ONLY objector identities; the operator/delegate/studio writers
// stay on the laptop). The objector contact string lives ONLY in
// objector_writers.name / promotion_objections.author_writer inside this
// DO's storage — it never crosses to the hub (display_name + minted id do).

export const SCHEMA = `
CREATE TABLE IF NOT EXISTS promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id TEXT NOT NULL,
    version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    opened_at TEXT NOT NULL,
    window_hours REAL NOT NULL DEFAULT 24,
    closes_at TEXT NOT NULL,
    resolved_at TEXT,
    evidence_json TEXT,
    thread_slug TEXT,
    citation_hash TEXT,
    sealed INTEGER NOT NULL DEFAULT 0,
    seal_error TEXT,
    waive_reason TEXT,
    opened_by TEXT,
    resolved_by TEXT,
    deliberation_slug TEXT
);

CREATE TABLE IF NOT EXISTS fcp_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL REFERENCES promotions(id),
    token_hash TEXT NOT NULL UNIQUE,
    invitee_label TEXT,
    minted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    use_limit INTEGER NOT NULL DEFAULT 1,
    uses INTEGER NOT NULL DEFAULT 0,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS promotion_objections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL,
    raised_at TEXT NOT NULL,
    body TEXT NOT NULL,
    resolution TEXT,
    resolution_body TEXT,
    author_writer TEXT,
    resolved_by TEXT,
    channel TEXT,
    token_id TEXT,
    sealed_record_hash TEXT
);

CREATE TABLE IF NOT EXISTS objector_writers (
    name TEXT PRIMARY KEY,
    threadhub_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    custodial INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS object_refusals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ip TEXT NOT NULL,
    path_kind TEXT NOT NULL CHECK (path_kind IN ('page','file','status')),
    reason_code TEXT NOT NULL CHECK (reason_code IN
        ('unknown','revoked','exhausted','expired','closed',
         'rate_limited','malformed')),
    token_id INTEGER
);

CREATE TRIGGER IF NOT EXISTS object_refusals_no_update
    BEFORE UPDATE ON object_refusals
    BEGIN SELECT RAISE(ABORT, 'object_refusals is append-only'); END;

CREATE TRIGGER IF NOT EXISTS object_refusals_no_delete
    BEFORE DELETE ON object_refusals
    BEGIN SELECT RAISE(ABORT, 'object_refusals is append-only'); END;
`;

// The objections query getPromotion uses — promotion_store.get_promotion's
// "SELECT * FROM promotion_objections WHERE promotion_id=? ORDER BY id"
// extended with the objector-writer join so operator responses carry
// author_threadhub_id + author_display_name (the laptop seal path needs
// them to build the writer map; the objector writers were minted HERE, not
// on the laptop). objections.validateToken's timing-normalization path
// mirrors this exact statement (statement-count equality) — if you change
// this query's shape, keep the import there intact.
export const OBJECTIONS_WITH_AUTHOR_QUERY =
  'SELECT o.*, w.threadhub_id AS author_threadhub_id, ' +
  'w.display_name AS author_display_name ' +
  'FROM promotion_objections o ' +
  'LEFT JOIN objector_writers w ON w.name = o.author_writer ' +
  'WHERE o.promotion_id = ? ORDER BY o.id';

// ---------------------------------------------------------------------------
// response descriptors — { status, contentType, body }; the Worker writes
// them verbatim. ONE constructor per refusal shape so every failure mode of
// a surface is byte- and header-identical by construction.

const html404 = () => ({ status: 404, contentType: HTML_TYPE, body: GENERIC_404_HTML });
const json404 = () => ({ status: 404, contentType: JSON_TYPE, body: GENERIC_404_JSON });
const html429 = () => ({ status: 429, contentType: HTML_TYPE, body: GENERIC_429_HTML });
const json429 = () => ({ status: 429, contentType: JSON_TYPE, body: GENERIC_429_JSON });
const jsonOk = (data, status = 200) => ({ status, contentType: JSON_TYPE, body: JSON.stringify(data) });
const jsonErr = (message, status) => jsonOk({ error: message }, status);

const unquote = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s; // Python urllib.parse.unquote leaves invalid escapes alone
  }
};

// GET /api/promotions/metrics?window= and /api/object-refusals?window= —
// server.py:1050-1062 window validation, verbatim statuses/messages.
function parseWindowParam(search) {
  const raw = new URLSearchParams(search ?? '').get('window');
  if (raw === null) return null;
  if (!/^\s*[+-]?\d+\s*$/.test(raw)) {
    throw new PromotionError('window must be a whole number of days', 422);
  }
  const windowDays = parseInt(raw.trim(), 10);
  if (windowDays <= 0) {
    throw new PromotionError('window must be a positive number of days', 422);
  }
  return windowDays;
}

// /api/admin/import table specs — column lists match SCHEMA above; rows
// land VERBATIM with explicit ids preserved (receipts minted against the
// laptop DB must keep working — token hashes, objection ids, promotion ids
// all survive the migration byte-for-byte).
const IMPORT_TABLES = {
  promotions: [
    'id', 'prompt_id', 'version', 'state', 'opened_at', 'window_hours',
    'closes_at', 'resolved_at', 'evidence_json', 'thread_slug',
    'citation_hash', 'sealed', 'seal_error', 'waive_reason', 'opened_by',
    'resolved_by', 'deliberation_slug',
  ],
  fcp_tokens: [
    'id', 'promotion_id', 'token_hash', 'invitee_label', 'minted_at',
    'expires_at', 'use_limit', 'uses', 'revoked', 'created_by',
  ],
  promotion_objections: [
    'id', 'promotion_id', 'raised_at', 'body', 'resolution',
    'resolution_body', 'author_writer', 'resolved_by', 'channel',
    'token_id', 'sealed_record_hash',
  ],
  objector_writers: [
    'name', 'threadhub_id', 'display_name', 'kind', 'custodial',
  ],
  object_refusals: [
    'id', 'ts', 'ip', 'path_kind', 'reason_code', 'token_id',
  ],
};

// ---------------------------------------------------------------------------

export class StudioState extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    // Fail-loud limiter config — a malformed OBJECT_RATE throws here and
    // the DO never serves a request.
    const [limit, windowSeconds] = parseRate(env.OBJECT_RATE ?? '10/60');
    this.limiter = new SlidingWindow(limit, windowSeconds);
    // Schema DDL before any request is answered.
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(SCHEMA);
    });
    // The facade objections.js validation functions consume.
    this.db = {
      one: (query, ...params) => this.#one(query, ...params),
      all: (query, ...params) => this.#all(query, ...params),
      nowIso: () => this.#nowIso(),
      getPromotion: (pid) => this.#getPromotion(pid),
      getObjectorWriter: (name) => this.#getObjectorWriter(name),
    };
  }

  // ── sql helpers ─────────────────────────────────────────────────────────

  #all(query, ...params) {
    return this.ctx.storage.sql.exec(query, ...params).toArray();
  }

  #one(query, ...params) {
    return this.#all(query, ...params)[0] ?? null;
  }

  #run(query, ...params) {
    this.ctx.storage.sql.exec(query, ...params);
  }

  #lastId() {
    return this.#one('SELECT last_insert_rowid() AS id').id;
  }

  #nowMs() {
    return Date.now();
  }

  #nowIso() {
    return isoOfMs(this.#nowMs());
  }

  #publicBase() {
    return (this.env.PUBLIC_BASE_URL ?? '').replace(/\/+$/, '');
  }

  #hubBase() {
    return (this.env.HUB_PUBLIC_BASE_URL ?? '').replace(/\/+$/, '');
  }

  // ── promotion_store.py port ─────────────────────────────────────────────

  #getPromotion(pid) {
    const row = this.#one('SELECT * FROM promotions WHERE id = ?', pid);
    if (row === null) throw new PromotionError('promotion not found', 404);
    const p = { ...row };
    p.evidence = p.evidence_json ? JSON.parse(p.evidence_json) : null;
    delete p.evidence_json;
    p.objections = this.#all(OBJECTIONS_WITH_AUTHOR_QUERY, p.id).map((o) => ({ ...o }));
    p.window_elapsed = this.#nowMs() >= Date.parse(p.closes_at);
    p.unresolved_objections = p.objections.filter((o) => o.resolution === null).length;
    return p;
  }

  #listPromotions() {
    return this.#all('SELECT id FROM promotions ORDER BY id DESC').map((r) =>
      this.#getPromotion(r.id),
    );
  }

  // promotion_store._has_fcp_tokens_table probes PRAGMA table_info; DO
  // storage restricts pragmas, so the existence probe goes through
  // sqlite_master — same semantics ("a table that does not exist"), and in
  // this DO the DDL above makes it always true. Kept faithful anyway: the
  // metrics disclosure contract distinguishes absence of measurement from
  // a measured zero.
  #hasFcpTokensTable() {
    return (
      this.#one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fcp_tokens'",
      ) !== null
    );
  }

  /** Waive-ratio metrics per DR-2026-07-12-fcp-metrics. Definitions are
   * sealed immutable in that DR — the formulas below match
   * promotion_store.metrics VERBATIM:
   *
   * - fcp_waive_ratio(window_days) = count(terminal outcomes in window
   *   where state == 'waived') / count(terminal outcomes in window)
   * - externally_contested_ratio(window_days) = count(terminal outcomes in
   *   window whose FCP window had >= 1 token invitation minted strictly
   *   before the outcome: EXISTS fcp_tokens row with promotion_id = p.id
   *   AND minted_at < p.resolved_at) / count(terminal outcomes in window)
   * - terminal outcomes: promotions.state in TERMINAL_STATES; resolved_at
   *   is the outcome timestamp
   * - window: resolved_at >= now - window_days; window_days null = all-time
   * - denominator 0 -> both ratios null (JSON null) with counts, never a
   *   fabricated 0.0 */
  #metrics(windowDays) {
    let where = `p.state IN (${TERMINAL_STATES.map(() => '?').join(',')})`;
    const params = [...TERMINAL_STATES];
    if (windowDays !== null) {
      where += ' AND p.resolved_at >= ?';
      params.push(isoOfMs(this.#nowMs() - windowDays * 86400000));
    }
    const total = this.#one(
      `SELECT COUNT(*) AS n FROM promotions p WHERE ${where}`, ...params).n;
    const waived = this.#one(
      `SELECT COUNT(*) AS n FROM promotions p WHERE ${where} AND p.state=?`,
      ...params, WAIVED).n;
    let invited;
    let contestedData;
    if (this.#hasFcpTokensTable()) {
      invited = this.#one(
        `SELECT COUNT(*) AS n FROM promotions p WHERE ${where}
             AND EXISTS (SELECT 1 FROM fcp_tokens t
                         WHERE t.promotion_id = p.id
                           AND t.minted_at < p.resolved_at)`,
        ...params).n;
      contestedData = CONTESTED_DATA_MEASURED;
    } else {
      invited = 0;
      contestedData = CONTESTED_DATA_ABSENT;
    }
    return {
      window_days: windowDays,
      terminal_total: total,
      waived,
      fcp_waive_ratio: total ? waived / total : null,
      invited,
      externally_contested_ratio: total ? invited / total : null,
      contested_data: contestedData,
      computed_at: this.#nowIso(),
    };
  }

  /** POST /api/promotions — open. The Python route derived prompt_id and
   * version from the URL and consulted the local prompts table (404 unknown
   * prompt, 409 already-production); prompts live on the laptop, so here
   * they arrive in the body pre-checked and those two refusals are the
   * laptop client's job. Duplicate-open stays HERE (this store is the one
   * source of FCP truth). */
  #openPromotion(data) {
    const promptId = data.prompt_id;
    const version = data.version;
    if (typeof promptId !== 'string' || promptId === '' ||
        typeof version !== 'string' || version === '') {
      throw new PromotionError('prompt_id and version are required', 422);
    }
    // evidence: a snapshot dict or an explicit/implicit null (disclosed
    // absence — server.py:997-1009 shape check, verbatim message).
    let evidence = null;
    if (data.evidence !== undefined && data.evidence !== null) {
      const ev = data.evidence;
      if (typeof ev !== 'object' || Array.isArray(ev) ||
          !('source_file' in ev) || !('content_hash' in ev)) {
        throw new PromotionError(
          'evidence must include source_file and content_hash', 422);
      }
      evidence = ev;
    }
    let windowHours = data.window_hours === undefined ? 24 : data.window_hours;
    if (typeof windowHours === 'string' && windowHours.trim() !== '') {
      windowHours = Number(windowHours);
    }
    if (typeof windowHours !== 'number' || !Number.isFinite(windowHours)) {
      throw new PromotionError('window_hours must be numeric', 422);
    }
    const deliberationSlug = data.deliberation_slug ?? null;
    if (deliberationSlug !== null && !isSafeSlug(deliberationSlug)) {
      throw new PromotionError('deliberation_slug must be a safe slug', 422);
    }
    const openedBy =
      typeof data.opened_by === 'string' && data.opened_by !== ''
        ? data.opened_by
        : 'operator';
    const dup = this.#one(
      'SELECT id FROM promotions WHERE prompt_id=? AND version=? AND state=?',
      promptId, version, OPEN);
    if (dup !== null) {
      throw new PromotionError(
        `promotion ${dup.id} already open for ${promptId}@${version}`, 409);
    }
    const opened = this.#nowMs();
    const closes = opened + windowHours * 3600000;
    this.#run(
      `INSERT INTO promotions
         (prompt_id, version, state, opened_at, window_hours, closes_at,
          evidence_json, opened_by, deliberation_slug)
         VALUES (?,?,?,?,?,?,?,?,?)`,
      promptId, version, OPEN, isoOfMs(opened), windowHours, isoOfMs(closes),
      evidence !== null ? JSON.stringify(evidence) : null, openedBy,
      deliberationSlug);
    return this.#getPromotion(this.#lastId());
  }

  #requireOpen(pid) {
    const p = this.#getPromotion(pid);
    if (p.state !== OPEN) {
      throw new PromotionError(`promotion is ${p.state}, not open`, 409);
    }
    return p;
  }

  #addObjection(pid, body, actor = 'operator') {
    this.#requireOpen(pid);
    const trimmed = typeof body === 'string' ? body.trim() : '';
    if (trimmed === '') throw new PromotionError('objection body required', 422);
    this.#run(
      `INSERT INTO promotion_objections (promotion_id, raised_at, body, author_writer)
         VALUES (?,?,?,?)`,
      pid, this.#nowIso(), trimmed, actor);
    return {
      ...this.#one('SELECT * FROM promotion_objections WHERE id=?', this.#lastId()),
    };
  }

  #resolveObjection(pid, oid, resolution, body, actor = 'operator') {
    this.#requireOpen(pid);
    if (resolution !== 'responded' && resolution !== 'upheld') {
      throw new PromotionError("resolution must be 'responded' or 'upheld'", 422);
    }
    const trimmed = typeof body === 'string' ? body.trim() : '';
    if (trimmed === '') throw new PromotionError('resolution body required', 422);
    const row = this.#one(
      'SELECT * FROM promotion_objections WHERE id=? AND promotion_id=?',
      oid, pid);
    if (row === null) throw new PromotionError('objection not found', 404);
    if (row.resolution !== null) {
      throw new PromotionError('objection already resolved', 409);
    }
    this.#run(
      'UPDATE promotion_objections SET resolution=?, resolution_body=?, resolved_by=? WHERE id=?',
      resolution, trimmed, actor, row.id);
    if (resolution === 'upheld') {
      // upheld objection forces abort; the resolver is the terminating
      // actor. The laptop notices the aborted state in this response and
      // runs the seal there (then posts seal-result).
      return this.#terminate(pid, ABORTED, { actor });
    }
    return this.#getPromotion(pid);
  }

  #terminate(pid, state, { waiveReason = null, actor = 'operator' } = {}) {
    const p = this.#requireOpen(pid);
    // Cloud split: promotion_store._terminate flips prompts.status to
    // production on close/waive — the prompts table is laptop state, so
    // the flip happens there after this call acks (documented non-atomic
    // seam, operator-recoverable).
    this.#run(
      'UPDATE promotions SET state=?, resolved_at=?, waive_reason=?, resolved_by=? WHERE id=?',
      state, this.#nowIso(), waiveReason, actor, p.id);
    return this.#getPromotion(p.id);
  }

  #closePromotion(pid, actor = 'operator') {
    const p = this.#requireOpen(pid);
    if (!p.window_elapsed) {
      throw new PromotionError(
        `window open until ${p.closes_at} — close later or waive`, 409);
    }
    if (p.unresolved_objections) {
      throw new PromotionError(
        `${p.unresolved_objections} unresolved objection(s) block close`, 409);
    }
    return this.#terminate(pid, CLOSED, { actor });
  }

  #waivePromotion(pid, reason, actor = 'operator') {
    const trimmed = typeof reason === 'string' ? reason.trim() : '';
    if (trimmed === '') throw new PromotionError('waive reason required', 422);
    return this.#terminate(pid, WAIVED, { waiveReason: trimmed, actor });
  }

  #abortPromotion(pid, actor = 'operator') {
    return this.#terminate(pid, ABORTED, { actor });
  }

  /** POST .../seal-result — promotion_store.mark_seal_result. The seal
   * itself happens on the laptop (subprocess tooling); this is the
   * bookkeeping half: {slug, citation_hash} on success, {error} on
   * failure. A failed seal never un-flips anything. */
  #markSealResult(pid, data) {
    const error = data.error ?? null;
    if (error === null) {
      this.#run(
        'UPDATE promotions SET sealed=1, seal_error=NULL, thread_slug=?, citation_hash=? WHERE id=?',
        data.slug ?? null, data.citation_hash ?? null, pid);
    } else {
      this.#run(
        'UPDATE promotions SET sealed=0, seal_error=? WHERE id=?',
        String(error), pid);
    }
    return this.#getPromotion(pid);
  }

  /** POST .../sealed-records — objections.backfill_sealed_records: match
   * the promotion's objections (ordered by id — the SAME ordering the
   * laptop's _author_for_event uses for the n-th ObjectionRaised writer
   * mapping) to the ObjectionRaised records of the seal's extended return,
   * in order, and write each sealed_record_hash.
   *
   * The count assertion runs BEFORE any UPDATE and the writes ride one
   * transaction: on mismatch NOTHING is back-filled and the 409 propagates
   * — the laptop records it as seal_error. The hub thread exists
   * regardless (the seal already happened); the message says so instead of
   * pretending otherwise. */
  #sealedRecords(pid, data) {
    const records = data.records;
    if (!Array.isArray(records)) {
      throw new PromotionError('records must be a list of sealed record envelopes', 422);
    }
    const p = this.#getPromotion(pid);
    const slug = data.slug ?? p.thread_slug ?? null;
    const objs = p.objections;
    const objRecords = records.filter(
      (r) => r !== null && typeof r === 'object' && r.event_type === 'ObjectionRaised');
    if (objRecords.length !== objs.length) {
      throw new PromotionError(
        `objection back-fill count mismatch: ${objs.length} stored ` +
          `objection(s) vs ${objRecords.length} ObjectionRaised record(s) ` +
          `in thread '${slug}' — refusing partial back-fill (the hub ` +
          'thread exists; recorded as seal_error for reseal)', 409);
    }
    this.ctx.storage.transactionSync(() => {
      for (let i = 0; i < objs.length; i++) {
        this.#run(
          'UPDATE promotion_objections SET sealed_record_hash=? WHERE id=?',
          objRecords[i].record_hash ?? null, objs[i].id);
      }
    });
    return { backfilled: objs.length, promotion_id: p.id };
  }

  // ── objections.py port: mint / revoke / file / writers / audit ─────────

  #getObjectorWriter(name) {
    const row = this.#one('SELECT * FROM objector_writers WHERE name=?', name);
    if (row === null) return null;
    return { ...row, custodial: Boolean(row.custodial) };
  }

  /** writers.ensure_writer for objector identities: mint-first,
   * insert-after — a crash between the hub mint and the local INSERT
   * leaves an orphan hub identity: harmless, disclosed, healed by the next
   * call minting a fresh one. Idempotent: an existing row never re-mints.
   * A hub failure THROWS (502) before any local write — hub-first
   * ordering means a hub failure files nothing. */
  async #ensureObjectorWriter(name, displayName) {
    const existing = this.#getObjectorWriter(name);
    if (existing !== null) return existing;
    let minted;
    try {
      minted = await mintIdentity(this.env, {
        display_name: displayName,
        kind: 'human',
      });
    } catch (err) {
      throw new PromotionError(
        `hub identity mint failed — nothing was filed: ${err.message}`, 502);
    }
    this.#run(
      'INSERT INTO objector_writers (name, threadhub_id, display_name, kind, custodial) VALUES (?,?,?,?,1)',
      name, minted.id, displayName, 'human');
    return this.#getObjectorWriter(name);
  }

  /** objections._display_name_for: invitee_label (operator-chosen at mint)
   * or label (objector-chosen) or objector-<n>. Any candidate CONTAINING
   * the contact string is discarded: display_name reaches the hub, and the
   * contact never does — that invariant is unconditional, not advisory. */
  #displayNameFor(token, label, contactNorm) {
    for (const candidate of [token.invitee_label, label]) {
      if (typeof candidate !== 'string') continue;
      const trimmed = candidate.trim();
      if (trimmed !== '' && !trimmed.toLowerCase().includes(contactNorm)) {
        return trimmed;
      }
    }
    const n = this.#one(
      "SELECT COUNT(*) AS n FROM objector_writers WHERE name LIKE 'objector:%'").n;
    return `objector-${n + 1}`;
  }

  /** objections.file_objection: validate the token, provision the objector
   * writer (hub mint FIRST — before the objection exists, so the laptop
   * seal path can attribute it), insert the objection (channel='token')
   * and burn a use in ONE transaction, return the immediate receipt
   * {objection_id, body_hash, status_url}.
   *
   * Privacy: the contact string is normalized (trim/lowercase) and lives
   * in the local writer NAME only ("objector:<contact>"); the hub sees the
   * display_name and the minted identity id, never the contact. */
  async #fileObjection(raw, data, ip) {
    const { token, promotion } = validateToken(this.db, raw);
    const body = typeof data.body === 'string' ? data.body.trim() : '';
    if (body === '') {
      this.#recordRefusal(ip, 'file', 'malformed', token.id);
      throw new PromotionError('objection body required', 422);
    }
    const contactNorm =
      typeof data.contact === 'string' ? data.contact.trim().toLowerCase() : '';
    if (contactNorm === '') {
      this.#recordRefusal(ip, 'file', 'malformed', token.id);
      throw new PromotionError(
        'contact required (kept local — never sent to the hub)', 422);
    }
    const writerName = `objector:${contactNorm}`;
    const displayName = this.#displayNameFor(token, data.label, contactNorm);
    // Mint-first (idempotent): a hub failure throws here — nothing has
    // been written locally yet, so a hub failure files nothing.
    await this.#ensureObjectorWriter(writerName, displayName);
    let oid;
    this.ctx.storage.transactionSync(() => {
      this.#run(
        `INSERT INTO promotion_objections
           (promotion_id, raised_at, body, author_writer, channel, token_id)
           VALUES (?,?,?,?,?,?)`,
        // token_id is a TEXT column (schema.sql): Python stores the int's
        // decimal string ("1"); a raw JS number here would land as "1.0"
        // under TEXT affinity, so stringify the integer for byte-parity.
        promotion.id, this.#nowIso(), body, writerName, 'token', String(token.id));
      oid = this.#lastId();
      this.#run('UPDATE fcp_tokens SET uses = uses + 1 WHERE id=?', token.id);
    });
    const statusPath = `/object/${raw}/status/${oid}`;
    const base = this.#publicBase();
    return {
      objection_id: oid,
      body_hash: 'sha256:' + sha256hex(body),
      // Absolute from PUBLIC_BASE_URL — the skeptic keeps this URL; it
      // must resolve from THEIR machine. Never the Host header.
      status_url: base ? base + statusPath : statusPath,
    };
  }

  /** objections.mint_token, minus the operator-writer-provisioned 409 (that
   * registry is laptop state; see the module docstring). The raw token
   * appears ONCE, in this return; only its sha256 lands in storage. */
  async #mintToken(pid, data) {
    const p = this.#getPromotion(pid);
    if (p.state !== OPEN) {
      throw new PromotionError(
        `promotion is ${p.state}, not open — tokens are minted only for ` +
          'an open FCP window', 409);
    }
    if (p.window_elapsed) {
      throw new PromotionError(
        'FCP window already elapsed — a token minted now would expire at ' +
          'birth (expires_at is the closes_at snapshot)', 409);
    }
    const useLimit = data.use_limit === undefined ? 1 : data.use_limit;
    if (typeof useLimit !== 'number' || !Number.isInteger(useLimit) || useLimit < 1) {
      throw new PromotionError('use_limit must be an integer >= 1', 422);
    }
    if ('deliberation_slug' in data) {
      // Task 15: mint-time override of the promotion's deliberation
      // association. Explicit null clears; absent leaves the open-time
      // association alone (the UNSET-sentinel semantics, carried by JSON
      // key presence).
      const dSlug = data.deliberation_slug;
      if (dSlug !== null && !isSafeSlug(dSlug)) {
        throw new PromotionError(
          'deliberation_slug must be a safe slug (or null to clear the ' +
            'association)', 422);
      }
      this.#run('UPDATE promotions SET deliberation_slug=? WHERE id=?', dSlug, p.id);
      p.deliberation_slug = dSlug;
    }
    let inviteeLabel =
      typeof data.invitee_label === 'string' ? data.invitee_label.trim() : '';
    inviteeLabel = inviteeLabel === '' ? null : inviteeLabel;
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    const raw = Buffer.from(bytes).toString('base64url'); // secrets.token_urlsafe(32) parity
    this.#run(
      `INSERT INTO fcp_tokens
         (promotion_id, token_hash, invitee_label, minted_at, expires_at,
          use_limit, created_by)
         VALUES (?,?,?,?,?,?,?)`,
      p.id, sha256hex(raw), inviteeLabel, this.#nowIso(), p.closes_at,
      useLimit, 'operator');
    const minted = {
      token: raw, // shown once; never stored, never logged
      token_id: this.#lastId(),
      promotion_id: p.id,
      // Share URL from CONFIG, never the Host header (a client-controlled
      // Host must not steer where an invitation points).
      url: `${this.#publicBase()}/object/${raw}`,
      expires_at: p.closes_at,
      use_limit: useLimit,
      invitee_label: inviteeLabel,
      deliberation_slug: p.deliberation_slug ?? null,
      custody: CUSTODY_DISCLOSURE_MINT,
      posture: postureNote(this.env),
    };
    // Task 15: the doorstep link rides the mint response — ONLY when a
    // deliberation thread is associated AND effectively published on the
    // hub (fail closed: no dead links in an invitation email, no
    // unpublished-slug leakage beyond the operator surface).
    const dSlug = minted.deliberation_slug;
    if (dSlug && (await isPublishedSafe(this.env, dSlug))) {
      minted.deliberation_url = `${this.#hubBase()}/t/${dSlug}/view`;
    }
    return minted;
  }

  #revokeToken(pid, tokenId) {
    const row = this.#one(
      'SELECT id FROM fcp_tokens WHERE id=? AND promotion_id=?', tokenId, pid);
    if (row === null) throw new PromotionError('token not found', 404);
    this.#run('UPDATE fcp_tokens SET revoked=1 WHERE id=?', row.id);
    return { revoked: true, token_id: row.id, promotion_id: Number(pid) };
  }

  /** objections.record_refusal — append one refusal witness (local by
   * design: hub-sealing per probe would let a prober spam the permanent
   * record). token_id is set only when the token was valid enough to
   * identify.
   *
   * NEVER raises: the prober's byte-identical generic response outranks
   * the witness. An audit-write failure must not turn a 404/429 into a
   * dropped connection — that would make audit health itself an observable
   * oracle. The failure is witnessed the only way left: console.error,
   * loud in the Worker log. */
  #recordRefusal(ip, pathKind, reasonCode, tokenId = null) {
    try {
      this.#run(
        'INSERT INTO object_refusals (ts, ip, path_kind, reason_code, token_id) VALUES (?,?,?,?,?)',
        this.#nowIso(), ip || '?', pathKind, reasonCode, tokenId);
    } catch (err) {
      console.error(
        `object_refusals witness FAILED (path_kind=${pathKind} ` +
          `reason=${reasonCode}) — refusal not recorded; prober response ` +
          'unaffected', err);
    }
  }

  /** objections.refusal_summary — operator view: counts by reason + the
   * most recent rows, optionally limited to the last <windowDays> days. */
  #refusalSummary(windowDays) {
    let where = '';
    const params = [];
    if (windowDays !== null) {
      where = ' WHERE ts >= ?';
      params.push(isoOfMs(this.#nowMs() - windowDays * 86400000));
    }
    const counts = {};
    for (const row of this.#all(
      `SELECT reason_code, COUNT(*) AS n FROM object_refusals${where} GROUP BY reason_code`,
      ...params)) {
      counts[row.reason_code] = row.n;
    }
    const recent = this.#all(
      `SELECT id, ts, ip, path_kind, reason_code, token_id FROM object_refusals${where} ORDER BY id DESC LIMIT 50`,
      ...params).map((r) => ({ ...r }));
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    return { window_days: windowDays, total, counts, recent };
  }

  /** POST /api/admin/import — one-shot state migration (plan phase 8).
   * Refuses 409 unless EVERY table is empty (an import must never merge
   * into live state); rows land verbatim with explicit ids preserved, in
   * one transaction — receipts minted against the laptop DB keep working
   * because token hashes, objection ids and promotion ids survive
   * byte-for-byte. */
  #adminImport(data) {
    for (const table of Object.keys(IMPORT_TABLES)) {
      const rows = data[table] ?? [];
      if (!Array.isArray(rows)) {
        throw new PromotionError(`${table} must be a list of rows`, 422);
      }
    }
    for (const table of Object.keys(IMPORT_TABLES)) {
      const n = this.#one(`SELECT COUNT(*) AS n FROM ${table}`).n;
      if (n !== 0) {
        throw new PromotionError(
          `import refused: ${table} is not empty (${n} row(s)) — the ` +
            'import is one-shot, into a fresh store only', 409);
      }
    }
    const imported = {};
    this.ctx.storage.transactionSync(() => {
      for (const [table, cols] of Object.entries(IMPORT_TABLES)) {
        const rows = data[table] ?? [];
        const placeholders = cols.map(() => '?').join(',');
        for (const row of rows) {
          this.#run(
            `INSERT INTO ${table} (${cols.join(', ')}) VALUES (${placeholders})`,
            ...cols.map((c) => row[c] ?? null));
        }
        imported[table] = rows.length;
      }
    });
    return { imported };
  }

  // ── the public skeptic surface (RPC from the Worker) ────────────────────

  /** Task 15 doorstep link: the hub viewer URL for the promotion's
   * associated deliberation thread — ONLY when an association exists AND
   * the thread is effectively published on the hub (checked live at render
   * time; the hub's record is the state, never a local flag). Every other
   * case — no association, unpublished, hub unreachable — returns null: an
   * unpublished association must render NOTHING (no dead links, no slug
   * leakage). The slug comes from stored operator state, never user input. */
  async #deliberationLink(promotion) {
    const slug = promotion.deliberation_slug;
    if (!slug) return null;
    if (!(await isPublishedSafe(this.env, slug))) return null;
    return `${this.#hubBase()}/t/${slug}/view`;
  }

  /** The one public RPC. { method, path, bodyText, bodyTooLarge, ip } —
   * scalars only, never a Request, never client headers. Returns a
   * response descriptor { status, contentType, body }. */
  async publicHandle({ method, path, bodyText, bodyTooLarge, ip } = {}) {
    if (method === 'GET' && path.startsWith('/object/')) {
      return this.#objectGet(path.slice('/object/'.length), ip);
    }
    if (method === 'POST' && path.startsWith('/api/object/')) {
      return this.#objectPost(
        path.slice('/api/object/'.length), bodyText, bodyTooLarge, ip);
    }
    // Unreachable via the Worker (it only RPCs matched skeptic routes);
    // answer the wall anyway — defense in depth, same bytes.
    return html404();
  }

  /** GET /object/<token> and GET /object/<token>/status/<oid> —
   * server.py handle_object_get, verbatim order: the limiter covers ALL
   * /object/* surfaces (page and status GETs included) and fires BEFORE
   * token validation, identically for any token, so it adds no oracle. */
  async #objectGet(rest, ip) {
    const parts = rest.split('?', 1)[0].split('/').map(unquote);
    const isStatus = parts.length === 3 && parts[1] === 'status';
    if (!this.limiter.allow(ip)) {
      this.#recordRefusal(ip, isStatus ? 'status' : 'page', 'rate_limited');
      return isStatus ? json429() : html429();
    }
    if (parts.length === 1 && parts[0]) return this.#objectPage(parts[0], ip);
    if (isStatus) return this.#objectStatus(parts[0], parts[2], ip);
    this.#recordRefusal(ip, 'page', 'malformed');
    return html404();
  }

  async #objectPage(raw, ip) {
    let token;
    let promotion;
    try {
      ({ token, promotion } = validateToken(this.db, raw));
    } catch (err) {
      if (!(err instanceof TokenInvalid)) throw err;
      this.#recordRefusal(ip, 'page', err.reasonCode, err.tokenId);
      return html404();
    }
    const body = renderObjectPage(
      promotion, token, raw, await this.#deliberationLink(promotion));
    return { status: 200, contentType: HTML_TYPE, body };
  }

  #objectStatus(raw, oid, ip) {
    try {
      return jsonOk(objectionStatus(this.db, raw, oid, this.#hubBase()));
    } catch (err) {
      if (!(err instanceof TokenInvalid)) throw err;
      this.#recordRefusal(ip, 'status', err.reasonCode, err.tokenId);
      return json404();
    }
  }

  /** POST /api/object/<token> {body, contact, label?} — file the
   * objection. Rate-limited per IP, sharing ONE budget with the
   * page/status GETs. */
  async #objectPost(rest, bodyText, bodyTooLarge, ip) {
    const raw = unquote(rest.split('?', 1)[0]);
    if (!this.limiter.allow(ip)) {
      this.#recordRefusal(ip, 'file', 'rate_limited');
      return json429();
    }
    if (bodyTooLarge) {
      // the token was never validated, so the witness carries no token_id
      this.#recordRefusal(ip, 'file', 'malformed');
      return jsonErr('Request body too large', 413);
    }
    let data;
    try {
      data = JSON.parse(bodyText ?? '');
    } catch {
      this.#recordRefusal(ip, 'file', 'malformed');
      return jsonErr('invalid JSON', 400);
    }
    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
      this.#recordRefusal(ip, 'file', 'malformed');
      return jsonErr('invalid JSON', 400);
    }
    try {
      return jsonOk(await this.#fileObjection(raw, data, ip));
    } catch (err) {
      if (err instanceof TokenInvalid) {
        this.#recordRefusal(ip, 'file', err.reasonCode, err.tokenId);
        return json404();
      }
      if (err instanceof PromotionError) return jsonErr(err.message, err.status);
      throw err;
    }
  }

  // ── the operator API (RPC from the Worker; bearer already verified) ─────

  /** Route → statuses (Task 19's client maps any non-2xx to
   * PromotionError(body.error, status), so these are contract):
   *
   *   POST /api/promotions                 200 | 409 dup-open | 422 body
   *   GET  /api/promotions                 200
   *   GET  /api/promotions/metrics         200 | 422 window param
   *   GET  /api/promotions/:pid            200 | 404
   *   POST /api/promotions/:pid/tokens     200 | 404 | 409 not-open/elapsed
   *                                            | 422 use_limit/slug | 400 body
   *   POST .../tokens/:tid/revoke          200 | 404 token
   *   POST .../objections                  200 | 404 | 409 not-open | 422 body
   *   POST .../objections/:oid/resolve     200 | 404 promo/objection
   *                                            | 409 not-open/already-resolved
   *                                            | 422 resolution/body
   *   POST .../close                       200 | 404 | 409 not-open/window-open/unresolved
   *   POST .../waive                       200 | 404 | 409 not-open | 422 reason
   *   POST .../abort                       200 | 404 | 409 not-open
   *   POST .../seal-result                 200 | 404 | 400 body
   *   POST .../sealed-records              200 | 404 | 409 count-mismatch (zero writes)
   *                                            | 422 records | 400 body
   *   GET  /api/object-refusals            200 | 422 window param
   *   POST /api/admin/import               200 | 409 non-empty | 422/400 body
   *
   * Body-taking routes answer 400 {"error": "invalid JSON"} on a
   * malformed body and 413 on an over-ceiling one. Any OTHER path or verb
   * — even with a valid bearer — answers the generic 404 HTML bytes: the
   * operator plane must be indistinguishable from a route that never
   * existed, and an authenticated typo learns nothing more than a prober. */
  async operatorHandle({ method, path, search, bodyText, bodyTooLarge } = {}) {
    try {
      return await this.#operatorRoute(method, path, search, bodyText, bodyTooLarge);
    } catch (err) {
      if (err instanceof PromotionError) return jsonErr(err.message, err.status);
      throw err;
    }
  }

  #parseBody(bodyText, bodyTooLarge) {
    if (bodyTooLarge) throw new PromotionError('Request body too large', 413);
    let data;
    try {
      data = JSON.parse(bodyText ?? '');
    } catch {
      throw new PromotionError('invalid JSON', 400);
    }
    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
      throw new PromotionError('invalid JSON', 400);
    }
    return data;
  }

  async #operatorRoute(method, path, search, bodyText, bodyTooLarge) {
    const body = () => this.#parseBody(bodyText, bodyTooLarge);
    if (method === 'GET') {
      if (path === '/api/promotions') return jsonOk(this.#listPromotions());
      if (path === '/api/promotions/metrics') {
        return jsonOk(this.#metrics(parseWindowParam(search)));
      }
      if (path === '/api/object-refusals') {
        return jsonOk(this.#refusalSummary(parseWindowParam(search)));
      }
      const get = path.match(/^\/api\/promotions\/([^/]+)$/);
      if (get) return jsonOk(this.#getPromotion(get[1]));
      return html404();
    }
    if (method === 'POST') {
      if (path === '/api/promotions') return jsonOk(this.#openPromotion(body()));
      if (path === '/api/admin/import') return jsonOk(this.#adminImport(body()));
      const revoke = path.match(/^\/api\/promotions\/([^/]+)\/tokens\/([^/]+)\/revoke$/);
      if (revoke) return jsonOk(this.#revokeToken(revoke[1], revoke[2]));
      const resolve = path.match(/^\/api\/promotions\/([^/]+)\/objections\/([^/]+)\/resolve$/);
      if (resolve) {
        const data = body();
        return jsonOk(
          this.#resolveObjection(resolve[1], resolve[2], data.resolution, data.body));
      }
      const action = path.match(
        /^\/api\/promotions\/([^/]+)\/(tokens|objections|close|waive|abort|seal-result|sealed-records)$/);
      if (action) {
        const [, pid, act] = action;
        if (act === 'tokens') return jsonOk(await this.#mintToken(pid, body()));
        if (act === 'objections') {
          return jsonOk(this.#addObjection(pid, body().body));
        }
        if (act === 'close') return jsonOk(this.#closePromotion(pid));
        if (act === 'waive') return jsonOk(this.#waivePromotion(pid, body().reason));
        if (act === 'abort') return jsonOk(this.#abortPromotion(pid));
        if (act === 'seal-result') return jsonOk(this.#markSealResult(pid, body()));
        if (act === 'sealed-records') return jsonOk(this.#sealedRecords(pid, body()));
      }
      return html404();
    }
    // Any other verb on the operator plane: indistinguishable from nothing.
    return html404();
  }
}
