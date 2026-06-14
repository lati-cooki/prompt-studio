import { test } from 'node:test';
import assert from 'node:assert';
import { EXTRACTION_PROMPT, buildExtractionMessages } from './seal-extract.js';

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
