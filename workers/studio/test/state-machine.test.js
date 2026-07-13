// state-machine.test.js — the promotion_store.py port: open → closed |
// waived | aborted, lazy window elapse, unresolved-objection block,
// upheld-forces-abort, terminal states refusing further acts, and the
// verbatim error messages/statuses Task 19's client maps back to
// PromotionError.
import { it, expect, beforeEach } from 'vitest';
import {
  opPost,
  opGet,
  openPromotion,
  mintToken,
  fileObjection,
  elapseWindow,
  resetStudio,
} from './helpers.js';

beforeEach(resetStudio);

it('duplicate open for the same prompt@version is 409', async () => {
  const p = await openPromotion({ prompt_id: 'dup', version: 'v1' });
  const dup = await opPost('/api/promotions', {
    prompt_id: 'dup', version: 'v1', evidence: null,
  });
  expect(dup.status).toBe(409);
  expect((await dup.json()).error).toBe(`promotion ${p.id} already open for dup@v1`);
  // a DIFFERENT version opens fine
  const other = await opPost('/api/promotions', {
    prompt_id: 'dup', version: 'v2', evidence: null,
  });
  expect(other.status).toBe(200);
});

it('open validates its body: evidence shape, window_hours, slug, required ids', async () => {
  const badEvidence = await opPost('/api/promotions', {
    prompt_id: 'x', version: 'v1', evidence: { source_file: 'only-this' },
  });
  expect(badEvidence.status).toBe(422);
  expect((await badEvidence.json()).error).toBe(
    'evidence must include source_file and content_hash');

  const badWindow = await opPost('/api/promotions', {
    prompt_id: 'x', version: 'v1', evidence: null, window_hours: 'soon',
  });
  expect(badWindow.status).toBe(422);
  expect((await badWindow.json()).error).toBe('window_hours must be numeric');

  const badSlug = await opPost('/api/promotions', {
    prompt_id: 'x', version: 'v1', evidence: null, deliberation_slug: '../etc',
  });
  expect(badSlug.status).toBe(422);
  expect((await badSlug.json()).error).toBe('deliberation_slug must be a safe slug');

  const missingIds = await opPost('/api/promotions', { evidence: null });
  expect(missingIds.status).toBe(422);
  expect((await missingIds.json()).error).toBe('prompt_id and version are required');
});

it('evidence-absent opens are recorded as disclosed absence (null), and opened_by lands', async () => {
  const p = await openPromotion({ evidence: null, opened_by: 'delegate' });
  expect(p.evidence).toBeNull();
  expect(p.opened_by).toBe('delegate');
});

it('window elapse is lazy: no scheduler flips state, reads compute it', async () => {
  const p = await openPromotion();
  expect(p.window_elapsed).toBe(false);
  await elapseWindow(p.id);
  const read = await (await opGet(`/api/promotions/${p.id}`)).json();
  expect(read.state).toBe('open'); // still open — elapse is not a state
  expect(read.window_elapsed).toBe(true);
});

it('close refuses while the window is open, then closes after it elapses', async () => {
  const p = await openPromotion();
  const early = await opPost(`/api/promotions/${p.id}/close`);
  expect(early.status).toBe(409);
  expect((await early.json()).error).toBe(
    `window open until ${p.closes_at} — close later or waive`);
  await elapseWindow(p.id);
  const closed = await (await opPost(`/api/promotions/${p.id}/close`)).json();
  expect(closed.state).toBe('closed');
  expect(closed.resolved_by).toBe('operator');
});

it('an unresolved objection blocks close even past the window', async () => {
  const p = await openPromotion();
  const obj = await (await opPost(`/api/promotions/${p.id}/objections`, {
    body: 'operator-channel objection',
  })).json();
  expect(obj.author_writer).toBe('operator');
  expect(obj.resolution).toBeNull();
  await elapseWindow(p.id);
  const blocked = await opPost(`/api/promotions/${p.id}/close`);
  expect(blocked.status).toBe(409);
  expect((await blocked.json()).error).toBe('1 unresolved objection(s) block close');
  await opPost(`/api/promotions/${p.id}/objections/${obj.id}/resolve`, {
    resolution: 'responded', body: 'addressed',
  });
  const closed = await opPost(`/api/promotions/${p.id}/close`);
  expect(closed.status).toBe(200);
});

it('an upheld objection forces abort', async () => {
  const p = await openPromotion();
  const obj = await (await opPost(`/api/promotions/${p.id}/objections`, {
    body: 'this must not ship',
  })).json();
  const res = await opPost(`/api/promotions/${p.id}/objections/${obj.id}/resolve`, {
    resolution: 'upheld', body: 'the objection stands',
  });
  expect(res.status).toBe(200);
  const aborted = await res.json();
  expect(aborted.state).toBe('aborted');
  expect(aborted.objections[0].resolution).toBe('upheld');
  expect(aborted.objections[0].resolution_body).toBe('the objection stands');
});

