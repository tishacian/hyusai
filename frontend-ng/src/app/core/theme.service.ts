import { Injectable, signal, effect } from '@angular/core';

const THEME_KEY = 'agentium_theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly isDark = signal(this.readInitial());

  constructor() {
    effect(() => {
      const dark = this.isDark();
      document.documentElement.classList.toggle('dark', dark);
      localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
    });
  }

  toggle(): void {
    this.isDark.update((v) => !v);
  }

  private readInitial(): boolean {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'light') return false;
    return true;
  }
}
