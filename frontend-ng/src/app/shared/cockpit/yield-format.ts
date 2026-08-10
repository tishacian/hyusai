/**
 * Bounded rendering for the yield readouts (ROI, efficiency) shared by the
 * Hypervisor balance sheet and the Run outcome card.
 *
 * The ceiling mirrors `MAX_SIGNAL_ROI_RATIO` in
 * `backend/app/api/v1/endpoints/hypervisor.py`, which caps the same claim in
 * the balance-sheet signal labels. Both must move together, otherwise the same
 * run reads as `> 1000%` in one surface and as a five-digit percentage in the
 * next.
 *
 * Values are ratios, as carried by the API: `0.5` means half again what the
 * run cost. Only the display is bounded — the payload keeps the raw ratio.
 */
export const MAX_YIELD_RATIO = 10;

/** Render a yield ratio as percent, capped past the ceiling. */
export function formatYieldPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value > MAX_YIELD_RATIO) return `> ${MAX_YIELD_RATIO * 100}%`;
  return `${Math.round(value * 100)}%`;
}

/** Render a yield ratio as a multiplier index, capped past the ceiling. */
export function formatYieldIndex(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value > MAX_YIELD_RATIO) return `> ${MAX_YIELD_RATIO.toFixed(2)}`;
  return value.toFixed(2);
}
