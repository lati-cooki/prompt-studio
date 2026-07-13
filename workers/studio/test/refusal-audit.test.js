// refusal-audit.test.js — the insert-only witness log (object_refusals).
// Every /object/* refusal leaves a row with the right reason_code and
// path_kind (and the token_id when the token was valid enough to
// identify), while the prober still gets the byte-identical generic
// response. Append-only is ENFORCED by triggers, not convention: UPDATE
// and DELETE abort.
import { it, expect, beforeEach } from 'vitest';
import { SELF } from 'cloudflare:test';
import {
  BASE,
  opPost,
  openPromotion,
  mintToken,
  fileObjection,
  expireToken,
  doSql,
  resetStudio,
} from './helpers.js';

beforeEach(resetStudio);

const page = (ip, token) =>
  SELF.fetch(`${BASE}/object/${token}`, { headers: { 'cf-connecting-ip': ip } });

// The single most-recent refusal row.
const lastRefusal = async () =>
  (await doSql('SELECT * FROM object_refusals ORDER BY id DESC LIMIT 1'))[0];

it("an unknown token is witnessed 'unknown' with no token_id", async () => {
  await page('192.0.2.1', 'no-such-token-xxxxxxxxxxxxxxxxxxxx');
  const r = await lastRefusal();
  expect(r.path_kind).toBe('page');
  expect(r.reason_code).toBe('unknown');
  expect(r.token_id).toBeNull(); // the dummy-token path can't identify one
});

it("a revoked token is witnessed 'revoked' WITH its token_id", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  await opPost(`/api/promotions/${p.id}/tokens/${t.token_id}/revoke`);
  await page('192.0.2.2', t.token);
  const r = await lastRefusal();
  expect(r.reason_code).toBe('revoked');
  expect(r.token_id).toBe(t.token_id);
});

it("an exhausted token is witnessed 'exhausted' WITH its token_id", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id, { use_limit: 1 });
  await fileObjection(t.token, {}, '192.0.2.30'); // burns the one use
  await page('192.0.2.3', t.token);
  const r = await lastRefusal();
  expect(r.reason_code).toBe('exhausted');
  expect(r.token_id).toBe(t.token_id);
});

it("an expired token is witnessed 'expired' WITH its token_id", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  await expireToken(t.token_id);
  await page('192.0.2.4', t.token);
  const r = await lastRefusal();
  expect(r.reason_code).toBe('expired');
  expect(r.token_id).toBe(t.token_id);
});

it("a token on a closed promotion is witnessed 'closed' WITH its token_id", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  await opPost(`/api/promotions/${p.id}/abort`);
  await page('192.0.2.5', t.token);
  const r = await lastRefusal();
  expect(r.reason_code).toBe('closed');
  expect(r.token_id).toBe(t.token_id);
});

it("a malformed /object path is witnessed 'malformed' on the page surface", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  await SELF.fetch(`${BASE}/object/${t.token}/bogus`, {
    headers: { 'cf-connecting-ip': '192.0.2.6' },
  });
  const r = await lastRefusal();
  expect(r.path_kind).toBe('page');
  expect(r.reason_code).toBe('malformed');
});

it("an empty filing body is witnessed 'malformed' on the file surface WITH token_id", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  const res = await fileObjection(t.token, { body: '   ' }, '192.0.2.7');
  expect(res.status).toBe(422); // the 422 response itself is unchanged
  const r = await lastRefusal();
  expect(r.path_kind).toBe('file');
  expect(r.reason_code).toBe('malformed');
  expect(r.token_id).toBe(t.token_id); // the token validated first
});

it("a malformed status oid is witnessed 'malformed' on the status surface", async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  await SELF.fetch(`${BASE}/object/${t.token}/status/not-a-number`, {
    headers: { 'cf-connecting-ip': '192.0.2.8' },
  });
  const r = await lastRefusal();
  expect(r.path_kind).toBe('status');
  expect(r.reason_code).toBe('malformed');
  expect(r.token_id).toBe(t.token_id);
});

it('every reason_code the CHECK constraint allows is reachable', async () => {
  // A coverage sweep: after the individual cases above run in isolation,
  // reproduce the full set in one store so the union is visible at once.
  const p = await openPromotion();
  const unknownT = 'no-such-token-yyyyyyyyyyyyyyyyyyyy';
  const revoked = await mintToken(p.id);
  await opPost(`/api/promotions/${p.id}/tokens/${revoked.token_id}/revoke`);
  const exhausted = await mintToken(p.id, { use_limit: 1 });
  await fileObjection(exhausted.token, {}, '192.0.2.40');
  const expired = await mintToken(p.id);
  await expireToken(expired.token_id);
  const live = await mintToken(p.id);

  await page('192.0.2.9', unknownT); // unknown
  await page('192.0.2.9', revoked.token); // revoked
  await page('192.0.2.9', exhausted.token); // exhausted
  await page('192.0.2.9', expired.token); // expired
  await fileObjection(live.token, { body: '' }, '192.0.2.9'); // malformed
  // rate_limited: exhaust this IP's remaining budget (10/window total)
  for (let i = 0; i < 10; i++) await page('192.0.2.9', unknownT);
  // closed
  const p2 = await openPromotion();
  const closedT = await mintToken(p2.id);
  await opPost(`/api/promotions/${p2.id}/abort`);
  await page('192.0.2.41', closedT.token);

  const codes = await doSql('SELECT DISTINCT reason_code FROM object_refusals ORDER BY reason_code');
  expect(codes.map((r) => r.reason_code)).toEqual([
    'closed', 'exhausted', 'expired', 'malformed', 'rate_limited', 'revoked', 'unknown',
  ]);
});

it('object_refusals is append-only: UPDATE and DELETE abort (triggers)', async () => {
  await page('192.0.2.20', 'bad-token-zzzzzzzzzzzzzzzzzzzzzzzz'); // one row exists
  await expect(
    doSql("UPDATE object_refusals SET reason_code='revoked' WHERE id=1"),
  ).rejects.toThrow(/append-only/);
  await expect(
    doSql('DELETE FROM object_refusals WHERE id=1'),
  ).rejects.toThrow(/append-only/);
  // the row survives both attempts
  const rows = await doSql('SELECT COUNT(*) AS n FROM object_refusals');
  expect(rows[0].n).toBe(1);
});
