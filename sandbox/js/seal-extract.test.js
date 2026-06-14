import { test } from 'node:test';
import assert from 'node:assert';
import { EXTRACTION_PROMPT, buildExtractionMessages, parseExtraction, paneContext, runExtraction } from './seal-extract.js';

test('EXTRACTION_PROMPT mentions the four output keys', () => {
  for (const k of ['question', 'decision', 'evidence', 'objections']) {
    assert.ok(EXTRACTION_PROMPT.includes(k), `prompt missing ${k}`);
  }
});

test('buildExtractionMessages: system prompt + rendered transcript', () => {
  const msgs = buildExtractionMessages([
    { role: 'user', content: 'Should we ship?' },
    { role: 'assistant', content: 'Ship to redacted only.' },
  ]);
  assert.strictEqual(msgs.length, 2);
  assert.strictEqual(msgs[0].role, 'system');
  assert.strictEqual(msgs[0].content, EXTRACTION_PROMPT);
  assert.strictEqual(msgs[1].role, 'user');
  assert.ok(msgs[1].content.includes('Should we ship?'));
  assert.ok(msgs[1].content.includes('Ship to redacted only.'));
});

test('buildExtractionMessages: tolerates non-array / non-string content', () => {
  const msgs = buildExtractionMessages(null);
  assert.strictEqual(msgs.length, 2);
  assert.strictEqual(msgs[1].role, 'user');
});

test('parseExtraction: clean JSON', () => {
  const out = parseExtraction('{"question":"Q","decision":"D","evidence":[{"source":"s","finding":"f"}],"objections":[{"text":"o"}]}');
  assert.deepStrictEqual(out, {
    question: 'Q', decision: 'D',
    evidence: [{ source: 's', finding: 'f' }],
    objections: [{ text: 'o' }],
  });
});

test('parseExtraction: JSON inside a markdown fence', () => {
  const out = parseExtraction('```json\n{"question":"Q","decision":"D","evidence":[],"objections":[]}\n```');
  assert.strictEqual(out.question, 'Q');
  assert.deepStrictEqual(out.evidence, []);
});

test('parseExtraction: JSON after a reasoning preamble', () => {
  const out = parseExtraction('Let me think... the question is clear.\n\n{"question":"Q","decision":"D","evidence":[],"objections":[]}');
  assert.strictEqual(out.decision, 'D');
});

test('parseExtraction: missing keys default to empty', () => {
  const out = parseExtraction('{"question":"Q"}');
  assert.strictEqual(out.decision, '');
  assert.deepStrictEqual(out.evidence, []);
  assert.deepStrictEqual(out.objections, []);
});

test('parseExtraction: drops malformed evidence/objection items', () => {
  const out = parseExtraction('{"evidence":["bad",{"source":"s","finding":"f"},{"source":"","finding":""}],"objections":["plain", {"text":"t"}, {"text":""}]}');
  assert.deepStrictEqual(out.evidence, [{ source: 's', finding: 'f' }]);
  assert.deepStrictEqual(out.objections, [{ text: 'plain' }, { text: 't' }]);
});

test('parseExtraction: garbage throws', () => {
  assert.throws(() => parseExtraction('no json here'));
  assert.throws(() => parseExtraction(''));
});

test('parseExtraction: braces inside a string value do not end the object', () => {
  const out = parseExtraction('{"question":"Q","decision":"Rejected {see note}","evidence":[],"objections":[]}');
  assert.strictEqual(out.decision, 'Rejected {see note}');
});

test('parseExtraction: skips a balanced {...} in prose before the real object', () => {
  const out = parseExtraction('Template: {"key":"val"} was used.\n{"question":"Q","decision":"D","evidence":[],"objections":[]}');
  assert.strictEqual(out.question, 'Q');
  assert.strictEqual(out.decision, 'D');
});

test('paneContext: empty map → null model, empty messages', () => {
  assert.deepStrictEqual(paneContext({}, {}), { model: null, messages: [] });
});

test('paneContext: first pane model + messages copy', () => {
  const map = { gemma: { state: { messages: [{ role: 'user', content: 'hi' }] } } };
  const models = { gemma: { id: 'gemma', provider: 'lmstudio' } };
  const ctx = paneContext(map, models);
  assert.strictEqual(ctx.model.id, 'gemma');
  assert.deepStrictEqual(ctx.messages, [{ role: 'user', content: 'hi' }]);
  assert.notStrictEqual(ctx.messages, map.gemma.state.messages);
});

test('runExtraction: lmstudio non-streaming returns content', async () => {
  const fakeFetch = async (url, opts) => {
    const body = JSON.parse(opts.body);
    assert.strictEqual(body.stream, false);
    return { ok: true, json: async () => ({ choices: [{ message: { content: '{"question":"Q"}' } }] }) };
  };
  const out = await runExtraction({ id: 'g', provider: 'lmstudio', endpoint: 'http://x/v1/chat/completions' },
    [{ role: 'user', content: 'hi' }], fakeFetch);
  assert.strictEqual(out, '{"question":"Q"}');
});

test('runExtraction: lmstudio falls back to reasoning when content empty', async () => {
  const fakeFetch = async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: '', reasoning: 'R' } }] }) });
  const out = await runExtraction({ id: 'g', provider: 'lmstudio', endpoint: 'http://x' }, [], fakeFetch);
  assert.strictEqual(out, 'R');
});

test('runExtraction: non-ok response throws', async () => {
  const fakeFetch = async () => ({ ok: false, status: 500 });
  await assert.rejects(() => runExtraction({ provider: 'lmstudio', endpoint: 'http://x' }, [], fakeFetch));
});
