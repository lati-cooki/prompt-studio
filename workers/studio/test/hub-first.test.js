// hub-first.test.js — filing is hub-first: the objector identity is minted
// on the hub BEFORE anything is written locally, so a hub failure files
// NOTHING and does not burn the token's use. (objections.file_objection's
// mint-first, insert-after ordering.) The stub throws mintIdentity when the
// display_name contains 'HUBFAIL'.
import { it, expect, beforeEach } from 'vitest';
import {
  opGet,
  openPromotion,
  mintToken,
  fileObjection,
  doSql,
  resetStudio,
} from './helpers.js';

beforeEach(resetStudio);

it('a hub mintIdentity failure files nothing and does not burn the use', async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id, { use_limit: 1 });

  // display_name derives from the objector's label; 'HUBFAIL' makes the
  // stub reject the mint.
  const res = await fileObjection(
    t.token,
    { body: 'a real objection', contact: 'someone@example.org', label: 'HUBFAIL-user' },
    '203.0.113.50',
  );
  expect(res.status).toBe(502);
  expect((await res.json()).error).toContain('nothing was filed');

  // Nothing landed: no writer, no objection, and the use is NOT burned.
  const writers = await doSql('SELECT COUNT(*) AS n FROM objector_writers');
  expect(writers[0].n).toBe(0);
  const objections = await doSql('SELECT COUNT(*) AS n FROM promotion_objections');
  expect(objections[0].n).toBe(0);
  const token = await doSql('SELECT uses FROM fcp_tokens WHERE id=?', t.token_id);
  expect(token[0].uses).toBe(0);

  // The token still works once the hub recovers: a normal label mints and
  // files, burning the use.
  const ok = await fileObjection(
    t.token,
    { body: 'a real objection', contact: 'someone@example.org', label: 'Recovered' },
    '203.0.113.51',
  );
  expect(ok.status).toBe(200);
  const burned = await doSql('SELECT uses FROM fcp_tokens WHERE id=?', t.token_id);
  expect(burned[0].uses).toBe(1);
});

it('the minted objector identity carries only display_name + hub id — never the contact', async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  const filed = await fileObjection(
    t.token,
    { body: 'objection', contact: 'private@contact.example', label: 'Public Name' },
    '203.0.113.52',
  );
  expect(filed.status).toBe(200);

  // The contact lives ONLY in the writer NAME (objector:<contact>) inside
  // the DO — the operator IS its custodian, so the operator plane may see
  // it (parity with promotion_store.get_promotion, which returns
  // author_writer). The invariant is that the HUB-BOUND fields
  // (display_name, threadhub_id) never carry it.
  const writer = (await doSql('SELECT * FROM objector_writers'))[0];
  expect(writer.name).toBe('objector:private@contact.example'); // local-only
  expect(writer.display_name).toBe('Public Name');
  expect(writer.threadhub_id).toMatch(/^id_stub_/);
  expect(writer.display_name).not.toContain('private@contact.example');
  // The stub derives its id from display_name + kind ONLY (hub.js sends
  // exactly those two fields) — so the hub id cannot encode the contact.
  expect(writer.threadhub_id).not.toContain('private');

  const view = await (await opGet(`/api/promotions/${p.id}`)).json();
  const obj = view.objections[0];
  expect(obj.author_display_name).toBe('Public Name');
  expect(obj.author_threadhub_id).toMatch(/^id_stub_/);
  // token_id stored as the integer's decimal string, matching Python (not
  // a REAL-affinity "1.0").
  expect(obj.token_id).toBe(String(t.token_id));
});

it('a display name containing the contact is discarded (contact must not reach the hub)', async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);
  // The objector-chosen label IS their contact — it must be dropped and a
  // synthetic objector-N used instead, so the contact never becomes a
  // hub-bound display_name.
  await fileObjection(
    t.token,
    { body: 'x', contact: 'leak@example.com', label: 'leak@example.com' },
    '203.0.113.53',
  );
  const writer = (await doSql('SELECT * FROM objector_writers'))[0];
  expect(writer.display_name).toBe('objector-1');
  expect(writer.display_name).not.toContain('leak@example.com');
});
