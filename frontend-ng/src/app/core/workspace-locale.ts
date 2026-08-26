/**
 * The language a workspace opens in when its reader has not asked for one.
 *
 * Read from `settings.presentation.locale`, beside `demo_safe`, because it is
 * the same kind of fact: how this workspace is meant to be shown. A tenant
 * whose audience is entirely anglophone should not depend on every visitor's
 * browser being configured for them, nor on somebody remembering the switcher
 * before a demo starts.
 *
 * A *default*, never an override. The switcher and `?lang=` still win, and they
 * win permanently: see `I18nService`, which only persists a locale somebody
 * chose.
 */
import type { Locale } from './locale';

export function workspaceLocale(
  settings: Readonly<Record<string, unknown>> | null | undefined,
): Locale | null {
  const presentation = settings?.['presentation'];
  if (presentation === null || typeof presentation !== 'object' || Array.isArray(presentation)) {
    return null;
  }
  const declared = (presentation as Record<string, unknown>)['locale'];
  return declared === 'fr' || declared === 'en' ? declared : null;
}
