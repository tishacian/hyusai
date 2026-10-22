import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import {
  CanonicalApiService,
  type ActivityTimelineItem,
  type JobHealthRow,
  type ObservabilityAlert,
  type SystemHealthRow,
  type WorkspaceOverview,
} from '@app/core/canonical-api.service';
import {
  type CkTagTone,
  GlyphComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { IconComponent } from '@app/shared/ui/icon.component';

import { FormsModule } from '@angular/forms';
import { navigationSurfaceUrl } from '@app/core/navigation.catalog';
import { Subscription } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { observabilityAnchor, observabilityPeriod, observabilitySystemId } from './observability-facets';
import { ActivityApiService } from './activities/activity-api.service';
import { ACTIVE_ACTIVITY_STATUS_FILTER } from './activities/activity.models';
import { ActivitySeriesComponent } from './activities/activity-series.component';
import { runTiles, seriesRange, type ActivitySeries } from './activities/activity-series.vm';
type WindowKey = '24h' | '7d' | '30d';

@Component({
  selector: 'app-workspace-monitor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink, ActivitySeriesComponent, FormsModule,
    PageFrameComponent,
    StatReadoutComponent,
    TagComponent,
    GlyphComponent,
    EmptyStateComponent,
    IconComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="t('context')"
      [title]="t('title')"
      [description]="t('description')"
    >
      <div actions class="inline-flex items-center gap-2">
        <div class="inline-flex items-center rounded border border-white/10 bg-white/[0.03] p-0.5">
          @for (item of windows; track item) {
            <button
              type="button"
              class="ck-mono h-7 rounded px-3 text-[10px] uppercase tracking-[0.14em]"
              [style.background]="window() === item ? 'var(--ck-bg-panel-hi)' : 'transparent'"
              [style.color]="window() === item ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
              (click)="setWindow(item)"
            >
              {{ item }}
            </button>
          }
        </div>
        <button
          type="button"
          class="ck-mono inline-flex h-7 items-center gap-1.5 rounded border border-white/10 bg-white/[0.03] px-3 text-[10px] uppercase tracking-[0.12em] text-gray-200 hover:bg-white/[0.07]"
          (click)="refreshAnchor()"
          [disabled]="loading()"
        >
          <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" />
          {{ t('refresh') }}
        </button>
      </div>

      <label class="block my-3">{{ i18n.t('observability.charts.system') }} <select [ngModel]="systemId()" (ngModelChange)="setSystem($event)"><option value="">{{ i18n.t('observability.charts.all_systems') }}</option>@for(system of systems();track system.id){<option [value]="system.id">{{ system.name }}</option>}</select></label>
      @if (seriesEnabled()) { <app-activity-series [systemId]="systemId()" kind="run" [since]="window()" [asOf]="asOf()" [compact]="true" /> }
      @if (error()) { <p role="alert" data-testid="operations-error">{{ t('load_error') }}</p> }
      @if (overview(); as data) { <p class="coverage-note" data-testid="operations-coverage">{{ t('sample') }} · {{ t('clock') }} · {{ data.as_of || asOf() }}</p> }
      @if (loading() && !overview()) {
        <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
          @for (_ of [0, 1, 2, 3]; track $index) {
            <div class="h-24 animate-pulse rounded-md border border-white/5 bg-white/[0.03]"></div>
          }
        </div>
      } @else if (!overview()) {
        <app-empty-state
          icon="activity"
          [title]="t('empty')"
          [description]="t('empty_hint')"
        />
      } @else {
        @if (alerts().length) {
          <section class="mb-4 rounded-md border border-amber-400/20 bg-amber-400/5 p-3">
            <div class="mb-2 flex items-center gap-2">
              <ck-glyph name="warn" [size]="13" />
              <span class="ck-mono text-[10px] uppercase tracking-[0.16em] text-amber-200">{{ t('alerts') }}</span>
              <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ alerts().length }}</span>
            </div>
            <div class="grid grid-cols-1 gap-2 lg:grid-cols-2">
              @for (alert of alerts().slice(0, 4); track alert.id) {
                <a [routerLink]="nativeRoute(alert.route)" class="rounded border border-white/5 bg-black/20 px-3 py-2 text-sm text-gray-200 hover:border-cyan-400/40">
                  <div class="flex items-center gap-2">
                    <span class="h-1.5 w-1.5 rounded" [style.background]="toneColor(alert.tone)"></span>
                    <span class="truncate">{{ alert.label }}</span>
                    <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ relative(alert.timestamp) }}</span>
                  </div>
                </a>
              }
            </div>
          </section>
        }

        <section class="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-6" data-testid="operations-tiles" [attr.data-source]="runTileValues() ? 'series' : 'sample'">
          @if (runTileValues(); as tiles) {
            <!-- Exhaustive Run series (R2): each tile opens the matching Activities filter. -->
            <a class="block" data-testid="operations-tile-runs" [routerLink]="observabilityUrl" [queryParams]="tileQuery()" [attr.aria-label]="t('runs') + ' · ' + t('tile_open')"><ck-stat-readout variant="tile" [label]="t('runs')" [value]="tiles.total" icon="activity" tone="cool" /></a>
            <a class="block" data-testid="operations-tile-completed" [routerLink]="observabilityUrl" [queryParams]="tileQuery('succeeded')" [attr.aria-label]="t('completed') + ' · ' + t('tile_open')"><ck-stat-readout variant="tile" [label]="t('completed')" [value]="tiles.succeeded" icon="check" tone="pos" /></a>
            <a class="block" data-testid="operations-tile-running" [routerLink]="observabilityUrl" [queryParams]="tileQuery(activeStatusFilter)" [attr.aria-label]="t('running') + ' · ' + t('tile_open')"><ck-stat-readout variant="tile" [label]="t('running')" [value]="tiles.running" icon="play" tone="warn" /></a>
            <a class="block" data-testid="operations-tile-failed" [routerLink]="observabilityUrl" [queryParams]="tileQuery('failed')" [attr.aria-label]="t('failed') + ' · ' + t('tile_open')"><ck-stat-readout variant="tile" [label]="t('failed')" [value]="tiles.failed" icon="alert-triangle" tone="neg" /></a>
            <a class="block" data-testid="operations-tile-latency" [routerLink]="observabilityUrl" [queryParams]="tileQuery()" [attr.aria-label]="t('latency') + ' · ' + t('tile_open')"><ck-stat-readout variant="tile" [label]="t('latency')" [value]="duration(tiles.p95_ms)" icon="activity" tone="cool" /></a>
          } @else {
            <ck-stat-readout variant="tile" [label]="t('runs')" [value]="summary().runs_total" icon="activity" tone="cool" />
            <ck-stat-readout variant="tile" [label]="t('completed')" [value]="summary().runs_completed" icon="check" tone="pos" />
            <ck-stat-readout variant="tile" [label]="t('running')" [value]="summary().runs_running" icon="play" tone="warn" />
            <ck-stat-readout variant="tile" [label]="t('failed')" [value]="summary().runs_failed" icon="alert-triangle" tone="neg" />
            <ck-stat-readout variant="tile" [label]="t('latency')" [value]="duration(summary().p95_latency_ms)" icon="activity" tone="cool" />
          }
          <ck-stat-readout variant="tile" [label]="t('breaches')" [value]="overview()!.evaluations.breaches" icon="shield" tone="warn" />
        </section>
        @if (runTileValues(); as tiles) {
          <p class="coverage-note" data-testid="operations-tiles-coverage">{{ t('tiles_series', {measured: tiles.measured, eligible: tiles.eligible}) }} · {{ runSeries()!.as_of }}</p>
        }

        <section class="mb-5 rounded-md border border-emerald-400/15 bg-emerald-400/[0.035]">
          <header class="flex items-center gap-2 border-b border-emerald-400/10 px-4 py-3">
            <ck-glyph name="flow" [size]="14" />
            <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-emerald-200">{{ t('decisions') }}</h2>
            <span class="ck-mono ml-auto text-[10px] text-emerald-300/70">
              {{ t('traced', {count: overview()!.retrieval_decisions?.total || 0, missing: overview()!.retrieval_decisions?.missing || 0}) }}
            </span>
          </header>
          <div class="grid grid-cols-1 gap-3 p-4 xl:grid-cols-12">
            <div class="xl:col-span-7">
              @if (retrievalRoutes().length) {
                <div class="grid gap-2 md:grid-cols-2">
                  @for (route of retrievalRoutes().slice(0, 6); track route.route) {
                    <div class="rounded border border-white/5 bg-black/20 px-3 py-2">
                      <div class="ck-mono text-[10px] uppercase tracking-[0.14em] text-gray-500">{{ t('route') }}</div>
                      <div class="mt-1 flex items-center gap-2">
                        <span class="truncate text-sm font-medium text-white">{{ routeLabel(route.route) }}</span>
                        <span class="ck-mono ml-auto text-xs text-emerald-300">{{ route.count }}</span>
                      </div>
                    </div>
                  }
                </div>
              } @else {
                <app-empty-state size="sm" icon="git-branch" [title]="t('decisions_empty')" [description]="t('decisions_hint')" />
              }
            </div>
            <div class="xl:col-span-5 grid grid-cols-2 gap-2">
              <ck-stat-readout variant="tile" [label]="t('sparse_fallbacks')" [value]="summary().sparse_fallbacks || 0" icon="alert-triangle" tone="warn" />
              <ck-stat-readout variant="tile" [label]="t('sparse_timeouts')" [value]="summary().sparse_timeouts || 0" icon="clock" tone="warn" />
              <ck-stat-readout variant="tile" [label]="t('cross_issues')" [value]="summary().cross_encoder_issues || 0" icon="shield" tone="neg" />
              <ck-stat-readout variant="tile" [label]="t('deep_launched')" [value]="summary().deep_launched || 0" icon="rocket" tone="cool" />
            </div>
          </div>
        </section>

        <div class="grid grid-cols-1 gap-5 xl:grid-cols-12">
          <section class="rounded-md border border-white/10 bg-white/[0.03] xl:col-span-7">
            <header class="flex items-center gap-2 border-b border-white/5 px-4 py-3">
              <ck-glyph name="flow" [size]="14" />
              <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-gray-200">{{ t('systems') }}</h2>
              <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ systems().length }}</span>
            </header>
            @if (!systems().length) {
              <app-empty-state size="sm" icon="box" [title]="t('systems_empty')" [description]="t('systems_hint')" />
            } @else {
              <div class="divide-y divide-white/5">
                @for (system of systems(); track system.id) {
                  <a [routerLink]="system.route || ['/systems', system.id]" class="grid grid-cols-12 gap-3 px-4 py-3 text-sm hover:bg-white/[0.035]">
                    <div class="col-span-5 min-w-0">
                      <div class="truncate font-medium text-white">{{ system.name }}</div>
                      <div class="ck-mono mt-0.5 truncate text-[10px] text-gray-500">{{ system.system_type || system.surface || system.id }}</div>
                    </div>
                    <div class="col-span-2">
                      <ck-tag [tone]="system.status === 'active' ? 'pos' : 'cool'" variant="soft">{{ system.status || '—' }}</ck-tag>
                    </div>
                    <div class="ck-mono col-span-2 text-right text-xs text-gray-300">{{ system.runs_total }} runs</div>
                    <div class="ck-mono col-span-2 text-right text-xs text-gray-300">{{ duration(system.avg_latency_ms) }}</div>
                    <div class="ck-mono col-span-1 text-right text-[10px]" [style.color]="toneColor(statusTone(system.latest_run_status))">
                      {{ shortStatus(system.latest_run_status) }}
                    </div>
                  </a>
                }
              </div>
            }
          </section>

          <section class="rounded-md border border-white/10 bg-white/[0.03] xl:col-span-5">
            <header class="flex items-center gap-2 border-b border-white/5 px-4 py-3">
              <ck-glyph name="ledger" [size]="14" />
              <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-gray-200">{{ t('work_items') }}</h2>
              <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ jobs().length }}</span>
            </header>
            @if (!jobs().length) {
              <app-empty-state size="sm" icon="briefcase" [title]="t('work_items_empty')" [description]="t('work_items_hint')" />
            } @else {
              <div class="divide-y divide-white/5">
                @for (job of jobs().slice(0, 8); track job.id) {
                  <a [routerLink]="nativeRoute(job.route || observabilityUrl)" class="block px-4 py-3 hover:bg-white/[0.035]">
                    <div class="flex items-center gap-2">
                      <span class="h-1.5 w-1.5 rounded" [style.background]="toneColor(statusTone(job.status))"></span>
                      <span class="truncate text-sm font-medium text-white">{{ job.title || job.kind }}</span>
                      <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ relative(job.updated_at || job.created_at) }}</span>
                    </div>
                    <div class="mt-1 flex items-center gap-2">
                      <ck-tag [tone]="tagTone(job.status)" variant="outline">{{ job.status }}</ck-tag>
                      <span class="ck-mono truncate text-[10px] text-gray-500">{{ job.kind }} · {{ job.stage || '—' }}</span>
                    </div>
                  </a>
                }
              </div>
            }
          </section>
        </div>

        <section class="mt-5 rounded-md border border-white/10 bg-white/[0.03]">
          <header class="flex items-center gap-2 border-b border-white/5 px-4 py-3">
            <ck-glyph name="pulse" [size]="14" />
            <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-gray-200">{{ t('timeline') }}</h2>
            <span class="ck-mono ml-auto text-[10px] text-gray-500">
              {{ t('updated') }} {{ relative(overview()!.generated_at) }}
            </span>
          </header>
          @if (!timeline().length) {
            <app-empty-state size="sm" icon="clock" [title]="t('timeline_empty')" [description]="t('timeline_hint')" />
          } @else {
            <ol class="divide-y divide-white/5">
              @for (item of timeline().slice(0, 12); track item.id) {
                <li>
                  <a [routerLink]="nativeRoute(item.route)" class="grid grid-cols-12 gap-3 px-4 py-2.5 text-sm hover:bg-white/[0.035]">
                    <div class="col-span-1 flex items-center">
                      <span class="h-2 w-2 rounded" [style.background]="toneColor(item.tone)"></span>
                    </div>
                    <div class="col-span-7 truncate text-gray-200">{{ item.label }}</div>
                    <div class="ck-mono col-span-2 text-[10px] uppercase tracking-[0.12em] text-gray-500">{{ item.kind }}</div>
                    <div class="ck-mono col-span-2 text-right text-[10px] text-gray-500">{{ relative(item.timestamp) }}</div>
                  </a>
                </li>
              }
            </ol>
          }
        </section>
      }
      <a [routerLink]="observabilityUrl" [queryParams]="{facet:'activities',systemId:systemId() || null,since:window(),as_of:asOf(),kind:'run'}">{{ i18n.t('observability.tabs.activities') }}</a>
    </ck-page-frame>
  `,
})
export class WorkspaceMonitorComponent implements OnInit, OnDestroy {
  readonly activeStatusFilter = ACTIVE_ACTIVITY_STATUS_FILTER;
  readonly observabilityUrl = navigationSurfaceUrl('observability');
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly activityApi = inject(ActivityApiService);
  private routeSub?: Subscription;
  private request?: Subscription;
  private resetters: Array<() => void> = [];
  private destroyed = false;
  readonly systemId = signal('');
  readonly asOf = signal(new Date().toISOString());
  readonly error = signal(false);
  readonly seriesEnabled = signal(false);
  readonly runSeries = signal<ActivitySeries | null>(null);
  readonly runTileValues = computed(() => { const series = this.runSeries(); return series ? runTiles(series) : null; });
  private seriesRequest?: AbortController;
  // Tiles follow the period, anchor and System only; the overview's 5–15 s poll
  // never re-reads the exhaustive series.
  private readonly seriesLoader = effect(onCleanup => {
    const context = { enabled: this.seriesEnabled(), since: this.window(), anchor: this.asOf(), system: this.systemId() };
    const request = new AbortController();
    this.seriesRequest?.abort(); this.seriesRequest = request;
    onCleanup(() => request.abort());
    untracked(() => void this.loadRunSeries(context, request.signal));
  });
  t(key: string, params?: Record<string, string | number>): string { return this.i18n.t('observability.operations.' + key, params); }
  private pollTimer: ReturnType<typeof setTimeout> | null = null;

  readonly windows: WindowKey[] = ['24h', '7d', '30d'];
  readonly window = signal<WindowKey>('7d');
  readonly overview = signal<WorkspaceOverview | null>(null);
  readonly loading = signal(false);

  readonly summary = computed(() => this.overview()?.summary ?? {
    active_systems: 0,
    runs_total: 0,
    runs_completed: 0,
    runs_failed: 0,
    runs_running: 0,
    avg_latency_ms: null,
    p95_latency_ms: null,
    jobs_total: 0,
    jobs_active: 0,
    jobs_failed: 0,
    evaluations_total: 0,
    alerts_total: 0,
    retrieval_traces_total: 0,
    retrieval_traces_missing: 0,
    sparse_timeouts: 0,
    sparse_fallbacks: 0,
    cross_encoder_issues: 0,
    deep_recommended: 0,
    deep_launched: 0,
  });
  readonly systems = computed<SystemHealthRow[]>(() => this.overview()?.systems ?? []);
  readonly jobs = computed<JobHealthRow[]>(() => this.overview()?.jobs ?? []);
  readonly alerts = computed<ObservabilityAlert[]>(() => this.overview()?.alerts ?? []);
  readonly timeline = computed<ActivityTimelineItem[]>(() => this.overview()?.timeline ?? []);
  readonly retrievalRoutes = computed(() => this.overview()?.retrieval_decisions?.routes ?? []);

  ngOnInit(): void {
    this.routeSub = this.route.queryParamMap.subscribe(params => {
      const period = observabilityPeriod(params.get('since'));
      this.window.set(period === '90d' ? '30d' : period); this.systemId.set(observabilitySystemId(params));
      this.asOf.set(observabilityAnchor(params.get('as_of'), this.asOf())); this.refresh(true);
    });
    this.resetters.push(this.workspace.registerContextReset(() => { this.clear(); queueMicrotask(() => { if (!this.destroyed) { this.refresh(true); void this.discover(); } }); }));
    this.resetters.push(this.auth.registerContextReset(() => this.clear()));
    void this.discover();
  }
  private async discover(): Promise<void> { try { const f = await this.activityApi.features(); if (!this.destroyed) this.seriesEnabled.set(!!f.enabled && !!f.activity_series_enabled); } catch { this.seriesEnabled.set(false); } }
  private clear(): void { this.request?.unsubscribe(); this.seriesRequest?.abort(); if (this.pollTimer) clearTimeout(this.pollTimer); this.overview.set(null); this.runSeries.set(null); this.seriesEnabled.set(false); }
  private async loadRunSeries(context: { enabled: boolean; since: string; anchor: string; system: string }, signal: AbortSignal): Promise<void> {
    this.runSeries.set(null);
    if (!context.enabled) return;
    try {
      const query: Record<string, string> = { ...seriesRange(context.since, context.anchor), metric: 'activity', kind: 'run', time_basis: 'created' };
      if (context.system) query['system_id'] = context.system;
      const series = await this.activityApi.series(query, signal);
      if (!signal.aborted && !this.destroyed) this.runSeries.set(series);
    } catch {
      // The sampled tiles stay in place; the chart below reports its own error.
      if (!signal.aborted && !this.destroyed) this.runSeries.set(null);
    }
  }
  tileQuery(status?: string) { return { facet: 'activities', systemId: this.systemId() || null, since: this.window(), as_of: this.asOf(), kind: 'run', status: status ?? null }; }
  ngOnDestroy(): void { this.destroyed = true; this.clear(); this.routeSub?.unsubscribe(); this.resetters.forEach(reset => reset()); }
  nativeRoute(url: string) { const tree = this.router.parseUrl(url); if (tree.root.children['primary']?.segments.map(part => part.path).join('/') === 'observability') tree.queryParams = { since: this.window(), as_of: this.asOf(), systemId: this.systemId() || undefined, ...tree.queryParams }; return tree; }
  setSystem(systemId: string): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { systemId: systemId || null }, queryParamsHandling: 'merge' }); }
  setWindow(window: WindowKey): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { since: window }, queryParamsHandling: 'merge' }); }
  refreshAnchor(): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { as_of: new Date().toISOString() }, queryParamsHandling: 'merge' }); }
  refresh(manual = false): void {
    if (this.destroyed) return;
    if (this.pollTimer) clearTimeout(this.pollTimer);
    this.request?.unsubscribe(); this.loading.set(true); this.error.set(false);
    this.request = this.canonical.workspaceOverview(this.window(), { as_of: this.asOf(), ...(this.systemId() ? { system_id: this.systemId() } : {}) }).subscribe({
      next: overview => { this.overview.set(overview); this.loading.set(false); this.scheduleNextPoll(); },
      error: error => { this.error.set(true); this.loading.set(false); if ([401,403,404].includes(error?.status)) this.overview.set(null); else this.scheduleNextPoll(); },
    });
  }

  private scheduleNextPoll(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const active = (this.summary().runs_running || 0) > 0 || (this.summary().jobs_active || 0) > 0;
    this.pollTimer = setTimeout(() => this.refresh(false), active ? 5000 : 15000);
  }

  duration(ms?: number | null): string {
    if (ms == null) return '—';
    if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
    return `${Math.round(ms)}ms`;
  }

  relative(value?: string | null): string {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const delta = Date.now() - date.getTime();
    if (delta < 60_000) return this.t('now');
    if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m`;
    if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h`;
    return `${Math.floor(delta / 86_400_000)}d`;
  }

  statusTone(status?: string | null): CkTagTone {
    if (status === 'completed' || status === 'active') return 'pos';
    if (status === 'failed' || status === 'cancelled') return 'neg';
    if (status === 'running' || status === 'queued' || status === 'pending' || status === 'created') return 'warn';
    return 'cool';
  }

  tagTone(status?: string | null): CkTagTone {
    return this.statusTone(status);
  }

  shortStatus(status?: string | null): string {
    return status ? status.slice(0, 4).toUpperCase() : '—';
  }

  routeLabel(route?: string | null): string {
    return String(route || 'retrieval').replace(/_/g, ' ');
  }

  toneColor(tone?: string | null): string {
    if (tone === 'pos') return 'var(--ck-signal-pos)';
    if (tone === 'neg') return 'var(--ck-signal-neg)';
    if (tone === 'warn') return 'var(--ck-signal-warn)';
    if (tone === 'cool' || tone === 'info') return 'var(--ck-signal-cool)';
    return 'var(--ck-signal-cool)';
  }
}
