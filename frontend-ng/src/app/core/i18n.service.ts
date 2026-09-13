import { Injectable, effect, inject, signal } from '@angular/core';

import type { I18nKey } from './i18n.dict';
import { CORE_EN_DICT, CORE_FR_DICT } from './i18n.core-dict';
import { LOCALES, isLocale, type Locale } from './locale';
import { workspaceLocale } from './workspace-locale';
import { WorkspaceService } from './workspace.service';

const LOCALE_KEY = 'agentium_locale';

export type { Locale };

/**
 * Runtime i18n service for the cockpit (Vague D / D3).
 *
 * Deliberately lightweight — no `@angular/localize`, no per-locale
 * bundle, no template marker pass across 80 components. Instead we
 * expose:
 *
 * * a `locale` signal persisted in `localStorage`, picked up on boot
 *   from the stored intent, the `lang` query-string, or the browser's
 *   `navigator.language`;
 * * a `t(key, params?)` translate function that reads the signal so
 *   any component that calls it via `i18n.t('…')` re-renders the
 *   moment the user flips the switcher in the account menu.
 *
 * Missing keys fall back through FR then to the key itself. FR/EN parity
 * is now enforced at compile time by each `core/i18n/<domain>.dict.ts`
 * module and by `npm run check:i18n`, so this fallback only fires for keys
 * assembled at runtime from an API value (`'runs.status.' + status`) — and
 * returning the key verbatim is what makes a typo visible on screen.
 * See `core/i18n/CONVENTION.md`.
 *
 * Interpolation is minimalist: `{name}` placeholders, no pluralisation
 * (we don't have any plural-sensitive surface yet; if one shows up we
 * switch to ICU via `@angular/localize` only for that surface).
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  private readonly workspace = inject(WorkspaceService);

  /**
   * Whether the reader has expressed a locale of their own — a stored choice or
   * `?lang=`. It gates the workspace's declared default: a tenant may decide
   * what its pages open in, never what a reader who has already chosen sees.
   */
  private readonly asked = signal<boolean>(false);

  readonly locale = signal<Locale>(this.readInitialLocale());

  private readonly dictionaryRevision = signal(0);
  private dicts: Record<Locale, Record<string, string>> = {
    fr: CORE_FR_DICT,
    en: CORE_EN_DICT,
  };
  private extendedDictionaryLoad?: Promise<void>;

  constructor() {
    this.scheduleExtendedDictionaryLoad();
    effect(() => {
      const declared = workspaceLocale(this.workspace.current()?.settings);
      if (declared && !this.asked()) {
        this.locale.set(declared);
      }
    });
    effect(() => {
      const locale = this.locale();
      // Persisted only once somebody has chosen: writing an inferred locale
      // here would make the first render indistinguishable from a decision, and
      // the workspace's default could then never apply again.
      if (this.asked()) {
        try {
          localStorage.setItem(LOCALE_KEY, locale);
        } catch {
          // Ignore quota/privacy errors.
        }
      }
      if (typeof document !== 'undefined') {
        document.documentElement.lang = locale;
      }
    });
  }

  /**
   * Translate a dot-notation key into the active locale. Returns the
   * key verbatim when both EN and FR dictionaries miss it, which
   * surfaces untranslated strings directly in the UI so they're easy
   * to audit.
   *
   * `{brand}` is filled in for every key without the call site asking: copy
   * that names the product must follow the active workspace's brand, and a
   * white-labelled tenant would otherwise read the editor's name.
   */
  readonly t = (
    key: I18nKey | string,
    params?: Record<string, string | number>,
  ): string => {
    this.dictionaryRevision();
    const locale = this.locale();
    const dict = this.dicts[locale] ?? this.dicts.fr;
    let value = dict[key] ?? this.dicts.fr[key];
    if (value === undefined) {
      void this.loadExtendedDictionaries();
      value = key;
    }
    for (const [k, v] of Object.entries({ brand: this.workspace.brandName(), ...params })) {
      value = value.replaceAll(`{${k}}`, String(v));
    }
    return value;
  };

  /** Pin a specific locale. */
  setLocale(locale: Locale): void {
    if (!LOCALES.includes(locale)) return;
    this.asked.set(true);
    this.locale.set(locale);
  }

  /** Toggle FR ↔ EN. */
  toggle(): void {
    this.asked.set(true);
    this.locale.update((l) => (l === 'fr' ? 'en' : 'fr'));
  }

  /** Exposed for the account-menu switcher so it doesn't own the list. */
  readonly supported: readonly Locale[] = LOCALES;

  private readInitialLocale(): Locale {
    try {
      const stored = localStorage.getItem(LOCALE_KEY);
      if (isLocale(stored)) {
        this.asked.set(true);
        return stored;
      }
    } catch {
      // Ignore storage errors.
    }
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const queryLang = params.get('lang');
      if (isLocale(queryLang)) {
        this.asked.set(true);
        return queryLang;
      }
    }
    // The browser's language and the workspace's default are both guesses, so
    // neither sets `asked`: whichever resolves last is free to win.
    if (typeof navigator !== 'undefined') {
      const nav = (navigator.language || 'fr').toLowerCase();
      if (nav.startsWith('en')) return 'en';
    }
    return 'fr';
  }

  private loadExtendedDictionaries(): Promise<void> {
    if (this.extendedDictionaryLoad) return this.extendedDictionaryLoad;

    this.extendedDictionaryLoad = import('./i18n.dict')
      .then(({ EN_DICT, FR_DICT }) => {
        this.dicts = { fr: FR_DICT, en: EN_DICT };
        this.dictionaryRevision.update((revision) => revision + 1);
      })
      .catch(() => {
        // A later lookup should be allowed to retry after a transient chunk
        // failure. Core navigation and Ask remain translated in the meantime.
        this.extendedDictionaryLoad = undefined;
      });
    return this.extendedDictionaryLoad;
  }

  private scheduleExtendedDictionaryLoad(): void {
    if (typeof window === 'undefined') return;

    const load = () => void this.loadExtendedDictionaries();
    if ('requestIdleCallback' in window) {
      window.requestIdleCallback(load, { timeout: 2_000 });
      return;
    }
    globalThis.setTimeout(load, 1_000);
  }
}
