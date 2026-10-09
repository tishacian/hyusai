import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shadowConfig, shadowErrorKey, shadowValue } from './shadow-evidence.vm';

test('configuration validates bounded integers and preserves explicit disable', () => {
  assert.deepEqual(shadowConfig(false, '100', '60'), { enabled: false, sample_percent: 100, timeout_s: 60 });
  assert.deepEqual(shadowConfig(true, '1', '1'), { enabled: true, sample_percent: 1, timeout_s: 1 });
  for (const [sample, timeout] of [['', '10'], ['0', '10'], ['101', '10'], ['1.5', '10'], ['10', '0'], ['10', '61'], ['10', '1.2']]) {
    assert.equal(shadowConfig(true, sample, timeout), null);
  }
});

test('unmeasured shadow evidence remains distinct from true zero in both languages', () => {
  for (const locale of ['fr', 'en']) {
    assert.equal(shadowValue(null, locale), null);
    assert.equal(shadowValue(undefined, locale), null);
    assert.equal(shadowValue(0, locale), '0');
    assert.match(shadowValue(0, locale, true)!, /^0\s?%$/);
    assert.match(shadowValue(1, locale, true)!, /^100\s?%$/);
    assert.equal(shadowValue(1.5, locale, true), null);
    assert.equal(shadowValue(Number.NaN, locale), null);
    assert.equal(shadowValue(-1, locale), null);
  }
});

test('public refusal codes have stable copy while unknown worker failures use a safe fallback', () => {
  assert.equal(shadowErrorKey('ML_SHADOW_FORBIDDEN'), 'models.shadow.error.forbidden');
  assert.equal(shadowErrorKey('ML_SHADOW_TIMEOUT'), 'models.shadow.error.timeout');
  assert.equal(shadowErrorKey('private path /srv/model'), 'models.shadow.error.failed');
});
