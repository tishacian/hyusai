import test from 'node:test';
import assert from 'node:assert/strict';
import { qualitySample } from './quality-sample';

test('quality mean uses observed denominator and preserves a measured zero', () => {
  assert.deepEqual(qualitySample([{ value: 0, count: 10 }, { value: 1, count: 30 }, { value: null, count: 100 }]), { value: .75, count: 40, limited: false });
});
test('a missing denominator cannot substantiate a percentage', () => {
  assert.deepEqual(qualitySample([{ value: .4, count: undefined }, { value: .5, count: 0 }]), { value: null, count: 0, limited: false });
});
test('the quality reservation applies below thirty observations', () => {
  assert.equal(qualitySample([{ value: 0, count: 29 }]).limited, true);
  assert.equal(qualitySample([{ value: 0, count: 30 }]).limited, false);
});
