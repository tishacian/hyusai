import { convertedTariffRate, declaredConversionRates, tariffProvenanceDraft, validateTariffProvenance } from './tariff-provenance.vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { budgetAvailable, budgetDraft, budgetPercent, usageAmount, usageBreakdown, usageChartMaximum, usageCostCoverage, usageNumber, usageQuery, usageSeriesValues, validateBudgetDraft } from './usage.vm';
import type { UsageSeries, UsageSummary } from './usage.models';
import { OBSERVABILITY_FR, OBSERVABILITY_EN } from '../../../core/i18n/observability.dict';

const summary: UsageSummary = {
  counts: { calls: 4, dispatched: 3, completed: 2, failed: 1, unknown: 0, blocked: 1 },
  tokens: { input: 0, output: 10, total: 10, cached_input: null, cache_write: null, reasoning: null, known_calls: 2, unknown_calls: 1 },
  costs: [{ currency: 'USD', known_amount: '0', known_calls: 1, unknown_calls: 1, basis: 'provider_tokens_at_versioned_tariff' },
    { currency: 'EUR', known_amount: '2.15', known_calls: 1, unknown_calls: 0, basis: 'provider_tokens_at_versioned_tariff' }],
  groups: [], coverage: { mode: 'complete_retained_calls', complete: true, scanned: 4, limit: 20_000 },
};
test('usage formatting keeps unknown distinct from zero and currency identity in both locales', () => {
  for (const locale of ['fr', 'en']) {
    assert.equal(usageNumber(null, locale), '—');
    assert.equal(usageNumber(0, locale), '0');
    assert.equal(usageAmount(null, 'USD', locale), '—');
    assert.notEqual(usageAmount('0', 'USD', locale), '—');
    assert.notEqual(usageAmount('1', 'USD', locale), usageAmount('1', 'EUR', locale));
  }
  assert.equal(usageAmount('not-a-number', 'USD'), '—');
  assert.deepEqual(usageCostCoverage(summary), { known: 2, total: 3 });
});
test('cost and token series preserve unmeasured gaps, including zero-priced tariffs', () => {
  const unknown = structuredClone(summary); unknown.tokens.known_calls = 0; unknown.tokens.total = null;
  unknown.costs = [{ currency: 'USD', known_amount: null, known_calls: 0, unknown_calls: 3, basis: 'provider_tokens_at_versioned_tariff' }];
  const series: UsageSeries = { timezone: 'UTC', buckets: [{ ...summary, date: '2026-10-21' }, { ...unknown, date: '2026-10-22' }] };
  assert.deepEqual(usageSeriesValues(series, 'USD').map(item => item.value), [0, null]);
  assert.deepEqual(usageSeriesValues(series, 'EUR').map(item => item.value), [2.15, null]);
  assert.deepEqual(usageSeriesValues(series, 'tokens').map(item => item.value), [10, null]);
});
test('usage chart scale is readable for small costs and large token counts without replacing unknown values', () => {
  assert.equal(usageChartMaximum([null, 0]), 1);
  assert.equal(usageChartMaximum([19, 2, null]), 20);
  assert.equal(usageChartMaximum([0.33, 0]), 0.5);
  assert.equal(usageChartMaximum([21432, 500]), 50000);
});
test('grouping never combines monetary currencies or invents a price for unpriced groups', () => {
  const result = usageBreakdown([
    { provider: 'provider-a', model: 'one', purpose: 'judge', calls: 2, total_tokens: 10, currency: 'USD', known_amount: '1.5' },
    { provider: 'provider-a', model: 'one', purpose: 'judge', calls: 1, total_tokens: null, currency: 'EUR', known_amount: '2' },
    { provider: 'provider-b', model: 'one', purpose: 'judge', calls: 1, total_tokens: null, currency: 'USD', known_amount: null },
  ], 'provider');
  assert.equal(result[0].calls, 3);
  assert.deepEqual(result[0].costs, [{ currency: 'USD', amount: 1.5 }, { currency: 'EUR', amount: 2 }]);
  assert.equal(result[1].tokens, null); assert.deepEqual(result[1].costs, []);
});
test('budget balances include reservations, preserve overspend and never substitute an absent limit', () => {
  assert.equal(budgetAvailable('10', '5', '2'), 3);
  assert.equal(budgetAvailable('10', '9', '2'), -1);
  assert.equal(budgetAvailable(null, '0', '0'), null);
  assert.equal(budgetPercent('10', '9', '2'), 100);
});
test('budget editing requires explicit limits, separate currencies and an IANA monthly timezone', () => {
  const draft = budgetDraft();
  assert.equal(validateBudgetDraft(draft, false, 0).error, 'limit_required');
  draft.tokenLimit = '0';
  assert.equal(validateBudgetDraft(draft, false, 0).body?.enabled, false);
  assert.equal(validateBudgetDraft(draft, true, 7).body?.expected_revision, 7);
  draft.timezone = 'Europe/Paris'; assert.ok(validateBudgetDraft(draft, false, 0).body);
  draft.timezone = 'invented'; assert.equal(validateBudgetDraft(draft, false, 0).error, 'timezone_invalid');
  draft.timezone = 'UTC'; draft.scope = 'system'; assert.equal(validateBudgetDraft(draft, false, 0).error, 'system_required');
  draft.systemId = 'system-a'; draft.currencies = [{ currency: 'usd', limit: '10' }, { currency: 'USD', limit: '20' }];
  assert.equal(validateBudgetDraft(draft, false, 0).error, 'currency_duplicate');
  draft.currencies.pop(); draft.tokenLimit = '-1'; assert.equal(validateBudgetDraft(draft, false, 0).error, 'limit_invalid');
  draft.tokenLimit = '100.5'; assert.equal(validateBudgetDraft(draft, false, 0).error, 'limit_invalid');
});
test('filter transport preserves anchored population and encodes provider/model values', () => {
  const query = new URLSearchParams(usageQuery({ traffic: 'evaluation', window: '90d', as_of: '2026-10-22T12:00:00Z', model: 'x&traffic=business', offset: 0 }));
  assert.equal(query.get('traffic'), 'evaluation'); assert.equal(query.get('model'), 'x&traffic=business'); assert.equal(query.get('offset'), '0');
  assert.equal(query.get('window'), '90d'); assert.equal(query.has('run_id'), false);
});
test('all usage keys have non-empty French and English translations', () => {
  const keys = Object.keys(OBSERVABILITY_FR).filter(key => key.startsWith('observability.usage.')) as Array<keyof typeof OBSERVABILITY_FR>;
  assert.ok(keys.length > 100);
  for (const key of keys) { assert.ok(OBSERVABILITY_FR[key].trim(), key); assert.ok(OBSERVABILITY_EN[key].trim(), key); }
});

