import { Injectable, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { LENS_MATCHES, type CockpitLens } from './navigation.catalog';

/**
 * `LensService` — exposes the currently active cockpit lens as a signal so
 * object-detail pages can adapt their tab *content* (never the tab *set*)
 * to the operator's intent.
 *
 * Contract (docs/mental-model.md §5bis.3, §5bis.5):
 *   - Same object → same tabs across every lens.
 *   - Content projection adapts: `Operate` shows runtime, `Steer` shows
 *     impact / policies, `Govern` shows audit trail, etc.
 *
 * Why a dedicated service rather than reading the URL ad-hoc: the lens is
 * read by many places (object header, tabs, KPI derivation), so a single
 * memoised computation keeps change detection cheap.
 */
@Injectable({ providedIn: 'root' })
export class LensService {
  private readonly router = inject(Router);

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  /** Currently active lens, defaulting to `build` when no match (e.g. on /). */
  readonly lens = computed<CockpitLens>(() => {
    const path = (this.url() || '/').split('?')[0];
    for (const [lens, prefixes] of Object.entries(LENS_MATCHES) as [CockpitLens, string[]][]) {
      if (prefixes.some((m) => path === m || path.startsWith(m + '/'))) {
        return lens;
      }
    }
    return 'build';
  });
}
