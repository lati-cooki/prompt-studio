// byte-identity.test.js — the crown jewel. To an outside prober, every
// failure mode of a surface answers the SAME bytes: same status, same
// content-type, byte-identical body, identical header sets. An unknown
// token, a revoked one, an exhausted one, an expired one, one whose
// promotion closed, a walled operator route (no/wrong/truncated bearer),
// and an arbitrary unknown path must be indistinguishable — no token
// oracle, no auth oracle, no route-existence oracle. And the constants
// themselves are pinned to the PYTHON serialization: json.dumps puts a
// space after the colon and ASCII-escapes the em-dash; JSON.stringify
// would not.
import { it, expect, beforeEach } from 'vitest';
import { SELF } from 'cloudflare:test';
import {
  GENERIC_404_JSON,
  GENERIC_404_HTML,
  GENERIC_429_JSON,
  GENERIC_429_HTML,
} from '../src/constants.js';
import {
  BASE,
  sha256,
  opPost,
  openPromotion,
  mintToken,
  fileObjection,
  expireToken,
  resetStudio,
} from './helpers.js';

beforeEach(resetStudio);

const HTML_TYPE = 'text/html; charset=utf-8';
const JSON_TYPE = 'application/json';

it('the four generic bodies are the pinned Python-serialized bytes', () => {
  expect(GENERIC_404_JSON).toBe('{"error": "not found"}');
  expect(GENERIC_404_HTML).toBe(
    "<!doctype html><meta charset='utf-8'><title>Not found</title><p>Not found.</p>");
  expect(GENERIC_429_JSON).toBe('{"error": "rate limited \\u2014 try again shortly"}');
  expect(GENERIC_429_HTML).toBe(
    "<!doctype html><meta charset='utf-8'><title>Too many requests</title><p>Too many requests — try again shortly.</p>");
  // The Python-serialization pin, made explicit: JSON.stringify of the
  // same objects produces DIFFERENT bytes (no space after the colon, and
  // a literal em-dash where ensure_ascii writes backslash-u-2-0-1-4) —
  // anyone "simplifying" these constants into stringify calls fails here.
  expect(GENERIC_404_JSON).not.toBe(JSON.stringify({ error: 'not found' }));
  expect(GENERIC_429_JSON).not.toBe(
    JSON.stringify({ error: 'rate limited — try again shortly' }));
  // ...while still parsing to the same values a client sees.
  expect(JSON.parse(GENERIC_404_JSON)).toEqual({ error: 'not found' });
  expect(JSON.parse(GENERIC_429_JSON)).toEqual({ error: 'rate limited — try again shortly' });
});

// Build one of every token failure mode, plus a healthy control.
async function seedTokenFailures() {
  const promo = await openPromotion();
  const revoked = await mintToken(promo.id);
  await opPost(`/api/promotions/${promo.id}/tokens/${revoked.token_id}/revoke`);
  const exhausted = await mintToken(promo.id, { use_limit: 1 });
  const filed = await fileObjection(exhausted.token, {}, '203.0.113.240');
  expect(filed.status).toBe(200);
  const expired = await mintToken(promo.id);
  await expireToken(expired.token_id);
  const healthy = await mintToken(promo.id);

  const closedPromo = await openPromotion();
  const closedToken = await mintToken(closedPromo.id);
  const aborted = await opPost(`/api/promotions/${closedPromo.id}/abort`);
  expect(aborted.status).toBe(200);
  return { promo, revoked, exhausted, expired, healthy, closedToken };
}

let ipCounter = 0;
const freshIp = () => `192.0.2.${++ipCounter}`; // one IP per probe: the limiter must not fire

const get = (path) =>
  SELF.fetch(BASE + path, { headers: { 'cf-connecting-ip': freshIp() } });
const post = (path, headers = {}, body = '{"body":"x","contact":"y"}') =>
  SELF.fetch(BASE + path, {
    method: 'POST',
    headers: { 'cf-connecting-ip': freshIp(), 'content-type': 'application/json', ...headers },
    body,
  });

async function expectAllIdentical(probes, { status, contentType, body }) {
  const expectedSha = sha256(body);
  let headerShape = null;
  for (const [name, probe] of probes) {
    const res = await probe();
    expect(res.status, name).toBe(status);
    expect(res.headers.get('content-type'), name).toBe(contentType);
    expect(sha256(await res.text()), name).toBe(expectedSha);
    // No extra oracle headers: every probe's header SET is identical.
    const shape = [...res.headers.keys()].sort().join(',');
    if (headerShape === null) headerShape = shape;
    expect(shape, name).toBe(headerShape);
  }
}

