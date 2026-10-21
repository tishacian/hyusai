export const MIN_QUALITY_SAMPLE = 30;
export interface QualitySample { value: number | null; count: number; limited: boolean; }

/** Pool bucket means using their actual observations, never all runs. */
export function qualitySample(buckets: ReadonlyArray<{ value: number | null | undefined; count: number | null | undefined }>): QualitySample {
  const observed = buckets.filter(bucket => typeof bucket.value === 'number' && Number.isFinite(bucket.value)
    && typeof bucket.count === 'number' && Number.isInteger(bucket.count) && bucket.count > 0);
  const count = observed.reduce((sum, bucket) => sum + bucket.count!, 0);
  return { value: count ? observed.reduce((sum, bucket) => sum + bucket.value! * bucket.count!, 0) / count : null,
    count, limited: count > 0 && count < MIN_QUALITY_SAMPLE };
}
