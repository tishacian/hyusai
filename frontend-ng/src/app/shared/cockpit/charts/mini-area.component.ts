import { ChangeDetectionStrategy, Component, ElementRef, Input, inject } from '@angular/core';

import { hostPointerPoint, nearestDayIndex } from './chart-interact';
import { CkChartTipComponent } from './chart-tip.component';
import { CK_DECLARED_DASH_THIN, ckChartIsDeclared, ckChartToneVar, ckChartUid, type CkChartTone } from './chart.types';
import { cubicSmoothAreaPath, cubicSmoothPath } from './svg-path';

@Component({
  selector: 'ck-chart-mini-area',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkChartTipComponent],
  template: `
    @if (points.length >= 2) {
      <svg
        [attr.viewBox]="'0 0 ' + width + ' ' + height"
        [attr.width]="width"
        [attr.height]="height"
        style="display:block;overflow:visible"
        (pointermove)="onMove($event)"
        (pointerleave)="onLeave()"
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
          [attr.stroke-dasharray]="lineDash"
        />
        <circle
          [attr.cx]="end.x"
          [attr.cy]="end.y"
          r="2.2"
          [attr.fill]="color"
        />
      </svg>
      <ck-chart-tip [open]="tipOpen" [title]="tipTitle" [lines]="[]" [x]="tipX" [y]="tipY" />
    }
  `,
  styles: [':host { display: block; position: relative; }'],
})
export class CkChartMiniAreaComponent {
  private readonly host = inject(ElementRef<HTMLElement>);

  @Input() values: number[] = [];
  @Input() width = 70;
  @Input() height = 24;
  @Input() tone: CkChartTone = 'ink';
  @Input() maxValue: number | null = null;
  @Input() valueLabel: (value: number, index: number) => string = (value) => String(value);

  tipOpen = false;
  tipTitle = '';
  tipX = 0;
  tipY = 0;

  readonly fillId = ckChartUid('ck-mini-area');

  get color(): string {
    return ckChartToneVar(this.tone);
  }

  /** Declared sparks are dashed: an estimate must read without its colour. */
  get lineDash(): string | null {
    return ckChartIsDeclared(this.tone) ? CK_DECLARED_DASH_THIN : null;
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

  onMove(event: PointerEvent): void {
    const values = this.values.filter((value) => Number.isFinite(value));
    const index = nearestDayIndex(event.offsetX, 2, this.width - 4, values.length);
    const pt = hostPointerPoint(this.host.nativeElement, event.clientX, event.clientY);
    this.tipX = pt.x;
    this.tipY = pt.y;
    this.tipTitle = this.valueLabel(values[index] ?? 0, index);
    this.tipOpen = true;
  }

  onLeave(): void {
    this.tipOpen = false;
  }
}
