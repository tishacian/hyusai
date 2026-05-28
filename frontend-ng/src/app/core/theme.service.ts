import { Injectable, effect, signal } from '@angular/core';

const THEME_KEY = 'agentium_theme';

type ThemeMode = 'dark' | 'light' | 'system';

/**
 * Theme facade kept for callers that still expose theme controls. The product
 * is pinned to dark mode until the light palette has enough contrast for demos.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly mode = signal<ThemeMode>('dark');
  readonly isDark = signal(true);

  constructor() {
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
}
