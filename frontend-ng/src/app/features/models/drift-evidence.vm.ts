import type { DriftFeature, DriftTest, DriftTestReason } from './models.vm';

const REASONS: ReadonlySet<string> = new Set<DriftTestReason>([
  'reference_unavailable', 'insufficient_samples', 'sparse_categories', 'high_cardinality', 'unsupported_type',
]);

export interface DriftTestRow {
  name: string;
  method: DriftTest['method'];
  status: DriftTest['status'];
  statistic: number | null;
  adjustedP: number | null;
  referenceCount: number | null;
  currentCount: number | null;
  reason: DriftTestReason | null;
}

function nonnegative(value: unknown, maximum = Number.POSITIVE_INFINITY): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= maximum ? value : null;
}

/** Project server evidence without inventing significance for an old reference. */
export function driftTestRows(features: readonly DriftFeature[] | undefined): DriftTestRow[] {
  return (features ?? []).filter(feature => !!feature.name).map(feature => {
    const test = feature.test;
    const method = test?.method === 'ks' || test?.method === 'chi2' ? test.method : null;
    const reason = test?.reason && REASONS.has(test.reason) ? test.reason : null;
    const measured = !!test && !!method && !reason && test.status !== 'unknown';
    const adjustedP = measured ? nonnegative(test.p_value_adjusted, 1) : null;
    const valid = adjustedP !== null && nonnegative(test?.statistic) !== null;
    return {
      name: feature.name, method,
      status: valid && test && ['ok', 'watch', 'alert'].includes(test.status) ? test.status : 'unknown',
      statistic: valid ? nonnegative(test?.statistic) : null,
      adjustedP: valid ? adjustedP : null,
      referenceCount: Number.isInteger(test?.n_reference) ? nonnegative(test?.n_reference) : null,
      currentCount: Number.isInteger(test?.n_current) ? nonnegative(test?.n_current) : null,
      reason: reason ?? (!test ? 'reference_unavailable' : null),
    };
  });
}

/** Tiny nonzero p-values must not round to a displayed zero. */
export function driftNumber(value: number | null, locale: string): string {
  if (value === null) return '—';
  return new Intl.NumberFormat(locale, value > 0 && value < 0.001
    ? { notation: 'scientific', maximumFractionDigits: 2 }
    : { maximumFractionDigits: 4 }).format(value);
}
