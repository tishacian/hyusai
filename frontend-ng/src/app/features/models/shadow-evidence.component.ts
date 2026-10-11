import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ModelsService } from './models.service';
import { shadowConfig, shadowErrorKey, shadowValue, type ShadowReport } from './shadow-evidence.vm';

@Component({
  selector: 'ck-shadow-evidence', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective],
  template: `
    @if (evidence(); as report) {
      <section data-testid="shadow-panel">
        <div class="head"><h3>{{ i18n.t('models.shadow.title') }}</h3>
          <button type="button" data-testid="shadow-refresh" [disabled]="busy()" (click)="refresh.emit()">{{ i18n.t('models.shadow.refresh') }}</button>
        </div>
        <p>{{ i18n.t('models.shadow.hint') }}</p>
        @if (!report.supported) { <p data-testid="shadow-unsupported">{{ i18n.t('models.shadow.error.unsupported') }}</p> }
        @else {
          <p>{{ i18n.t('models.shadow.observed', { version: version() }) }}
            @if (report.challenger; as challenger) { · <a [navLink]="{leaf:'model-doc',ref:challenger.id}">{{ i18n.t('models.shadow.challenger', { version: challenger.version }) }}</a> }
            @else { · {{ i18n.t('models.shadow.error.no_challenger') }} }
          </p>
          <p data-testid="shadow-state">{{ i18n.t(report.config.enabled ? 'models.shadow.enabled' : 'models.shadow.disabled') }}</p>
          <div class="settings">
            <label class="enable"><input type="checkbox" data-testid="shadow-enabled" [checked]="enabled()" [disabled]="!editable() || busy()" (change)="enabled.set($any($event.target).checked)" />{{ i18n.t('models.shadow.enable') }}</label>
            <label>{{ i18n.t('models.shadow.sample') }}<input type="number" data-testid="shadow-sample" min="1" max="100" step="1" [value]="sample()" [disabled]="!editable() || busy()" (input)="sample.set($any($event.target).value)" /></label>
            <label>{{ i18n.t('models.shadow.timeout') }}<input type="number" data-testid="shadow-timeout" min="1" max="60" step="1" [value]="timeout()" [disabled]="!editable() || busy()" (input)="timeout.set($any($event.target).value)" /></label>
            @if (editable()) { <button type="button" data-testid="shadow-save" [disabled]="busy() || !config()" (click)="save()">{{ i18n.t('models.shadow.save') }}</button> }
          </div>
          @if (!editable()) { <p>{{ i18n.t('models.shadow.read_only') }}</p> }
          @if (error()) { <p role="alert">{{ i18n.t(error()) }}</p> }
          @if (saved()) { <p role="status">{{ i18n.t('models.shadow.saved') }}</p> }
          <p>{{ i18n.t('models.shadow.limits', { rows: report.limits.max_rows, pending: report.limits.max_pending, attempts: report.limits.max_attempts }) }}</p>
          @if (report.limits.window != null) { <p>{{ i18n.t('models.shadow.window_limit', { count: report.limits.window }) }}</p> }
          <dl class="counts">
            @for (key of countKeys; track key) { <div><dt>{{ i18n.t('models.shadow.count.' + key) }}</dt><dd [attr.data-count]="key">{{ report.window[key] }}</dd></div> }
          </dl>
          <p>{{ i18n.t('models.shadow.pair_scope', { rows: report.window.compared_rows, labeled: report.window.labeled_pairs }) }}</p>
          <dl class="metrics" data-testid="shadow-comparison">
            @if (task() === 'classification') {
              <dt>{{ i18n.t('models.shadow.agreement') }}</dt><dd data-metric="agreement">{{ value(report.comparison.agreement, true) }}</dd>
              <dt>{{ i18n.t('models.shadow.primary_accuracy') }}</dt><dd data-metric="primary-accuracy">{{ value(report.comparison.champion_accuracy, true) }}</dd>
              <dt>{{ i18n.t('models.shadow.challenger_accuracy') }}</dt><dd data-metric="challenger-accuracy">{{ value(report.comparison.challenger_accuracy, true) }}</dd>
            } @else {
              <dt>{{ i18n.t('models.shadow.difference') }}</dt><dd data-metric="difference">{{ value(report.comparison.mean_absolute_difference) }}</dd>
              <dt>{{ i18n.t('models.shadow.primary_mae') }}</dt><dd data-metric="primary-mae">{{ value(report.comparison.champion_mae) }}</dd>
              <dt>{{ i18n.t('models.shadow.challenger_mae') }}</dt><dd data-metric="challenger-mae">{{ value(report.comparison.challenger_mae) }}</dd>
            }
            <dt>{{ i18n.t('models.shadow.primary_latency') }}</dt><dd>{{ value(report.latencies.primary_ms) }}</dd>
            <dt>{{ i18n.t('models.shadow.shadow_latency') }}</dt><dd>{{ value(report.latencies.shadow_ms) }}</dd>
            <dt>{{ i18n.t('models.shadow.load_latency') }}</dt><dd>{{ value(report.latencies.shadow_load_ms) }}</dd>
            <dt>{{ i18n.t('models.shadow.total_latency') }}</dt><dd>{{ value(report.latencies.shadow_total_ms) }}</dd>
          </dl>
          @if (report.recent.length) {
            <div class="table-wrap"><table><thead><tr>
              <th>{{ i18n.t('models.shadow.prediction') }}</th><th>{{ i18n.t('models.shadow.version') }}</th><th>{{ i18n.t('models.shadow.rows') }}</th><th>{{ i18n.t('models.shadow.status') }}</th>
            </tr></thead><tbody>@for (item of report.recent; track item.prediction_id) {
              <tr><td>{{ item.prediction_id }}</td><td>{{ item.version == null ? '—' : 'v' + item.version }}</td><td>{{ item.rows }}</td>
                <td>{{ state(item.status) }} @if (item.error) { <small>{{ i18n.t(reason(item.error)) }}</small> }</td>
              </tr>
            }</tbody></table></div>
          }
        }
      </section>
    }
  `,
  styles: [`section{padding:16px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin-bottom:16px;color:var(--ck-fg-1)}.head{display:flex;justify-content:space-between;gap:12px;align-items:center}h3{font-size:13px;margin:0}p,small{font-size:12px;line-height:1.5;color:var(--ck-fg-3)}a{color:var(--ck-signal-cool)}.settings{display:flex;gap:12px;align-items:end;flex-wrap:wrap}label{display:grid;gap:6px;font-size:12px}.enable{display:flex;align-items:center;align-self:center}input[type=number]{width:100px}input,button{color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);border:1px solid var(--ck-stroke-2);border-radius:4px;padding:6px}button:disabled,input:disabled{opacity:.5}button:focus-visible,input:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:2px}.counts{display:flex;gap:20px;flex-wrap:wrap;font-size:12px}.counts dd{margin:6px 0;font-variant-numeric:tabular-nums}.metrics{display:grid;grid-template-columns:minmax(160px,1fr) auto;gap:8px 16px;font-size:12px}.metrics dt{color:var(--ck-fg-3)}.metrics dd{margin:0;font-variant-numeric:tabular-nums}.table-wrap{overflow:auto}table{width:100%;font-size:12px;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid var(--ck-stroke-2)}small{display:block}[role=alert]{color:var(--ck-signal-neg)}`],
})
export class ShadowEvidenceComponent {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  readonly evidence = input<ShadowReport>();
  readonly modelId = input.required<string>();
  readonly version = input.required<number>();
  readonly task = input.required<string>();
  readonly changed = output<ShadowReport>();
  readonly refresh = output<void>();
  readonly enabled = signal(false);
  readonly sample = signal('10');
  readonly timeout = signal('15');
  readonly busy = signal(false);
  readonly saved = signal(false);
  readonly error = signal('');
  readonly forbidden = signal(false);
  readonly editable = computed(() => this.evidence()?.supported === true && this.evidence()?.can_configure === true && !this.forbidden());
  readonly config = computed(() => shadowConfig(this.enabled(), this.sample(), this.timeout()));
  readonly countKeys = ['jobs', 'completed', 'pending', 'failed', 'skipped'] as const;
  private generation = 0;
  private seeded = '';

