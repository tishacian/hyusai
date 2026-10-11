/** Theme preference. `system` follows `prefers-color-scheme`. */
export type ThemeMode = 'system' | 'light' | 'dark';

export const THEME_KEY = 'agentium_theme';
/** Pre-unification business-shell key. Read once, then deleted. */
export const LEGACY_BUSINESS_THEME_KEY = 'agentium_business_theme';

/** The order the title-bar and business-shell switches walk through. */
export const THEME_CYCLE: readonly ThemeMode[] = ['system', 'light', 'dark'];

function asMode(value: string | null): ThemeMode | null {
  return value === 'system' || value === 'light' || value === 'dark' ? value : null;
}

/**
 * Fold the two historical preference keys into one.
 *
 * `agentium_theme` used to be written as a constant `'dark'` by the global
 * pin, so a stored `dark` there is not evidence that anyone chose dark —
 * whereas `agentium_business_theme` only ever held a real click from the
 * business shell or NAWA. When both are present and the unified key still
 * carries the pin's `dark`, the business choice wins.
 */
export function resolveStoredThemeMode(
  unified: string | null,
  legacyBusiness: string | null,
): ThemeMode {
  const stored = asMode(unified);
  const legacy = asMode(legacyBusiness);
  if (stored && !(stored === 'dark' && legacy)) return stored;
  return legacy ?? stored ?? 'system';
}
