import { formatInstant } from '@app/core/format-instant';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription, firstValueFrom } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { navigationObjectUrl, navigationRunFlowUrl, navigationSurfaceUrl } from '@app/core/navigation.catalog';
import { ActivityApiService, ActivityApiError } from '../observability/activities/activity-api.service';
import { activityLink, type ActivityLink } from '../observability/activities/activity.models';
import type { StreamState } from '../observability/activities/activity-stream';
import { RunExecutionApiService } from './run-execution-api.service';
import { RunExecutionGraphComponent } from './run-execution-graph.component';
import { executionInterval, executionTimeline, type ExecutionItem, type RunExecutionView } from './run-execution.models';
@Component({ selector: 'app-run-execution-view', standalone: true, imports: [FormsModule, RouterLink, RunExecutionGraphComponent], changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './run-execution-view.component.html', styleUrl: './run-execution-view.component.css' })
export class RunExecutionViewComponent implements OnInit, OnDestroy {
  readonly observabilityUrl = navigationSurfaceUrl('observability');
  readonly i18n = inject(I18nService); private readonly route = inject(ActivatedRoute); readonly router = inject(Router);
  private readonly api = inject(RunExecutionApiService); private readonly features = inject(ActivityApiService); private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService); private readonly auth = inject(AuthStore);
  readonly data = signal<RunExecutionView | null>(null); readonly loading = signal(true); readonly error = signal(''); readonly enabled = signal(false);
  readonly runs = signal<Run[]>([]); readonly runId = signal(''); readonly nodeId = signal(''); readonly activityId = signal(''); readonly offset = signal(0);
  readonly selectedItem = signal(''); readonly streamState = signal<StreamState>('disconnected'); readonly freshness = signal('');
  readonly labels = computed(() => Object.fromEntries(['not_started','not_executed','skipped','unavailable','pending','queued','running','waiting_human','waiting_external','succeeded','failed','cancelled','lost','deadline_exceeded','waiting','timed_out','unknown'].map(status => [status, this.status(status)])));
  readonly dynamicNodes = computed(() => this.data()?.nodes.filter(node => !this.data()!.graph.nodes.some(defined => defined.id === node.node_id)) || []);
  readonly timeline = computed(() => executionTimeline(this.data()?.items || []));
  readonly observedEnd = computed(() => this.data()?.run.finished_at || this.data()?.items.map(item => item.finished_at).filter((value): value is string => !!value).sort().at(-1) || null);
  private subscriptions: Subscription[] = []; private resets: Array<() => void> = []; private request?: AbortController; private stream?: AbortController;
  private liveAllowed = false; private generation = 0; private destroyed = false; private refreshTimer?: ReturnType<typeof setTimeout>; private lastValidated = 0;
  t(key: string, params?: Record<string, string | number>): string { return this.i18n.t('observability.flow.' + key, params); }
  status(status: string): string { const key = ['not_started','not_executed','skipped','unavailable'].includes(status) ? 'observability.flow.status.' + status : 'observability.activities.status.' + status; const label = this.i18n.t(key); return label === key ? status : label; }
  date(value: string | null | undefined): string { return formatInstant(value, this.i18n.locale(), { seconds: true }) ?? this.t('unknown'); }
  number(value: number | null | undefined, unit = ''): string { return value == null ? this.t('unknown') : new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 5 }).format(value) + unit; }
  nodeSummary(nodeId: string) { return this.data()?.nodes.find(node => node.node_id === nodeId); }
  safeLink(link: ActivityLink) { const href = activityLink(link); return href ? this.router.parseUrl(href) : null; }
  activityQuery(item: ExecutionItem) { return { facet: 'activities', activityId: item.activity_id, systemId: this.data()?.run.system_id || null }; }
  cost(item: ExecutionItem): string { const measured = item.measurements; if (!measured.cost_known) return this.t('unknown'); if (measured.cost_amount != null && measured.currency) return this.number(measured.cost_amount, ' ' + measured.currency); if (measured.infrastructure_cost_usd != null) return this.number(measured.infrastructure_cost_usd, ' USD'); return this.number(measured.provider_cost_usd, ' USD'); }

  interval(item: Pick<ExecutionItem, 'started_at' | 'finished_at'>) { return executionInterval(item, this.data()?.run.started_at || null, this.observedEnd()); }
  ngOnInit(): void {
    this.resets.push(this.workspace.registerContextReset(() => { this.purge(); queueMicrotask(() => { if (!this.destroyed) void this.discover(); }); }));
    this.resets.push(this.auth.registerContextReset(() => { this.purge(); this.error.set('forbidden'); }));
    this.subscriptions.push(this.route.paramMap.subscribe(params => { const id = params.get('runId') || ''; if (id !== this.runId()) { this.purge(); this.runId.set(id); if (this.enabled()) void this.reload(true); } }));
    this.subscriptions.push(this.route.queryParamMap.subscribe(params => { this.nodeId.set(params.get('nodeId') || ''); this.activityId.set(params.get('activityId') || ''); this.offset.set(Math.max(0, Number(params.get('offset')) || 0)); this.selectedItem.set(params.get('attemptId') || ''); if (this.enabled()) void this.reload(); }));
    void this.discover();
  }
  private async discover(): Promise<void> {
    const generation = this.generation; this.loading.set(true);
    try { const features = await this.features.features(); if (this.destroyed || generation !== this.generation) return; this.liveAllowed = features.enabled; this.enabled.set(!!features.execution_view_enabled); if (!this.enabled()) { this.error.set('disabled'); this.loading.set(false); return; } await this.reload(true); }
    catch (error) { if (!this.destroyed && generation === this.generation) { this.error.set(error instanceof ActivityApiError && [401,403].includes(error.status) ? 'forbidden' : 'failed'); this.loading.set(false); } }
  }
  async reload(reconnect = false): Promise<void> {
    if (!this.enabled() || this.destroyed || !this.runId()) return;
    const generation = ++this.generation; this.request?.abort(); this.request = new AbortController(); this.loading.set(true); this.error.set('');
    if (reconnect) { this.stream?.abort(); this.stream = undefined; }
    try {
      const value = await this.api.read(this.runId(), { node_id: this.nodeId() || undefined, activity_id: this.activityId() || undefined, offset: this.offset() }, this.request.signal);
      if (generation !== this.generation || this.destroyed) return;
      this.data.set(value); this.lastValidated = Date.now(); this.freshness.set(new Date().toISOString());
      if (value.capabilities.live === false) { this.stream?.abort(); this.stream = undefined; this.streamState.set('disconnected'); }
      if (!this.stream && this.liveAllowed && value.capabilities.live !== false) this.connect(value.snapshot_cursor);
      if (!this.runs().length && value.run.system_id) void this.loadRuns(value.run.system_id, generation);
    } catch (error) {
      if (generation !== this.generation || (error instanceof DOMException && error.name === 'AbortError')) return;
      if (error instanceof ActivityApiError && [401,403,404].includes(error.status)) { this.purge(); this.error.set('forbidden'); }
      else this.error.set('failed');
    } finally { if (generation === this.generation || this.error() === 'forbidden') this.loading.set(false); }
  }
  private async loadRuns(systemId: string, generation: number): Promise<void> {
    try { const rows = await firstValueFrom(this.canonical.listRuns({ system_id: systemId })); if (generation === this.generation && !this.destroyed) this.runs.set(rows); } catch { /* Selected authorized Run remains readable. */ }
  }
  private connect(cursor: string): void {
    const stream = new AbortController(); this.stream = stream;
    void this.api.follow(this.runId(), { cursor, signal: stream.signal,
      state: state => { if (stream.signal.aborted) return; this.streamState.set(state); if (state === 'revoked') { this.purge(); this.error.set('forbidden'); } },
      frame: frame => { if (stream.signal.aborted) return; if (frame.event === 'heartbeat') { if (Date.now() - this.lastValidated > 15000) this.schedule(); } else if (['activity.updated','activity.snapshot'].includes(frame.event)) this.schedule(); },
      resync: () => { if (!stream.signal.aborted) { this.stream?.abort(); this.stream = undefined; this.data.set(null); this.schedule(); } },
    });
  }
  private schedule(): void { if (this.refreshTimer || this.destroyed) return; this.refreshTimer = setTimeout(() => { this.refreshTimer = undefined; void this.reload(); }, 250); }
  selectNode(nodeId: string): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { nodeId: nodeId || null, activityId: null, offset: null, attemptId: null }, queryParamsHandling: 'merge' }); }
  selectItem(id: string): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { attemptId: id }, queryParamsHandling: 'merge' }); }
  page(delta: number): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { offset: Math.max(0, this.offset() + delta * 50), attemptId: null }, queryParamsHandling: 'merge' }); }
  selectRun(id: string): void { if (id && id !== this.runId()) void this.router.navigateByUrl(navigationRunFlowUrl(id)); }
  detailUrl(): string { return navigationObjectUrl('run', this.runId()); }
  private purge(): void { this.generation++; this.request?.abort(); this.stream?.abort(); this.stream = undefined; clearTimeout(this.refreshTimer); this.refreshTimer = undefined; this.data.set(null); this.runs.set([]); this.streamState.set('disconnected'); }
  ngOnDestroy(): void { this.destroyed = true; this.purge(); this.subscriptions.forEach(sub => sub.unsubscribe()); this.resets.forEach(reset => reset()); }
}
