import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';
import { I18nService } from '@app/core/i18n.service';
import { durationChart, expenseChart, volumeChart, type ActivitySeries } from './activity-series.vm';

@Component({
  selector: 'app-activity-series-charts', standalone: true, imports: [BaseChartDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="chart"><canvas baseChart type="bar" [data]="bars()" [options]="options"
      role="img" [attr.aria-label]="i18n.t(series().population.metric === 'cost' ? 'observability.series.expenses' : 'observability.series.volume')"></canvas></div>
    @if (series().population.metric === 'activity' && lines().datasets.length) {
      <div class="chart"><canvas baseChart type="line" [data]="lines()" [options]="lineOptions"
        role="img" [attr.aria-label]="i18n.t('observability.series.durations')"></canvas></div>
    }
  `,
  styles: [`.chart{height:230px;position:relative;min-width:0;margin:16px 0}`],
})
export class ActivitySeriesChartsComponent {
  readonly series = input.required<ActivitySeries>();
  readonly i18n = inject(I18nService);
  readonly bars = computed(() => this.series().population.metric === 'cost' ? expenseChart(this.series(), basis => this.i18n.t('observability.series.basis.' + basis)) : volumeChart(this.series(), status => this.i18n.t('observability.activities.status.' + status)));
  readonly lines = computed(() => durationChart(this.series(), kind => this.i18n.t('observability.activities.kind.' + kind)));
  readonly options: ChartConfiguration<'bar'>['options'] = {
    responsive: true, maintainAspectRatio: false, animation: false,
    scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { beginAtZero: true } },
    plugins: { legend: { position: 'bottom' } },
  };
  readonly lineOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true, maintainAspectRatio: false, animation: false,
    scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { beginAtZero: true } },
    plugins: { legend: { position: 'bottom' } },
  };
}
