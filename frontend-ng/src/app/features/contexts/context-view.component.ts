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
import { I18nService } from '@app/core/i18n.service';

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
      [eyebrow]="i18n.t('contexts.view.eyebrow')"
      [title]="ctx()?.name || i18n.t('contexts.view.title_fallback')"
      [subtitle]="subtitle()"
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="impactPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="alert-triangle" [size]="14" /> {{ i18n.t('contexts.view.impact') }}
      </button>
      <a
        actions
        routerLink="/steering/contexts"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> {{ i18n.t('common.back') }}
      </a>
      <button
        actions
        type="button"
        (click)="remove()"
        [disabled]="saving()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-red-500/10 hover:bg-red-500/20 ring-1 ring-red-500/30 text-red-300 transition"
      >
        <app-icon name="trash-2" [size]="14" /> {{ i18n.t('common.delete') }}
      </button>
    </ck-object-header>

    @if (!ctx()) {
      <div class="ck-surface rounded-md p-8 text-center text-gray-400 text-sm">
        <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
        {{ i18n.t('contexts.view.loading') }}
      </div>
    } @else {
      <ck-tabs
        [active]="activeTab()"
        (activeChange)="onTabChange($event)"
        [ariaLabel]="i18n.t('contexts.view.facets_aria')"
      >
        <ck-tab id="overview" [label]="i18n.t('contexts.view.tab.overview')">
          <section class="ck-surface t-elevated rounded-md p-5 space-y-4 max-w-2xl">
            <div>
              <label class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 block mb-1">
                {{ i18n.t('contexts.view.name') }}
              </label>
              <input
                type="text"
                [(ngModel)]="draftName"
                class="w-full bg-black/20 border border-white/10 rounded px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
              <div>
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('contexts.view.version') }}</div>
                <div class="text-lg font-semibold text-white tabular-nums">v{{ ctx()?.version ?? 1 }}</div>
              </div>
              <div>
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('contexts.view.created') }}</div>
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
                {{ i18n.t('contexts.view.save_name') }}
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="data" [label]="i18n.t('contexts.view.tab.data')">
          <section class="ck-surface rounded-md p-5 space-y-3">
            <p class="text-xs text-gray-400">
              {{ i18n.t('contexts.view.data_description') }}
            </p>
            @for (ref of draftDataRefs(); track $index; let i = $index) {
              <div class="flex items-center gap-2">
                <input
                  class="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  [ngModel]="ref"
                  (ngModelChange)="setDataRef(i, $event)"
                  [placeholder]="i18n.t('contexts.view.data_placeholder')"
                />
                <button
                  type="button"
                  class="text-gray-500 hover:text-red-400 transition p-1"
                  [title]="i18n.t('contexts.view.remove')"
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
                <app-icon name="plus" [size]="12" /> {{ i18n.t('contexts.view.add_ref') }}
              </button>
              <button
                type="button"
                (click)="saveRefs()"
                [disabled]="saving()"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white transition"
              >
                <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                {{ i18n.t('contexts.view.save_refs') }}
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="memory" [label]="i18n.t('contexts.view.tab.memory')">
          <section class="ck-surface rounded-md p-5 space-y-3">
            <p class="text-xs text-gray-400">
              {{ i18n.t('contexts.view.memory_description') }}
            </p>
            @for (ref of draftMemoryRefs(); track $index; let i = $index) {
              <div class="flex items-center gap-2">
                <input
                  class="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  [ngModel]="ref"
                  (ngModelChange)="setMemoryRef(i, $event)"
                  [placeholder]="i18n.t('contexts.view.memory_placeholder')"
                />
                <button
                  type="button"
                  class="text-gray-500 hover:text-red-400 transition p-1"
                  [title]="i18n.t('contexts.view.remove')"
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
                <app-icon name="plus" [size]="12" /> {{ i18n.t('contexts.view.add_ref') }}
              </button>
              <button
                type="button"
                (click)="saveRefs()"
                [disabled]="saving()"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white transition"
              >
                <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                {{ i18n.t('contexts.view.save_refs') }}
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="permissions" [label]="i18n.t('contexts.view.tab.permissions')">
          <section class="ck-surface rounded-md p-5 space-y-3">
            <p class="text-xs text-gray-400">
              {{ i18n.t('contexts.view.permissions_description') }}
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
                {{ i18n.t('contexts.view.save_permissions') }}
              </button>
              <button
                type="button"
                (click)="resetPermissions()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-300 transition"
              >
                {{ i18n.t('contexts.view.reset') }}
              </button>
            </div>
          </section>
        </ck-tab>

        <ck-tab id="systems" [label]="i18n.t('contexts.view.tab.systems')">
          @if (boundSystems().length === 0) {
            <app-empty-state
              icon="cube"
              [title]="i18n.t('contexts.view.systems_empty_title')"
              [description]="i18n.t('contexts.view.systems_empty_description')"
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
      [eyebrow]="i18n.t('contexts.view.impact_eyebrow')"
      [title]="i18n.t('contexts.view.impact_title')"
      width="420px"
    >
      @if (boundSystems().length === 0) {
        <p class="text-xs text-gray-400">
          {{ i18n.t('contexts.view.impact_safe') }}
        </p>
      } @else {
        <div
          class="text-xs mb-3"
          style="color: var(--ck-signal-warn);"
        >
          <app-icon name="alert-triangle" [size]="12" class="inline-block mr-1" />
          {{
            boundSystems().length === 1
              ? i18n.t('contexts.view.impact_warning_one')
              : i18n.t('contexts.view.impact_warning_many', { count: boundSystems().length })
          }}
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
  readonly i18n = inject(I18nService);

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
    const params = {
      data: c.data_refs?.length ?? 0,
      memory: c.memory_refs?.length ?? 0,
      systems: this.boundSystems().length,
    };
    return this.boundSystems().length === 1
      ? this.i18n.t('contexts.view.subtitle_one', params)
      : this.i18n.t('contexts.view.subtitle_many', params);
  });

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const c = this.ctx();
    const bound = this.boundSystems().length;
    return [
      {
        label: this.i18n.t('contexts.view.tab.data'),
        value: String(c?.data_refs?.length ?? 0),
        tone: 'cool',
        hint: this.i18n.t('contexts.view.kpi.data_hint'),
      },
      {
        label: this.i18n.t('contexts.view.tab.memory'),
        value: String(c?.memory_refs?.length ?? 0),
        tone: 'neutral',
        hint: this.i18n.t('contexts.view.kpi.memory_hint'),
      },
      {
        label: this.i18n.t('contexts.view.tab.systems'),
        value: String(bound),
        tone: bound > 0 ? 'violet' : 'neutral',
        hint: this.i18n.t('contexts.view.kpi.systems_hint'),
      },
      {
        label: this.i18n.t('contexts.view.version'),
        value: `v${c?.version ?? 1}`,
        tone: 'neutral',
        hint: this.i18n.t('contexts.view.kpi.version_hint'),
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
          this.toast.error(this.i18n.t('contexts.toast.not_found'), this.i18n.t('contexts.page.title'));
          this.router.navigateByUrl('/steering/contexts');
          return;
        }
        this.applyContext(c);
      },
      error: () => {
        this.toast.error(this.i18n.t('contexts.toast.load_failed'), this.i18n.t('contexts.page.title'));
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
    const msg =
      bound === 0
        ? this.i18n.t('contexts.confirm.delete', { name: c.name })
        : bound === 1
          ? this.i18n.t('contexts.confirm.delete_bound_one', { name: c.name })
          : this.i18n.t('contexts.confirm.delete_bound_many', { name: c.name, count: bound });
    if (!confirm(msg)) return;
    this.saving.set(true);
    this.canonical.deleteContext(c.id).subscribe({
      next: (ok) => {
        this.saving.set(false);
        if (ok) {
          this.toast.success(
            this.i18n.t('contexts.toast.deleted', { name: c.name }),
            this.i18n.t('contexts.view.title_fallback'),
          );
          this.router.navigateByUrl('/steering/contexts');
        } else {
          this.toast.error(this.i18n.t('contexts.toast.delete_failed'), this.i18n.t('contexts.view.title_fallback'));
        }
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.t('contexts.toast.delete_failed'), this.i18n.t('contexts.view.title_fallback'));
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
          this.toast.success(
            this.i18n.t('contexts.toast.saved', { version: updated.version ?? '?' }),
            this.i18n.t('contexts.toast.updated_title'),
          );
        } else {
          this.toast.error(this.i18n.t('contexts.toast.update_failed'), this.i18n.t('contexts.view.title_fallback'));
        }
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.t('contexts.toast.update_failed'), this.i18n.t('contexts.view.title_fallback'));
      },
    });
  }
}
