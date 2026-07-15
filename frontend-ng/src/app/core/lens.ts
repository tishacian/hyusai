import { Injectable, inject } from '@angular/core';
import { ZoomContextService } from './zoom-context.service';

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
  private readonly navigation = inject(ZoomContextService);

  /** Same gated Router projection used by rails, breadcrumb and guards. */
  readonly lens = this.navigation.lens;
}
