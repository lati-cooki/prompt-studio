// token-lifecycle.test.js — the whole arc, end to end: open → mint →
// page → file → status filed → revoke (status survives — POLICY DECIDED
// in phase 5: revocation kills future filing, never an already-filed
// objector's receipt) → resolve → close (blocked, then allowed) →
// sealed-records (mismatch 409 = zero writes, then success) → seal-result
// → status sealed with the full receipt.
import { it, expect, beforeEach } from 'vitest';
import { CUSTODY_DISCLOSURE_MINT } from '../src/constants.js';
import {
  BASE,
  HUB_BASE,
  sha256,
  opPost,
  opGet,
  pubGet,
  openPromotion,
  mintToken,
  fileObjection,
  doSql,
  elapseWindow,
  resetStudio,
} from './helpers.js';
import { GENERIC_404_JSON } from '../src/constants.js';

beforeEach(resetStudio);

it('runs the full token lifecycle end to end', async () => {
  // ── open ────────────────────────────────────────────────────────────────
  const promo = await openPromotion({ prompt_id: 'lifecycle', version: 'v7' });
  expect(promo.state).toBe('open');
  expect(promo.window_elapsed).toBe(false);
  expect(promo.evidence).toEqual({
    source_file: 'evals/greeter-v2.md',
    content_hash: expect.stringContaining('sha256:'),
  });

  // ── mint ────────────────────────────────────────────────────────────────
  const minted = await mintToken(promo.id, { invitee_label: 'Dana Q.', use_limit: 1 });
  expect(minted.token.length).toBeGreaterThanOrEqual(43); // secrets.token_urlsafe(32) parity
  expect(minted.url).toBe(`${BASE}/object/${minted.token}`);
  expect(minted.expires_at).toBe(promo.closes_at); // window snapshot
  expect(minted.custody).toBe(CUSTODY_DISCLOSURE_MINT);
  expect(minted.posture).toContain('enforce bearer auth');
  expect(minted.posture).toContain('generic 404');
  // only the hash is stored — the raw token appears exactly once
  const rows = await doSql('SELECT token_hash FROM fcp_tokens WHERE id=?', minted.token_id);
  expect(rows[0].token_hash).toBe(sha256(minted.token));
  expect(rows[0].token_hash).not.toBe(minted.token);

  // ── page ────────────────────────────────────────────────────────────────
  const page = await pubGet(`/object/${minted.token}`, '203.0.113.10');
  expect(page.status).toBe(200);
  expect(page.headers.get('content-type')).toBe('text/html; charset=utf-8');
  const html = await page.text();
  expect(html).toContain('<b>lifecycle v7</b>');
  expect(html).toContain('Invitation for: <b>Dana Q.</b>');
  expect(html).toContain(`<code>${promo.closes_at}</code>`);
  expect(html).toContain('Pinned evidence content_hash:');
  expect(html).toContain(JSON.stringify(minted.token)); // the fetch target, _js-embedded

  // ── file ────────────────────────────────────────────────────────────────
  const objBody = 'I object: the eval set is too small.';
  const filed = await fileObjection(minted.token, { body: objBody, label: 'Dana' }, '203.0.113.11');
  expect(filed.status).toBe(200);
  const receipt = await filed.json();
  expect(receipt.body_hash).toBe('sha256:' + sha256(objBody));
  expect(receipt.status_url).toBe(
    `${BASE}/object/${minted.token}/status/${receipt.objection_id}`);

  // use burned: a second file on use_limit=1 answers the generic 404 bytes
  const second = await fileObjection(minted.token, {}, '203.0.113.12');
  expect(second.status).toBe(404);
  expect(await second.text()).toBe(GENERIC_404_JSON);

  // ── status: filed ───────────────────────────────────────────────────────
  const statusPath = `/object/${minted.token}/status/${receipt.objection_id}`;
  let status = await (await pubGet(statusPath, '203.0.113.13')).json();
  expect(status).toEqual({
    objection_id: receipt.objection_id,
    body_hash: receipt.body_hash,
    promotion_state: 'open',
    status: 'filed',
    sealed: false,
  });

  // ── revoke: filing dies, the receipt survives (POLICY DECIDED) ─────────
  const revoked = await (await opPost(
    `/api/promotions/${promo.id}/tokens/${minted.token_id}/revoke`)).json();
  expect(revoked).toEqual({
    revoked: true,
    token_id: minted.token_id,
    promotion_id: promo.id,
  });
  const pageAfterRevoke = await pubGet(`/object/${minted.token}`, '203.0.113.14');
  expect(pageAfterRevoke.status).toBe(404);
  const statusAfterRevoke = await pubGet(statusPath, '203.0.113.15');
  expect(statusAfterRevoke.status).toBe(200); // still readable
  expect((await statusAfterRevoke.json()).status).toBe('filed');

  // ── close is blocked while an objection is unresolved ──────────────────
  await elapseWindow(promo.id);
  const blockedClose = await opPost(`/api/promotions/${promo.id}/close`);
  expect(blockedClose.status).toBe(409);
  expect((await blockedClose.json()).error).toBe(
    '1 unresolved objection(s) block close');

  // ── resolve responded ───────────────────────────────────────────────────
  const resolved = await opPost(
    `/api/promotions/${promo.id}/objections/${receipt.objection_id}/resolve`,
    { resolution: 'responded', body: 'Sample size documented in the eval.' });
  expect(resolved.status).toBe(200);
  const afterResolve = await resolved.json();
  expect(afterResolve.state).toBe('open');
  expect(afterResolve.unresolved_objections).toBe(0);
  // the operator view carries the hub attribution, never only the contact
  expect(afterResolve.objections[0].author_display_name).toBe('Dana Q.');
  expect(afterResolve.objections[0].author_threadhub_id).toMatch(/^id_stub_/);

  // ── close ───────────────────────────────────────────────────────────────
  const closed = await (await opPost(`/api/promotions/${promo.id}/close`)).json();
  expect(closed.state).toBe('closed');
  expect(closed.resolved_at).toBeTruthy();

  // ── sealed-records: mismatch is 409 and writes NOTHING ─────────────────
  const mismatch = await opPost(`/api/promotions/${promo.id}/sealed-records`, {
    slug: 'fcp-lifecycle-v7',
    records: [
      { record_hash: 'sha256:' + 'a'.repeat(64), event_type: 'ObjectionRaised' },
      { record_hash: 'sha256:' + 'b'.repeat(64), event_type: 'ObjectionRaised' },
    ],
  });
  expect(mismatch.status).toBe(409);
  const mismatchError = (await mismatch.json()).error;
  expect(mismatchError).toContain('back-fill count mismatch');
  expect(mismatchError).toContain("thread 'fcp-lifecycle-v7'");
  const unbackfilled = await doSql(
    'SELECT sealed_record_hash FROM promotion_objections WHERE id=?',
    receipt.objection_id);
  expect(unbackfilled[0].sealed_record_hash).toBeNull(); // zero writes

  // ── sealed-records: the matched back-fill ───────────────────────────────
  const recordHash = 'sha256:' + 'c'.repeat(64);
  const backfilled = await opPost(`/api/promotions/${promo.id}/sealed-records`, {
    slug: 'fcp-lifecycle-v7',
    records: [
      { record_hash: 'sha256:' + 'd'.repeat(64), event_type: 'PromotionDecided' },
      { record_hash: recordHash, event_type: 'ObjectionRaised' },
    ],
  });
  expect(backfilled.status).toBe(200);
  expect(await backfilled.json()).toEqual({ backfilled: 1, promotion_id: promo.id });

  // ── seal-result ─────────────────────────────────────────────────────────
  const citation = 'sha256:' + 'e'.repeat(64);
  const sealed = await (await opPost(`/api/promotions/${promo.id}/seal-result`, {
    slug: 'fcp-lifecycle-v7',
    citation_hash: citation,
  })).json();
  expect(sealed.sealed).toBe(1);
  expect(sealed.seal_error).toBeNull();
  expect(sealed.thread_slug).toBe('fcp-lifecycle-v7');

  // ── status: the full sealed receipt (still on the revoked token) ───────
  status = await (await pubGet(statusPath, '203.0.113.16')).json();
  expect(status.status).toBe('sealed');
  expect(status.promotion_state).toBe('closed');
  expect(status.record_hash).toBe(recordHash);
  expect(status.thread_slug).toBe('fcp-lifecycle-v7');
  expect(status.citation_hash).toBe(citation);
  expect(status.record_url).toBe(`${HUB_BASE}/r/${recordHash}`);
  expect(status.verify_url).toBe(`${HUB_BASE}/t/fcp-lifecycle-v7/verify`);
  expect(status.checker_url).toBe(`${HUB_BASE}/verify.mjs`);
  // custody names the ACTUAL custodial identity — display name + hub id,
  // never the contact
  expect(status.custody).toContain("CUSTODIAL identity 'Dana Q.'");
  expect(status.custody).toContain('hub identity id_stub_');
  expect(status.custody).not.toContain('skeptic@example.org');
  expect(status.instructions).toContain('Verify this objection yourself');
  expect(status.instructions).toContain(`curl -o verify.mjs ${HUB_BASE}/verify.mjs`);
  expect(status.instructions).toContain(citation);
  expect(status.instructions).toContain(recordHash);
  expect(status.instructions).not.toContain('skeptic@example.org');
});

it('records a seal FAILURE as bookkeeping, never a crash (seal-result {error})', async () => {
  const promo = await openPromotion();
  await opPost(`/api/promotions/${promo.id}/abort`);
  const res = await opPost(`/api/promotions/${promo.id}/seal-result`, {
    error: 'gate.py refused: anchors out of date',
  });
  expect(res.status).toBe(200);
  const p = await res.json();
  expect(p.sealed).toBe(0);
  expect(p.seal_error).toBe('gate.py refused: anchors out of date');
  expect(p.state).toBe('aborted');
});

it('mint responses never appear in later reads (raw token shown exactly once)', async () => {
  const promo = await openPromotion();
  const minted = await mintToken(promo.id);
  const listed = await (await opGet(`/api/promotions/${promo.id}`)).json();
  expect(JSON.stringify(listed)).not.toContain(minted.token);
});
