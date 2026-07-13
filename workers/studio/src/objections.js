// objections.js — uniform-work token validation and receipt/status shaping,
// ported faithfully from objections.py (validate_token:420-467,
// _validate_token_for_status:577-620, objection_status:640-682,
// posture_note:138-167 rewritten honestly for this deployment).
//
// The db facade every function takes is provided by the StudioState DO
// (src/do.js): { one(sql, ...params), all(sql, ...params), nowIso(),
// getPromotion(pid), getObjectorWriter(name) }. getPromotion throws
// PromotionError('promotion not found', 404) on a miss after exactly one
// statement, and runs exactly two statements on a hit — the statement-count
// uniformity below depends on that shape.
import { createHash } from 'node:crypto';
import {
  CUSTODY_DISCLOSURE_MINT,
  custodyDisclosureFor,
  receiptInstructions,
} from './constants.js';
import { PromotionError, OPEN, OBJECTIONS_WITH_AUTHOR_QUERY } from './do.js';

/** Raised for EVERY token-check failure on /object/* paths. Routes map
 * this to one byte-identical generic 404 — deliberately no detail: an
 * outsider probing tokens must not learn whether one exists, is revoked,
 * is exhausted, is expired, or belongs to a closed promotion.
 *
 * Carries reasonCode and tokenId for the LOCAL refusal audit only
 * (object_refusals) — the prober-visible response never varies with them.
 * tokenId is resolved only when the token was valid enough to identify
 * (its hash matched a stored row). */
export class TokenInvalid extends Error {
  constructor(reasonCode = 'unknown', tokenId = null) {
    super(reasonCode);
    this.reasonCode = reasonCode;
    this.tokenId = tokenId;
  }
}

// A row shaped like fcp_tokens for the unknown-token path: validation runs
// the SAME work over it (hash comparison, flag checks, promotion lookup)
// instead of returning early. Its hash can never equal a real sha256 hex
// digest and promotion_id -1 can never exist. (objections.py:413-417)
export const DUMMY_TOKEN = {
  id: null,
  token_hash: '!'.repeat(64),
  invitee_label: null,
  revoked: 0,
  uses: 0,
  use_limit: 1,
  expires_at: '9999-12-31T23:59:59Z',
  promotion_id: -1,
};

export const sha256hex = (s) =>
  createHash('sha256').update(s, 'utf8').digest('hex');

export const hashToken = (raw) => sha256hex(raw);

/** Constant-time string comparison, ported from the Python discipline
 * (hmac.compare_digest / server.operator_authorized): hash both sides to
 * fixed length with sha256, then timingSafeEqual — hashing first makes the
 * comparison length-independent too. */
export function timingSafeEqualStr(a, b) {
  const da = createHash('sha256').update(a, 'utf8').digest();
  const db = createHash('sha256').update(b, 'utf8').digest();
  return crypto.subtle.timingSafeEqual(da, db);
}

/** Full validation for the page and filing paths. Returns
 * { token, promotion } or throws TokenInvalid.
 *
 * TIMING NOTE (ported from objections.py:423-433): perfect timing
 * invariance is not achievable, but the gross channel is eliminated:
 * EVERY failure mode computes the token hash, runs the SAME NUMBER of DB
 * statements (token lookup + getPromotion's promotion and objections
 * queries; the unknown-token dummy path runs a compensating objections
 * query so it is not one statement lighter), and compares hashes
 * constant-time. No unknown-token fast path vs known-token slow path. */
export function validateToken(db, raw) {
  const supplied = hashToken(raw ?? '');
  const row = db.one('SELECT * FROM fcp_tokens WHERE token_hash = ?', supplied);
  const token = row !== null ? { ...row } : { ...DUMMY_TOKEN };
  // fetch everything first, evaluate at the end
  const hashOk = timingSafeEqualStr(token.token_hash, supplied);
  const revoked = Boolean(token.revoked);
  const exhausted = token.uses >= token.use_limit;
  const expired = db.nowIso() >= token.expires_at; // window-close snapshot
  let promotion;
  try {
    promotion = db.getPromotion(token.promotion_id);
  } catch (err) {
    if (!(err instanceof PromotionError)) throw err;
    // uniform DB work: a found promotion costs getPromotion a second query
    // (its objections list); run the SAME statement here — imported from
    // do.js so the shapes cannot drift — and the missing-promotion path
    // (the unknown-token dummy) issues the same number of statements.
    db.all(OBJECTIONS_WITH_AUTHOR_QUERY, token.promotion_id);
    promotion = null;
  }
  const notOpen = promotion === null || promotion.state !== OPEN;
  if (!hashOk) throw new TokenInvalid('unknown');
  if (revoked) throw new TokenInvalid('revoked', token.id);
  if (exhausted) throw new TokenInvalid('exhausted', token.id);
  if (expired) throw new TokenInvalid('expired', token.id);
  if (notOpen) throw new TokenInvalid('closed', token.id);
  return { token, promotion };
}

