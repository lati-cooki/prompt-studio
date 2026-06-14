import { test } from 'node:test';
import assert from 'node:assert';
import { EXTRACTION_PROMPT, buildExtractionMessages, parseExtraction } from './seal-extract.js';

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
