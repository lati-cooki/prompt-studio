import { test } from 'node:test';
import assert from 'node:assert';
import { VIEWS, resolveView, homeState, promotionMetricsLabel } from './view.js';

test('VIEWS lists the five views', () => {
  assert.deepStrictEqual(VIEWS, ['home', 'deliberate', 'decisions', 'registry', 'sessions']);
});

test('resolveView: known ids pass through', () => {
  for (const v of VIEWS) assert.strictEqual(resolveView(v), v);
});

test('resolveView: leading # and case tolerated', () => {
  assert.strictEqual(resolveView('#Decisions'), 'decisions');
  assert.strictEqual(resolveView('  REGISTRY '), 'registry');
});

test('resolveView: sessions resolves', () => {
  assert.strictEqual(resolveView('sessions'), 'sessions');
  assert.strictEqual(resolveView('#Sessions'), 'sessions');
});

test('resolveView: unknown/empty falls back to home', () => {
  assert.strictEqual(resolveView('nope'), 'home');
  assert.strictEqual(resolveView(''), 'home');
  assert.strictEqual(resolveView(null), 'home');
  assert.strictEqual(resolveView(undefined), 'home');
});

test('homeState: empty when no sessions and no decisions', () => {
  assert.strictEqual(homeState(0, 0), 'empty');
});

test('homeState: hub when any sessions or decisions exist', () => {
  assert.strictEqual(homeState(1, 0), 'hub');
  assert.strictEqual(homeState(0, 3), 'hub');
  assert.strictEqual(homeState(2, 5), 'hub');
});

test('homeState: tolerates non-number input as empty', () => {
  assert.strictEqual(homeState(undefined, null), 'empty');
});

test('promotionMetricsLabel: renders counts compactly', () => {
  assert.strictEqual(
    promotionMetricsLabel({ terminal_total: 5, waived: 0, invited: 0 }),
    'waive 0/5 · contested 0/5');
  assert.strictEqual(
    promotionMetricsLabel({ terminal_total: 8, waived: 2, invited: 3 }),
    'waive 2/8 · contested 3/8');
});

test('promotionMetricsLabel: zero outcomes still shows counts (ratio is null upstream)', () => {
  assert.strictEqual(
    promotionMetricsLabel({ terminal_total: 0, waived: 0, invited: 0 }),
    'waive 0/0 · contested 0/0');
});

test('promotionMetricsLabel: null on malformed input (graceful when endpoint errors)', () => {
  assert.strictEqual(promotionMetricsLabel(null), null);
  assert.strictEqual(promotionMetricsLabel(undefined), null);
  assert.strictEqual(promotionMetricsLabel({}), null);
  assert.strictEqual(promotionMetricsLabel({ terminal_total: 'x', waived: 0, invited: 0 }), null);
});
