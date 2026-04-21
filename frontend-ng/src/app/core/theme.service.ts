import { Injectable, signal, effect } from '@angular/core';

const THEME_KEY = 'agentium_theme';

/**
 * Manages the dark/light theme. Cockpit components target `[data-theme]`
 * (cockpit tokens), legacy components keep using the `.dark` class.
 * Both flags are kept in sync so legacy and cockpit surfaces stay coherent
 * during the migration window.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly isDark = signal(this.readInitial());

  constructor() {
    effect(() => {
      const dark = this.isDark();
      const root = document.documentElement;
      root.classList.toggle('dark', dark);
      root.setAttribute('data-theme', dark ? 'dark' : 'light');
      localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
    });
  }

  toggle(): void {
    this.isDark.update((v) => !v);
  }

  setDark(dark: boolean): void {
    this.isDark.set(dark);
  }

  private readInitial(): boolean {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'light') return false;
    return true;
  }
}
