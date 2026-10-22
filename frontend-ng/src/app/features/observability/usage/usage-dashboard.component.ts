import { ChangeDetectionStrategy, Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, firstValueFrom } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { UsageApiService } from './usage-api.service';
import type { UsageCallPage, UsageFilters, UsageSeries, UsageSummary, UsageSystemOption, UsageTraffic } from './usage.models';
import { USAGE_TRAFFIC, usageAmount, usageBreakdown, usageChartMaximum, usageNumber, usageSeriesValues, type UsageDimension } from './usage.vm';
import { UsageSummaryComponent } from './usage-summary.component';
import { UsageCallsComponent } from './usage-calls.component';
import { UsageBudgetsComponent } from './usage-budgets.component';

@Component({
  selector: 'app-usage-dashboard', standalone: true, imports: [FormsModule, UsageSummaryComponent, UsageCallsComponent, UsageBudgetsComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="usage-page">
      <header class="page-heading"><div><h1>{{ t('title') }}</h1><p>{{ t('subtitle') }}</p></div>
        <nav class="views" [attr.aria-label]="t('views')"><button type="button" [attr.aria-current]="view() === 'overview' ? 'page' : null" (click)="setView('overview')">{{ t('consumption') }}</button><button type="button" [attr.aria-current]="view() === 'budgets' ? 'page' : null" (click)="setView('budgets')">{{ t('budgets') }}</button></nav></header>
      @if (view() === 'budgets') { <app-usage-budgets [systems]="systems()" /> }
      @else {
        <div class="filters">
          <label>{{ t('system') }}<select [ngModel]="filters().system_id || ''" (ngModelChange)="setFilter('systemId', $event)"><option value="">{{ t('all_systems') }}</option>@for (system of systems(); track system.id) { <option [value]="system.id">{{ system.name }}</option> }</select></label>
          <label>{{ t('population') }}<select [ngModel]="filters().traffic" (ngModelChange)="setFilter('traffic', $event)">@for (traffic of populations; track traffic) { <option [value]="traffic">{{ label('traffic', traffic) }}</option> }</select></label>
          <label>{{ t('provider') }}<select [ngModel]="filters().provider || ''" (ngModelChange)="setFilter('provider', $event)"><option value="">{{ t('all_providers') }}</option>@for (provider of providers(); track provider) { <option [value]="provider">{{ provider }}</option> }</select></label>
          <label>{{ t('model') }}<select [ngModel]="filters().model || ''" (ngModelChange)="setFilter('model', $event)"><option value="">{{ t('all_models') }}</option>@for (model of models(); track model) { <option [value]="model">{{ model }}</option> }</select></label>
          <label>{{ t('purpose') }}<select [ngModel]="filters().purpose || ''" (ngModelChange)="setFilter('purpose', $event)"><option value="">{{ t('all_purposes') }}</option>@for (purpose of purposes(); track purpose) { <option [value]="purpose">{{ label('purpose', purpose) }}</option> }</select></label>
        </div>
        @if (systemsError()) { <p class="notice" role="status">{{ t('systems_error') }}</p> }
        <section [attr.aria-busy]="loading()">
          @if (error()) { <p class="notice error" role="alert">{{ t('load_error') }} <button type="button" (click)="reload()">{{ i18n.t('common.refresh') }}</button></p> }
          @if (loading() && !summary()) { <p class="notice" role="status">{{ t('loading') }}</p> }
          @if (summary(); as value) {
            <app-usage-summary [data]="value" />
            @if (value.counts.calls === 0) { <p class="notice">{{ t('no_usage') }}</p> }
          }
          @if (series(); as history) {
            <section class="trend" aria-labelledby="usage-trend-title">
              <div class="section-heading"><h2 id="usage-trend-title">{{ t('trend') }}</h2>
                <label class="metric-select"><span>{{ t('measure') }}</span><select [ngModel]="metric()" (ngModelChange)="metric.set($event)"><option value="calls">{{ t('calls') }}</option><option value="tokens">{{ t('tokens') }}</option>@for (cost of summary()?.costs || []; track cost.currency) { <option [value]="cost.currency">{{ t('calculated_cost') }} · {{ cost.currency }}</option> }</select></label></div>
              @if (points().length) {
                <div class="chart-plot">
                  <div class="chart-axis" aria-hidden="true"><span>{{ axisValue(chartMaximum()) }}</span><span>{{ axisValue(chartMaximum() / 2) }}</span><span>{{ axisValue(0) }}</span></div>
                  <div class="bars" role="group" [attr.aria-label]="t('trend') + ' · ' + metricLabel()">
                    @for (point of points(); track point.date) {
                      <div class="bar-column" tabindex="0" role="img" [class.unknown]="point.value === null" [class.zero]="point.value === 0" [attr.aria-label]="date(point.date) + ' · ' + metricLabel() + ' · ' + pointValue(point.value)">
                        <span class="bar-fill" [style.height.%]="barHeight(point.value)"></span>
                        <span class="bar-tooltip" aria-hidden="true"><b>{{ date(point.date) }}</b>{{ pointValue(point.value) }}</span>
                      </div>
                    }
                  </div>
                </div>
              }
              <div class="chart-range"><span>{{ date(points()[0]?.date) }}</span><span>{{ metricLabel() }} · {{ history.timezone }}</span><span>{{ date(points()[points().length - 1]?.date) }}</span></div>
              @if (hasUnknownPoints()) { <p class="chart-legend"><span aria-hidden="true"></span>{{ t('chart_unknown') }}</p> }
              <details class="chart-data"><summary>{{ t('chart_data') }}</summary><div class="table-wrap"><table><thead><tr><th scope="col">{{ t('started') }}</th><th scope="col">{{ metricLabel() }}</th></tr></thead><tbody>@for (point of points(); track point.date) { <tr><td>{{ date(point.date) }}</td><td>{{ pointValue(point.value) }}</td></tr> }</tbody></table></div></details>
            </section>
          }
          @if (summary(); as value) {
            <div class="section-heading"><h2>{{ t('breakdown') }}</h2><label class="metric-select"><span>{{ t('group_by') }}</span><select [ngModel]="dimension()" (ngModelChange)="dimension.set($event)">@for (axis of dimensions; track axis) { <option [value]="axis">{{ t(axis === 'system_id' ? 'system' : axis === 'traffic' ? 'population' : axis) }}</option> }</select></label></div>
            <div class="table-wrap" tabindex="0" role="region" [attr.aria-label]="t('breakdown')"><table><thead><tr><th scope="col">{{ t(dimension() === 'system_id' ? 'system' : dimension() === 'traffic' ? 'population' : dimension()) }}</th><th scope="col" class="numeric">{{ t('calls') }}</th><th scope="col" class="numeric">{{ t('tokens') }}</th><th scope="col" class="numeric">{{ t('calculated_cost') }}</th></tr></thead><tbody>
              @for (group of groups(); track group.key) { <tr><td>{{ groupLabel(group.key) }}</td><td class="numeric">{{ number(group.calls) }}</td><td class="numeric">{{ number(group.tokens) }}</td><td class="numeric">@for (cost of group.costs; track cost.currency) { <span class="cost-line">{{ amount(cost.amount, cost.currency) }}</span> }@empty { — }</td></tr> }
              @empty { <tr><td class="empty" colspan="4">{{ t('no_calls') }}</td></tr> }
            </tbody></table></div>
          }
          <div class="section-heading"><h2>{{ t('evidence') }}</h2><label class="check"><input type="checkbox" [ngModel]="filters().status === 'blocked'" (ngModelChange)="setFilter('status', $event ? 'blocked' : '')" />{{ t('blocked_only') }}</label></div>
          @if (calls(); as page) { <app-usage-calls [page]="page" [busy]="loading()" (pageChange)="setOffset($event)" /> }
        </section>
      }
    </div>
  `,
  styleUrls: ['./usage-shared.css', './usage-dashboard.component.css'],
})
export class UsageDashboardComponent implements OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly api = inject(UsageApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  readonly summary = signal<UsageSummary | null>(null);
  readonly series = signal<UsageSeries | null>(null);
  readonly calls = signal<UsageCallPage | null>(null);
  readonly systems = signal<UsageSystemOption[]>([]);
  readonly systemsError = signal(false);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly view = signal<'overview' | 'budgets'>('overview');
  readonly filters = signal<UsageFilters>({ window: '7d', traffic: 'all' });
  readonly metric = signal('calls');
  readonly dimension = signal<UsageDimension>('model');
  readonly dimensions: UsageDimension[] = ['provider', 'model', 'purpose', 'system_id', 'traffic'];
  readonly populations = USAGE_TRAFFIC;
  readonly providers = computed(() => this.options('provider'));
  readonly models = computed(() => this.options('model'));
  readonly purposes = computed(() => this.options('purpose'));
  readonly groups = computed(() => usageBreakdown(this.summary()?.groups || [], this.dimension()));
  readonly points = computed(() => this.series() ? usageSeriesValues(this.series()!, this.metric()) : []);
  readonly chartMaximum = computed(() => usageChartMaximum(this.points().map(point => point.value)));
  readonly hasUnknownPoints = computed(() => this.points().some(point => point.value === null));
  readonly metricLabel = computed(() => this.metric() === 'calls' || this.metric() === 'tokens' ? this.t(this.metric()) : this.t('calculated_cost') + ' · ' + this.metric());
  private controller?: AbortController;
  private generation = 0;
  private destroyed = false;
  private subscriptions = new Subscription();
  private resetters: Array<() => void> = [];
  constructor() {
    this.subscriptions.add(this.route.queryParamMap.subscribe(query => {
      const since = query.get('since'), traffic = query.get('traffic');
      this.view.set(query.get('usageView') === 'budgets' ? 'budgets' : 'overview');
      this.filters.set({ window: since === '90d' || since === '30d' || since === '24h' ? since : '7d', as_of: query.get('as_of') || undefined,
        system_id: query.get('systemId') || undefined, provider: query.get('provider') || undefined,
        model: query.get('model') || undefined, purpose: query.get('purpose') || undefined,
        traffic: USAGE_TRAFFIC.includes(traffic as UsageTraffic) ? traffic as UsageTraffic : 'all', status: query.get('status') === 'blocked' ? 'blocked' : undefined });
      if (this.view() === 'overview') void this.load(Math.max(0, Number(query.get('offset')) || 0));
    }));
    const clear = () => { this.generation++; this.controller?.abort(); this.summary.set(null); this.calls.set(null); this.series.set(null); this.systems.set([]); this.loading.set(false); this.error.set(false); };
    this.resetters.push(this.workspace.registerContextReset(() => { clear(); queueMicrotask(() => { if (!this.destroyed) { void this.loadSystems(); this.reload(); } }); }), this.auth.registerContextReset(clear));
    void this.loadSystems();
  }
  t(key: string): string { return this.i18n.t('observability.usage.' + key); }
  label(group: string, value: string): string { const key = 'observability.usage.' + group + '.' + value, text = this.i18n.t(key); return text === key ? value || this.t('unknown') : text; }
  number(value: unknown): string { return usageNumber(value, this.i18n.locale()); }
  amount(value: unknown, currency: string | null): string { return usageAmount(value, currency, this.i18n.locale()); }
  date(value?: string): string { const date = new Date(value || ''); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(this.i18n.locale(), { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date) : '—'; }
  pointValue(value: number | null): string { return value === null ? this.t('not_measured') : ['calls', 'tokens'].includes(this.metric()) ? this.number(value) : this.amount(value, this.metric()); }
  axisValue(value: number): string { return ['calls', 'tokens'].includes(this.metric()) ? new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 2 }).format(value) : this.amount(value, this.metric()); }
  barHeight(value: number | null): number { return value === null ? 0 : value === 0 ? 0 : Math.max(1, value / this.chartMaximum() * 100); }
  groupLabel(key: string): string { return this.dimension() === 'system_id' ? this.systems().find(system => system.id === key)?.name || this.t(key ? 'system' : 'no_system') : ['purpose', 'traffic'].includes(this.dimension()) ? this.label(this.dimension(), key) : key || this.t('unknown'); }
  setView(view: 'overview' | 'budgets'): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { usageView: view === 'budgets' ? view : null }, queryParamsHandling: 'merge' }); }
  setFilter(key: string, value: string): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { [key]: value || null, ...(key === 'provider' ? { model: null } : {}), offset: null }, queryParamsHandling: 'merge' }); }
  setOffset(offset: number): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { offset: offset || null }, queryParamsHandling: 'merge' }); }
  reload(): void { if (this.view() === 'overview') void this.load(); }
  private options(key: 'provider' | 'model' | 'purpose'): string[] { return [...new Set([...(this.summary()?.groups || []).map(group => group[key]), this.filters()[key] || ''].filter(Boolean))].sort(); }
  private async loadSystems(): Promise<void> {
    const scope = this.workspace.captureRequestScope(), principal = this.auth.captureRequestScope(); this.systemsError.set(false);
    try { const systems = await firstValueFrom(this.canonical.listSystems({ workspaceSlug: scope.workspaceSlug, propagateErrors: true }));
      if (!this.destroyed && this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) this.systems.set(systems.map(system => ({ id: system.id, name: system.name || system.id }))); }
    catch { if (!this.destroyed && this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) this.systemsError.set(true); }
  }
  private async load(offset = 0): Promise<void> {
    if (this.destroyed) return;
    this.controller?.abort(); const controller = this.controller = new AbortController(), generation = ++this.generation;
    this.loading.set(true); this.error.set(false); this.calls.set(null);
    if (offset === 0) { this.summary.set(null); this.series.set(null); }
    const filters = this.filters(), aggregate = { ...filters, status: undefined };
    const values = await Promise.allSettled([this.api.summary(aggregate, controller.signal), this.api.series(aggregate, controller.signal), this.api.calls({ ...filters, limit: 25, offset }, controller.signal)]);
    if (generation !== this.generation || controller.signal.aborted || this.destroyed) return;
    if (values[0].status === 'fulfilled') this.summary.set(values[0].value);
    if (values[1].status === 'fulfilled') this.series.set(values[1].value);
    if (values[2].status === 'fulfilled') this.calls.set(values[2].value);
    this.error.set(values.some(value => value.status === 'rejected'));
    this.loading.set(false);
  }
  ngOnDestroy(): void { this.destroyed = true; this.generation++; this.controller?.abort(); this.subscriptions.unsubscribe(); this.resetters.forEach(reset => reset()); }
}
