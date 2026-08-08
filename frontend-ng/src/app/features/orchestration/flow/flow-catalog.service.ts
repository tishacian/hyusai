/**
 * `FlowCatalogService` — the dynamic palette source (P3).
 *
 * Projects the live `/skills` catalog (each Skill carrying its typed
 * `input_schema`) into `PaletteItem`s the palette can render and drop. The
 * structural graph primitives (source / sink / decision / fork / join / loop)
 * stay client-defined in `DEFAULT_PALETTE` — they are graph semantics, not
 * catalog entries.
 *
 * Two things beyond the entries themselves, both already served and until now
 * unconsumed:
 *   - `include_filtered=true` returns the registry rows this workspace does
 *     *not* see, each with the rule that excluded it. They are kept apart from
 *     `skillItems()` (nothing may drop a Skill the workspace cannot run) and
 *     exist so an empty or narrowed palette can explain itself.
 *   - Capabilities are the palette's first disclosure level, so the visible
 *     Capability rows are fetched alongside. Their absence is not fatal: the
 *     grouping falls back to the carrier slugs the Skill rows already carry.
 *
 * Read-only. Requests are workspace-scoped and replaced on context reset.
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { skillToPaletteItem, type PaletteItem } from './flow.types';
import type { PaletteCapabilitySource } from './flow-palette.vm';

export type FlowCatalogState = 'loading' | 'loaded' | 'error';

/** The `catalog` block `/skills` returns next to the rows. */
export interface FlowCatalogSummary {
  total: number;
  visible: number;
  filtered: number;
  /** Whether an admin stated this workspace's industries or the platform
   * inferred them from the family. The two need different sentences, and no
   * production workspace has ever stated them. */
  industriesConfigured: boolean;
}

interface SkillsResponse {
  skills?: Skill[];
  catalog?: {
    total?: number;
    visible?: number;
    filtered?: number;
    policy?: { allowed_industries_source?: string };
  };
}

const EMPTY_SUMMARY: FlowCatalogSummary = {
  total: 0,
  visible: 0,
  filtered: 0,
  industriesConfigured: false,
};

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
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private requests = new Subscription();
  private readonly _entries = signal<PaletteItem[]>([]);
  private readonly _capabilities = signal<PaletteCapabilitySource[]>([]);
  private readonly _summary = signal<FlowCatalogSummary>(EMPTY_SUMMARY);

  /** Entries this workspace can actually drop into a Flow. */
  readonly skillItems = computed(() =>
    this._entries().filter((item) => !item.unavailableReason),
  );
  /** Registry rows excluded here, each carrying its stated reason. */
  readonly filteredItems = computed(() =>
    this._entries().filter((item) => !!item.unavailableReason),
  );
  readonly capabilities = this._capabilities.asReadonly();
  readonly summary = this._summary.asReadonly();
  readonly state = signal<FlowCatalogState>('loading');

  constructor() {
    this.load();
    this.workspace.registerContextReset((transition) => {
      this.requests.unsubscribe();
      this.requests = new Subscription();
      this.reset();
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

  private reset(): void {
    this._entries.set([]);
    this._capabilities.set([]);
    this._summary.set(EMPTY_SUMMARY);
    this.state.set('loading');
  }

  private load(): void {
    const scope = this.workspace.captureRequestScope();
    this.requests.unsubscribe();
    this.requests = new Subscription();
    this.state.set('loading');
    this.requests.add(
      this.api
        .get<SkillsResponse>('/skills', { include_filtered: 'true' })
        .subscribe({
          next: (response) => {
            if (!this.workspace.isRequestScopeCurrent(scope)) return;
            const rows = response?.skills ?? [];
            this._entries.set(projectSkillCatalog(rows));
            this._summary.set(this.readSummary(response));
            this.state.set('loaded');
          },
          error: () => {
            if (!this.workspace.isRequestScopeCurrent(scope)) return;
            this._entries.set([]);
            this._summary.set(EMPTY_SUMMARY);
            this.state.set('error');
          },
        }),
    );
    // Level 1 is a nicety over the carrier slugs already present on every
    // Skill row, so this request never gates or fails the palette.
    this.requests.add(
      this.canonical.listCapabilities().subscribe((capabilities) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this._capabilities.set(
          capabilities.map((capability) => ({
            slug: capability.slug,
            name: capability.name,
            description: capability.description,
          })),
        );
      }),
    );
  }

  private readSummary(response: SkillsResponse | null): FlowCatalogSummary {
    const catalog = response?.catalog;
    const rows = response?.skills ?? [];
    if (!catalog) {
      const filtered = rows.filter(
        (row) => (row as { visibility?: { visible?: boolean } }).visibility?.visible === false,
      ).length;
      return {
        total: rows.length,
        visible: rows.length - filtered,
        filtered,
        industriesConfigured: false,
      };
    }
    return {
      total: catalog.total ?? rows.length,
      visible: catalog.visible ?? rows.length,
      filtered: catalog.filtered ?? 0,
      industriesConfigured: catalog.policy?.allowed_industries_source === 'configured',
    };
  }
}
