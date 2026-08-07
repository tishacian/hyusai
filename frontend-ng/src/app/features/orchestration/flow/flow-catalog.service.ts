/**
 * `FlowCatalogService` — the dynamic palette source (P3).
 *
 * Projects the live `/skills` catalog (each Skill carrying its typed
 * `input_schema`) into `PaletteItem`s the palette can render and drop. The
 * structural graph primitives (source / sink / decision / fork / join / loop)
 * stay client-defined in `DEFAULT_PALETTE` — they are graph semantics, not
 * catalog entries.
 *
 * Read-only: it only consumes `CanonicalApiService.listSkills()` and shapes
 * the result. The single in-flight request is shared + replayed so every
 * palette instance reuses one fetch.
 */
import { Injectable, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { skillToPaletteItem, type PaletteItem } from './flow.types';

export type FlowCatalogState = 'loading' | 'loaded' | 'error';

/** Stable projection kept outside the service so ordering/classification can
 * be regression-tested without HTTP or Angular lifecycle machinery. */
export function projectSkillCatalog(skills: readonly Skill[]): PaletteItem[] {
  return skills
    .map((skill) => skillToPaletteItem(skill))
    .sort(
      (a, b) =>
        a.label.localeCompare(b.label) ||
        String(a.config?.['skill_slug'] ?? '').localeCompare(
          String(b.config?.['skill_slug'] ?? ''),
        ),
    );
}

@Injectable({ providedIn: 'root' })
export class FlowCatalogService {
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private request: Subscription | null = null;
  private readonly _skillItems = signal<PaletteItem[]>([]);

  readonly skillItems = this._skillItems.asReadonly();
  readonly state = signal<FlowCatalogState>('loading');

  constructor() {
    this.load();
    this.workspace.registerContextReset((transition) => {
      this.request?.unsubscribe();
      this.request = null;
      this._skillItems.set([]);
      this.state.set('loading');
      queueMicrotask(() => {
        if (this.workspace.contextEpoch() === transition.nextEpoch) this.load();
      });
    });
  }

  /** Retry is deliberately public so an unavailable catalog never looks like
   * an authoritative empty catalog. */
  retry(): void {
    this.load();
  }

  private load(): void {
    const scope = this.workspace.captureRequestScope();
    this.request?.unsubscribe();
    this.state.set('loading');
    this.request = this.canonical.listSkills({ propagateErrors: true }).subscribe({
      next: (skills) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this._skillItems.set(projectSkillCatalog(skills));
        this.state.set('loaded');
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this._skillItems.set([]);
        this.state.set('error');
      },
    });
  }
}
