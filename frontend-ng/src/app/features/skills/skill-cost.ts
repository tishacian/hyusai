/** Preserve unknown costs and positive amounts below the display precision. */
export function formatSkillCost(
  value: number | null | undefined,
  currency: string | null | undefined = 'USD',
): string {
  const code = typeof currency === 'string' ? currency.trim().toUpperCase() : null;
  if (value == null || !Number.isFinite(value) || value < 0 || !code || !/^[A-Z]{3}$/.test(code)) return '—';
  const belowPrecision = value > 0 && value < 0.0001;
  const digits = value === 0 || value >= 1 ? 2 : value < 0.01 ? 4 : 3;
  const amount = new Intl.NumberFormat('en-US', {
    style: 'currency', currency: code,
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(belowPrecision ? 0.0001 : value === 0 ? 0 : value);
  return belowPrecision ? `< ${amount}` : amount;
}

/** A catalog tariff, including its default zero, is not an observed cost. */
export function observedSkillCost(metrics: {
  calls?: number;
  total_cost?: number | null;
  cost_state?: string;
} | null | undefined): number | null {
  const cost = metrics?.total_cost;
  if (metrics?.calls === 0 || metrics?.cost_state === 'not_measured'
    || cost == null || !Number.isFinite(cost) || cost < 0) return null;
  return cost;
}
