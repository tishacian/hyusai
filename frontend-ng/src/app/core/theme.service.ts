import { Injectable, computed, effect, signal } from '@angular/core';

const THEME_KEY = 'agentium_theme';
const BUSINESS_THEME_KEY = 'agentium_business_theme';

type ThemeMode = 'dark' | 'light' | 'system';

/** Business-shell theme preference. `system` follows `prefers-color-scheme`. */
export type BusinessTheme = 'system' | 'light' | 'dark';

/**
 * Theme facade. The global `html` is pinned to dark mode until the light
 * palette has enough contrast for demos, so cockpit admin chrome stays dark.
 *
 * The business shell (Recherche / Capture / Client360) is the exception: it
 * scopes a `data-theme` attribute onto its own subtree so business end users
 * can flip system/light/dark without touching the global dark pin.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly mode = signal<ThemeMode>('dark');
  readonly isDark = signal(true);

  /** Business-shell preference, persisted to `agentium_business_theme`. */
  readonly businessTheme = signal<BusinessTheme>(this.readBusinessTheme());

  /** Tracks the OS `prefers-color-scheme: dark` media query for `system`. */
  private readonly systemPrefersDark = signal(this.matchSystemDark());

  /** The concrete theme applied to the business subtree (`light` | `dark`). */
  readonly businessResolved = computed<'light' | 'dark'>(() => {
    const theme = this.businessTheme();
    if (theme === 'system') {
      return this.systemPrefersDark() ? 'dark' : 'light';
    }
    return theme;
  });

  constructor() {
    // Global dark pin — do NOT relax this; the cockpit admin chrome relies on it.
    effect(() => {
      const root = document.documentElement;
      root.classList.add('dark');
      root.setAttribute('data-theme', 'dark');
    });

    effect(() => {
      try {
        localStorage.setItem(THEME_KEY, 'dark');
      } catch {
        // Ignore quota/privacy errors.
      }
    });

    // Persist the business-shell preference on every change.
    effect(() => {
      const theme = this.businessTheme();
      try {
        localStorage.setItem(BUSINESS_THEME_KEY, theme);
      } catch {
        // Ignore quota/privacy errors.
      }
    });

    this.watchSystemPreference();
  }

  toggle(): void {
    this.setMode('dark');
  }

  setMode(_mode: ThemeMode): void {
    this.mode.set('dark');
    this.isDark.set(true);
  }

  /** @deprecated use {@link setMode} instead. */
  setDark(_dark: boolean): void {
    this.setMode('dark');
  }

  /** Cycle the business-shell theme: system → light → dark → system. */
  cycleBusinessTheme(): void {
    const order: BusinessTheme[] = ['system', 'light', 'dark'];
    const next = order[(order.indexOf(this.businessTheme()) + 1) % order.length];
    this.businessTheme.set(next);
  }

  private watchSystemPreference(): void {
    try {
      const mql = window.matchMedia('(prefers-color-scheme: dark)');
      mql.addEventListener('change', (event) => this.systemPrefersDark.set(event.matches));
    } catch {
      // matchMedia unavailable (SSR/legacy) — stay on the initial value.
    }
  }

  private matchSystemDark(): boolean {
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    } catch {
      return true;
    }
  }

  private readBusinessTheme(): BusinessTheme {
    try {
      const stored = localStorage.getItem(BUSINESS_THEME_KEY);
      if (stored === 'light' || stored === 'dark' || stored === 'system') {
        return stored;
      }
    } catch {
      // Ignore quota/privacy errors.
    }
    return 'system';
  }
}