it('every page-surface failure and every walled route answers the identical 404 HTML bytes', async () => {
  const { revoked, exhausted, expired, healthy, closedToken } = await seedTokenFailures();

  const probes = [
    // the /object/* page surface, one probe per failure mode
    ['unknown token page', () => get('/object/no-such-token-aaaaaaaaaaaaaaaaaaaaaa')],
    ['revoked token page', () => get(`/object/${revoked.token}`)],
    ['exhausted token page', () => get(`/object/${exhausted.token}`)],
    ['expired token page', () => get(`/object/${expired.token}`)],
    ['closed-promotion token page', () => get(`/object/${closedToken.token}`)],
    ['malformed object path', () => get(`/object/${healthy.token}/extra`)],
    ['empty object path', () => get('/object/')],
    // the wall: unknown paths and every operator route without the bearer
    ['unknown path', () => get('/no/such/route')],
    ['root', () => get('/')],
    ['GET on the filing path (wrong verb)', () => get('/api/object/whatever')],
    ['POST on the page path (wrong verb)', () => post('/object/whatever')],
    ['operator list, no bearer', () => get('/api/promotions')],
    ['operator list, wrong bearer', () =>
      SELF.fetch(`${BASE}/api/promotions`, {
        headers: { authorization: 'Bearer wrong-token', 'cf-connecting-ip': freshIp() },
      })],
    ['operator list, truncated bearer', () =>
      SELF.fetch(`${BASE}/api/promotions`, {
        headers: { authorization: 'Bearer test-operator-toke', 'cf-connecting-ip': freshIp() },
      })],
    ['operator list, bearer scheme missing', () =>
      SELF.fetch(`${BASE}/api/promotions`, {
        headers: { authorization: 'test-operator-token', 'cf-connecting-ip': freshIp() },
      })],
    ['operator open, no bearer', () => post('/api/promotions')],
    ['operator mint, no bearer', () => post('/api/promotions/1/tokens')],
    ['operator refusals, no bearer', () => get('/api/object-refusals')],
    ['admin import, no bearer', () => post('/api/admin/import')],
    ['PUT anywhere', () =>
      SELF.fetch(`${BASE}/api/promotions/1`, { method: 'PUT', headers: { 'cf-connecting-ip': freshIp() } })],
    ['DELETE anywhere', () =>
      SELF.fetch(`${BASE}/api/promotions/1`, { method: 'DELETE', headers: { 'cf-connecting-ip': freshIp() } })],
    // an AUTHENTICATED typo is indistinguishable from the wall too
    ['operator unknown api path, valid bearer', () =>
      SELF.fetch(`${BASE}/api/nope`, {
        headers: { authorization: 'Bearer test-operator-token', 'cf-connecting-ip': freshIp() },
      })],
    ['operator retired reseal action, valid bearer', () =>
      SELF.fetch(`${BASE}/api/promotions/1/reseal`, {
        method: 'POST',
        headers: { authorization: 'Bearer test-operator-token', 'cf-connecting-ip': freshIp() },
      })],
  ];

  await expectAllIdentical(probes, {
    status: 404,
    contentType: HTML_TYPE,
    body: GENERIC_404_HTML,
  });
});

it('every JSON-surface failure answers the identical 404 JSON bytes', async () => {
  const { revoked, exhausted, expired, healthy, closedToken, promo } =
    await seedTokenFailures();

  // an objection owned by a DIFFERENT token, for the ownership probes
  const otherToken = await mintToken(promo.id, { use_limit: 2 });
  const otherFiled = await (await fileObjection(otherToken.token, {}, '203.0.113.241')).json();

  const filePost = (raw) => () => post(`/api/object/${raw}`);
  const probes = [
    // filing failures
    ['file with unknown token', filePost('no-such-token-bbbbbbbbbbbbbbbbbbbbbb')],
    ['file with revoked token', filePost(revoked.token)],
    ['file with exhausted token', filePost(exhausted.token)],
    ['file with expired token', filePost(expired.token)],
    ['file on closed promotion', filePost(closedToken.token)],
    // status failures
    ['status with unknown token', () => get('/object/no-such-token-cc/status/1')],
    ['status for nonexistent objection', () => get(`/object/${healthy.token}/status/999999`)],
    ["status for another token's objection", () =>
      get(`/object/${healthy.token}/status/${otherFiled.objection_id}`)],
    ['status with malformed oid', () => get(`/object/${healthy.token}/status/abc`)],
  ];

  await expectAllIdentical(probes, {
    status: 404,
    contentType: JSON_TYPE,
    body: GENERIC_404_JSON,
  });
});

it('page-surface failures match the wall bytes exactly (token probe == route probe)', async () => {
  // The wall (an unknown path) and a bad token on the page surface must be
  // the same bytes — a prober cannot even tell the skeptic surface exists.
  const wall = await get('/definitely/not/a/route');
  const badToken = await get('/object/not-a-real-token-dddddddddddddddddd');
  expect(badToken.status).toBe(wall.status);
  expect(badToken.headers.get('content-type')).toBe(wall.headers.get('content-type'));
  expect(await badToken.text()).toBe(await wall.text());
});
