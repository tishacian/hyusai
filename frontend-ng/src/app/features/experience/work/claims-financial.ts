/** A declared scenario. Technical Run latency never substitutes human work. */
export interface ClaimsFinancialAssumptions {
  manualMinutes: number;
  assistedMinutes: number;
  hourlyEur: number;
  budgetEur: number;
  volume: number;
}

export function claimsFinancialProjection(a: ClaimsFinancialAssumptions) {
  if (Object.values(a).some(v => v == null || typeof v !== 'number' || !Number.isFinite(v) || v < 0)
    || !Number.isInteger(a.volume) || a.volume > 1000000
    || a.manualMinutes > 1440 || a.assistedMinutes > 1440
    || a.hourlyEur > 1000000 || a.budgetEur > 1000000) return null;
  const savedMinutes = a.manualMinutes - a.assistedMinutes;
  const capacityEur = savedMinutes / 60 * a.hourlyEur;
  const netEur = capacityEur - a.budgetEur;
  return {
    savedMinutes, capacityEur, netEur,
    roi: a.budgetEur > 0 ? netEur / a.budgetEur : null,
    breakEvenSavedMinutes: a.hourlyEur > 0 ? a.budgetEur / a.hourlyEur * 60 : null,
    monthlyNetEur: netEur * a.volume,
  };
}
