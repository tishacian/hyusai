import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ModelsService } from './models.service';
import type { MonitoringReport } from './models.vm';
import { RetrainingContextComponent } from './retraining-context.component';
import { ModelSystemsComponent } from './model-systems.component';
import { monitoringPolicy, monitoringDate, retrainingReason, retrainingState, proposalBinding, type ScheduledMonitoringReport } from './retraining-evidence.vm';

@Component({
 selector: 'ck-scheduled-monitoring', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
 imports: [NavLinkDirective, RetrainingContextComponent, ModelSystemsComponent],
 template: `
 @if (evidence(); as report) {
  <section data-testid="scheduled-monitoring">
   <div class="head"><h3>{{ t('title') }}</h3><button type="button" data-testid="monitoring-refresh" [disabled]="busy()" (click)="refresh.emit()">{{ i18n.t('models.shadow.refresh') }}</button></div>
   <p>{{ t(report.family === 'forecasting' ? 'forecast_hint' : 'hint') }}</p><p>{{ i18n.t('models.shadow.observed', {version: version()}) }}</p>
   @if (!report.supported) { <p data-testid="monitoring-unsupported">{{ i18n.t('models.retraining.reason.monitoring_unsupported') }}</p> }
   @else {
    <p data-testid="monitoring-state">{{ t(report.policy.enabled ? 'enabled' : 'disabled') }}</p>
    <div class="settings">
     <label><input type="checkbox" data-testid="monitoring-enabled" [checked]="enabled()" [disabled]="!editable() || busy()" (change)="enabled.set($any($event.target).checked)" />{{ t('enable') }}</label>
     <label>{{ t('interval') }}<select data-testid="monitoring-interval" [value]="interval()" [disabled]="!editable() || busy()" (change)="interval.set($any($event.target).value)">
      <option value="60">{{ i18n.t('models.retraining.interval.hour') }}</option><option value="360">{{ i18n.t('models.retraining.interval.six_hours') }}</option><option value="1440">{{ i18n.t('models.retraining.interval.day') }}</option>
     </select></label>
     <label><input type="checkbox" data-testid="monitoring-propose" [checked]="propose()" [disabled]="!editable() || busy()" (change)="propose.set($any($event.target).checked)" />{{ t('propose') }}</label>
     @if (editable()) { <button type="button" data-testid="monitoring-save" [disabled]="busy() || !config()" (click)="save()">{{ i18n.t('models.shadow.save') }}</button> }
    </div>
    @if (!editable()) { <p>{{ t('read_only') }}</p> }
   }
   @if (error()) { <p role="alert">{{ i18n.t(error()) }}</p> }
   @if (saved()) { <p role="status">{{ i18n.t('models.shadow.saved') }}</p> }
   @if (report.policy.system_id; as systemId) { <a data-testid="monitoring-flow" [navLink]="{leaf:'system-flow',ref:systemId}">{{ t('open_flow') }}</a> }
   <ck-model-systems [modelId]="modelId()" />
   <h4>{{ t('history') }}</h4>
   @if (!report.history.length) { <p>{{ t('history_empty') }}</p> }
   @else { <div class="table-wrap"><table data-testid="monitoring-history"><thead><tr><th>{{ t('date') }}</th><th>{{ t('badge') }}</th><th>{{ t('prediction_count') }}</th><th>{{ t(report.family === 'forecasting' ? 'observed_count' : 'labeled_count') }}</th><th>{{ t('reason') }}</th></tr></thead><tbody>
    @for (item of report.history; track item.id) { <tr><td>{{ date(item.created_at) }}</td><td>{{ badge(item.badge) }}</td><td>{{ item.window.predictions }}</td><td>{{ item.window.labeled }}</td><td>{{ item.reason ? reason(item.reason) : '—' }}</td></tr> }
   </tbody></table></div> }
   <h4>{{ t('proposals') }}</h4>
   @if (!report.proposals.length) { <p>{{ t('proposals_empty') }}</p> }
   @for (item of report.proposals; track item.id) {
    <article data-testid="retraining-proposal"><p>{{ date(item.created_at) }} · {{ state(item.stage) }} · {{ state(item.status) }}</p>
     @if (item.error) { <p role="alert">{{ reason(item.error) }}</p> }
     <div class="links">
      @if (item.run_id) { <a data-testid="proposal-run" [navLink]="{type:'run',ref:item.run_id}">{{ t('open_run') }}</a> }
      <a [navLink]="{leaf:'data-doc',ref:item.dataset_id}">{{ t('dataset') }} · v{{ item.dataset_version }}</a>
      @if (item.model_id) { <a data-testid="proposal-model" [navLink]="{leaf:'model-doc',ref:item.model_id}">{{ t('new_model') }}</a> }
     </div>
     <details><summary>{{ t('inspect_proposal') }}</summary><ck-retraining-context [binding]="proposalBinding(item)" /></details>
    </article>
   }
  </section>
 }
 `,
 styles: [`section{padding:16px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin-bottom:16px;color:var(--ck-fg-1)}.head{display:flex;align-items:center;justify-content:space-between;gap:12px}h3,h4{font-size:13px}h3{margin:0}h4{margin:20px 0 8px}p,summary{font-size:12px;line-height:1.5;color:var(--ck-fg-3)}.settings,.links{display:flex;gap:16px;align-items:center;flex-wrap:wrap}label{display:flex;gap:6px;align-items:center;font-size:12px}select,button{color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);border:1px solid var(--ck-stroke-2);border-radius:4px;padding:6px}button:disabled,select:disabled,input:disabled{opacity:.5}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:2px}a{font-size:12px;color:var(--ck-signal-cool)}article{margin:12px 0;padding:12px;border:1px solid var(--ck-stroke-2);border-radius:6px}summary{cursor:pointer;margin-top:12px}.table-wrap{overflow:auto}table{width:100%;font-size:12px;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid var(--ck-stroke-2)}[role=alert]{color:var(--ck-signal-neg)}`],
})
export class ScheduledMonitoringComponent {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  readonly evidence = input<ScheduledMonitoringReport>();
  readonly modelId = input.required<string>();
  readonly version = input.required<number>();

