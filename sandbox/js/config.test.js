import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { getActiveModelKey, DEFAULT_MODEL_KEY } from './config.js';

describe('getActiveModelKey', () => {
  let originalLocalStorage;

  beforeEach(() => {
    originalLocalStorage = global.localStorage;
  });

  afterEach(() => {
    global.localStorage = originalLocalStorage;
  });

  it('returns default model when localStorage returns null', () => {
    global.localStorage = {
      getItem: (key) => null
    };
    assert.equal(getActiveModelKey(), DEFAULT_MODEL_KEY);
  });

  it('returns saved model when localStorage returns a valid model', () => {
    global.localStorage = {
      getItem: (key) => 'gpt-4o'
    };
    assert.equal(getActiveModelKey(), 'gpt-4o');
  });

  it('returns default model when localStorage returns an invalid model', () => {
    global.localStorage = {
      getItem: (key) => 'non-existent-model'
    };
    assert.equal(getActiveModelKey(), DEFAULT_MODEL_KEY);
  });

  it('returns default model when localStorage throws an exception', () => {
    global.localStorage = {
      getItem: (key) => { throw new Error('localStorage is disabled'); }
    };
    assert.equal(getActiveModelKey(), DEFAULT_MODEL_KEY);
  });

  it('returns default model when global.localStorage is undefined', () => {
    delete global.localStorage;
    assert.equal(getActiveModelKey(), DEFAULT_MODEL_KEY);
  });
});
