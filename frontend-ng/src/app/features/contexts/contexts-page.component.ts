/**
 * Contexts management page (Steering > Contexts).
 *
 * This is now a **pure list** surface. The inline master-detail pattern
 * was replaced by a dedicated detail route
 * (`/steering/contexts/:id` → `ContextViewComponent`), so the cockpit
 * behaves identically to every other object type (Capability, System,
 * Skill, Knowledge base).
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import {
  CanonicalApiService,
  type Context,
  type System,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';

@Component({
  selector: 'app-contexts-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NavLinkDirective,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="i18n.t('contexts.page.eyebrow')"
      [title]="i18n.t('contexts.page.title')"
      [subtitle]="i18n.t('contexts.page.subtitle')"
      [kpis]="kpis()"
    >
      <a
        actions
        [navLink]="{ leaf: 'system-new' }"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
      >
        <app-icon name="plus" [size]="14" /> {{ i18n.t('contexts.page.new_via_builder') }}
      </a>
    </ck-object-header>

    @if (loading() && contexts().length === 0) {
      <div class="space-y-2">
        @for (_ of [0, 1, 2]; track $index) {
          <div class="ck-surface rounded-md p-5 animate-pulse">
            <div class="h-3 w-60 bg-white/5 rounded"></div>
          </div>
        }
      </div>
    } @else if (contexts().length === 0) {
      <app-empty-state
        icon="database"
        [title]="i18n.t('contexts.empty.title')"
        [description]="i18n.t('contexts.empty.description')"
      >
        <a
          [navLink]="{ leaf: 'system-new' }"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
        >
          <app-icon name="plus" [size]="14" /> {{ i18n.t('contexts.empty.open_builder') }}
        </a>
      </app-empty-state>
    } @else {
      <ul class="space-y-2">
        @for (c of contexts(); track c.id) {
          <li>
            <a
              [navLink]="{ leaf: 'context-doc', ref: c.id }"
              class="flex items-center gap-3 ck-surface rounded-md px-4 py-3 transition hover:bg-white/5 group"
            >
              <div
                class="w-9 h-9 rounded bg-cyan-500/15 text-cyan-400 ring-1 ring-cyan-500/30 flex items-center justify-center shrink-0"
              >
                <app-icon name="database" [size]="16" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium text-white truncate">{{ c.name }}</span>
                  <span
                    class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-gray-400 ring-1 ring-white/10"
                  >
                    v{{ c.version ?? 1 }}
                  </span>
                  @if (isUsed(c)) {
                    <span
                      class="ck-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
                      style="color: var(--ck-signal-pos); border: 1px solid rgba(16,185,129,0.25); background: rgba(16,185,129,0.05);"
                    >
                      {{ i18n.t('contexts.list.in_use') }}
                    </span>
                  }
                </div>
                <div class="text-[11px] text-gray-500 font-mono mt-0.5">
                  {{
                    i18n.t('contexts.list.meta', {
                      data: c.data_refs?.length ?? 0,
                      mem: c.memory_refs?.length ?? 0,
                      systems: systemsBound(c).length
                    })
                  }}
                </div>
              </div>
              <app-icon name="chevron-right" [size]="14" class="text-gray-500 group-hover:text-white transition shrink-0" />
            </a>
          </li>
        }
      </ul>
    }
  `,
})
export class ContextsPageComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  readonly i18n = inject(I18nService);

  readonly contexts = signal<Context[]>([]);
  readonly systems = signal<System[]>([]);
  readonly loading = signal(false);

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const total = this.contexts().length;
    const pinned = this.contexts().filter((c) => this.systemsBound(c).length > 0).length;
    const unused = total - pinned;
    const stale = this.contexts().filter((c) => (c.version ?? 1) >= 3).length;
    return [
      { label: this.i18n.t('contexts.kpi.total'), value: String(total), tone: 'cool', hint: this.i18n.t('contexts.kpi.total_hint') },
      { label: this.i18n.t('contexts.kpi.pinned'), value: String(pinned), tone: 'pos', hint: this.i18n.t('contexts.kpi.pinned_hint') },
      { label: this.i18n.t('contexts.kpi.unused'), value: String(unused), tone: unused ? 'warn' : 'neutral', hint: this.i18n.t('contexts.kpi.unused_hint') },
      { label: this.i18n.t('contexts.kpi.stale'), value: String(stale), tone: stale ? 'warn' : 'neutral', hint: this.i18n.t('contexts.kpi.stale_hint') },
    ];
  });

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.canonical.listContexts().subscribe({
      next: (list) => {
        this.contexts.set(list ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.contexts.set([]);
        this.loading.set(false);
      },
    });
    this.canonical.listSystems().subscribe({
      next: (list) => this.systems.set(list ?? []),
      error: () => this.systems.set([]),
    });
  }

  systemsBound(c: Context): System[] {
    return this.systems().filter((s) => s.context_id === c.id);
  }

  isUsed(c: Context): boolean {
    return this.systemsBound(c).length > 0;
  }
}
