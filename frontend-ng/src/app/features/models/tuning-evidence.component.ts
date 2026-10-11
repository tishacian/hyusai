import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { tuningKnobs, tuningPoints, temporalTuning, tuningWarningKey, type TuningResult } from './tuning-evidence.vm';

@Component({
  selector: 'ck-tuning-evidence', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (result(); as tuning) {
      <div class="charts ck-charts" data-testid="tuning-evidence">
        <section>
          <h3>{{ i18n.t('models.tuning.title') }}</h3>
          @if (temporal(); as validation) {
            <div data-testid="tuning-temporal-validation">
              <p>{{ i18n.t('models.tuning.temporal_validation', { metric: tuning.metric, folds: tuning.folds }) }}</p>
              <p>{{ i18n.t('models.tuning.temporal_range', { start: validation.train_start, end: validation.train_end }) }}</p>
              <p>{{ i18n.t('models.tuning.temporal_holdout', { start: validation.holdout_start, rows: validation.holdout_rows }) }}</p>
              <p>{{ i18n.t('models.tuning.temporal_naive') }}: <strong>{{ number(tuning.baseline?.mae) }}</strong></p>
            </div>
          } @else {
            <p>{{ i18n.t('models.tuning.validation', { metric: tuning.metric, folds: tuning.folds }) }}</p>
          }
          @if (points().length) {
            <svg viewBox="0 0 400 180" role="img" [attr.aria-label]="i18n.t('models.tuning.chart')">
              <path d="M24 15 V150 H385" fill="none" stroke="var(--ck-stroke-2)" />
              @for (point of points(); track point.n) {
                <circle [attr.cx]="point.x" [attr.cy]="point.y" [attr.r]="point.best ? 5 : 3" fill="var(--ck-fg-2)">
                  <title>{{ i18n.t('models.tuning.trial') }} {{ point.n }}: {{ number(point.score) }}</title>
                </circle>
              }
              <text x="24" y="172">0</text><text x="375" y="172">{{ tuning.trials_run - 1 }}</text>
            </svg>
          }
          <p>{{ i18n.t('models.tuning.start') }}: <strong>{{ number(tuning.start.score) }}</strong> ± {{ number(tuning.start.std) }}
             · {{ i18n.t('models.tuning.best') }}: <strong>{{ number(tuning.best.score) }}</strong> ± {{ number(tuning.best.std) }}</p>
          <p>@if (!tuning.warning) { {{ i18n.t('models.tuning.' + tuning.stopped_by) }} · }{{ number(tuning.elapsed_s) }} / {{ tuning.budget_s }} s</p>
          <p>{{ i18n.t('models.tuning.counts', { run: tuning.trials_run, pruned: tuning.trials_pruned, failed: tuning.trials_failed }) }}</p>
          @if (warningKey(); as key) { <p role="status">{{ i18n.t(key) }}</p> }
        </section>
        <section>
          <h3>{{ i18n.t('models.tuning.knobs') }}</h3>
          <table><thead><tr><th>{{ i18n.t('models.tuning.setting') }}</th><th>{{ i18n.t('models.tuning.start') }}</th><th>{{ i18n.t('models.tuning.best') }}</th></tr></thead>
            <tbody>@for (row of knobs(); track row.key) {
              <tr><th>{{ label(row.key) }}</th><td>{{ value(row.before) }}</td><td>{{ value(row.after) }}</td></tr>
            }</tbody>
          </table>
          <p>{{ i18n.t(temporal() ? 'models.tuning.temporal_hint' : 'models.tuning.hint') }}</p>
        </section>
      </div>
    }
  `,
  styles: [`
    .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 16px; }
    section { padding: 14px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; min-width: 0; }
    h3 { font-size: 12px; color: var(--ck-fg-2); margin: 0 0 10px; }
    p, table { font-size: 11px; line-height: 1.6; color: var(--ck-fg-3); }
    svg { width: 100%; max-height: 210px; } text { fill: var(--ck-fg-3); font-size: 10px; }
    table { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: 5px; border-bottom: 1px solid var(--ck-stroke-2); }
  `],
})
export class TuningEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly result = input<TuningResult>();
  protected readonly temporal = computed(() => temporalTuning(this.result()));
  protected readonly warningKey = computed(() => tuningWarningKey(this.result()));
  protected readonly points = computed(() => tuningPoints(this.result()));
  protected readonly knobs = computed(() => tuningKnobs(this.result()));
  protected number(value: number | null | undefined): string { return value == null ? '—' : value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 }); }
  protected value(value: unknown): string { return value === null ? this.i18n.t('models.tuning.auto') : typeof value === 'number' ? this.number(value) : String(value); }
  protected label(key: string): string { const name = 'models.knob.' + key; const text = this.i18n.t(name); return text === name ? key : text; }
}
