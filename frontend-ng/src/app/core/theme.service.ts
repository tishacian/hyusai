import { Injectable, effect, signal } from '@angular/core';

const THEME_KEY = 'agentium_theme';

type ThemeMode = 'dark' | 'light' | 'system';

/**
 * Manages the dark/light theme with three intents: explicit `dark`, explicit
 * `light` and `system` (follow OS). Cockpit components consume `[data-theme]`
 * (cockpit tokens), legacy components keep using the `.dark` class. Both flags
 * are kept in sync so legacy and cockpit surfaces stay coherent during the
 * migration window.
 *
 * When `mode === 'system'` we subscribe to `prefers-color-scheme` so the UI
 * swaps instantly when the OS theme flips — matching macOS/Windows native
 * behaviour.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly mediaQuery = typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null;

  /** Stored user intent (`dark` / `light` / `system`). */
  readonly mode = signal<ThemeMode>(this.readInitialMode());

  /** Resolved OS preference — updates live when the user flips their OS theme. */
  private readonly osPrefersDark = signal(this.mediaQuery?.matches ?? true);

  /** Effective dark state — what should actually be applied right now. */
  readonly isDark = signal(this.resolveIsDark(this.mode(), this.osPrefersDark()));

  constructor() {
    // Live-update OS preference when the system theme flips.
    if (this.mediaQuery) {
      const listener = (ev: MediaQueryListEvent) => this.osPrefersDark.set(ev.matches);
      try {
        this.mediaQuery.addEventListener('change', listener);
      } catch {
        this.mediaQuery.addListener?.(listener);
      }
    }

    // Recompute effective theme when either intent or OS preference changes.
    effect(() => {
      const next = this.resolveIsDark(this.mode(), this.osPrefersDark());
      this.isDark.set(next);
    });

    // Apply to the DOM whenever `isDark` changes.
    effect(() => {
      const dark = this.isDark();
      const root = document.documentElement;
      root.classList.toggle('dark', dark);
      root.setAttribute('data-theme', dark ? 'dark' : 'light');
    });

    // Persist the user intent (not the resolved state) so "follow system"
    // survives reloads.
    effect(() => {
      try {
        localStorage.setItem(THEME_KEY, this.mode());
      } catch {
        // Ignore quota/privacy errors.
      }
    });
  }

  /** Flip between explicit dark ↔ explicit light. Clears the "system" intent. */
  toggle(): void {
    this.mode.update((m) => (m === 'dark' ? 'light' : m === 'light' ? 'dark' : this.isDark() ? 'light' : 'dark'));
  }

  /** Explicitly pin a theme. Pass `'system'` to follow the OS. */
  setMode(mode: ThemeMode): void {
    this.mode.set(mode);
  }

  /** @deprecated use {@link setMode} instead. */
  setDark(dark: boolean): void {
    this.setMode(dark ? 'dark' : 'light');
  }

  private resolveIsDark(mode: ThemeMode, osPrefersDark: boolean): boolean {
    if (mode === 'dark') return true;
    if (mode === 'light') return false;
    return osPrefersDark;
  }

  private readInitialMode(): ThemeMode {
    try {
      const raw = localStorage.getItem(THEME_KEY);
      if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
    } catch {
      // Ignore storage errors.
    }
    // No stored intent → follow the OS, so first-visit users see their native theme.
    return 'system';
  }
}
