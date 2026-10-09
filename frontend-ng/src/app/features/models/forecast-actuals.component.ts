import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ModelsService } from './models.service';
import type { MonitoringReport } from './models.vm';
import type { DatasetDto } from '../data/data.service';
import { actualMetric, actualReason, actualStatus, type ForecastActualsReport } from './forecast-actuals.vm';

@Component({
 selector: 'ck-forecast-actuals', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
 imports: [NavLinkDirective],
 template: `
 @if (evidence(); as report) {
  <section data-testid="forecast-actuals">
   <div class="head"><h3>{{ t('title') }}</h3>@if (!readOnly()) { <button type="button" [disabled]="busy()" (click)="refresh.emit()">{{ t('refresh') }}</button> }</div>
   <p>{{ t('hint') }}</p>
   <p data-testid="actuals-status">{{ i18n.t(status(report.status)) }}</p>
   @if (report.reason) { <p>{{ i18n.t(reason(report.reason)) }}</p> }
   @if (!readOnly()) {
    @if (editable()) {
     <div class="settings">
      <button type="button" data-testid="actuals-load-datasets" [disabled]="busy()" (click)="loadDatasets()">{{ t('choose') }}</button>
      <label>{{ t('dataset') }}<select data-testid="actuals-dataset" [value]="datasetId()" [disabled]="busy() || !datasets().length" (change)="datasetId.set($any($event.target).value)">
       <option value="">{{ t('select') }}</option>@for (item of datasets(); track item.id) { <option [value]="item.id">{{ item.name }} · v{{ item.version }}</option> }
      </select></label>
      <label><input type="checkbox" data-testid="actuals-follow" [checked]="followLatest()" [disabled]="busy()" (change)="followLatest.set($any($event.target).checked)" />{{ t('follow') }}</label>
      <button type="button" data-testid="actuals-save" [disabled]="busy() || !datasetId()" (click)="save()">{{ t('associate') }}</button>
     </div>
     @if (loaded() && !datasets().length) { <p>{{ t('no_datasets') }}</p> }
    } @else { <p>{{ t('read_only') }}</p> }
    @if (error()) { <p role="alert">{{ i18n.t(error()) }}</p> }
    @if (saved()) { <p role="status">{{ t('saved') }}</p> }
   }
   @if (report.dataset; as dataset) {
    <p><a [navLink]="{leaf:'data-doc',ref:dataset.id}">{{ dataset.name }} · v{{ dataset.version }}</a> · {{ t(dataset.follow_latest ? 'following' : 'pinned') }}</p>
    <p>{{ t('selection') }}</p><p>{{ t('thresholds') }}</p>
    <dl class="metrics" data-testid="actuals-metrics">
     @for (key of metricKeys; track key) { <div><dt>{{ t('metric.' + key) }}</dt><dd [attr.data-metric]="key">{{ value(report.overall[key], key === 'coverage' || key === 'nominal_coverage') }}</dd></div> }
    </dl>
    <p>{{ t('window', { calls: report.window.calls, points: report.window.retained_points, matched: report.window.matched, late: report.window.excluded_late, future: report.window.excluded_future, duplicates: report.window.duplicates }) }}</p>
    @if (report.window.truncated) { <p>{{ t('truncated', { calls: report.window.limit_calls, points: report.window.limit_points }) }}</p> }
    @if (report.by_series.length) {
     <h4>{{ t('by_series') }}</h4><div class="table-wrap"><table data-testid="actuals-series"><thead><tr><th>{{ t('series') }}</th><th>{{ i18n.t('models.actuals.metric.count') }}</th><th>MAE</th><th>RMSE</th><th>{{ i18n.t('models.actuals.metric.coverage') }}</th></tr></thead><tbody>
      @for (item of report.by_series; track item.series) { <tr><td>{{ item.series }}</td><td>{{ item.count }}</td><td>{{ value(item.mae) }}</td><td>{{ value(item.rmse) }}</td><td>{{ value(item.coverage,true) }}</td></tr> }
     </tbody></table></div>
    }
    @if (report.by_horizon.length) {
     <h4>{{ t('by_horizon') }}</h4><div class="table-wrap"><table data-testid="actuals-horizons"><thead><tr><th>{{ t('horizon') }}</th><th>{{ i18n.t('models.actuals.metric.count') }}</th><th>MAE</th><th>RMSE</th><th>{{ i18n.t('models.actuals.metric.coverage') }}</th></tr></thead><tbody>
      @for (item of report.by_horizon; track item.horizon) { <tr><td>+{{ item.horizon }}</td><td>{{ item.count }}</td><td>{{ value(item.mae) }}</td><td>{{ value(item.rmse) }}</td><td>{{ value(item.coverage,true) }}</td></tr> }
     </tbody></table></div>
    }
    @if (report.anomalies.length) {
     <h4>{{ t('anomalies') }}</h4><div class="table-wrap"><table data-testid="actuals-anomalies"><thead><tr><th>{{ t('series') }}</th><th>{{ t('timestamp') }}</th><th>{{ t('horizon') }}</th><th>{{ t('actual') }}</th><th>{{ t('pred') }}</th><th>{{ t('interval') }}</th></tr></thead><tbody>
      @for (item of report.anomalies; track item.prediction_id + item.series + item.timestamp + item.horizon) { <tr><td>{{ item.series }}</td><td>{{ item.timestamp }}</td><td>+{{ item.horizon }}</td><td>{{ value(item.actual) }}</td><td>{{ value(item.pred) }}</td><td>{{ value(item.lower_bound) }} – {{ value(item.upper_bound) }}</td></tr> }
     </tbody></table></div>
    }
   }
  </section>
 }
 `,
 styles: [`section{padding:16px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin-bottom:16px;color:var(--ck-fg-1)}.head,.settings{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.head{justify-content:space-between}h3,h4{font-size:13px}h3{margin:0}p{font-size:12px;line-height:1.5;color:var(--ck-fg-3)}label{display:flex;gap:6px;align-items:center;font-size:12px}select,button{max-width:100%;color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);border:1px solid var(--ck-stroke-2);border-radius:4px;padding:6px}button:disabled,select:disabled{opacity:.5}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:2px}.metrics{display:flex;gap:16px;flex-wrap:wrap;font-size:12px}.metrics dt{color:var(--ck-fg-3)}.metrics dd{margin:6px 0;font-variant-numeric:tabular-nums}a{color:var(--ck-signal-cool)}.table-wrap{overflow:auto}table{width:100%;font-size:12px;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid var(--ck-stroke-2)}[role=alert]{color:var(--ck-signal-neg)}`],
})
export class ForecastActualsComponent {
 readonly i18n = inject(I18nService);
 private readonly models = inject(ModelsService);
 private readonly workspace = inject(WorkspaceService);
 private readonly destroy = inject(DestroyRef);
 readonly evidence = input<ForecastActualsReport | null>();
 readonly modelId = input('');
 readonly readOnly = input(false);
 readonly changed = output<MonitoringReport>();
 readonly refresh = output<void>();
 readonly datasets = signal<DatasetDto[]>([]);
 readonly datasetId = signal('');
 readonly followLatest = signal(false);
 readonly busy = signal(false);
 readonly loaded = signal(false);
 readonly saved = signal(false);
 readonly error = signal('');
 readonly forbidden = signal(false);
 readonly editable = computed(() => !this.readOnly() && this.evidence()?.can_configure === true && !this.forbidden());
 readonly metricKeys = ['count','mae','rmse','smape','nominal_coverage','coverage','interval_count','mean_interval_width','anomalies'] as const;
 readonly status = actualStatus;
 readonly reason = actualReason;
 private generation = 0;
 private seeded = '';
 constructor() {
  effect(() => { this.modelId(); this.workspace.current()?.id; untracked(() => {
   this.generation++; this.datasets.set([]); this.datasetId.set(''); this.loaded.set(false); this.busy.set(false); this.saved.set(false); this.error.set(''); this.forbidden.set(false); this.seeded = '';
  }); });
  effect(() => {
   const dataset = this.evidence()?.dataset, key = JSON.stringify([this.modelId(), this.workspace.current()?.id, dataset]);
   if (key === this.seeded) return;
   this.seeded = key;
   untracked(() => { this.datasetId.set(dataset?.id ?? ''); this.followLatest.set(dataset?.follow_latest ?? false); });
  });
  this.destroy.onDestroy(() => { this.generation++; });
 }
 async loadDatasets(): Promise<void> {
  if (!this.editable() || this.busy()) return;
  const generation = ++this.generation, id = this.modelId(), scope = this.workspace.captureRequestScope();
  const current = () => generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
  this.busy.set(true); this.error.set('');
  try { const rows = await this.models.forecastActualDatasets(); if (current()) { this.datasets.set(rows.filter(row => row.status === 'ready')); this.loaded.set(true); } }
  catch { if (current()) this.error.set(actualReason()); }
  finally { if (current()) this.busy.set(false); }
 }
 async save(): Promise<void> {
  if (!this.editable() || this.busy() || !this.datasetId()) return;
  const generation = ++this.generation, id = this.modelId(), scope = this.workspace.captureRequestScope();
  const current = () => generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
  this.busy.set(true); this.saved.set(false); this.error.set('');
  try { const report = await this.models.configureForecastActuals(id, this.datasetId(), this.followLatest()); if (current()) { this.changed.emit(report); this.saved.set(true); } }
  catch (error) { if (current()) {
   if (error instanceof HttpErrorResponse && error.status === 403) this.forbidden.set(true);
   this.error.set(actualReason(error instanceof HttpErrorResponse ? error.error?.detail?.code : undefined));
  } }
  finally { if (current()) this.busy.set(false); }
 }
 t(key: string, params?: Record<string,string|number>): string { return this.i18n.t('models.actuals.' + key, params); }
 value(value: number | null | undefined, ratio = false): string { return actualMetric(value, this.i18n.locale(), ratio); }
}
