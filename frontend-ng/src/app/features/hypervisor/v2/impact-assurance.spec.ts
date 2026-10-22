import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assuranceTraffic, knownSpend, qualityPassFraction, type AssuranceQuality, type AssuranceUsage } from './impact-assurance';
test('all technical failures leave business quality unassessed, never zero or perfect', () => {
  assert.equal(qualityPassFraction({totals:{assessed:0, passed:0, technical_failures:9}} as AssuranceQuality), null);
  assert.equal(qualityPassFraction({totals:{assessed:4, passed:3, technical_failures:2}} as AssuranceQuality), .75);
});
test('spend retains real zero and separate currencies, excludes unavailable pricing', () => {
  assert.deepEqual(knownSpend({costs:[
    {currency:'USD',known_amount:'0.33',known_calls:3}, {currency:'EUR',known_amount:0,known_calls:1},
    {currency:'GBP',known_amount:null,known_calls:0}, {currency:'CAD',known_amount:0,known_calls:0},
  ]} as AssuranceUsage), [{currency:'USD',amount:.33},{currency:'EUR',amount:0}]);
});
test('Impact excludes QA by default, while configured QA and combined scopes remain explicit', () => {
  assert.equal(assuranceTraffic({}), 'business');
  assert.equal(assuranceTraffic({traffic:'evaluation'}), 'evaluation');
  assert.equal(assuranceTraffic({traffic:'all'}), 'all');
  assert.equal(assuranceTraffic({traffic:'forged'}), 'business');
});
