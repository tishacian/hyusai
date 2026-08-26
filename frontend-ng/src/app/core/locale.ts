/**
 * The supported UI locales, in their own module so that code which only needs
 * to *name* a locale does not have to import the whole i18n service — and the
 * dictionaries it carries — to do it.
 */

/** Supported UI locales. French is the product's default. */
export type Locale = 'fr' | 'en';

export const LOCALES: readonly Locale[] = ['fr', 'en'] as const;

export function isLocale(value: unknown): value is Locale {
  return value === 'fr' || value === 'en';
}
