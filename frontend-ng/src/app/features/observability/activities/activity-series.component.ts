import { ChangeDetectionStrategy, Component, OnDestroy, effect, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivitySeriesChartsComponent } from './activity-series-charts.component';
import { ActivityApiService } from './activity-api.service';
import { seriesRange, type ActivitySeries } from './activity-series.vm';

@Component({
  selector: 'app-activity-series', standalone: true, imports: [ActivitySeriesChartsComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (enabled() || error()) {
      <section class="series" data-testid="activity-series">
        <h2>{{i18n.t('observability.series.title')}}</h2>
        <div class="controls">
          @for (choice of modes; track choice) {
            <button type="button" [attr.aria-pressed]="mode() === choice" (click)="mode.set(choice)">{{i18n.t('observability.series.' + choice)}}</button>
          }
          @if(mode() === 'activity') {
            <button type="button" (click)="basis.set(basis() === 'created' ? 'finished' : 'created')">{{i18n.t('observability.series.' + basis())}}</button>
          }
        </div>
        @if(error()) { <p role="alert">{{i18n.t('observability.series.error')}}</p> }
        @else if(loading()) { <p role="status">{{i18n.t('observability.series.loading')}}</p> }
        @else if(data(); as series) {
          <p class="scope">{{i18n.t(mode() === 'activity' ? 'observability.series.' + basis() : 'observability.series.cost_scope')}} · UTC · {{series.from}} → {{series.until}}</p>
          <p>{{i18n.t('observability.series.count')}}: {{series.totals.total}} · {{i18n.t('observability.series.observed')}}: {{series.as_of}}</p>
          @if(series.totals.snapshot_only_count) { <p>{{i18n.t('observability.series.snapshots')}}: {{series.totals.snapshot_only_count}}</p> }
          @if(series.coverage.missing_finished_at) { <p>{{i18n.t('observability.series.missing_date')}}: {{series.coverage.missing_finished_at}}</p> }
          @if(mode() !== 'activity') {
            <p>{{i18n.t('observability.series.known')}}: {{series.totals.cost_known_count}} · {{i18n.t('observability.series.unknown')}}: {{series.totals.cost_unknown_count}}</p>
            @for(cost of series.totals.costs; track cost.basis + cost.currency) {
              <p>{{i18n.t('observability.series.basis.' + cost.basis)}} · {{cost.known_amount}} {{cost.currency}} · {{i18n.t(series.totals.cost_complete ? 'observability.series.complete' : 'observability.series.partial')}}</p>
            }
          }
          @if(series.totals.total === 0) { <p>{{i18n.t('observability.series.empty')}}</p> }
          @else {
            @defer (on viewport) { <app-activity-series-charts [series]="series" /> }
            @placeholder { <p>{{i18n.t('observability.series.loading')}}</p> }
            <details [open]="!compact()">
              <summary>{{i18n.t('observability.series.table')}}</summary>
              <div class="table"><table><caption>{{i18n.t('observability.series.table')}} · UTC</caption>
                <thead><tr><th scope="col">{{i18n.t('observability.series.period')}}</th><th scope="col">{{i18n.t('observability.series.count')}}</th><th scope="col">{{i18n.t('observability.series.evidence')}}</th></tr></thead>
                <tbody>@for(cell of series.buckets; track cell.from) {
                  <tr><th scope="row">{{cell.from}}</th><td>{{cell.total}}</td><td>
                    @if(mode() === 'activity') {
                      @for(entry of entries(cell.by_status); track entry[0]) { <span>{{i18n.t('observability.activities.status.' + entry[0])}}: {{entry[1]}} </span> }
                      @for(entry of entries(cell.durations); track entry[0]) { <div>{{i18n.t('observability.activities.kind.' + entry[0])}}: p50 {{entry[1].p50_ms ?? '—'}} / p95 {{entry[1].p95_ms ?? '—'}} ms · {{entry[1].measured_count}}/{{entry[1].eligible_count}}</div> }
                    } @else {
                      @for(cost of cell.costs; track cost.basis + cost.currency) { <span>{{i18n.t('observability.series.basis.' + cost.basis)}}: {{cost.known_amount}} {{cost.currency}} </span> }
                      {{i18n.t('observability.series.unknown')}}: {{cell.cost_unknown_count}}
                    }
                  </td></tr>
                }</tbody>
              </table></div>
            </details>
          }
        }
      </section>
    }
  `,
  styles: [`.series{border-top:1px solid var(--ck-stroke-2);padding:20px 0;color:var(--ck-fg-1)}h2{font-size:18px}.controls{display:flex;flex-wrap:wrap;gap:8px}button{padding:6px 12px;border:1px solid var(--ck-stroke-2);border-radius:4px;background:var(--ck-bg-panel);color:var(--ck-fg-1)}button[aria-pressed=true]{border-color:var(--ck-signal-cool)}button:focus-visible,summary:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:2px}.scope{overflow-wrap:anywhere;font-size:12px;color:var(--ck-fg-2)}.table{overflow-x:auto}table{width:100%;text-align:left;font-size:12px}th,td{padding:8px;border-bottom:1px solid var(--ck-stroke-2)}summary{cursor:pointer}`],
})
export class ActivitySeriesComponent implements OnDestroy {
  readonly systemId = input(''); readonly kind = input(''); readonly status = input('');
  readonly since = input('7d'); readonly asOf = input(''); readonly compact = input(false);
  readonly refreshToken = input(0);
  readonly i18n = inject(I18nService);
  private readonly transport = inject(WorkspaceFetchService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly api = inject(ActivityApiService);
  readonly modes = ['activity', 'skill_cost', 'compute_cost'] as const;
  readonly mode = signal<typeof this.modes[number]>('activity');
  readonly basis = signal<'created' | 'finished'>('created');
  readonly enabled = signal(false); readonly loading = signal(false);
  readonly error = signal(false); readonly data = signal<ActivitySeries | null>(null);
  private request?: AbortController;
  private unregister = this.workspace.registerContextReset(() => this.clear());
  private unregisterAuth = this.auth.registerContextReset(() => this.clear());
  constructor() {
    effect(onCleanup => {
      const context = { system: this.systemId(), kind: this.kind(), status: this.status(), since: this.since(), anchor: this.asOf(), mode: this.mode(), basis: this.basis(), refresh: this.refreshToken(), workspace: this.workspace.current()?.id };
      const request = new AbortController(); this.request?.abort(); this.request = request;
      onCleanup(() => request.abort());
      void this.load(context, request.signal);
    });
  }
  entries<T>(value: Record<string, T>): Array<[string, T]> { return Object.entries(value); }
  private clear(): void { this.request?.abort(); this.data.set(null); this.enabled.set(false); this.error.set(false); }
  private async load(context: { system: string; kind: string; status: string; since: string; anchor: string; mode: string; basis: string }, signal: AbortSignal): Promise<void> {
    const scope = this.workspace.captureRequestScope(); const principal = this.auth.captureRequestScope();
    const valid = () => !signal.aborted && this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal);
    this.data.set(null); this.error.set(false); this.loading.set(true);
    try {
      const features = await this.api.features(signal);
      if (!valid()) return;
      this.enabled.set(Boolean(features.activity_series_enabled));
      if (!features.activity_series_enabled) return;
      const range = seriesRange(context.since, context.anchor);
      const params = new URLSearchParams({ ...range, metric: context.mode === 'activity' ? 'activity' : 'cost', time_basis: context.mode === 'activity' ? context.basis : 'finished' });
      if (context.system) params.set('system_id', context.system);
      if (context.status) params.set('status', context.status);
      if (context.mode === 'activity') { if(context.kind) params.set('kind', context.kind); }
      else params.set('kind', context.mode === 'skill_cost' ? 'skill_invocation' : 'compute_run');
      const response = await this.transport.fetch('/api/v1/observability/activities/series?' + params, { signal, workspaceSlug: scope.workspaceSlug });
      if(!valid()) return;
      if(!response.ok) throw new Error('series');
      const data: ActivitySeries = await response.json();
      if(valid()) this.data.set(data);
    } catch {
      if(valid()) { this.data.set(null); this.error.set(true); }
    } finally { if(valid()) this.loading.set(false); }
  }
  ngOnDestroy(): void { this.clear(); this.unregister(); this.unregisterAuth(); }
}
