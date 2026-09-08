import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { ckChartUid, type CkChartTick } from './chart.types';
import { radialDayAngle, radialSpokeEndpoints, radialSpokeLength } from './svg-path';

export interface CkRadialDay {
  measured: number;
  declared: number;
  weekend?: boolean;
  label?: string;
}

export interface CkRadialMark {
  x: number;
  y: number;
  label: string;
}

@Component({
  selector: 'ck-chart-radial-days',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + size + ' ' + size"
      [attr.width]="size"
      [attr.height]="size"
      style="display:block;overflow:visible"
    >
      <defs>
        <radialGradient [attr.id]="haloId">
          <stop offset="0" stop-color="var(--ck-signal-cool)" stop-opacity="0.18" />
          <stop offset="0.6" stop-color="var(--ck-signal-cool)" stop-opacity="0.045" />
          <stop offset="1" stop-color="var(--ck-signal-cool)" stop-opacity="0" />
        </radialGradient>
      </defs>
      <circle [attr.cx]="cx" [attr.cy]="cy" [attr.r]="haloRadius" [attr.fill]="'url(#' + haloId + ')'" />
      @for (r of guideRadii; track r) {
        <circle
          [attr.cx]="cx"
          [attr.cy]="cy"
          [attr.r]="r"
          fill="none"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.1"
          stroke-width="1"
        />
      }
      @if (inkPath) {
        <path [attr.d]="inkPath" fill="none" stroke="var(--ck-fg-1)" stroke-width="5" stroke-linecap="round" />
      }
      @if (tealPath) {
        <path [attr.d]="tealPath" fill="none" stroke="var(--ck-signal-cool)" stroke-width="5" stroke-linecap="round" />
      }
      @if (inkWeekendPath) {
        <path
          [attr.d]="inkWeekendPath"
          fill="none"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.35"
          stroke-width="5"
          stroke-linecap="round"
        />
      }
      @if (tealWeekendPath) {
        <path
          [attr.d]="tealWeekendPath"
          fill="none"
          stroke="var(--ck-signal-cool)"
          stroke-opacity="0.35"
          stroke-width="5"
          stroke-linecap="round"
        />
      }
      @for (mark of peakMarks; track $index) {
        <text
          [attr.x]="mark.x"
          [attr.y]="mark.y"
          fill="var(--ck-fg-1)"
          font-family="var(--ck-font-mono)"
          font-size="10"
          text-anchor="middle"
        >{{ mark.label }}</text>
      }
      @for (tick of tickMarks; track $index) {
        <text
          [attr.x]="tick.x"
          [attr.y]="tick.y"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-mono)"
          font-size="8"
          text-anchor="middle"
        >{{ tick.label }}</text>
      }
      @if (rangeLabel) {
        <text
          [attr.x]="cx"
          y="9"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-mono)"
          font-size="8"
          letter-spacing="1"
          text-anchor="middle"
        >{{ rangeLabel }}</text>
      }
      @if (centerValue) {
        <text
          [attr.x]="cx"
          [attr.y]="cy - 4"
          fill="var(--ck-fg-1)"
          font-family="var(--ck-font-sans)"
          font-weight="600"
          font-size="26"
          letter-spacing="-0.5"
          text-anchor="middle"
        >{{ centerValue }}</text>
      }
      @if (centerCaption) {
        <text
          [attr.x]="cx"
          [attr.y]="cy + 14"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-sans)"
          font-size="10"
          text-anchor="middle"
        >{{ centerCaption }}</text>
      }
    </svg>
  `,
  styles: [':host { display: block; }'],
})
export class CkChartRadialDaysComponent {
  @Input() days: CkRadialDay[] = [];
  @Input() size = 360;
  @Input() innerRadius = 62;
  @Input() outerRadius = 156;
  @Input() maxValue: number | null = null;
  @Input() centerValue = '';
  @Input() centerCaption = '';
  @Input() rangeLabel = '';
  @Input() ticks: CkChartTick[] = [];

  readonly haloId = ckChartUid('ck-radial-halo');

  get cx(): number {
    return this.size / 2;
  }

  get cy(): number {
    return this.size / 2;
  }

  get haloRadius(): number {
    return this.outerRadius + 12;
  }

  get guideRadii(): number[] {
    return [this.innerRadius, (this.innerRadius + this.outerRadius) / 2, this.outerRadius];
  }

  get inkPath(): string {
    return this.build().ink;
  }

  get tealPath(): string {
    return this.build().teal;
  }

  get inkWeekendPath(): string {
    return this.build().inkWeekend;
  }

  get tealWeekendPath(): string {
    return this.build().tealWeekend;
  }

  get peakMarks(): CkRadialMark[] {
    return this.build().peaks;
  }

  get tickMarks(): CkRadialMark[] {
    return this.build().tickMarks;
  }

  private build(): {
    ink: string;
    teal: string;
    inkWeekend: string;
    tealWeekend: string;
    peaks: CkRadialMark[];
    tickMarks: CkRadialMark[];
  } {
    const days = this.days;
    const n = days.length;
    const max = this.resolvedMax();
    const ink: string[] = [];
    const teal: string[] = [];
    const inkWeekend: string[] = [];
    const tealWeekend: string[] = [];
    const peaks: CkRadialMark[] = [];
    for (let i = 0; i < n; i += 1) {
      const day = days[i];
      const measured = Math.max(0, day.measured);
      const declared = Math.max(0, day.declared);
      const total = measured + declared;
      if (total <= 0) continue;
      const angle = radialDayAngle(i, n);
      const length = radialSpokeLength(total, max, this.innerRadius, this.outerRadius);
      const ends = radialSpokeEndpoints({
        cx: this.cx,
        cy: this.cy,
        angle,
        innerRadius: this.innerRadius,
        length,
        measuredShare: measured / total,
      });
      const inner = `M${ends.start.x.toFixed(1)},${ends.start.y.toFixed(1)}L${ends.mid.x.toFixed(1)},${ends.mid.y.toFixed(1)}`;
      const outer = `M${ends.mid.x.toFixed(1)},${ends.mid.y.toFixed(1)}L${ends.end.x.toFixed(1)},${ends.end.y.toFixed(1)}`;
      if (day.weekend) {
        if (measured > 0) inkWeekend.push(inner);
        if (declared > 0) tealWeekend.push(outer);
      } else {
        if (measured > 0) ink.push(inner);
        if (declared > 0) teal.push(outer);
      }
      if (day.label) {
        peaks.push({
          x: this.cx + (this.innerRadius + length + 13) * Math.cos(angle),
          y: this.cy + (this.innerRadius + length + 13) * Math.sin(angle) + 3,
          label: day.label,
        });
      }
    }
    const tickCount = n || 30;
    return {
      ink: ink.join(''),
      teal: teal.join(''),
      inkWeekend: inkWeekend.join(''),
      tealWeekend: tealWeekend.join(''),
      peaks,
      tickMarks: this.ticks.map((tick) => {
        const angle = radialDayAngle(tick.index, tickCount);
        return {
          x: this.cx + (this.outerRadius + 13) * Math.cos(angle),
          y: this.cy + (this.outerRadius + 13) * Math.sin(angle) + 3,
          label: tick.label,
        };
      }),
    };
  }

  private resolvedMax(): number {
    if (this.maxValue != null && this.maxValue > 0) return this.maxValue;
    const peak = this.days.reduce(
      (max, day) => Math.max(max, Math.max(0, day.measured) + Math.max(0, day.declared)),
      0,
    );
    return peak || 1;
  }
}
