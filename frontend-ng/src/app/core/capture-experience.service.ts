import { Injectable, computed, inject, signal } from '@angular/core';
import { WorkspaceService } from './workspace.service';

/** Which capture experience to render at the stable `/knowledge/capture` route. */
export type CaptureExperience = 'v0' | 'fil';

/** Per-user A/B override key (localStorage), mirrors the VoiceCaptureMode pattern. */
const STORAGE_KEY = 'agentium.capture_experience';
/** URL override (`?exp=fil`) used for one-off A/B without flipping localStorage. */
const QUERY_PARAM = 'exp';

/**
 * Hosts the `capture_experience` flag that decides whether the stable
 * `/knowledge/capture` route renders the frozen v0 monolith
 * (`KnowledgeCaptureComponent`) or the new cockpit "Le Fil" experience
 * (`CaptureFilShellComponent`).
 *
 * Resolution order (highest wins):
 *   1. `?exp=fil` query param override (one-off A/B)
 *   2. `localStorage['agentium.capture_experience']` (per-user override)
 *   3. `workspace.current().settings['capture_experience']` (per-tenant)
 *   4. default `'v0'` — existing users are unaffected.
 */
@Injectable({ providedIn: 'root' })
export class CaptureExperienceService {
  private readonly workspace = inject(WorkspaceService);

  private readonly queryOverride = signal<CaptureExperience | null>(this.readQueryOverride());
  private readonly localOverride = signal<CaptureExperience | null>(this.readLocalOverride());

  /** Effective capture experience after applying the resolution order above. */
  readonly experience = computed<CaptureExperience>(() => {
    const query = this.queryOverride();
    if (query) return query;
    const local = this.localOverride();
    if (local) return local;
    const tenant = this.normalize(this.workspace.current()?.settings?.['capture_experience']);
    if (tenant) return tenant;
    return 'v0';
  });

  readonly isFil = computed(() => this.experience() === 'fil');

  /**
   * Re-read the `?exp=` override from the current URL. The root service is
   * created at app start (before navigation), so the route wrapper calls this
   * once it activates to honour a `?exp=fil` deep-link.
   */
  syncFromUrl(): void {
    this.queryOverride.set(this.readQueryOverride());
  }

  /** Persist (or clear, with `null`) the per-user A/B override. */
  setExperience(value: CaptureExperience | null): void {
    this.localOverride.set(value);
    try {
      if (value) localStorage.setItem(STORAGE_KEY, value);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* storage unavailable (private mode / SSR) — keep the in-memory signal */
    }
  }

  private readLocalOverride(): CaptureExperience | null {
    try {
      return this.normalize(localStorage.getItem(STORAGE_KEY));
    } catch {
      return null;
    }
  }

  private readQueryOverride(): CaptureExperience | null {
    try {
      return this.normalize(new URLSearchParams(window.location.search).get(QUERY_PARAM));
    } catch {
      return null;
    }
  }

  private normalize(value: unknown): CaptureExperience | null {
    return value === 'fil' || value === 'v0' ? value : null;
  }
}