it('resolve validates: resolution enum, body, existence, double-resolve', async () => {
  const p = await openPromotion();
  const obj = await (await opPost(`/api/promotions/${p.id}/objections`, {
    body: 'q',
  })).json();

  const badEnum = await opPost(
    `/api/promotions/${p.id}/objections/${obj.id}/resolve`,
    { resolution: 'dismissed', body: 'x' });
  expect(badEnum.status).toBe(422);
  expect((await badEnum.json()).error).toBe("resolution must be 'responded' or 'upheld'");

  const noBody = await opPost(
    `/api/promotions/${p.id}/objections/${obj.id}/resolve`,
    { resolution: 'responded', body: '   ' });
  expect(noBody.status).toBe(422);
  expect((await noBody.json()).error).toBe('resolution body required');

  const missing = await opPost(
    `/api/promotions/${p.id}/objections/999999/resolve`,
    { resolution: 'responded', body: 'x' });
  expect(missing.status).toBe(404);
  expect((await missing.json()).error).toBe('objection not found');

  await opPost(`/api/promotions/${p.id}/objections/${obj.id}/resolve`, {
    resolution: 'responded', body: 'first',
  });
  const twice = await opPost(
    `/api/promotions/${p.id}/objections/${obj.id}/resolve`,
    { resolution: 'responded', body: 'second' });
  expect(twice.status).toBe(409);
  expect((await twice.json()).error).toBe('objection already resolved');
});

it('waive requires a reason and records it; abort needs nothing', async () => {
  const p = await openPromotion();
  const noReason = await opPost(`/api/promotions/${p.id}/waive`, {});
  expect(noReason.status).toBe(422);
  expect((await noReason.json()).error).toBe('waive reason required');
  const waived = await (await opPost(`/api/promotions/${p.id}/waive`, {
    reason: 'hotfix, window waived deliberately',
  })).json();
  expect(waived.state).toBe('waived');
  expect(waived.waive_reason).toBe('hotfix, window waived deliberately');

  const p2 = await openPromotion();
  const aborted = await (await opPost(`/api/promotions/${p2.id}/abort`)).json();
  expect(aborted.state).toBe('aborted');
});

it('terminal states refuse mint, operator objections, resolve, and re-termination', async () => {
  const p = await openPromotion();
  const minted = await mintToken(p.id, { use_limit: 5 });
  const obj = await (await opPost(`/api/promotions/${p.id}/objections`, {
    body: 'pending',
  })).json();
  await opPost(`/api/promotions/${p.id}/abort`);

  const mint = await opPost(`/api/promotions/${p.id}/tokens`, {});
  expect(mint.status).toBe(409);
  expect((await mint.json()).error).toBe(
    'promotion is aborted, not open — tokens are minted only for an open FCP window');

  const object = await opPost(`/api/promotions/${p.id}/objections`, { body: 'late' });
  expect(object.status).toBe(409);
  expect((await object.json()).error).toBe('promotion is aborted, not open');

  const resolve = await opPost(
    `/api/promotions/${p.id}/objections/${obj.id}/resolve`,
    { resolution: 'responded', body: 'late' });
  expect(resolve.status).toBe(409);

  for (const act of ['close', 'waive', 'abort']) {
    const res = await opPost(`/api/promotions/${p.id}/${act}`, { reason: 'r' });
    expect(res.status, act).toBe(409);
  }

  // and the still-valid token files nothing into a terminal promotion
  const filed = await fileObjection(minted.token, {}, '203.0.113.99');
  expect(filed.status).toBe(404);
});

it('mint refuses on an elapsed window (a token minted now would expire at birth)', async () => {
  const p = await openPromotion();
  await elapseWindow(p.id);
  const mint = await opPost(`/api/promotions/${p.id}/tokens`, {});
  expect(mint.status).toBe(409);
  expect((await mint.json()).error).toBe(
    'FCP window already elapsed — a token minted now would expire at birth ' +
      '(expires_at is the closes_at snapshot)');
});

it('mint validates use_limit like the Python (integer >= 1)', async () => {
  const p = await openPromotion();
  for (const bad of [0, -1, 1.5, '2', true]) {
    const res = await opPost(`/api/promotions/${p.id}/tokens`, { use_limit: bad });
    expect(res.status, String(bad)).toBe(422);
    expect((await res.json()).error).toBe('use_limit must be an integer >= 1');
  }
});

it('unknown promotions are 404 on every operator route', async () => {
  for (const [path, body] of [
    ['/api/promotions/424242', undefined],
    ['/api/promotions/424242/tokens', {}],
    ['/api/promotions/424242/objections', { body: 'x' }],
    ['/api/promotions/424242/close', undefined],
    ['/api/promotions/424242/abort', undefined],
    ['/api/promotions/424242/seal-result', { slug: 's' }],
    ['/api/promotions/424242/sealed-records', { records: [] }],
  ]) {
    const res = body === undefined && path === '/api/promotions/424242'
      ? await opGet(path)
      : await opPost(path, body);
    expect(res.status, path).toBe(404);
    expect((await res.json()).error, path).toBe('promotion not found');
  }
});

it('lists promotions newest-first with full shapes', async () => {
  const a = await openPromotion();
  const b = await openPromotion();
  const list = await (await opGet('/api/promotions')).json();
  expect(list.map((p) => p.id)).toEqual([b.id, a.id]);
  expect(list[0]).toHaveProperty('objections');
  expect(list[0]).toHaveProperty('window_elapsed');
  expect(list[0]).toHaveProperty('unresolved_objections');
});
