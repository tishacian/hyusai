/**
 * `ContextViewComponent` — detail surface for a single Context, opened
 * at `/steering/contexts/:id`.
 *
 * Exposes 5 canonical facets:
 *
 *   - **Overview**     — name + version (editable)
 *   - **Data refs**    — editable list of `data_refs[]`
 *   - **Memory refs**  — editable list of `memory_refs[]` (was never
 *                         exposed before this commit)
 *   - **Permissions**  — JSON editor on `permissions` with live parse
 *                         feedback and save/cancel buttons
 *   - **Systems**      — cross-filter of every System using this
 *                         Context as its `context_id`, with a warning
 *                         panel when count > 0
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import {
  CanonicalApiService,
  type Context,
  type System,
} from '@app/core/canonical-api.service';

type ContextTabId = 'overview' | 'data' | 'memory' | 'permissions' | 'systems';

@Component({
  selector: 'app-context-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Contexts · Context"
      [title]="ctx()?.name || 'Context'"
      [subtitle]="subtitle()"
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="impactPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="alert-triangle" [size]="14" /> Impact
      </button>
      <a
        actions
        routerLink="/steering/contexts"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back
      </a>
      <button
        actions
        type="button"
        (click)="remove()"
        [disabled]="saving()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-red-500/10 hover:bg-red-500/20 ring-1 ring-red-500/30 text-red-300 transition"
      >
        <app-icon name="trash-2" [size]="14" /> Delete
      </button>
    </ck-object-header>

    @if (!ctx()) {
      <div class="ck-surface rounded-md p-8 text-center text-gray-400 text-sm">
        <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
        Loading context…
      </div>
    } @else {
      <ck-tabs
        [active]="activeTab()"
        (activeChange)="onTabChange($event)"
        ariaLabel="Context facets"
      >
        <ck-tab id="overview" label="Overview">
          <section class="ck-surface t-elevated rounded-md p-5 space-y-4 max-w-2xl">
            <div>
              <label class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 block mb-1">
                Name
              </label>
              <input
                type="text"
                [(ngModel)]="draftName"
                class="w-full bg-black/20 border border-white/10 rounded px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
              <div>
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Version</div>
                <div class="text-lg font-semibold text-white tabular-nums">v{{ ctx()?.version ?? 1 }}</div>
              </div>
              <div>
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Created</div>
                <div class="text-sm text-gray-300">{{ ctx()?.created_at?.slice(0, 10) || '—' }}</div>
              </div>
            </div>
            <div class="flex items-center gap-2 pt-3 border-t border-white/5">
              <button
                type="button"
                (click)="saveOverview()"
                [disabled]="saving()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white transition"
              >
                <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                Save name
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="data" label="Data refs">
          <section class="ck-surface rounded-md p-5 space-y-3">
            <p class="text-xs text-gray-400">
              Knowledge collections the Runs powered by this Context can cite.
            </p>
            @for (ref of draftDataRefs(); track $index; let i = $index) {
              <div class="flex items-center gap-2">
                <input
                  class="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  [ngModel]="ref"
                  (ngModelChange)="setDataRef(i, $event)"
                  placeholder="collection name"
                />
                <button
                  type="button"
                  class="text-gray-500 hover:text-red-400 transition p-1"
                  title="Remove"
                  (click)="removeDataRef(i)"
                >
                  <app-icon name="x" [size]="14" />
                </button>
              </div>
            }
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200"
                (click)="addDataRef()"
              >
                <app-icon name="plus" [size]="12" /> Add ref
              </button>
              <button
                type="button"
                (click)="saveRefs()"
                [disabled]="saving()"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white transition"
              >
                <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                Save refs
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="memory" label="Memory refs">
          <section class="ck-surface rounded-md p-5 space-y-3">
            <p class="text-xs text-gray-400">
              Persistent memory bins (chat histories, vector stores) the Context opens at run time.
            </p>
            @for (ref of draftMemoryRefs(); track $index; let i = $index) {
              <div class="flex items-center gap-2">
                <input
                  class="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  [ngModel]="ref"
                  (ngModelChange)="setMemoryRef(i, $event)"
                  placeholder="memory key"
                />
                <button
                  type="button"
                  class="text-gray-500 hover:text-red-400 transition p-1"
                  title="Remove"
                  (click)="removeMemoryRef(i)"
                >
                  <app-icon name="x" [size]="14" />
                </button>
              </div>
            }
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200"
                (click)="addMemoryRef()"
              >
                <app-icon name="plus" [size]="12" /> Add ref
              </button>
              <button
                type="button"
                (click)="saveRefs()"
                [disabled]="saving()"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white transition"
              >
                <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                Save refs
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="permissions" label="Permissions">
          <section class="ck-surface rounded-md p-5 space-y-3">
            <p class="text-xs text-gray-400">
              Free-form permissions bag (JSON). Consumed by the run engine to gate tool and resource access.
            </p>
            <textarea
              [(ngModel)]="permissionsDraft"
              rows="12"
              spellcheck="false"
              class="w-full bg-black/30 border border-white/10 rounded px-3 py-2 text-xs font-mono text-gray-200 focus:outline-none focus:ring-1 focus:ring-cyan-400 resize-none"
            ></textarea>
            @if (permissionsError()) {
              <div class="text-[11px] ck-mono" style="color: var(--ck-signal-neg);">
                <app-icon name="alert-triangle" [size]="12" class="inline-block mr-1" />
                {{ permissionsError() }}
              </div>
            }
            <div class="flex items-center gap-2 pt-2 border-t border-white/5">
              <button
                type="button"
                (click)="savePermissions()"
                [disabled]="saving() || !!permissionsError()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white transition"
              >
                <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                Save permissions
              </button>
              <button
                type="button"
                (click)="resetPermissions()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
              >
                Reset
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="systems" label="Systems">
          @if (boundSystems().length === 0) {
            <app-empty-state
              icon="cube"
              title="No Systems bound"
              description="No System references this Context as its primary context_id."
            />
          } @else {
            <ul class="space-y-2">
              @for (sys of boundSystems(); track sys.id) {
                <li class="ck-surface rounded-md p-4 flex items-center gap-3">
                  <div class="w-9 h-9 rounded bg-cyan-500/15 text-cyan-400 ring-1 ring-cyan-500/30 flex items-center justify-center shrink-0">
                    <app-icon name="box" [size]="16" />
                  </div>
                  <div class="flex-1 min-w-0">
                    <a
                      [routerLink]="['/systems', sys.id]"
                      class="text-sm font-medium text-white hover:text-cyan-300 transition truncate block"
                    >
                      {{ sys.name }}
                    </a>
                    <div class="text-[11px] text-gray-500 truncate">{{ sys.objective || '—' }}</div>
                  </div>
                  <span
                    class="ck-mono text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-white/5 text-gray-400"
                  >
                    {{ sys.status || 'active' }}
                  </span>
                </li>
              }
            </ul>
          }
        </ck-tab>
      </ck-tabs>
    }

    <ck-panel
      [open]="impactPanelOpen()"
      (openChange)="impactPanelOpen.set($event)"
      position="side"
      eyebrow="Context · impact"
      title="Downstream impact"
      width="420px"
    >
      @if (boundSystems().length === 0) {
        <p class="text-xs text-gray-400">
          No System currently references this Context. Editing or deleting it is safe.
        </p>
      } @else {
        <div
          class="text-xs mb-3"
          style="color: var(--ck-signal-warn);"
        >
          <app-icon name="alert-triangle" [size]="12" class="inline-block mr-1" />
          {{ boundSystems().length }} System{{ boundSystems().length === 1 ? '' : 's' }} reference this Context.
          Changes propagate on next Run.
        </div>
        <ul class="space-y-1.5">
          @for (sys of boundSystems(); track sys.id) {
            <li>
              <a
                [routerLink]="['/systems', sys.id]"
                class="text-xs text-cyan-300 hover:text-cyan-200 transition truncate block"
              >
                {{ sys.name }}
              </a>
            </li>
          }
        </ul>
      }
    </ck-panel>
  `,
})
export class ContextViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);

  readonly ctx = signal<Context | null>(null);
  readonly systems = signal<System[]>([]);
  readonly saving = signal(false);
  readonly activeTab = signal<ContextTabId>('overview');
  readonly impactPanelOpen = signal(false);

  draftName = '';
  readonly draftDataRefs = signal<string[]>([]);
  readonly draftMemoryRefs = signal<string[]>([]);
  permissionsDraft = '{}';
  readonly permissionsError = signal<string | null>(null);

  readonly boundSystems = computed(() => {
    const id = this.ctx()?.id;
    if (!id) return [];
    return this.systems().filter((s) => s.context_id === id);
  });

  readonly subtitle = computed(() => {
    const c = this.ctx();
    if (!c) return '';
    return `${c.data_refs?.length ?? 0} data refs · ${c.memory_refs?.length ?? 0} memory refs · ${this.boundSystems().length} System${this.boundSystems().length === 1 ? '' : 's'} bound.`;
  });

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const c = this.ctx();
    const bound = this.boundSystems().length;
    return [
      {
        label: 'Data refs',
        value: String(c?.data_refs?.length ?? 0),
        tone: 'cool',
        hint: 'Number of knowledge refs declared on this context.',
      },
      {
        label: 'Memory refs',
        value: String(c?.memory_refs?.length ?? 0),
        tone: 'neutral',
        hint: 'Number of memory bins opened at run time.',
      },
      {
        label: 'Systems',
        value: String(bound),
        tone: bound > 0 ? 'violet' : 'neutral',
        hint: 'Systems currently bound via context_id.',
      },
      {
        label: 'Version',
        value: `v${c?.version ?? 1}`,
        tone: 'neutral',
        hint: 'Increments on every save.',
      },
    ];
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    if (!id) {
      this.router.navigateByUrl('/steering/contexts');
      return;
    }
    this.load(id);
    this.canonical.listSystems().subscribe({
      next: (list) => this.systems.set(list ?? []),
      error: () => this.systems.set([]),
    });
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as ContextTabId);
  }

  private load(id: string): void {
    this.canonical.getContext(id).subscribe({
      next: (c) => {
        if (!c) {
          this.toast.error('Context not found', 'Contexts');
          this.router.navigateByUrl('/steering/contexts');
          return;
        }
        this.applyContext(c);
      },
      error: () => {
        this.toast.error('Could not load context', 'Contexts');
        this.router.navigateByUrl('/steering/contexts');
      },
    });
  }

  private applyContext(c: Context): void {
    this.ctx.set(c);
    this.draftName = c.name ?? '';
    this.draftDataRefs.set([...(c.data_refs ?? [])]);
    this.draftMemoryRefs.set([...(c.memory_refs ?? [])]);
    this.permissionsDraft = JSON.stringify(c.permissions ?? {}, null, 2);
    this.permissionsError.set(null);
  }

  setDataRef(i: number, value: string): void {
    const refs = [...this.draftDataRefs()];
    refs[i] = value;
    this.draftDataRefs.set(refs);
  }

  addDataRef(): void {
    this.draftDataRefs.set([...this.draftDataRefs(), '']);
  }

  removeDataRef(i: number): void {
    const refs = [...this.draftDataRefs()];
    refs.splice(i, 1);
    this.draftDataRefs.set(refs);
  }

  setMemoryRef(i: number, value: string): void {
    const refs = [...this.draftMemoryRefs()];
    refs[i] = value;
    this.draftMemoryRefs.set(refs);
  }

  addMemoryRef(): void {
    this.draftMemoryRefs.set([...this.draftMemoryRefs(), '']);
  }

  removeMemoryRef(i: number): void {
    const refs = [...this.draftMemoryRefs()];
    refs.splice(i, 1);
    this.draftMemoryRefs.set(refs);
  }

  saveOverview(): void {
    const c = this.ctx();
    if (!c) return;
    const name = this.draftName.trim() || c.name;
    this.patch({ name });
  }

  saveRefs(): void {
    this.patch({
      data_refs: this.draftDataRefs().filter((r) => r.trim()),
      memory_refs: this.draftMemoryRefs().filter((r) => r.trim()),
    });
  }

  savePermissions(): void {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(this.permissionsDraft || '{}');
    } catch (err) {
      this.permissionsError.set((err as Error).message);
      return;
    }
    this.permissionsError.set(null);
    this.patch({ permissions: parsed });
  }

  resetPermissions(): void {
    const c = this.ctx();
    this.permissionsDraft = JSON.stringify(c?.permissions ?? {}, null, 2);
    this.permissionsError.set(null);
  }

  remove(): void {
    const c = this.ctx();
    if (!c) return;
    const bound = this.boundSystems().length;
    const msg = bound > 0
      ? `Delete "${c.name}"? ${bound} System${bound === 1 ? '' : 's'} will lose their context pin.`
      : `Delete "${c.name}"?`;
    if (!confirm(msg)) return;
    this.saving.set(true);
    this.canonical.deleteContext(c.id).subscribe({
      next: (ok) => {
        this.saving.set(false);
        if (ok) {
          this.toast.success(`${c.name} deleted`, 'Context');
          this.router.navigateByUrl('/steering/contexts');
        } else {
          this.toast.error('Delete failed', 'Context');
        }
      },
      error: () => {
        this.saving.set(false);
        this.toast.error('Delete failed', 'Context');
      },
    });
  }

  private patch(body: Partial<Context>): void {
    const c = this.ctx();
    if (!c) return;
    this.saving.set(true);
    this.canonical.updateContext(c.id, body).subscribe({
      next: (updated) => {
        this.saving.set(false);
        if (updated) {
          this.applyContext(updated);
          this.toast.success(`v${updated.version ?? '?'} saved`, 'Context updated');
        } else {
          this.toast.error('Update failed', 'Context');
        }
      },
      error: () => {
        this.saving.set(false);
        this.toast.error('Update failed', 'Context');
      },
    });
  }
}
