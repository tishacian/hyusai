import type { UsageRateKey, UsageTariffProvenance, UsageTariffWrite } from './usage.models';
export const TARIFF_RATE_KEYS: UsageRateKey[] = ['input_per_million', 'output_per_million', 'cached_input_per_million', 'cache_write_per_million'];
export interface TariffProvenanceDraft {
  reference: string; observedOn: string; conversionEnabled: boolean; sourceCurrency: string;
  rate: string; rateReference: string; rateObservedOn: string; sourceRates: Record<UsageRateKey, string>;
}
export function tariffProvenanceDraft(): TariffProvenanceDraft {
  return { reference: '', observedOn: '', conversionEnabled: false, sourceCurrency: '', rate: '', rateReference: '', rateObservedOn: '',
    sourceRates: { input_per_million: '', output_per_million: '', cached_input_per_million: '', cache_write_per_million: '' } };
}
function decimalText(value: unknown): string { return String(value ?? '').trim().replace(',', '.'); }
function fixedDecimal(value: unknown): bigint {
  const text = decimalText(value), parsed = /^(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(text);
  if (text.length > 100 || !parsed || Math.abs(Number(parsed[3] || 0)) > 40) throw new Error('USAGE_TARIFF_PROVENANCE_INVALID');
  let coefficient = BigInt(parsed[1] + (parsed[2] || ''));
  const scale = (parsed[2] || '').length - Number(parsed[3] || 0);
  if (scale > 12) coefficient = halfEven(coefficient, 10n ** BigInt(scale - 12));
  else coefficient *= 10n ** BigInt(12 - scale);
  if (coefficient > 100000000000000000000000n) throw new Error('USAGE_TARIFF_PROVENANCE_INVALID');
  return coefficient;
}
function halfEven(value: bigint, divisor: bigint): bigint {
  const remainder = value % divisor, integer = value / divisor;
  return remainder * 2n > divisor || (remainder * 2n === divisor && integer % 2n === 1n) ? integer + 1n : integer;
}
/** Exact decimal arithmetic, using the server's declared half-even 12-place convention. No rate lookup. */
export function convertedTariffRate(source: unknown, rate: unknown): string {
  const left = fixedDecimal(source), right = fixedDecimal(rate);
  if (right <= 0n) throw new Error('USAGE_TARIFF_PROVENANCE_INVALID');
  const result = halfEven(left * right, 1000000000000n);
  if (result > 100000000000000000000000n) throw new Error('USAGE_TARIFF_PROVENANCE_INVALID');
  const text = result.toString().padStart(13, '0');
  return (text.slice(0, -12) + '.' + text.slice(-12)).replace(/\.?0+$/, '') || '0';
}
function validDate(value: string): boolean { return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number(value.slice(0, 4)) > 0 && new Date(value).toISOString().slice(0, 10) === value; }
function validReference(value: string): boolean { return value.trim().length > 0 && value.trim().length <= 500; }
export function declaredConversionRates(draft: TariffProvenanceDraft, target: UsageTariffWrite): Partial<Record<UsageRateKey, string>> {
  if (!draft.conversionEnabled || !/^[A-Z]{3}$/.test(target.currency.trim().toUpperCase()) || !/^[A-Z]{3}$/.test(draft.sourceCurrency.trim().toUpperCase()) || draft.sourceCurrency.trim().toUpperCase() === target.currency.trim().toUpperCase()) throw new Error('USAGE_TARIFF_PROVENANCE_INVALID');
  return Object.fromEntries(TARIFF_RATE_KEYS.filter(key => key === 'input_per_million' || key === 'output_per_million' || (target[key] !== '' && target[key] != null) || draft.sourceRates[key] !== '').map(key => [key, convertedTariffRate(draft.sourceRates[key], draft.rate)]));
}
export function validateTariffProvenance(draft: TariffProvenanceDraft, target: UsageTariffWrite): { provenance?: UsageTariffProvenance; error?: string } {
  if (!draft.reference.trim() && !draft.observedOn && !draft.conversionEnabled) return {};
  try {
    if (!validReference(draft.reference) || !validDate(draft.observedOn)) return { error: 'USAGE_TARIFF_PROVENANCE_INVALID' };
    const provenance: UsageTariffProvenance = { reference: draft.reference.trim(), observed_on: draft.observedOn };
    if (draft.conversionEnabled) {
      if (!validReference(draft.rateReference) || !validDate(draft.rateObservedOn)) return { error: 'USAGE_TARIFF_PROVENANCE_INVALID' };
      const calculated = declaredConversionRates(draft, target), keys = TARIFF_RATE_KEYS.filter(key => target[key] !== undefined && target[key] !== '');
      if (Object.keys(calculated).length !== keys.length || keys.some(key => convertedTariffRate(target[key], '1') !== calculated[key])) return { error: 'USAGE_TARIFF_CONVERSION_MISMATCH' };
      provenance.conversion = { source_currency: draft.sourceCurrency.trim().toUpperCase(), source_rates: Object.fromEntries(keys.map(key => [key, decimalText(draft.sourceRates[key])])), rate: decimalText(draft.rate), reference: draft.rateReference.trim(), observed_on: draft.rateObservedOn, convention: 'target_per_source', rounding: 'half_even_12dp' };
    }
    return { provenance };
  } catch { return { error: 'USAGE_TARIFF_PROVENANCE_INVALID' }; }
}
