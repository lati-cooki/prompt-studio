// page-render.test.js — the standalone objection page (render_object_page
// port). The doorstep deliberation link renders ONLY when the cited thread
// is effectively published on the hub (stub isPublished true); when it is
// unpublished OR the hub check throws, the page renders NOTHING there and
// is BYTE-IDENTICAL to a promotion with no association at all. All
// user-derived strings are escaped with Python html.escape parity
// (&#x27; not &#39;).
import { it, expect, beforeEach } from 'vitest';
import { HUB_BASE, pubGet, openPromotion, mintToken, doSql, resetStudio } from './helpers.js';

beforeEach(resetStudio);

const setSlug = (pid, slug) =>
  doSql('UPDATE promotions SET deliberation_slug=? WHERE id=?', slug, pid);

it('renders the promotion, window, evidence hash and the filing form', async () => {
  const p = await openPromotion({ prompt_id: 'greeter', version: 'v9' });
  const t = await mintToken(p.id, { invitee_label: 'Dana' });
  const html = await (await pubGet(`/object/${t.token}`, '203.0.113.30')).text();
  expect(html).toContain('<title>Objection — greeter v9</title>');
  expect(html).toContain('<b>greeter v9</b>');
  expect(html).toContain('Invitation for: <b>Dana</b>');
  expect(html).toContain(`<code>${p.closes_at}</code>`);
  expect(html).toContain('Pinned evidence content_hash:');
  expect(html).toContain('<textarea name="body" required>');
  // the inline fetch targets the raw token, _js-embedded
  expect(html).toContain(`"/api/object/" + ${JSON.stringify(t.token)}`);
});

it('discloses evidence ABSENCE when the promotion carried none', async () => {
  const p = await openPromotion({ evidence: null });
  const t = await mintToken(p.id);
  const html = await (await pubGet(`/object/${t.token}`, '203.0.113.31')).text();
  expect(html).toContain('No pinned eval evidence is attached to this promotion');
  expect(html).not.toContain('Pinned evidence content_hash');
});

it('renders the deliberation link ONLY when the hub says the thread is published', async () => {
  const p = await openPromotion();
  const t = await mintToken(p.id);

  // Baseline: no association at all.
  await setSlug(p.id, null);
  const htmlNone = await (await pubGet(`/object/${t.token}`, '203.0.113.32')).text();
  expect(htmlNone).not.toContain('Read the deliberation');

  // Unpublished association (stub isPublished false for non 'pub-' slugs):
  // renders NOTHING and is byte-identical to the unassociated page.
  await setSlug(p.id, 'priv-thread');
  const htmlPriv = await (await pubGet(`/object/${t.token}`, '203.0.113.33')).text();
  expect(htmlPriv).toBe(htmlNone);

  // Hub check THROWS (stub throws on 'huberr' slugs): fail closed —
  // still byte-identical to the unassociated page, no dead link, no slug
  // leakage.
  await setSlug(p.id, 'huberr-thread');
  const htmlErr = await (await pubGet(`/object/${t.token}`, '203.0.113.34')).text();
  expect(htmlErr).toBe(htmlNone);

  // Published (stub true for 'pub-' slugs): the link appears, and the page
  // is NO LONGER byte-identical to the unassociated one.
  await setSlug(p.id, 'pub-thread');
  const htmlPub = await (await pubGet(`/object/${t.token}`, '203.0.113.35')).text();
  expect(htmlPub).toContain('Read the deliberation');
  expect(htmlPub).toContain(`href="${HUB_BASE}/t/pub-thread/view"`);
  expect(htmlPub).not.toBe(htmlNone);
});

it('escapes hostile prompt_id and invitee_label with html.escape parity', async () => {
  const hostilePrompt = `p<script>evil</script>&"'`;
  const hostileLabel = `Dana<script>x</script>"'&`;
  const p = await openPromotion({ prompt_id: hostilePrompt, version: 'v1' });
  const t = await mintToken(p.id, { invitee_label: hostileLabel });
  const html = await (await pubGet(`/object/${t.token}`, '203.0.113.36')).text();

  // prompt_id escaped in both the title and the body — note &#x27; (Python
  // html.escape), NOT &#39;.
  expect(html).toContain('p&lt;script&gt;evil&lt;/script&gt;&amp;&quot;&#x27;');
  expect(html).not.toContain('<script>evil</script>'); // the hostile tag never lands raw
  // invitee_label escaped in the greeting.
  expect(html).toContain('Invitation for: <b>Dana&lt;script&gt;x&lt;/script&gt;&quot;&#x27;&amp;</b>');
  // the single-quote entity is the hex form, never the decimal one.
  expect(html).not.toContain('&#39;');
});
