// rate-limit.test.js — the per-IP sliding window (OBJECT_RATE=10/60 in the
// test env) lives in the DO, ported from objections.allow_request. It
// fires BEFORE token validation on all three public surfaces, identically
// for any token (so it adds no oracle beyond "this IP is rate limited"),
// and the 11th request in a window answers the per-surface 429 bytes. The
// budget is SHARED across the three surfaces per IP, and every refusal is
// witnessed. The injectable clock is exercised at the unit level
// (SlidingWindow), where a frozen `now` makes the boundaries exact.
import { it, expect, beforeEach } from 'vitest';
import { SELF } from 'cloudflare:test';
import { SlidingWindow } from '../src/do.js';
import {
  GENERIC_429_HTML,
  GENERIC_429_JSON,
} from '../src/constants.js';
import { BASE, opGet, doSql, resetStudio } from './helpers.js';

beforeEach(resetStudio);

const HTML_TYPE = 'text/html; charset=utf-8';
const JSON_TYPE = 'application/json';

const page = (ip, token = 'anytoken') =>
  SELF.fetch(`${BASE}/object/${token}`, { headers: { 'cf-connecting-ip': ip } });
const status = (ip, token = 'anytoken') =>
  SELF.fetch(`${BASE}/object/${token}/status/1`, { headers: { 'cf-connecting-ip': ip } });
const file = (ip, token = 'anytoken') =>
  SELF.fetch(`${BASE}/api/object/${token}`, {
    method: 'POST',
    headers: { 'cf-connecting-ip': ip, 'content-type': 'application/json' },
    body: '{"body":"x","contact":"y"}',
  });

// ── unit: injectable clock ─────────────────────────────────────────────────

it('SlidingWindow admits N per window and refuses the N+1th at a frozen clock', () => {
  const w = new SlidingWindow(10, 60);
  for (let i = 0; i < 10; i++) expect(w.allow('ip1', 1000)).toBe(true);
  expect(w.allow('ip1', 1000)).toBe(false); // 11th, same instant
  // A second IP has an independent budget.
  expect(w.allow('ip2', 1000)).toBe(true);
  // Once the window slides fully past, the bucket ages out and admits again.
  expect(w.allow('ip1', 1061)).toBe(true);
  // A backwards clock jump forces a sweep but never crashes.
  expect(w.allow('ip1', 500)).toBe(true);
});

// ── integration: per-surface 429 bytes ─────────────────────────────────────

it('the 11th page GET in the window answers the 429 HTML bytes', async () => {
  const ip = '198.51.100.10';
  for (let i = 0; i < 10; i++) expect((await page(ip)).status).toBe(404); // admitted (bad token → 404)
  const limited = await page(ip);
  expect(limited.status).toBe(429);
  expect(limited.headers.get('content-type')).toBe(HTML_TYPE);
  expect(await limited.text()).toBe(GENERIC_429_HTML);
});

it('the 11th status GET answers the 429 JSON bytes', async () => {
  const ip = '198.51.100.11';
  for (let i = 0; i < 10; i++) expect((await status(ip)).status).toBe(404);
  const limited = await status(ip);
  expect(limited.status).toBe(429);
  expect(limited.headers.get('content-type')).toBe(JSON_TYPE);
  expect(await limited.text()).toBe(GENERIC_429_JSON);
});

it('the 11th file POST answers the 429 JSON bytes', async () => {
  const ip = '198.51.100.12';
  for (let i = 0; i < 10; i++) expect((await file(ip)).status).toBe(404);
  const limited = await file(ip);
  expect(limited.status).toBe(429);
  expect(limited.headers.get('content-type')).toBe(JSON_TYPE);
  expect(await limited.text()).toBe(GENERIC_429_JSON);
});

it('the budget is SHARED across the three surfaces for one IP', async () => {
  const ip = '198.51.100.13';
  // 4 page + 3 status + 3 file = 10 admitted requests, one shared budget.
  for (let i = 0; i < 4; i++) expect((await page(ip)).status).toBe(404);
  for (let i = 0; i < 3; i++) expect((await status(ip)).status).toBe(404);
  for (let i = 0; i < 3; i++) expect((await file(ip)).status).toBe(404);
  // The 11th on ANY surface is now limited — the surfaces do not each get
  // their own 10.
  expect((await page(ip)).status).toBe(429);
  expect((await status(ip)).status).toBe(429);
  expect((await file(ip)).status).toBe(429);
  // A different IP is unaffected.
  expect((await page('198.51.100.99')).status).toBe(404);
});

it('every rate-limited refusal is witnessed with reason_code rate_limited', async () => {
  const ip = '198.51.100.14';
  for (let i = 0; i < 10; i++) await page(ip);
  await page(ip); // 429, one rate_limited witness (page)
  await status(ip); // 429, another (status)
  await file(ip); // 429, another (file)
  const summary = await (await opGet('/api/object-refusals')).json();
  expect(summary.counts.rate_limited).toBe(3);
  // one per path_kind
  const kinds = await doSql(
    "SELECT path_kind FROM object_refusals WHERE reason_code='rate_limited' ORDER BY path_kind");
  expect(kinds.map((r) => r.path_kind)).toEqual(['file', 'page', 'status']);
});