  constructor() {
    effect(() => { this.modelId(); this.workspace.current()?.id; untracked(() => {
      this.generation++; this.busy.set(false); this.error.set(''); this.saved.set(false); this.forbidden.set(false); this.seeded = '';
    }); });
    effect(() => {
      const report = this.evidence();
      untracked(() => this.forbidden.set(false));
      const key = JSON.stringify([this.modelId(), this.workspace.current()?.id, report?.config]);
      if (!report || key === this.seeded) return;
      this.seeded = key;
      untracked(() => { this.enabled.set(report.config.enabled); this.sample.set(String(report.config.sample_percent)); this.timeout.set(String(report.config.timeout_s)); });
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
      const report = await this.models.configureShadow(id, config);
      if (!current()) return;
      this.changed.emit(report); this.saved.set(true);
    } catch (error) {
      if (!current()) return;
      const code = error instanceof HttpErrorResponse ? error.error?.detail?.code : null;
      if (error instanceof HttpErrorResponse && error.status === 403) this.forbidden.set(true);
      this.error.set(shadowErrorKey(code));
    } finally { if (current()) this.busy.set(false); }
  }
  value(raw: number | null | undefined, percent = false): string { return shadowValue(raw, this.i18n.locale(), percent) ?? this.i18n.t('models.shadow.unavailable'); }
  reason(code: string): string { return shadowErrorKey(code); }
  state(status: string): string { return this.i18n.t('models.shadow.state.' + (['queued', 'running', 'completed', 'failed', 'cancelled', 'skipped'].includes(status) ? status : 'unknown')); }
}
