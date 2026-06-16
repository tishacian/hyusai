import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
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

type WindowKey = '24h' | '7d';

@Component({
  selector: 'app-workspace-monitor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    PageFrameComponent,
    StatReadoutComponent,
    TagComponent,
    GlyphComponent,
    EmptyStateComponent,
    IconComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Measure · Observability"
      title="Workspace monitor"
      description="Live workspace operations: systems, runs, jobs, quality signals and operator alerts."
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
          (click)="refresh(true)"
          [disabled]="loading()"
        >
          <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" />
          Refresh
        </button>
      </div>

      @if (loading() && !overview()) {
        <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
          @for (_ of [0, 1, 2, 3]; track $index) {
            <div class="h-24 animate-pulse rounded-md border border-white/5 bg-white/[0.03]"></div>
          }
        </div>
      } @else if (!overview()) {
        <app-empty-state
          icon="activity"
          title="No workspace telemetry"
          description="Run the chat or launch a system to populate workspace observability."
        />
      } @else {
        @if (alerts().length) {
          <section class="mb-4 rounded-md border border-amber-400/20 bg-amber-400/5 p-3">
            <div class="mb-2 flex items-center gap-2">
              <ck-glyph name="warn" [size]="13" />
              <span class="ck-mono text-[10px] uppercase tracking-[0.16em] text-amber-200">Operator alerts</span>
              <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ alerts().length }}</span>
            </div>
            <div class="grid grid-cols-1 gap-2 lg:grid-cols-2">
              @for (alert of alerts().slice(0, 4); track alert.id) {
                <a [routerLink]="alert.route" class="rounded border border-white/5 bg-black/20 px-3 py-2 text-sm text-gray-200 hover:border-brand-400/40">
                  <div class="flex items-center gap-2">
                    <span class="h-1.5 w-1.5 rounded-full" [style.background]="toneColor(alert.tone)"></span>
                    <span class="truncate">{{ alert.label }}</span>
                    <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ relative(alert.timestamp) }}</span>
                  </div>
                </a>
              }
            </div>
          </section>
        }

        <section class="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-6">
          <ck-stat-readout variant="tile" label="Runs" [value]="summary().runs_total" icon="activity" tone="cool" />
          <ck-stat-readout variant="tile" label="Completed" [value]="summary().runs_completed" icon="check" tone="pos" />
          <ck-stat-readout variant="tile" label="Running" [value]="summary().runs_running" icon="play" tone="warn" />
          <ck-stat-readout variant="tile" label="Failed" [value]="summary().runs_failed" icon="warn" tone="neg" />
          <ck-stat-readout variant="tile" label="P95 latency" [value]="duration(summary().p95_latency_ms)" icon="telemetry" tone="violet" />
          <ck-stat-readout variant="tile" label="Eval breaches" [value]="overview()!.evaluations.breaches" icon="shield" tone="warn" />
        </section>

        <section class="mb-5 rounded-md border border-emerald-400/15 bg-emerald-400/[0.035]">
          <header class="flex items-center gap-2 border-b border-emerald-400/10 px-4 py-3">
            <ck-glyph name="flow" [size]="14" />
            <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-emerald-200">Retrieval decisions</h2>
            <span class="ck-mono ml-auto text-[10px] text-emerald-300/70">
              {{ overview()!.retrieval_decisions?.total || 0 }} traced · {{ overview()!.retrieval_decisions?.missing || 0 }} missing
            </span>
          </header>
          <div class="grid grid-cols-1 gap-3 p-4 xl:grid-cols-12">
            <div class="xl:col-span-7">
              @if (retrievalRoutes().length) {
                <div class="grid gap-2 md:grid-cols-2">
                  @for (route of retrievalRoutes().slice(0, 6); track route.route) {
                    <div class="rounded border border-white/5 bg-black/20 px-3 py-2">
                      <div class="ck-mono text-[10px] uppercase tracking-[0.14em] text-gray-500">Route</div>
                      <div class="mt-1 flex items-center gap-2">
                        <span class="truncate text-sm font-medium text-white">{{ routeLabel(route.route) }}</span>
                        <span class="ck-mono ml-auto text-xs text-emerald-300">{{ route.count }}</span>
                      </div>
                    </div>
                  }
                </div>
              } @else {
                <app-empty-state size="sm" icon="git-branch" title="No decision trace yet" description="Run the chat to capture retrieval routing decisions." />
              }
            </div>
            <div class="xl:col-span-5 grid grid-cols-2 gap-2">
              <ck-stat-readout variant="tile" label="Sparse fallbacks" [value]="summary().sparse_fallbacks || 0" icon="warn" tone="warn" />
              <ck-stat-readout variant="tile" label="Sparse timeouts" [value]="summary().sparse_timeouts || 0" icon="timer" tone="warn" />
              <ck-stat-readout variant="tile" label="Cross issues" [value]="summary().cross_encoder_issues || 0" icon="shield" tone="neg" />
              <ck-stat-readout variant="tile" label="Deep launched" [value]="summary().deep_launched || 0" icon="rocket" tone="violet" />
            </div>
          </div>
        </section>

        <div class="grid grid-cols-1 gap-5 xl:grid-cols-12">
          <section class="rounded-md border border-white/10 bg-white/[0.03] xl:col-span-7">
            <header class="flex items-center gap-2 border-b border-white/5 px-4 py-3">
              <ck-glyph name="flow" [size]="14" />
              <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-gray-200">Systems</h2>
              <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ systems().length }}</span>
            </header>
            @if (!systems().length) {
              <app-empty-state size="sm" icon="box" title="No systems" description="No active system is attached to this workspace." />
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
              <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-gray-200">Jobs</h2>
              <span class="ck-mono ml-auto text-[10px] text-gray-500">{{ jobs().length }}</span>
            </header>
            @if (!jobs().length) {
              <app-empty-state size="sm" icon="briefcase" title="No recent jobs" description="Deep Search, SFTP and indexing jobs will appear here." />
            } @else {
              <div class="divide-y divide-white/5">
                @for (job of jobs().slice(0, 8); track job.id) {
                  <a [routerLink]="job.route || '/observability'" class="block px-4 py-3 hover:bg-white/[0.035]">
                    <div class="flex items-center gap-2">
                      <span class="h-1.5 w-1.5 rounded-full" [style.background]="toneColor(statusTone(job.status))"></span>
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
            <h2 class="ck-mono text-[11px] uppercase tracking-[0.18em] text-gray-200">Activity timeline</h2>
            <span class="ck-mono ml-auto text-[10px] text-gray-500">
              updated {{ relative(overview()!.generated_at) }}
            </span>
          </header>
          @if (!timeline().length) {
            <app-empty-state size="sm" icon="clock" title="No recent activity" description="Runs, jobs and evaluations will stream into this timeline." />
          } @else {
            <ol class="divide-y divide-white/5">
              @for (item of timeline().slice(0, 12); track item.id) {
                <li>
                  <a [routerLink]="item.route" class="grid grid-cols-12 gap-3 px-4 py-2.5 text-sm hover:bg-white/[0.035]">
                    <div class="col-span-1 flex items-center">
                      <span class="h-2 w-2 rounded-full" [style.background]="toneColor(item.tone)"></span>
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
    </ck-page-frame>
  `,
})
export class WorkspaceMonitorComponent implements OnInit, OnDestroy {
  private readonly canonical = inject(CanonicalApiService);
  private pollTimer: ReturnType<typeof setTimeout> | null = null;

  readonly windows: WindowKey[] = ['24h', '7d'];
  readonly window = signal<WindowKey>('24h');
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
    this.refresh(true);
  }

  ngOnDestroy(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
  }

  setWindow(window: WindowKey): void {
    this.window.set(window);
    this.refresh(true);
  }

  refresh(manual = false): void {
    if (manual) {
      if (this.pollTimer) clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    this.loading.set(true);
    this.canonical.workspaceOverview(this.window()).subscribe({
      next: (overview) => {
        this.overview.set(overview);
        this.loading.set(false);
        this.scheduleNextPoll();
      },
      error: () => {
        this.loading.set(false);
        this.scheduleNextPoll();
      },
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
    if (delta < 60_000) return 'now';
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
    if (tone === 'violet') return 'var(--ck-signal-violet)';
    return 'var(--ck-signal-cool)';
  }
}
