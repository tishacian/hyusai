import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import {
  APPS,
  AppDef,
  appById,
  readAppToggles,
  writeAppToggles,
} from '../resources/resources.catalog';

type Filter = 'all' | 'enabled' | 'ready' | 'beta';
const RUNTIME_APPS = APPS.filter((app) => app.wiring === 'wired');

interface WorkspaceAppsResponse {
  enabled?: string[];
  apps?: Array<{
    id: string;
    wiring?: 'wired' | 'catalog';
    enabled?: boolean;
    connector_route?: string | null;
  }>;
  wired_enabled_count?: number;
  has_wired_apps?: boolean;
}

@Component({
  selector: 'app-apps-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgClass,
    FormsModule,
    RouterLink,
    IconComponent,
    CkObjectHeaderComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="i18n.t('apps.eyebrow')"
      [title]="i18n.t('apps.title')"
      [subtitle]="i18n.t('apps.subtitle')"
      [kpis]="headerKpis()"
    ></ck-object-header>

    @if (wiredEnabledCount() > 0) {
      <div class="mb-5 rounded-md p-3 bg-cyan-500/5 ring-1 ring-cyan-500/25 flex items-start gap-3">
        <app-icon name="plug" [size]="14" class="text-cyan-400 mt-0.5 shrink-0" />
        <div class="flex-1">
          <div class="text-[11px] uppercase tracking-wider font-semibold text-cyan-300 mb-0.5">
            {{ i18n.t('apps.banner.wired.title') }}
          </div>
          <p class="text-[11px] text-cyan-200/80 leading-relaxed">
            {{
              wiredEnabledCount() === 1
                ? i18n.t('apps.banner.wired.one')
                : i18n.t('apps.banner.wired.many', { count: wiredEnabledCount() })
            }}
          </p>
        </div>
      </div>
    }

    @if (loadError(); as err) {
      <div class="mb-4 rounded-md bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-400/25">
        {{ err }}
      </div>
    }

    <div class="flex items-center gap-1 mb-5 p-1 bg-white/5 ring-1 ring-white/10 rounded-md w-fit">
      @for (f of filters; track f.id) {
        <button
          type="button"
          (click)="filter.set(f.id)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition"
          [ngClass]="filter() === f.id
            ? 'bg-cyan-500 text-white shadow-glow-sm'
            : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'"
        >
          {{ i18n.t(f.labelKey) }}
          <span
            class="ml-1 text-[9px] font-mono px-1 rounded"
            [class.bg-white\\/15]="filter() === f.id"
            [class.bg-white\\/5]="filter() !== f.id"
          >
            {{ f.count() }}
          </span>
        </button>
      }
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
      @for (a of filtered(); track a.id) {
        <div
          class="ck-surface t-elevated rounded-md p-4 flex flex-col gap-2.5 transition"
          [ngClass]="isEnabled(a.id)
            ? 'ring-1 ring-cyan-500/40 bg-cyan-500/5'
            : ''"
        >
          <div class="flex items-start justify-between">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center"
              [ngClass]="isEnabled(a.id)
                ? 'bg-cyan-500/20 text-cyan-300'
                : 'bg-white/5 text-gray-400'"
            >
              <app-icon [name]="a.icon" [size]="20" />
            </div>
            <div class="flex items-center gap-2">
              <span
                class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ring-1 bg-cyan-500/10 text-cyan-300 ring-cyan-500/30"
                [title]="i18n.t('apps.badge.wired.hint')"
              >
                {{ i18n.t('apps.badge.wired') }}
              </span>
              <button
                type="button"
                (click)="toggle(a.id)"
                role="switch"
                [attr.aria-checked]="isEnabled(a.id)"
                [disabled]="saving() || loading()"
                class="w-10 h-5 rounded-full relative transition-colors disabled:opacity-50"
                [ngClass]="isEnabled(a.id) ? 'bg-cyan-500' : 'bg-white/10'"
              >
                <span
                  class="block w-3.5 h-3.5 bg-white rounded-full absolute top-[3px] transition-all"
                  [ngClass]="isEnabled(a.id) ? 'left-[22px]' : 'left-[3px]'"
                ></span>
              </button>
            </div>
          </div>
          <div>
            <div class="text-sm font-semibold text-white">{{ a.name }}</div>
            <p class="text-[11px] text-gray-400 leading-relaxed mt-0.5">
              {{ appDescription(a) }}
            </p>
          </div>
          <div class="flex items-center justify-between gap-2 mt-auto pt-2 border-t border-white/5">
            <div class="text-[10px] font-mono text-gray-500">
              {{ i18n.t('apps.card.id', { id: a.id }) }}
            </div>
            @if (a.connectorRoute) {
              <a
                [routerLink]="a.connectorRoute"
                class="text-[10px] text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1"
              >
                {{ i18n.t('connectors.action.configure') }} <app-icon name="arrow-right" [size]="10" />
              </a>
            }
          </div>
        </div>
      }
    </div>

    <div class="mt-6 rounded-md p-4 bg-cyan-500/5 ring-1 ring-cyan-500/20 flex items-start gap-3 max-w-2xl">
      <app-icon name="lightbulb" [size]="14" class="text-cyan-400 mt-0.5 shrink-0" />
      <p class="text-[11px] text-cyan-200/90 leading-relaxed">
        {{ i18n.t('apps.footer.lead') }}
        <span class="font-semibold">{{ i18n.t('apps.footer.wired_word') }}</span>
        {{ i18n.t('apps.footer.tail') }}
      </p>
    </div>
  `,
})
export class AppsPageComponent implements OnInit {
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  private readonly api = inject(ApiService);
  readonly i18n = inject(I18nService);

  readonly APPS = RUNTIME_APPS;
  readonly filter = signal<Filter>('all');
  private readonly version = signal(0);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly loadError = signal<string | null>(null);
  /** Server-authoritative enabled ids. */
  private readonly enabledIds = signal<Set<string>>(new Set());

  /** Label keys resolved with t() in the template so the pills react to
   * locale changes (a label frozen here would not). */
  readonly filters = [
    { id: 'all' as Filter, labelKey: 'common.all', count: () => RUNTIME_APPS.length },
    { id: 'enabled' as Filter, labelKey: 'apps.filter.enabled', count: () => this.enabledCount() },
    { id: 'ready' as Filter, labelKey: 'apps.filter.ready', count: () => this.readyCount() },
    { id: 'beta' as Filter, labelKey: 'apps.filter.beta', count: () => this.betaCount() },
  ];

  readonly filtered = computed<AppDef[]>(() => {
    this.version();
    const enabled = this.enabledIds();
    switch (this.filter()) {
      case 'enabled':
        return RUNTIME_APPS.filter((a) => enabled.has(a.id));
      case 'ready':
        return RUNTIME_APPS.filter((a) => a.status === 'ready');
      case 'beta':
        return RUNTIME_APPS.filter((a) => a.status === 'beta');
      default:
        return RUNTIME_APPS;
    }
  });

  readonly enabledCount = computed(() => {
    this.version();
    return this.enabledIds().size;
  });
  readonly wiredCount = computed(() => RUNTIME_APPS.length);
  readonly wiredEnabledCount = computed(() => {
    this.version();
    const enabled = this.enabledIds();
    return RUNTIME_APPS.filter((a) => enabled.has(a.id)).length;
  });
  readonly readyCount = computed(() => RUNTIME_APPS.filter((a) => a.status === 'ready').length);
  readonly betaCount = computed(() => RUNTIME_APPS.filter((a) => a.status === 'beta').length);

  readonly headerKpis = computed<CkObjectKpi[]>(() => [
    { label: this.i18n.t('apps.kpi.total'), value: String(RUNTIME_APPS.length) },
    {
      label: this.i18n.t('apps.kpi.enabled'),
      value: String(this.enabledCount()),
      hint:
        this.enabledCount() > 0
          ? this.i18n.t('apps.kpi.enabled.hint_on')
          : this.i18n.t('apps.kpi.enabled.hint_off'),
      tone: this.enabledCount() > 0 ? 'pos' : 'neutral',
    },
    {
      label: this.i18n.t('apps.kpi.wired'),
      value: String(this.wiredEnabledCount()),
      hint: this.i18n.t('apps.kpi.wired.hint', { count: this.wiredCount() }),
      tone: this.wiredEnabledCount() > 0 ? 'cool' : 'neutral',
    },
    {
      label: this.i18n.t('apps.kpi.beta'),
      value: String(this.betaCount()),
      tone: this.betaCount() > 0 ? 'warn' : 'neutral',
    },
  ]);

  ngOnInit(): void {
    this.loadFromApi();
  }

  isEnabled(id: string): boolean {
    this.version();
    return this.enabledIds().has(id);
  }

  /** Static catalog entries are translated at render time by stable id, with a
   * fallback to the raw description (rpa_bridge has no key on purpose: its
   * wording is lexicon-restricted, so the source text shows as-is). */
  appDescription(app: AppDef): string {
    const key = `resources.catalog.${app.id}.description`;
    const label = this.i18n.t(key);
    return label === key ? app.description : label;
  }

  toggle(id: string): void {
    const slug = this.workspace.currentSlug();
    if (!slug || this.saving()) return;
    const next = new Set(this.enabledIds());
    const wasEnabled = next.has(id);
    if (wasEnabled) next.delete(id);
    else next.add(id);
    const enabledList = Array.from(next).sort();
    this.saving.set(true);
    this.api
      .put<WorkspaceAppsResponse>(`/workspaces/${encodeURIComponent(slug)}/apps`, {
        enabled: enabledList,
      })
      .subscribe({
        next: (res) => {
          this.applyServerState(res);
          this.saving.set(false);
          const app = appById(id);
          if (app) {
            this.toast.success(
              this.i18n.t(wasEnabled ? 'apps.toast.disabled' : 'apps.toast.enabled', {
                name: app.name,
              }),
              this.i18n.t('apps.toast.title'),
            );
          }
        },
        error: (err) => {
          this.saving.set(false);
          const detail = err?.error?.detail;
          this.toast.error(
            typeof detail === 'string' ? detail : this.i18n.t('apps.toast.update_failed'),
            this.i18n.t('apps.toast.title'),
          );
        },
      });
  }

  private loadFromApi(): void {
    const slug = this.workspace.currentSlug();
    if (!slug) {
      // Fall back to local cache when no workspace is selected.
      this.applyEnabledList(
        Object.entries(readAppToggles(null))
          .filter(([, on]) => on)
          .map(([id]) => id),
      );
      return;
    }
    this.loading.set(true);
    this.loadError.set(null);
    this.api.get<WorkspaceAppsResponse>(`/workspaces/${encodeURIComponent(slug)}/apps`).subscribe({
      next: (res) => {
        this.applyServerState(res);
        this.loading.set(false);
      },
      error: () => {
        // API wins when available; on failure keep local cache so the page stays usable.
        const cached = readAppToggles(slug);
        this.applyEnabledList(
          Object.entries(cached)
            .filter(([, on]) => on)
            .map(([id]) => id),
        );
        this.loadError.set(this.i18n.t('apps.load_error'));
        this.loading.set(false);
      },
    });
  }

  private applyServerState(res: WorkspaceAppsResponse): void {
    const enabled = Array.isArray(res?.enabled) ? res.enabled : [];
    this.applyEnabledList(enabled);
    writeAppToggles(this.workspace.currentSlug(), enabled);
  }

  private applyEnabledList(enabled: string[]): void {
    const runtimeIds = new Set(RUNTIME_APPS.map((app) => app.id));
    this.enabledIds.set(new Set(enabled.filter((id) => runtimeIds.has(id))));
    this.version.update((v) => v + 1);
  }
}
