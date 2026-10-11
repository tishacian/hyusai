import { Injectable, computed, effect, signal } from '@angular/core';
import {
  LEGACY_BUSINESS_THEME_KEY,
  THEME_CYCLE,
  THEME_KEY,
  resolveStoredThemeMode,
  type ThemeMode,
} from './theme-preference';

export type { ThemeMode } from './theme-preference';

/** @deprecated Historical name of `ThemeMode`; the preference is global now. */
export type BusinessTheme = ThemeMode;

/**
 * Theme facade: one tri-state preference for the whole app.
 *
 * The mode resolves to a concrete `light`/`dark` that is applied to `html` as
 * both `data-theme` (the `--ck-*` token switch) and the `.dark` class Tailwind
 * keys its `dark:` variants on. The business shell and NAWA read the same
 * preference; NAWA keeps its own `--nawa-*` palette on top of it.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly mode = signal<ThemeMode>(this.readStoredMode());

  /** Tracks the OS `prefers-color-scheme: dark` media query for `system`. */
  private readonly systemPrefersDark = signal(this.matchSystemDark());

  /** The concrete theme on screen. */
  readonly resolved = computed<'light' | 'dark'>(() => {
    const mode = this.mode();
    if (mode === 'system') return this.systemPrefersDark() ? 'dark' : 'light';
    return mode;
  });

  readonly isDark = computed(() => this.resolved() === 'dark');

  /** @deprecated Use {@link mode}; the preference is no longer shell-scoped. */
  readonly businessTheme = this.mode;
  /** @deprecated Use {@link resolved}. */
  readonly businessResolved = this.resolved;

  constructor() {
    effect(() => {
      const root = document.documentElement;
      const resolved = this.resolved();
      root.classList.toggle('dark', resolved === 'dark');
      root.setAttribute('data-theme', resolved);
    });

    effect(() => {
      const mode = this.mode();
      try {
        localStorage.setItem(THEME_KEY, mode);
        localStorage.removeItem(LEGACY_BUSINESS_THEME_KEY);
      } catch {
        // Ignore quota/privacy errors.
      }
    });

    this.watchSystemPreference();
  }

  setMode(mode: ThemeMode): void {
    this.mode.set(mode);
  }

  /** Flip between the two concrete themes, leaving `system` behind. */
  toggle(): void {
    this.setMode(this.resolved() === 'dark' ? 'light' : 'dark');
  }

  /** Cycle the preference: system → light → dark → system. */
  cycle(): void {
    this.setMode(THEME_CYCLE[(THEME_CYCLE.indexOf(this.mode()) + 1) % THEME_CYCLE.length]);
  }

  /** @deprecated Use {@link cycle}. */
  cycleBusinessTheme(): void {
    this.cycle();
  }

  /** @deprecated Use {@link setMode}. */
  setDark(dark: boolean): void {
    this.setMode(dark ? 'dark' : 'light');
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

  private readStoredMode(): ThemeMode {
    try {
      return resolveStoredThemeMode(
        localStorage.getItem(THEME_KEY),
        localStorage.getItem(LEGACY_BUSINESS_THEME_KEY),
      );
    } catch {
      return 'system';
    }
  }
}
