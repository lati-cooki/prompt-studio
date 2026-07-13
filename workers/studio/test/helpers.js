// helpers.js — shared test plumbing. The operator token and URL bases
// match the miniflare bindings in vitest.config.js (test-only; production
// uses a wrangler secret and wrangler.jsonc vars).
import crypto from 'node:crypto';
import { SELF, env, runInDurableObject } from 'cloudflare:test';
import { SCHEMA } from '../src/do.js';

// This pool version (0.18.x) does not expose isolatedStorage, so the single
// named DO (idFromName('studio')) persists its SQL and in-memory limiter
// across every test in a run. resetStudio() gives each test a clean slate:
// DROP every table (which drops its append-only triggers too — a plain
// DELETE on object_refusals would abort) and rebuild from SCHEMA, restart
// AUTOINCREMENT (DROP clears sqlite_sequence → ids from 1), and clear the
// sliding-window limiter's buckets. Call it in beforeEach.
const STUDIO_TABLES = [
  'object_refusals',
  'fcp_tokens',
  'promotion_objections',
  'objector_writers',
  'promotions',
];

export async function resetStudio() {
  const stub = env.STUDIO.get(env.STUDIO.idFromName('studio'));
  await runInDurableObject(stub, (instance, state) => {
    for (const t of STUDIO_TABLES) state.storage.sql.exec(`DROP TABLE IF EXISTS ${t}`);
    state.storage.sql.exec(SCHEMA);
    instance.limiter.buckets.clear();
    instance.limiter.lastSweep = 0;
  });
  promoCounter = 0;
}

export const BASE = 'https://studio.example';
export const HUB_BASE = 'https://hub.example';
export const TOKEN = 'test-operator-token';
export const OPERATOR = { authorization: `Bearer ${TOKEN}` };

export const sha256 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');

// Operator-authenticated JSON POST.
export async function opPost(path, body, headers = {}) {
  return SELF.fetch(BASE + path, {
    method: 'POST',
    headers: { ...OPERATOR, 'content-type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const opGet = (path) => SELF.fetch(BASE + path, { headers: OPERATOR });

// Public (skeptic) requests. Every call names its IP explicitly where the
// rate limit matters; the default keeps unrelated tests off each other's
// budgets only because isolated storage also resets the DO between tests.
export const pubGet = (path, ip = '198.51.100.1') =>
  SELF.fetch(BASE + path, { headers: { 'cf-connecting-ip': ip } });

export const pubPost = (path, body, ip = '198.51.100.1', headers = {}) =>
  SELF.fetch(BASE + path, {
    method: 'POST',
    headers: { 'cf-connecting-ip': ip, 'content-type': 'application/json', ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });

// Operator fixtures ---------------------------------------------------------

let promoCounter = 0;

/** Open a promotion; unique prompt_id per call unless overridden. */
export async function openPromotion(overrides = {}) {
  promoCounter += 1;
  const res = await opPost('/api/promotions', {
    prompt_id: `greeter-${promoCounter}`,
    version: 'v2',
    window_hours: 24,
    evidence: { source_file: 'evals/greeter-v2.md', content_hash: 'sha256:evd' + promoCounter },
    ...overrides,
  });
  if (res.status !== 200) throw new Error(`openPromotion failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function mintToken(pid, body = {}) {
  const res = await opPost(`/api/promotions/${pid}/tokens`, body);
  if (res.status !== 200) throw new Error(`mintToken failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function fileObjection(rawToken, body = {}, ip = '198.51.100.1') {
  return pubPost(`/api/object/${rawToken}`, {
    body: 'I object: the eval set is too small.',
    contact: 'skeptic@example.org',
    ...body,
  }, ip);
}

// Direct SQL against the DO's storage — for elapsing windows/expiries
// without wall-clock waits and for asserting stored state (e.g. only the
// token HASH is stored). Runs inside the same singleton instance the
// Worker routes to.
export async function doSql(query, ...params) {
  const stub = env.STUDIO.get(env.STUDIO.idFromName('studio'));
  return runInDurableObject(stub, (_instance, state) =>
    state.storage.sql.exec(query, ...params).toArray());
}

export const elapseWindow = (pid) =>
  doSql("UPDATE promotions SET closes_at='2000-01-01T00:00:00Z' WHERE id=?", pid);

export const expireToken = (tokenId) =>
  doSql("UPDATE fcp_tokens SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", tokenId);
