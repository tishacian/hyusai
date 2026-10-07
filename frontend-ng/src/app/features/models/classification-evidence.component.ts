import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { CurveChartComponent, type CurveReference } from '@app/features/data/viz/curve-chart.component';
import { calibrationWorsened, decisionRows, type CalibrationEvidence, type DecisionEvidence } from './classification-evidence.vm';

@Component({
  selector: 'ck-classification-evidence',
  standalone: true,
  imports: [CurveChartComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (calibration(); as cal) {
      <section class="ck-chart" data-testid="calibration-evidence" [class.ck-worse]="worse()">
        <div class="ck-section-label">{{ i18n.t('models.calibration.title') }} · {{ cal.method }}</div>
        <p class="ck-hint">{{ i18n.t('models.calibration.rows', { fit: cal.fit_rows, calibration: cal.calibration_rows }) }}</p>
        <table>
          <thead><tr><th></th><th>{{ i18n.t('models.calibration.before') }}</th><th>{{ i18n.t('models.calibration.after') }}</th></tr></thead>
          <tbody>
            <tr><th>Brier</th><td>{{ number(cal.before.brier_score) }}</td><td>{{ number(cal.after.brier_score) }}</td></tr>
            <tr><th>Log loss</th><td>{{ number(cal.before.log_loss) }}</td><td>{{ number(cal.after.log_loss) }}</td></tr>
          </tbody>
        </table>
        <p class="ck-hint">{{ i18n.t(worse() ? 'models.calibration.worse' : 'models.calibration.hint') }}</p>
        @if (cal.before.curve?.length) {
          <div class="ck-section-label">{{ i18n.t('models.calibration.before') }}</div>
          <ck-curve-chart [points]="cal.before.curve" [reference]="diagonal" [fill]="false"
            [label]="i18n.t('models.calibration.before')" [xLabel]="i18n.t('models.calibration.x')" [yLabel]="i18n.t('models.calibration.y')" />
          <div class="ck-section-label">{{ i18n.t('models.calibration.after') }}</div>
          <ck-curve-chart [points]="cal.after.curve" [reference]="diagonal" [fill]="false"
            [label]="i18n.t('models.calibration.after')" [xLabel]="i18n.t('models.calibration.x')" [yLabel]="i18n.t('models.calibration.y')" />
        }
      </section>
    }
    @if (decision(); as value) {
      <section class="ck-chart" data-testid="decision-evidence">
        <div class="ck-section-label">{{ i18n.t('models.decision.title') }} · {{ number(value.threshold) }}</div>
        <p class="ck-hint">{{ i18n.t('models.decision.hint', { criterion: i18n.t('models.spec.threshold.' + value.criterion) }) }}</p>
        <table>
          <thead><tr><th></th><th>{{ i18n.t('models.decision.default') }}</th><th>{{ i18n.t('models.decision.tuned') }}</th></tr></thead>
          <tbody>@for (row of rows(); track row.key) {
            <tr><th>{{ i18n.t('models.metric.' + row.key) }}</th><td>{{ percent(row.before) }}</td><td>{{ percent(row.after) }}</td></tr>
          }</tbody>
        </table>
      </section>
    }
    @for (warning of warnings(); track warning.code) {
      <p class="ck-warning" role="status" data-testid="classification-warning">{{ i18n.t('models.error.' + warning.code) }}</p>
    }
  `,
  styles: [`
    :host { display: contents; }
    .ck-chart { min-width: 0; padding: 16px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; }
    .ck-section-label { color: var(--ck-fg-2); font-size: 12px; margin-bottom: 8px; }
    .ck-hint { color: var(--ck-fg-4); font-size: 11px; line-height: 1.5; }
    .ck-worse { border-color: var(--ck-signal-warn); }
    .ck-worse > .ck-hint, .ck-warning { color: var(--ck-signal-warn); }
    .ck-warning { font-size: 12px; }
    table { width: 100%; font-size: 12px; color: var(--ck-fg-2); border-collapse: collapse; }
    th, td { text-align: right; padding: 8px 4px; border-bottom: 1px solid var(--ck-stroke-2); font-variant-numeric: tabular-nums; }
    th:first-child { text-align: left; font-weight: 400; }
  `],
})
export class ClassificationEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly calibration = input<CalibrationEvidence | null | undefined>();
  readonly decision = input<DecisionEvidence | null | undefined>();
  readonly warnings = input<{ code: string }[]>([]);
  protected readonly diagonal: CurveReference = { kind: 'diagonal' };
  protected readonly worse = computed(() => calibrationWorsened(this.calibration()));
  protected readonly rows = computed(() => decisionRows(this.decision()));
  protected number(value: number | null): string { return value === null ? '—' : value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 }); }
  protected percent(value: number | null): string { return value === null ? '—' : value.toLocaleString(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 }); }
}