/** Weaker validation for the receipt route: the token must exist and OWN
 * the objection — but revocation, exhaustion and window close do NOT block
 * it. The receipt must outlive the window that produced it (post-seal is
 * exactly when it matters). Failures are still the one generic
 * TokenInvalid.
 *
 * REVOKED TOKENS (controller-decided policy, ported verbatim): a revoked
 * token remains valid on THIS route only, for its own objections. The
 * status route files nothing and reveals nothing the hub does not already
 * serve publicly (record hashes, thread slug, verify URLs — never contact
 * data); revocation kills future FILING (validateToken, unchanged), not
 * the DR 5.6 disclosure guarantee for already-filed objections — an
 * operator action must not silently sever an objector from their receipt.
 *
 * TIMING NOTE: same normalization as validateToken — every failure mode
 * computes the hash, runs the token lookup AND the objection lookup (a
 * dummy row/sentinel oid keeps the work uniform), constant-time compare. */
export function validateTokenForStatus(db, raw, oid) {
  const supplied = hashToken(raw ?? '');
  const row = db.one('SELECT * FROM fcp_tokens WHERE token_hash = ?', supplied);
  const token = row !== null ? { ...row } : { ...DUMMY_TOKEN };
  const hashOk = timingSafeEqualStr(token.token_hash, supplied);
  // deliberately NO revoked check here — see the policy note above
  let oidInt;
  let oidOk;
  if (typeof oid === 'string' && /^\s*[+-]?\d+\s*$/.test(oid)) {
    oidInt = parseInt(oid.trim(), 10);
    oidOk = true;
  } else if (typeof oid === 'number' && Number.isInteger(oid)) {
    oidInt = oid;
    oidOk = true;
  } else {
    oidInt = -1; // sentinel keeps the lookup running
    oidOk = false;
  }
  const objRow = db.one('SELECT * FROM promotion_objections WHERE id = ?', oidInt);
  const obj = objRow !== null ? { ...objRow } : null;
  const owns =
    obj !== null &&
    obj.token_id !== null &&
    obj.token_id !== undefined &&
    token.id !== null &&
    Number(obj.token_id) === token.id;
  if (!hashOk) throw new TokenInvalid('unknown');
  if (!oidOk) throw new TokenInvalid('malformed', token.id);
  if (!owns) throw new TokenInvalid('unknown', token.id); // missing objection or another token's
  return { token, obj };
}

/** GET /object/<token>/status/<oid> — pre-seal: { status: 'filed' };
 * post-seal: the full receipt (record_hash + thread_slug + citation_hash
 * + record_url + verify_url + checker_url + DR 5.6 custody disclosure +
 * runnable checker instructions). This is the conversion moment: the
 * receipt lets the objector verify their own objection with no account
 * and no trust in this server. hubBase is the externally reachable hub
 * (HUB_PUBLIC_BASE_URL) — a receipt must never hand an external skeptic a
 * URL that only resolves from inside the deployment. */
export function objectionStatus(db, raw, oid, hubBase) {
  const { token, obj } = validateTokenForStatus(db, raw, oid);
  let promotion;
  try {
    promotion = db.getPromotion(obj.promotion_id);
  } catch (err) {
    if (!(err instanceof PromotionError)) throw err;
    throw new TokenInvalid('unknown', token.id);
  }
  const base = {
    objection_id: obj.id,
    body_hash: 'sha256:' + sha256hex(obj.body),
    promotion_state: promotion.state,
  };
  const recordHash = obj.sealed_record_hash;
  if (recordHash && promotion.thread_slug) {
    const hub = hubBase;
    const slug = promotion.thread_slug;
    const citation = promotion.citation_hash;
    const writer = obj.author_writer
      ? db.getObjectorWriter(obj.author_writer)
      : null;
    const custody = writer
      ? custodyDisclosureFor(writer)
      : CUSTODY_DISCLOSURE_MINT;
    return {
      ...base,
      status: 'sealed',
      record_hash: recordHash,
      thread_slug: slug,
      citation_hash: citation,
      record_url: `${hub}/r/${recordHash}`,
      verify_url: `${hub}/t/${slug}/verify`,
      checker_url: `${hub}/verify.mjs`,
      custody,
      instructions: receiptInstructions(hub, slug, citation, recordHash),
    };
  }
  return { ...base, status: 'filed', sealed: Boolean(promotion.sealed) };
}

/** Honest, config-derived posture disclosure — REWRITTEN for the cloud
 * deployment (allowed: this is config-derived disclosure text for NEW
 * mints; stored/sealed records keep the text they quoted). The Python
 * original described localhost binding vs STUDIO_PUBLIC_MODE; neither
 * exists here, and quoting them would be a false disclosure. What is true
 * here: the Worker is public by construction, only the skeptic surface is
 * served without a bearer, and an unset secret fails CLOSED (no operator
 * surface) rather than open. */
export function postureNote(env) {
  let auth;
  if (env.STUDIO_OPERATOR_TOKEN) {
    auth =
      'Operator routes on this deployment enforce bearer auth: every ' +
      "operator route requires 'Authorization: Bearer <token>' " +
      '(constant-time comparison over sha256 digests), and a request ' +
      'without it — absent, wrong, or truncated — answers the same ' +
      'generic 404 as a route that never existed.';
  } else {
    auth =
      'No operator credential is configured (STUDIO_OPERATOR_TOKEN is ' +
      'unset): this Worker fails CLOSED — the operator surface is ' +
      'unreachable and nothing can be minted or changed until the ' +
      'secret is set.';
  }
  const mode =
    ' This is a public cloud deployment (Cloudflare Worker): only the ' +
    'tokenized objection surface (/object/* pages and receipts, ' +
    '/api/object/* filing) is served to the public; every other route ' +
    'answers a generic 404.';
  return auth + mode;
}
