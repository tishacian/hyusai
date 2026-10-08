import { ChangeDetectionStrategy, Component, ElementRef, computed, inject, input } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { ThemeService } from '@app/core/theme.service';
import { I18nService } from '@app/core/i18n.service';
import { tokenAlpha } from '@app/features/data/viz/viz.vm';
import { partialPlot, type PartialEffect } from './explanation-evidence.vm';

@Component({
  selector: 'ck-partial-effect-chart', standalone: true, imports: [BaseChartDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div class="ck-plot"><canvas baseChart type="line" [data]="data()" [options]="options()" role="img" [attr.aria-label]="effect().feature"></canvas></div>`,
  styles: [`.ck-plot { height: 220px; position: relative; min-width: 0; }`],
})
export class PartialEffectChartComponent {
  readonly effect = input.required<PartialEffect>();
  readonly i18n = inject(I18nService);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly theme = inject(ThemeService);
  private readonly plot = computed(() => partialPlot(this.effect(), this.i18n.locale()));
  private readonly palette = computed(() => {
    this.theme.resolved();
    const styles = typeof getComputedStyle === 'function' ? getComputedStyle(this.host.nativeElement) : null;
    const read = (name: string, fallback: string) => styles?.getPropertyValue(name).trim() || fallback;
    return { line: read('--ck-fg-2', '#a1a1aa'), faint: tokenAlpha(read('--ck-fg-4', '#71717a'), 0.22), text: read('--ck-fg-3', '#a1a1aa'), grid: read('--ck-stroke-2', '#27272a') };
  });
  protected readonly data = computed<ChartData<'line'>>(() => {
    const series = this.plot(), palette = this.palette();
    return {
      labels: series.labels,
      datasets: [
        { label: this.i18n.t('models.explain.pdp.average'), data: series.average, borderColor: palette.line, borderWidth: 2.5, pointRadius: 1, pointHoverRadius: 4, order: 0 },
        ...series.ice.map((row) => ({ data: row, borderColor: palette.faint, borderWidth: 1, pointRadius: 0, order: 1 })),
      ],
    };
  });
  protected readonly options = computed<ChartConfiguration<'line'>['options']>(() => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    locale: this.i18n.locale(),
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: false }, tooltip: { filter: (item) => item.datasetIndex === 0 } },
    scales: { x: { type: this.plot().scale, ticks: { color: this.palette().text, maxTicksLimit: 6 }, grid: { display: false } }, y: { ticks: { color: this.palette().text }, grid: { color: this.palette().grid } } },
  }));
}
