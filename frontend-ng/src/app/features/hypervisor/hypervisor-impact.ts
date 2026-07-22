const SERIALIZED_NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

/** Keep missing measurements out of arithmetic while preserving measured zero. */
export function measuredImpactDelta(
  projected: number | null | undefined,
  base: number | null | undefined,
): number | null {
  if (projected == null || base == null) return null;
  return projected - base;
}

/** Count portfolio capabilities without ever substituting the Run count. */
export function measuredCapabilityCount(
  visibleCapabilities: number,
  persistedCapabilities: number | null | undefined,
): number {
  return Math.max(visibleCapabilities, persistedCapabilities ?? 0);
}

/**
 * Format the mixed JSON values accepted by the Hypervisor decision API.
 * Numeric values retain the historical display while descriptive values are
 * rendered as labels instead of being coerced to NaN.
 */
export function formatHypervisorImpact(value: unknown): string {
  let numeric: number | null = null;

  if (typeof value === 'number') {
    numeric = value;
  } else if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return '—';
    if (!SERIALIZED_NUMBER.test(text)) return text.replace(/_/g, ' ');
    numeric = Number(text);
  }

  if (numeric == null || !Number.isFinite(numeric)) return '—';
  if (Math.abs(numeric) >= 1000) return `$${(numeric / 1000).toFixed(1)}k`;
  if (Math.abs(numeric) < 1 && numeric !== 0) return `${(numeric * 100).toFixed(0)}%`;
  return numeric.toFixed(2);
}
