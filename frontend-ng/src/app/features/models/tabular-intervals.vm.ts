import type { IntervalEvidence, PredictionRow } from './models.vm';

export function intervalEvidence(value: IntervalEvidence | null | undefined): IntervalEvidence | null {
  if (!value?.levels?.length) return null;
  const levels = value.levels.filter(row =>
    [row.level, row.q, row.coverage, row.width].every(Number.isFinite) &&
    row.level > 0 && row.level < 1 && row.q >= 0 && row.width >= 0 && row.coverage >= 0 && row.coverage <= 1,
  ).sort((a, b) => a.level - b.level);
  return levels.length ? { ...value, levels } : null;
}

export function predictionInterval(row: PredictionRow | null | undefined): { lower: number; upper: number; level: number } | null {
  if (!row || ![row.lower, row.upper, row.level, row.prediction].every(value => typeof value === 'number' && Number.isFinite(value))) return null;
  return row.lower! <= Number(row.prediction) && Number(row.prediction) <= row.upper!
    ? { lower: row.lower!, upper: row.upper!, level: row.level! } : null;
}
