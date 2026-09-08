import { ChangeDetectionStrategy, Component, ElementRef, Input, inject } from '@angular/core';

import { hostPointerPoint } from './chart-interact';
import { CkChartTipComponent } from './chart-tip.component';
import { ckChartToneVar, type CkChartTone } from './chart.types';

@Component({
  selector: 'ck-chart-unit-dots',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkChartTipComponent],
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + svgWidth + ' ' + svgHeight"
      [attr.width]="svgWidth"
      [attr.height]="svgHeight"
      style="display:block;overflow:visible"
      (pointermove)="onMove($event)"
      (pointerleave)="onLeave()"
    >
      @for (dot of dots; track $index) {
        <circle [attr.cx]="dot.x" [attr.cy]="dot.y" [attr.r]="radius" [attr.fill]="color" />
      }
    </svg>
    <ck-chart-tip [open]="tipOpen" [title]="tipTitle" [lines]="[]" [x]="tipX" [y]="tipY" />
  `,
  styles: [':host { display: block; position: relative; }'],
})
export class CkChartUnitDotsComponent {
  private readonly host = inject(ElementRef<HTMLElement>);
  @Input() units = 0;
  @Input() unitsPerDot = 1;
  @Input() tone: CkChartTone = 'ink';
  @Input() dotSize = 5;
  @Input() gap = 3;
  @Input() width: number | null = null;
  @Input() tipTitle = '';

  tipOpen = false;
  tipX = 0;
  tipY = 0;

  get color(): string {
    return ckChartToneVar(this.tone);
  }

  get radius(): number {
    return this.dotSize / 2;
  }

  get count(): number {
    if (!(this.unitsPerDot > 0) || !(this.units > 0)) return 0;
    return Math.max(1, Math.round(this.units / this.unitsPerDot));
  }

  get columns(): number {
    const count = this.count;
    if (!count) return 1;
    if (this.width == null || this.width <= 0) return count;
    const cell = this.dotSize + this.gap;
    return Math.max(1, Math.floor((this.width + this.gap) / cell));
  }

  get svgWidth(): number {
    const cols = Math.min(this.columns, Math.max(this.count, 1));
    return cols * this.dotSize + Math.max(0, cols - 1) * this.gap;
  }

  get svgHeight(): number {
    const rows = Math.max(1, Math.ceil(this.count / this.columns));
    return rows * this.dotSize + Math.max(0, rows - 1) * this.gap;
  }

  onMove(event: PointerEvent): void {
    if (!this.tipTitle) return;
    const pt = hostPointerPoint(this.host.nativeElement, event.clientX, event.clientY);
    this.tipX = pt.x;
    this.tipY = pt.y;
    this.tipOpen = true;
  }

  onLeave(): void {
    this.tipOpen = false;
  }

  get dots(): { x: number; y: number }[] {
    const count = this.count;
    const cols = this.columns;
    const cell = this.dotSize + this.gap;
    const r = this.radius;
    const out: { x: number; y: number }[] = [];
    for (let i = 0; i < count; i += 1) {
      const col = i % cols;
      const row = Math.floor(i / cols);
      out.push({ x: col * cell + r, y: row * cell + r });
    }
    return out;
  }
}
