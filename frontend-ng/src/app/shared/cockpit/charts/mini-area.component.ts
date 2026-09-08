import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { ckChartToneVar, ckChartUid, type CkChartTone } from './chart.types';
import { cubicSmoothAreaPath, cubicSmoothPath } from './svg-path';

@Component({
  selector: 'ck-chart-mini-area',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (points.length >= 2) {
      <svg
        [attr.viewBox]="'0 0 ' + width + ' ' + height"
        [attr.width]="width"
        [attr.height]="height"
        style="display:block;overflow:visible"
      >
        <defs>
          <linearGradient [attr.id]="fillId" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" [attr.stop-color]="color" stop-opacity="0.35" />
            <stop offset="1" [attr.stop-color]="color" stop-opacity="0.02" />
          </linearGradient>
        </defs>
        <path [attr.d]="area" [attr.fill]="'url(#' + fillId + ')'" />
        <path
          [attr.d]="line"
          fill="none"
          [attr.stroke]="color"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <circle
          [attr.cx]="end.x"
          [attr.cy]="end.y"
          r="2.2"
          [attr.fill]="color"
        />
      </svg>
    }
  `,
  styles: [':host { display: block; }'],
})
export class CkChartMiniAreaComponent {
  @Input() values: number[] = [];
  @Input() width = 70;
  @Input() height = 24;
  @Input() tone: CkChartTone = 'ink';
  @Input() maxValue: number | null = null;

  readonly fillId = ckChartUid('ck-mini-area');

  get color(): string {
    return ckChartToneVar(this.tone);
  }

  get points(): { x: number; y: number }[] {
    const values = this.values.filter((value) => Number.isFinite(value));
    if (values.length < 2) return [];
    const max = this.maxValue != null && this.maxValue > 0
      ? this.maxValue
      : Math.max(0, ...values) || 1;
    const padX = 2;
    const padY = 1;
    const span = this.width - padX * 2;
    const rise = this.height - padY * 2;
    const step = span / (values.length - 1);
    return values.map((value, i) => ({
      x: padX + i * step,
      y: this.height - padY - (Math.max(0, value) / max) * rise,
    }));
  }

  get line(): string {
    return cubicSmoothPath(this.points);
  }

  get area(): string {
    return cubicSmoothAreaPath(this.points, null, this.height);
  }

  get end(): { x: number; y: number } {
    return this.points[this.points.length - 1] ?? { x: 0, y: 0 };
  }
}
