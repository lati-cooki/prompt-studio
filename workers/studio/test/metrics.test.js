// metrics.test.js — DR-2026-07-12-fcp-metrics parity. The formulas are
// sealed immutable; these tests hand-compute the expected ratios against
// promotion_store.metrics and assert the DO matches:
//   fcp_waive_ratio            = waived / terminal_total
//   externally_contested_ratio = invited / terminal_total
//     invited = terminal outcomes with >= 1 fcp_tokens row whose
//               minted_at < resolved_at (STRICT — a token minted at or
//               after the outcome does NOT count)
//   denominator 0 -> both ratios null (never a fabricated 0.0)
import { it, expect, beforeEach } from 'vitest';
import { CONTESTED_DATA_MEASURED } from '../src/do.js';
import {
  opPost,
  opGet,
  openPromotion,
  mintToken,
  elapseWindow,
  doSql,
  resetStudio,
} from './helpers.js';

beforeEach(resetStudio);

const setMintedAt = (tokenId, ts) =>
  doSql('UPDATE fcp_tokens SET minted_at=? WHERE id=?', ts, tokenId);
const setResolvedAt = (pid, ts) =>
  doSql('UPDATE promotions SET resolved_at=? WHERE id=?', ts, pid);

const closeElapsed = async (pid) => {
  await elapseWindow(pid);
  const res = await opPost(`/api/promotions/${pid}/close`);
  expect(res.status).toBe(200);
};

/** Seed the five terminal shapes + one open (excluded):
 *   P1 closed,  no token                         terminal, not waived, not contested
 *   P2 waived,  no token                         terminal, WAIVED,     not contested
 *   P3 aborted, token minted strictly before     terminal, not waived, CONTESTED
 *   P4 closed,  token minted strictly before     terminal, not waived, CONTESTED
 *   P6 closed,  token minted AFTER the outcome    terminal, not waived, NOT contested
 *   P5 open                                       excluded entirely
 * => terminal_total 5, waived 1, invited 2. */
async function seedTerminalMix() {
  const p1 = await openPromotion();
  await closeElapsed(p1.id);

  const p2 = await openPromotion();
  await opPost(`/api/promotions/${p2.id}/waive`, { reason: 'deliberate waive' });

  const p3 = await openPromotion();
  const t3 = await mintToken(p3.id);
  await setMintedAt(t3.token_id, '2020-01-01T00:00:00Z'); // strictly before
  await opPost(`/api/promotions/${p3.id}/abort`);

  const p4 = await openPromotion();
  const t4 = await mintToken(p4.id);
  await setMintedAt(t4.token_id, '2020-01-01T00:00:00Z');
  await closeElapsed(p4.id);

  const p6 = await openPromotion();
  const t6 = await mintToken(p6.id);
  await closeElapsed(p6.id);
  await setMintedAt(t6.token_id, '2099-01-01T00:00:00Z'); // AFTER the outcome

  await openPromotion(); // P5, open — excluded
  return { p1 };
}

it('all-time metrics match the hand-computed ratios', async () => {
  await seedTerminalMix();
  const m = await (await opGet('/api/promotions/metrics')).json();
  expect(m.window_days).toBeNull();
  expect(m.terminal_total).toBe(5);
  expect(m.waived).toBe(1);
  expect(m.invited).toBe(2);
  expect(m.fcp_waive_ratio).toBe(1 / 5); // 0.2
  expect(m.externally_contested_ratio).toBe(2 / 5); // 0.4
  expect(m.contested_data).toBe(CONTESTED_DATA_MEASURED);
  expect(m.computed_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
});

it('windowing filters by resolved_at (outcome older than the window drops out)', async () => {
  const { p1 } = await seedTerminalMix();
  // Age P1's outcome out of a 7-day window; the other four stay in.
  await setResolvedAt(p1.id, '2000-01-01T00:00:00Z');
  const m = await (await opGet('/api/promotions/metrics?window=7')).json();
  expect(m.window_days).toBe(7);
  expect(m.terminal_total).toBe(4); // P1 excluded
  expect(m.waived).toBe(1);
  expect(m.invited).toBe(2);
  expect(m.fcp_waive_ratio).toBe(1 / 4); // 0.25
  expect(m.externally_contested_ratio).toBe(2 / 4); // 0.5
});

it('an empty store yields null ratios with zero counts, never a fabricated 0.0', async () => {
  const m = await (await opGet('/api/promotions/metrics')).json();
  expect(m.terminal_total).toBe(0);
  expect(m.waived).toBe(0);
  expect(m.invited).toBe(0);
  expect(m.fcp_waive_ratio).toBeNull();
  expect(m.externally_contested_ratio).toBeNull();
});

it('a token minted at the SAME instant as the outcome is not contested (strict <)', async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  await elapseWindow(p.id);
  const closed = await (await opPost(`/api/promotions/${p.id}/close`)).json();
  // Force minted_at exactly equal to resolved_at — the strict inequality
  // must exclude it.
  await setMintedAt(t.token_id, closed.resolved_at);
  const m = await (await opGet('/api/promotions/metrics')).json();
  expect(m.terminal_total).toBe(1);
  expect(m.invited).toBe(0);
  expect(m.externally_contested_ratio).toBe(0);
});

it('the window query param is validated like the Python handler', async () => {
  const bad = await opGet('/api/promotions/metrics?window=abc');
  expect(bad.status).toBe(422);
  expect((await bad.json()).error).toBe('window must be a whole number of days');
  const zero = await opGet('/api/promotions/metrics?window=0');
  expect(zero.status).toBe(422);
  expect((await zero.json()).error).toBe('window must be a positive number of days');
});