  readonly changed = output<MonitoringReport>();
  readonly refresh = output<void>();
  readonly enabled = signal(false);
  readonly propose = signal(false);
  readonly interval = signal('60');
  readonly busy = signal(false);
  readonly saved = signal(false);
  readonly error = signal('');
  readonly forbidden = signal(false);
  readonly editable = computed(() => this.evidence()?.supported === true && this.evidence()?.can_configure === true && !this.forbidden());
  readonly config = computed(() => monitoringPolicy(this.enabled(), this.propose(), this.interval()));
  readonly proposalBinding = proposalBinding;
  private generation = 0;
  private seeded = '';

  constructor() {
    effect(() => { this.modelId(); this.workspace.current()?.id; untracked(() => {
      this.generation++; this.busy.set(false); this.error.set(''); this.saved.set(false); this.forbidden.set(false); this.seeded = '';
    }); });
    effect(() => {
      const report = this.evidence();
      untracked(() => this.forbidden.set(false));
      const key = JSON.stringify([this.modelId(), this.workspace.current()?.id, report?.policy]);
      if (!report || key === this.seeded) return;
      this.seeded = key;
      untracked(() => { this.enabled.set(report.policy.enabled); this.propose.set(report.policy.propose_retraining); this.interval.set(String(report.policy.interval_minutes)); });
    });
    this.destroy.onDestroy(() => { this.generation++; });
  }

  async save(): Promise<void> {
    const config = this.config();
    if (!this.editable() || this.busy() || !config) return;
    const id = this.modelId(), generation = ++this.generation, scope = this.workspace.captureRequestScope();
    const current = () => generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
    this.busy.set(true); this.saved.set(false); this.error.set('');
    try {
      const report = await this.models.configureMonitoringPolicy(id, config);
      if (!current()) return;
      this.changed.emit(report); this.saved.set(true);
    } catch (error) {
      if (!current()) return;
      const code = error instanceof HttpErrorResponse ? error.error?.detail?.code : null;
      if (error instanceof HttpErrorResponse && error.status === 403) this.forbidden.set(true);
      this.error.set(retrainingReason(code));
    } finally { if (current()) this.busy.set(false); }
  }
  t(key: string): string { return this.i18n.t('models.retraining.' + key); }
  reason(code: string): string { return this.i18n.t(retrainingReason(code)); }
  state(status: string): string { return this.i18n.t(retrainingState(status)); }
  date(value: string): string { return monitoringDate(value, this.i18n.locale()); }
  badge(value: string | null | undefined): string { return this.i18n.t('models.monitor.tests.status.' + (['ok','watch','alert'].includes(value ?? '') ? value : 'unknown')); }
}
