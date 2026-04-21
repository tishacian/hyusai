import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import {
  APPS,
  CONNECTOR_CATEGORIES,
  CONNECTORS,
  ConnectorDef,
  hasConnectorConfig,
  readAppToggles,
  readConnectorConfig,
  writeAppToggle,
  writeConnectorConfig,
} from './resources.catalog';

interface ModelInfo {
  id?: string;
  name?: string;
  provider?: string;
  context_length?: number;
  size?: number;
  modified_at?: string;
  [key: string]: unknown;
}

type Tab = 'models' | 'connectors' | 'apps';

@Component({
  selector: 'app-resources-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NgClass,
    RouterLink,
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    EmptyStateComponent,
    StatusPulseComponent,
    DrawerComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Configure"
      title="Resources"
      icon="plug"
      subtitle="Models, connectors and apps available to your systems."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refresh()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
    </app-section-header>

    <!-- KPIs -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile label="Models" [value]="models().length" icon="cpu" />
      <app-stat-tile
        label="Providers"
        [value]="providers().length"
        icon="server"
      />
      <app-stat-tile
        label="Connectors"
        [value]="connectorsAvailable()"
        icon="plug"
        [hint]="connectorsActive() + ' configured · ' + connectorsComingSoon() + ' coming'"
      />
      <app-stat-tile
        label="Apps enabled"
        [value]="appsEnabled()"
        icon="sparkles"
        [hint]="APPS.length + ' available'"
      />
    </div>

    <!-- Tabs -->
    <div class="flex items-center gap-1 mb-5 p-1 bg-white/5 ring-1 ring-white/10 rounded-md w-fit">
      @for (t of tabs; track t.id) {
        <button
          type="button"
          (click)="tab.set(t.id)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition"
          [ngClass]="tab() === t.id
            ? 'bg-brand-500 text-white shadow-glow-sm'
            : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'"
        >
          <app-icon [name]="t.icon" [size]="12" />
          {{ t.label }}
          <span
            class="ml-1 text-[9px] font-mono px-1 rounded"
            [class.bg-white\\/15]="tab() === t.id"
            [class.bg-white\\/5]="tab() !== t.id"
          >
            {{ t.count() }}
          </span>
        </button>
      }
    </div>

    <!-- Models tab -->
    @if (tab() === 'models') {
      <section class="t-card t-elevated rounded-md overflow-hidden">
        <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="cpu" [size]="16" class="text-brand-400" />
            Available models
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ models().length }} / {{ providers().length }} providers
          </span>
        </div>

        @if (loading() && models().length === 0) {
          <div class="divide-y divide-white/5">
            @for (_ of [0, 1, 2, 3, 4]; track $index) {
              <div class="px-5 py-3 animate-pulse">
                <div class="h-3 w-60 bg-white/5 rounded"></div>
              </div>
            }
          </div>
        } @else if (models().length === 0) {
          <app-empty-state
            icon="cpu"
            title="No models configured"
            description="Configure a provider in backend settings or start an Ollama instance."
          />
        } @else {
          <ul class="divide-y divide-white/5">
            @for (m of models(); track modelKey(m)) {
              <li class="px-5 py-3 grid grid-cols-12 gap-3 items-center text-sm" [title]="usageLabel(m)">
                <div class="col-span-6 min-w-0 flex items-center gap-2">
                  <div class="w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold shrink-0 bg-gradient-to-br from-brand-500/20 to-violet-500/20 ring-1 ring-brand-500/30 text-brand-400">
                    {{ providerInitial(m) }}
                  </div>
                  <div class="min-w-0">
                    <div class="text-white truncate font-mono text-xs">{{ modelName(m) }}</div>
                    @if (m.provider) {
                      <div class="text-[11px] text-gray-500 capitalize">{{ m.provider }}</div>
                    }
                  </div>
                </div>
                <div class="col-span-2 text-xs text-gray-400 font-mono tabular-nums">
                  @if (m.context_length) {
                    {{ (m.context_length / 1000).toFixed(0) }}k ctx
                  }
                </div>
                <div class="col-span-2 text-xs text-gray-400 font-mono tabular-nums">
                  @if (m.size) {
                    {{ (m.size / 1e9).toFixed(1) }} GB
                  }
                </div>
                <div class="col-span-1 text-xs text-right">
                  @if (usageCount(m) > 0) {
                    <span
                      class="font-mono text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20"
                      [title]="'Pinned by: ' + (systemUsage()[modelKey(m)] || systemUsage()[modelName(m)] || []).join(', ')"
                    >
                      {{ usageLabel(m) }}
                    </span>
                  } @else {
                    <span class="text-gray-600">—</span>
                  }
                </div>
                <div class="col-span-1 text-right">
                  <app-status-pulse tone="success" label="ready" />
                </div>
              </li>
            }
          </ul>
        }
      </section>
    }

    <!-- Connectors tab -->
    @if (tab() === 'connectors') {
      @for (cat of categories; track cat.id) {
        <section class="mb-6">
          <header class="flex items-center gap-2 mb-3">
            <app-icon [name]="cat.icon" [size]="14" class="text-brand-400" />
            <h3 class="text-[10px] uppercase tracking-[0.16em] font-semibold text-gray-400">
              {{ cat.label }}
            </h3>
            <span class="text-[9px] font-mono text-gray-500">
              {{ connectorsInCategory(cat.id).length }}
            </span>
            <div class="flex-1 h-px bg-white/5 ml-2"></div>
          </header>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            @for (c of connectorsInCategory(cat.id); track c.id) {
              <button
                type="button"
                (click)="openConnector(c)"
                class="group t-card t-elevated rounded-md p-4 text-left relative hover:-translate-y-0.5 transition-transform"
              >
                <div class="flex items-start justify-between mb-2.5">
                  <div
                    class="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
                    [ngClass]="c.status === 'coming-soon'
                      ? 'bg-white/5 text-gray-400'
                      : 'bg-brand-500/15 text-brand-400'"
                  >
                    <app-icon [name]="c.icon" [size]="18" />
                  </div>
                  @if (c.status === 'active' || isConfigured(c.id)) {
                    <app-status-pulse tone="success" label="connected" />
                  } @else if (c.status === 'available') {
                    <app-status-pulse tone="accent" label="available" />
                  } @else {
                    <span class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20">
                      Soon
                    </span>
                  }
                </div>
                <h4 class="text-sm font-semibold text-white mb-1">{{ c.name }}</h4>
                <p class="text-[11px] text-gray-400 leading-relaxed line-clamp-2">
                  {{ c.description }}
                </p>
                <div class="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
                  <span class="text-[10px] font-mono text-gray-500">{{ c.version }}</span>
                  <span class="text-[10px] font-medium flex items-center gap-1 text-brand-400 group-hover:gap-1.5 transition-all">
                    Configure <app-icon name="arrow-right" [size]="10" />
                  </span>
                </div>
              </button>
            }
          </div>
        </section>
      }
    }

    <!-- Apps tab -->
    @if (tab() === 'apps') {
      <div class="mb-4 flex items-center justify-between">
        <div>
          <h3 class="text-sm font-semibold text-white mb-0.5">Apps & skills</h3>
          <p class="text-xs text-gray-500">
            Enable capabilities the orchestrator can plug into any system. Changes
            are saved locally and respected by the builder wizard.
          </p>
        </div>
        <a
          routerLink="/apps"
          class="text-[11px] text-brand-400 hover:text-brand-300 inline-flex items-center gap-1"
        >
          Dedicated page <app-icon name="arrow-right" [size]="10" />
        </a>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        @for (a of APPS; track a.id) {
          <div
            class="t-card t-elevated rounded-md p-4 flex flex-col gap-2.5 transition"
            [ngClass]="isAppEnabled(a.id)
              ? 'ring-1 ring-brand-500/40 bg-brand-500/5'
              : ''"
          >
            <div class="flex items-start justify-between">
              <div
                class="w-9 h-9 rounded-md flex items-center justify-center"
                [ngClass]="isAppEnabled(a.id)
                  ? 'bg-brand-500/20 text-brand-300'
                  : 'bg-white/5 text-gray-400'"
              >
                <app-icon [name]="a.icon" [size]="18" />
              </div>
              <div class="flex items-center gap-2">
                <span
                  class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ring-1"
                  [ngClass]="a.status === 'ready'
                    ? 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-400 ring-amber-500/20'"
                >
                  {{ a.status }}
                </span>
                <button
                  type="button"
                  (click)="toggleApp(a.id)"
                  role="switch"
                  [attr.aria-checked]="isAppEnabled(a.id)"
                  class="w-9 h-5 rounded-full relative transition-colors"
                  [ngClass]="isAppEnabled(a.id) ? 'bg-brand-500' : 'bg-white/10'"
                >
                  <span
                    class="block w-3.5 h-3.5 bg-white rounded-full absolute top-[3px] transition-all"
                    [ngClass]="isAppEnabled(a.id) ? 'left-[20px]' : 'left-[3px]'"
                  ></span>
                </button>
              </div>
            </div>
            <div>
              <div class="text-sm font-semibold text-white">{{ a.name }}</div>
              <p class="text-[11px] text-gray-400 leading-relaxed mt-0.5">
                {{ a.description }}
              </p>
            </div>
          </div>
        }
      </div>
    }

    <!-- Connector config drawer -->
    <app-drawer
      [open]="drawerOpen()"
      [title]="active()?.name ?? 'Connector'"
      [subtitle]="active()?.version ?? ''"
      [icon]="active()?.icon ?? 'plug'"
      [width]="440"
      (close)="closeDrawer()"
    >
      @if (active(); as c) {
        <div class="space-y-5">
          <p class="text-xs text-gray-400 leading-relaxed">{{ c.description }}</p>

          @if (c.backendPrefix) {
            <div class="rounded-md bg-emerald-500/5 ring-1 ring-emerald-500/20 p-3 flex items-start gap-2">
              <app-icon name="check-circle-2" [size]="14" class="text-emerald-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-emerald-200/90 leading-relaxed">
                Backend endpoint live at
                <span class="font-mono text-emerald-300">/api/v1/{{ c.backendPrefix }}</span>.
                Save configuration then hit <span class="font-semibold">Test connection</span>.
              </div>
            </div>
          } @else if (c.status === 'coming-soon') {
            <div class="rounded-md bg-amber-500/5 ring-1 ring-amber-500/20 p-3 flex items-start gap-2">
              <app-icon name="clock" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-amber-200/90 leading-relaxed">
                Backend adapter not shipped yet — configuration is saved locally so you can
                pre-fill it and migrate later.
              </div>
            </div>
          } @else {
            <div class="rounded-md bg-brand-500/5 ring-1 ring-brand-500/20 p-3 flex items-start gap-2">
              <app-icon name="info" [size]="14" class="text-brand-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-brand-200/90 leading-relaxed">
                Configuration is stored locally. Backend adapter will pick it up automatically
                once registered.
              </div>
            </div>
          }

          <form (ngSubmit)="saveConnector()" class="space-y-4">
            @for (f of c.fields; track f.key) {
              <div>
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ f.label }}
                  @if (f.required) {
                    <span class="text-red-400">*</span>
                  }
                </label>
                <input
                  [type]="f.type"
                  [value]="draftValues[f.key] || ''"
                  (input)="onFieldInput(f.key, $event)"
                  [placeholder]="f.placeholder ?? ''"
                  [required]="!!f.required"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 focus:border-brand-500/50 transition text-sm"
                />
              </div>
            }

            <div class="flex items-center gap-2 pt-2">
              <button
                type="submit"
                class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-brand-500 hover:bg-brand-600 text-white text-sm font-medium shadow-glow-sm transition"
              >
                <app-icon name="save" [size]="14" /> Save
              </button>
              <button
                type="button"
                (click)="testConnector()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
              >
                <app-icon name="zap" [size]="14" /> Test
              </button>
              <button
                type="button"
                (click)="clearConnector()"
                class="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded text-red-300 hover:bg-red-500/10 text-sm transition"
              >
                <app-icon name="trash-2" [size]="14" /> Clear
              </button>
            </div>
          </form>
        </div>
      }
    </app-drawer>
  `,
})
export class ResourcesPageComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);

  readonly APPS = APPS;
  readonly categories = CONNECTOR_CATEGORIES;
  readonly allConnectors = CONNECTORS;

  readonly tab = signal<Tab>('models');

  readonly models = signal<ModelInfo[]>([]);
  readonly loading = signal(false);

  // Reverse index model_id (provider:name | name) → list of systems pinning it,
  // populated from the canonical `/systems` list so the Models tab can show
  // which Systems override each model.
  readonly systemUsage = signal<Record<string, string[]>>({});

  readonly active = signal<ConnectorDef | null>(null);
  readonly drawerOpen = signal(false);
  draftValues: Record<string, string> = {};

  private readonly appsVersion = signal(0);
  private readonly connectorsVersion = signal(0);

  readonly providers = computed(() => {
    const set = new Set<string>();
    for (const m of this.models()) if (m.provider) set.add(m.provider);
    return Array.from(set);
  });

  readonly connectorsActive = computed(() => {
    this.connectorsVersion();
    return CONNECTORS.filter((c) => c.status === 'active' || hasConnectorConfig(c.id)).length;
  });
  readonly connectorsAvailable = computed(() => CONNECTORS.filter((c) => c.status !== 'coming-soon').length);
  readonly connectorsComingSoon = computed(() => CONNECTORS.filter((c) => c.status === 'coming-soon').length);
  readonly appsEnabled = computed(() => {
    this.appsVersion();
    const t = readAppToggles();
    return Object.values(t).filter(Boolean).length;
  });

  readonly tabs = [
    { id: 'models' as Tab, label: 'Models', icon: 'cpu', count: () => this.models().length },
    { id: 'connectors' as Tab, label: 'Connectors', icon: 'plug', count: () => CONNECTORS.length },
    { id: 'apps' as Tab, label: 'Apps', icon: 'sparkles', count: () => APPS.length },
  ];

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.api.get<{ models: ModelInfo[] } | ModelInfo[]>('/models').subscribe({
      next: (res) => {
        const list = Array.isArray(res) ? res : res?.models ?? [];
        this.models.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.models.set([]);
        this.loading.set(false);
      },
    });
    this.refreshSystemUsage();
  }

  private refreshSystemUsage(): void {
    this.api
      .get<{ systems: Array<{ id: string; name: string; default_model?: string | null }> } | Array<{ id: string; name: string; default_model?: string | null }>>('/systems')
      .subscribe({
        next: (res) => {
          const systems = Array.isArray(res) ? res : res?.systems ?? [];
          const idx: Record<string, string[]> = {};
          for (const s of systems) {
            if (!s.default_model) continue;
            if (!idx[s.default_model]) idx[s.default_model] = [];
            idx[s.default_model].push(s.name);
          }
          this.systemUsage.set(idx);
        },
        error: () => this.systemUsage.set({}),
      });
  }

  usageCount(m: ModelInfo): number {
    const idx = this.systemUsage();
    const byQualified = idx[this.modelKey(m)] ?? [];
    const byPlain = idx[this.modelName(m)] ?? [];
    return byQualified.length + byPlain.length;
  }

  usageLabel(m: ModelInfo): string {
    const n = this.usageCount(m);
    if (n === 0) return '';
    return n === 1 ? '1 system' : `${n} systems`;
  }

  connectorsInCategory(id: string): ConnectorDef[] {
    return CONNECTORS.filter((c) => c.category === id);
  }

  isConfigured(id: string): boolean {
    this.connectorsVersion();
    return hasConnectorConfig(id);
  }

  openConnector(c: ConnectorDef): void {
    this.active.set(c);
    this.draftValues = { ...readConnectorConfig(c.id) };
    this.drawerOpen.set(true);
  }

  closeDrawer(): void {
    this.drawerOpen.set(false);
  }

  onFieldInput(key: string, ev: Event): void {
    const input = ev.target as HTMLInputElement;
    this.draftValues = { ...this.draftValues, [key]: input.value };
  }

  saveConnector(): void {
    const c = this.active();
    if (!c) return;
    writeConnectorConfig(c.id, this.draftValues);
    this.connectorsVersion.update((v) => v + 1);
    this.toast.success(`${c.name} configuration saved`, 'Connector');
    this.drawerOpen.set(false);
  }

  testConnector(): void {
    const c = this.active();
    if (!c) return;
    if (c.backendPrefix === 'sharepoint') {
      this.api.get(`/${c.backendPrefix}/health`).subscribe({
        next: () => this.toast.success(`${c.name} reachable`, 'Connection test'),
        error: () =>
          this.toast.error(`${c.name} is unreachable — check the backend`, 'Connection test'),
      });
      return;
    }
    this.toast.info(
      `${c.name} doesn't have a live adapter yet. Config is stored locally.`,
      'Simulated test',
    );
  }

  clearConnector(): void {
    const c = this.active();
    if (!c) return;
    this.draftValues = {};
    writeConnectorConfig(c.id, {});
    this.connectorsVersion.update((v) => v + 1);
    this.toast.info(`${c.name} configuration cleared`, 'Connector');
  }

  isAppEnabled(id: string): boolean {
    this.appsVersion();
    return !!readAppToggles()[id];
  }

  toggleApp(id: string): void {
    const current = !!readAppToggles()[id];
    writeAppToggle(id, !current);
    this.appsVersion.update((v) => v + 1);
  }

  modelName(m: ModelInfo): string {
    return (
      (typeof m.id === 'string' && m.id) ||
      (typeof m.name === 'string' && m.name) ||
      JSON.stringify(m)
    );
  }

  modelKey(m: ModelInfo): string {
    return this.modelName(m) + ':' + (m.provider ?? '');
  }

  providerInitial(m: ModelInfo): string {
    const p = (m.provider || this.modelName(m)).toString();
    return p.charAt(0).toUpperCase();
  }
}