test('tariff provenance is optional for historical payloads and never silently converts amounts', () => {
  const draft = tariffProvenanceDraft(), target = { provider: 'provider', model: 'model', currency: 'EUR', input_per_million: '1', output_per_million: '4' };
  assert.deepEqual(validateTariffProvenance(draft, target), {});
  draft.reference = 'Published price';
  assert.equal(validateTariffProvenance(draft, target).error, 'USAGE_TARIFF_PROVENANCE_INVALID');
  draft.observedOn = '2026-10-22';
  assert.deepEqual(validateTariffProvenance(draft, target), { provenance: { reference: 'Published price', observed_on: '2026-10-22' } });
  assert.equal(target.input_per_million, '1');
  draft.observedOn = '2026-02-30';
  assert.equal(validateTariffProvenance(draft, target).error, 'USAGE_TARIFF_PROVENANCE_INVALID');
});
test('declared conversion uses decimal arithmetic and the same half-even precision as the server', () => {
  assert.equal(convertedTariffRate('1.25', '0.92'), '1.15');
  assert.equal(convertedTariffRate('0E-12', '0.92'), '0');
  assert.equal(convertedTariffRate('1E-12', '0.5'), '0');
  assert.equal(convertedTariffRate('3E-12', '0.5'), '0.000000000002');
  assert.equal(convertedTariffRate('0.1', '0.2'), '0.02');
  assert.equal(convertedTariffRate('1.0000000000005', '1'), '1');
  assert.equal(convertedTariffRate('1.25', '0,92'), '1.15');
  assert.throws(() => convertedTariffRate('1', '0'));
  assert.throws(() => convertedTariffRate('1', 'NaN'));
});
test('conversion provenance binds the exact entered rates, preserves zero cache rates and refuses stale conversions', () => {
  const draft = tariffProvenanceDraft();Object.assign(draft, { reference: 'Provider pricing', observedOn: '2026-10-22', conversionEnabled: true, sourceCurrency: 'USD', rate: '0,92', rateReference: 'Treasury convention', rateObservedOn: '2026-10-21' });
  draft.sourceRates.input_per_million = '1.25'; draft.sourceRates.output_per_million = '10'; draft.sourceRates.cached_input_per_million = '0';
  const target = { provider: 'provider', model: 'model', currency: 'EUR', input_per_million: '1.15', output_per_million: '9.2', cached_input_per_million: '0' };
  assert.deepEqual(declaredConversionRates(draft, target), { input_per_million: '1.15', output_per_million: '9.2', cached_input_per_million: '0' });
  const valid = validateTariffProvenance(draft, target);assert.equal(valid.error, undefined);assert.equal(valid.provenance?.conversion?.rate, '0.92');
  assert.equal(valid.provenance?.conversion?.source_rates.cached_input_per_million, '0');assert.equal('cache_write_per_million' in valid.provenance!.conversion!.source_rates, false);
  target.input_per_million = '1.16';assert.equal(validateTariffProvenance(draft, target).error, 'USAGE_TARIFF_CONVERSION_MISMATCH');assert.equal(target.input_per_million, '1.16');
  draft.sourceCurrency = 'EUR';assert.equal(validateTariffProvenance(draft, target).error, 'USAGE_TARIFF_PROVENANCE_INVALID');
});

test('a positive sub-micro currency cost never appears as a free call in French or English', () => {
  for (const locale of ['fr','en']) {
    const tiny=usageAmount('0.00000038','USD',locale),zero=usageAmount('0','USD',locale);
    assert.ok(tiny.startsWith('< '));assert.ok(tiny.includes(locale==='fr'?'0,000001':'0.000001'));assert.notEqual(tiny,zero);assert.equal(zero.startsWith('< '),false);
    assert.equal(usageAmount('0.000001','USD',locale).startsWith('< '),false);assert.equal(usageAmount(null,'USD',locale),'—');
  }
});
