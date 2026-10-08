import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { CurveChartComponent } from '@app/features/data/viz/curve-chart.component';
import type { IntervalEvidence } from './models.vm';
import { intervalEvidence } from './tabular-intervals.vm';

@Component({
  selector: 'ck-tabular-intervals', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush, imports: [CurveChartComponent],
  template: `
    @if (evidence(); as block) {
      <section class="ck-charts" data-testid="interval-evidence">
        <div class="ck-chart">
          <h3>{{ i18n.t('models.intervals.title') }}</h3>
          <ck-curve-chart [points]="points()" [reference]="diagonal"
            [label]="i18n.t('models.intervals.title')"
            [xLabel]="i18n.t('models.intervals.level')" [yLabel]="i18n.t('models.intervals.coverage')" />
          <p>{{ i18n.t('models.intervals.hint', { folds: block.folds, rows: block.residual_rows }) }}</p>
        </div>
        <div class="ck-chart">
          <table>
            <thead><tr><th>{{ i18n.t('models.intervals.level') }}</th><th>{{ i18n.t('models.intervals.coverage') }}</th><th>{{ i18n.t('models.intervals.width') }}</th></tr></thead>
            <tbody>@for (row of block.levels; track row.level) {
              <tr><td>{{ percent(row.level) }}</td><td>{{ percent(row.coverage) }}</td><td>{{ number(row.width) }}</td></tr>
            }</tbody>
          </table>
        </div>
      </section>
    }
  `,
  styles: [`
    .ck-charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 16px; margin: 20px 0; }
    .ck-chart { min-width: 0; padding: 16px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; }
    h3, th { font-size: 12px; font-weight: 500; color: var(--ck-fg-2); }
    p { font-size: 11px; color: var(--ck-fg-4); line-height: 1.5; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    td, th { padding: 10px 4px; text-align: right; border-bottom: 1px solid var(--ck-stroke-2); }
    td:first-child, th:first-child { text-align: left; }
  `],
})
export class TabularIntervalsComponent {
  readonly i18n = inject(I18nService);
  readonly intervals = input<IntervalEvidence | null | undefined>(null);
  protected readonly evidence = computed(() => intervalEvidence(this.intervals()));
  protected readonly points = computed(() => this.evidence()?.levels.map(row => ({ x: row.level, y: row.coverage })) ?? []);
  protected readonly diagonal = { kind: 'diagonal' } as const;
  protected percent(value: number): string { return new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 }).format(value); }
  protected number(value: number): string { return new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 3 }).format(value); }
}
