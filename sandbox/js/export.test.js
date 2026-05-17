import { test } from 'node:test';
import assert from 'node:assert';
import { slugify } from './export.js';

test('slugify: normal string', () => {
  assert.strictEqual(slugify('Hello World'), 'hello-world');
});

test('slugify: trims leading and trailing non-alphanumerics', () => {
  assert.strictEqual(slugify('  Hello World  '), 'hello-world');
  assert.strictEqual(slugify('--Hello World--'), 'hello-world');
  assert.strictEqual(slugify('@@Hello World##'), 'hello-world');
});

test('slugify: replaces multiple non-alphanumerics with a single dash', () => {
  assert.strictEqual(slugify('Hello   World'), 'hello-world');
  assert.strictEqual(slugify('Hello@#$World'), 'hello-world');
});

test('slugify: truncates to 40 characters', () => {
  const longString = 'a'.repeat(50);
  assert.strictEqual(slugify(longString).length, 40);
  assert.strictEqual(slugify(longString), 'a'.repeat(40));
});

test('slugify: falls back to "prompt-sandbox" if empty after processing', () => {
  assert.strictEqual(slugify(''), 'prompt-sandbox');
  assert.strictEqual(slugify('@@@'), 'prompt-sandbox');
  assert.strictEqual(slugify('   '), 'prompt-sandbox');
});

test('slugify: edge cases (null, undefined, non-strings)', () => {
  assert.strictEqual(slugify(null), 'prompt-sandbox');
  assert.strictEqual(slugify(undefined), 'prompt-sandbox');
  assert.strictEqual(slugify(123), 'prompt-sandbox');
  assert.strictEqual(slugify({}), 'prompt-sandbox');
  assert.strictEqual(slugify([]), 'prompt-sandbox');
});
