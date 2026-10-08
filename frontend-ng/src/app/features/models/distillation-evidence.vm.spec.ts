import assert from 'node:assert/strict';
import { test } from 'node:test';
import { distillationValue } from './distillation-evidence.vm';

test('missing or invalid evidence is unavailable, while an explicit zero remains evidence', () => {
  for (const value of [null, undefined, NaN, Infinity, -1, '0']) assert.equal(distillationValue(value), null);
  assert.equal(distillationValue(0), 0);
  assert.equal(distillationValue(0.9, 1), 0.9);
  assert.equal(distillationValue(1.2, 1), null);
  assert.equal(distillationValue(1.2), 1.2);
});
