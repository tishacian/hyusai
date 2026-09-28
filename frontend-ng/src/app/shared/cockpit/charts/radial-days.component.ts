import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  SimpleChanges,
  OnChanges,
} from '@angular/core';

import {
  attrFromTarget,
  hostPointerPoint,
  shouldRebuildLayout,
} from './chart-interact';
import { CkChartTipComponent, type CkChartTipLine } from './chart-tip.component';
import { CK_DECLARED_DASH_BOLD, ckChartUid, type CkChartTick } from './chart.types';
import { radialDayAngle, radialSpokeEndpoints, radialSpokeLength } from './svg-path';

export interface CkRadialDay {
  measured: number;
  declared: number;
  weekend?: boolean;
  dateLabel?: string;
  shortLabel?: string;
  runs?: number;
  systems?: number;
  tip?: { title: string; lines: readonly CkChartTipLine[] };
  aria?: string;
}

export interface CkRadialMark {
  x: number;
  y: number;
  label: string;
  index?: number;
}

export interface RadialSpoke {
  index: number;
  weekend: boolean;
  peak: boolean;
  len: number;
  ink: string;
  teal: string;
  /** Dash pattern of the declared segment: the estimate reads without colour. */
  tealDash: string | null;
  hit: string;
  tipX: number;
  tipY: number;
  total: number;
  aria: string;
}

interface RadialLayout {
  spokes: RadialSpoke[];
  peaks: CkRadialMark[];
  tickMarks: CkRadialMark[];
}

/** Days at or above this share of the maximum get a value label at the spoke tip. */
export const CK_RADIAL_PEAK_SHARE = 0.93;

const HIT_PAD = 12;

@Component({
  selector: 'ck-chart-radial-days',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkChartTipComponent],
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + size + ' ' + size"
      [attr.width]="size"
      [attr.height]="size"
      style="display:block;overflow:visible"
      [class.is-lock-view]="isLockView()"
      (pointerdown)="onPointer($event)"
      (pointermove)="onPointer($event)"
      (pointerleave)="onLeave()"
      (focusin)="onPointer($event)"
      (focusout)="onLeave()"
      (click)="onClick($event)"
      (keydown)="onKeydown($event)"
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
      @for (spoke of spokes; track spoke.index) {
        <g
          class="ck-spoke"
          [class.is-lit]="isDayLit(spoke.index)"
          [class.is-dim]="isDimmed() && !isDayLit(spoke.index)"
          [style.--i]="spoke.index"
          [style.--len]="spoke.len"
        >
          @if (spoke.ink) {
            <path
              class="ck-spoke-stroke"
              [attr.d]="spoke.ink"
              fill="none"
              stroke="var(--ck-data-measured)"
              [attr.stroke-opacity]="spoke.weekend ? 0.35 : 1"
              stroke-width="5"
              stroke-linecap="round"
            />
          }
          @if (spoke.teal) {
            <path
              class="ck-spoke-declared"
              [attr.d]="spoke.teal"
              fill="none"
              stroke="var(--ck-data-declared)"
              [attr.stroke-opacity]="spoke.weekend ? 0.35 : 1"
              stroke-width="5"
              stroke-linecap="round"
              [attr.stroke-dasharray]="spoke.tealDash"
            />
          }
          <path
            class="ck-hit"
            role="button"
            [attr.d]="spoke.hit"
            [attr.data-day]="spoke.index"
            [attr.data-testid]="spoke.peak ? 'ck-radial-peak' : null"
            [attr.tabindex]="spoke.index === rovingDay() ? 0 : -1"
            [attr.aria-pressed]="spoke.index === lockedDay"
            [attr.aria-label]="spoke.aria"
          />
        </g>
      }
      @if (lockMark; as mark) {
        <circle
          class="ck-lock-mark"
          data-testid="ck-radial-lock"
          [attr.cx]="mark.x"
          [attr.cy]="mark.y"
          r="3.5"
          fill="var(--ck-bg-base)"
          stroke="var(--ck-fg-1)"
          stroke-width="1.5"
          aria-hidden="true"
        />
      }
      @for (mark of peakMarks; track $index) {
        <text
          [attr.x]="mark.x"
          [attr.y]="mark.y"
          fill="var(--ck-fg-1)"
          font-family="var(--ck-font-mono)"
          [attr.font-size]="10 * labelScale"
          text-anchor="middle"
        >{{ mark.label }}</text>
      }
      @for (tick of tickMarks; track $index) {
        <g [attr.data-week]="tick.index">
          <rect
            class="ck-hit"
            role="img"
            [attr.x]="tick.x - 14"
            [attr.y]="tick.y - 10"
            width="28"
            height="16"
            [attr.tabindex]="0"
            [attr.aria-label]="tick.label"
          />
          <text
            [attr.x]="tick.x"
            [attr.y]="tick.y"
            fill="var(--ck-fg-3)"
            font-family="var(--ck-font-mono)"
            [attr.font-size]="8 * labelScale"
            text-anchor="middle"
          >{{ tick.label }}</text>
        </g>
      }
      @if (rangeLabel) {
        <text
          [attr.x]="cx"
          [attr.y]="10 * labelScale"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-mono)"
          [attr.font-size]="9 * labelScale"
          text-anchor="middle"
        >{{ rangeLabel }}</text>
      }
      @if (shownCenter) {
        <text
          [attr.x]="cx"
          [attr.y]="cy - 4 * textScale"
          fill="var(--ck-fg-1)"
          font-family="var(--ck-font-sans)"
          font-weight="600"
          [attr.font-size]="26 * textScale"
          letter-spacing="-0.5"
          text-anchor="middle"
        >{{ shownCenter }}</text>
      }
      @if (shownCaption) {
        <text
          [attr.x]="cx"
          [attr.y]="cy + 14 * textScale"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-sans)"
          [attr.font-size]="10 * textScale"
          text-anchor="middle"
        >{{ shownCaption }}</text>
      }
    </svg>
    <ck-chart-tip
      [open]="tipOpen"
      [title]="tipTitle"
      [lines]="tipLines"
      [x]="tipX"
      [y]="tipY"
    />
  `,
  styles: [`
    :host { display: block; position: relative; max-width: 100%; }
    svg { max-width: 100%; height: auto; }
    .ck-spoke { transition: opacity 160ms var(--ck-ease-out, ease-out); }
    /* Arrow keys walk the days: keyboard moves never animate. */
    svg:has(.ck-hit:focus-visible) .ck-spoke { transition: none; }
    .ck-spoke.is-dim { opacity: 0.35; }
    /* A lock stays on screen while the reader works elsewhere: dim less than a passing hover. */
    .is-lock-view .ck-spoke.is-dim { opacity: 0.55; }
    .ck-spoke.is-lit { opacity: 1; }
    .ck-hit { fill: transparent; stroke: transparent; stroke-width: 12; stroke-linecap: round; pointer-events: stroke; cursor: pointer; }
    path.ck-hit:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 1px; }
    rect.ck-hit { pointer-events: all; stroke-width: 0; }
    :host-context(.hv2-enter) .ck-spoke-stroke {
      stroke-dasharray: var(--len);
      stroke-dashoffset: var(--len);
      animation: ckSpokeIn 520ms var(--ck-ease-out, ease-out) forwards;
      animation-delay: calc(var(--i, 0) * 6ms);
    }
    /* The declared segment keeps its dashes: a draw-in would need the dash
       array for itself, so it fades in on the same timing instead. */
    :host-context(.hv2-enter) .ck-spoke-declared {
      opacity: 0;
      animation: ckSpokeFade 520ms var(--ck-ease-out, ease-out) forwards;
      animation-delay: calc(var(--i, 0) * 6ms);
    }
    @keyframes ckSpokeIn { to { stroke-dashoffset: 0; } }
    @keyframes ckSpokeFade { to { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) {
      .ck-spoke { transition: none; }
      :host-context(.hv2-enter) .ck-spoke-stroke { animation: none; stroke-dashoffset: 0; }
      :host-context(.hv2-enter) .ck-spoke-declared { animation: none; opacity: 1; }
    }
  `],
})
export class CkChartRadialDaysComponent implements OnChanges {
  @Input() days: CkRadialDay[] = [];
  @Input() size = 360;
  @Input() innerRadius = 62;
  @Input() outerRadius = 156;
  @Input() maxValue: number | null = null;
  @Input() centerValue = '';
  @Input() centerCaption = '';
  @Input() rangeLabel = '';
  @Input() ticks: CkChartTick[] = [];
  /** Formats the total of a peak day for its spoke-tip label (e.g. `71 h`). */
  @Input() peakLabel: (total: number) => string = (total) => String(Math.round(total));
  @Input() hoverDay: number | null = null;
  /** The day the page locked (click, Enter, Space): keeps its ring and the keyboard entry point. */
  @Input() lockedDay: number | null = null;
  @Output() readonly dayHover = new EventEmitter<number | null>();
  /** Click, Enter or Space on a spoke: the page toggles its lock on that day. */
  @Output() readonly dayLock = new EventEmitter<number>();

  readonly haloId = ckChartUid('ck-radial-halo');

  tipOpen = false;
  tipTitle = '';
  tipLines: CkChartTipLine[] = [];
  tipX = 0;
  tipY = 0;
  private hoverWeek: number | null = null;
  private localDay: number | null = null;
  /** Roving tab stop: the spoke the arrow keys last moved to. */
  private focusDay: number | null = null;
  private built: RadialLayout | null = null;

  get cx(): number {
    return this.size / 2;
  }

  get cy(): number {
    return this.size / 2;
  }

  /** Centre copy grows with the dial so a 580-unit cadran does not whisper. */
  get textScale(): number {
    return Math.max(1, this.size / 360);
  }

  /** Tick, peak and range labels grow more slowly than the centre. */
  get labelScale(): number {
    return Math.max(1, Math.sqrt(this.size / 360));
  }

  get haloRadius(): number {
    return this.outerRadius + 12;
  }

  get guideRadii(): number[] {
    return [this.innerRadius, (this.innerRadius + this.outerRadius) / 2, this.outerRadius];
  }

  get spokes(): RadialSpoke[] {
    return this.layout().spokes;
  }

  get peakMarks(): CkRadialMark[] {
    return this.layout().peaks;
  }

  get tickMarks(): CkRadialMark[] {
    return this.layout().tickMarks;
  }

  get shownCenter(): string {
    const day = this.activeDay();
    if (day == null) return this.centerValue;
    const spoke = this.spokes[day];
    return spoke ? this.peakLabel(spoke.total) : this.centerValue;
  }

  get shownCaption(): string {
    const day = this.activeDay();
    if (day == null) return this.centerCaption;
    return this.days[day]?.shortLabel || this.days[day]?.dateLabel || this.centerCaption;
  }

  /** Ring on the tip of the locked spoke: tells a lock from a passing preview, without motion. */
  get lockMark(): { x: number; y: number } | null {
    const day = this.lockedDay;
    if (day == null) return null;
    const spoke = this.spokes[day];
    if (!spoke) return null;
    const angle = radialDayAngle(day, this.days.length || 30);
    const reach = this.innerRadius + Math.max(8, spoke.len) + 7;
    return { x: this.cx + reach * Math.cos(angle), y: this.cy + reach * Math.sin(angle) };
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (shouldRebuildLayout(Object.keys(changes)) || !this.built) {
      this.built = this.build();
    }
    if (changes['days'] && this.focusDay != null && this.focusDay >= this.days.length) this.focusDay = null;
  }

  /** The one spoke in the tab order: the last one reached by arrows, else the lock, else the peak. */
  rovingDay(): number {
    const n = this.spokes.length;
    const pick = this.focusDay ?? this.lockedDay;
    if (pick != null && pick >= 0 && pick < n) return pick;
    const peak = this.spokes.findIndex((spoke) => spoke.peak);
    return peak >= 0 ? peak : 0;
  }

  onClick(event: MouseEvent): void {
    const dayAttr = attrFromTarget(event.target, 'data-day');
    if (dayAttr == null) return;
    this.dayLock.emit(Number(dayAttr));
  }

  onKeydown(event: KeyboardEvent): void {
    const dayAttr = attrFromTarget(event.target, 'data-day');
    if (dayAttr == null) return;
    const index = Number(dayAttr);
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.dayLock.emit(index);
      return;
    }
    const n = this.spokes.length;
    if (!n) return;
    const next = rovingTarget(event.key, index, n);
    if (next == null) return;
    event.preventDefault();
    this.focusSpoke(event.currentTarget, next);
  }

  private focusSpoke(svg: EventTarget | null, index: number): void {
    if (!(svg instanceof Element)) return;
    const target = svg.querySelector(`[data-day="${index}"]`);
    if (!(target instanceof SVGElement)) return;
    // The global ring skips [tabindex="-1"]; the stop moves before focus does.
    svg.querySelectorAll('[data-day][tabindex="0"]').forEach((node) => node.setAttribute('tabindex', '-1'));
    target.setAttribute('tabindex', '0');
    this.focusDay = index;
    target.focus();
  }

  isDayLit(index: number): boolean {
    const day = this.activeDay();
    if (day === index) return true;
    if (this.hoverWeek != null) return index >= this.hoverWeek && index < this.hoverWeek + 7;
    return false;
  }

  /** The lit day is the lock, not a pointer or keyboard preview. */
  isLockView(): boolean {
    return this.lockedDay != null && this.localDay == null && this.hoverWeek == null && this.hoverDay === this.lockedDay;
  }

  isDimmed(): boolean {
    return this.activeDay() != null || this.hoverWeek != null;
  }

  onPointer(event: PointerEvent | FocusEvent): void {
    const dayAttr = attrFromTarget(event.target, 'data-day');
    const weekAttr = attrFromTarget(event.target, 'data-week');
    if (event instanceof PointerEvent && event.pointerType === 'touch' && event.type === 'pointermove') {
      return;
    }
    if (dayAttr != null) {
      const index = Number(dayAttr);
      if (event instanceof PointerEvent && event.pointerType === 'touch' && event.type === 'pointerdown') {
        this.toggleDay(index);
        this.showDayTip(index, event);
        return;
      }
      this.setLocalDay(index);
      this.showDayTip(index, event);
      return;
    }
    if (weekAttr != null) {
      this.hoverWeek = Number(weekAttr);
      this.setLocalDay(null);
      this.tipOpen = false;
      return;
    }
    if (event.type === 'pointermove') return;
    this.onLeave();
  }

  onLeave(): void {
    this.hoverWeek = null;
    this.setLocalDay(null);
    this.tipOpen = false;
  }

  private activeDay(): number | null {
    return this.localDay ?? this.hoverDay;
  }

  private toggleDay(index: number): void {
    this.setLocalDay(this.localDay === index ? null : index);
    if (this.localDay == null) this.tipOpen = false;
  }

  private setLocalDay(index: number | null): void {
    if (this.localDay === index) return;
    this.localDay = index;
    this.hoverWeek = null;
    this.dayHover.emit(index);
  }

  private showDayTip(index: number, event: Event): void {
    const spoke = this.spokes[index];
    const day = this.days[index];
    if (!spoke || !day) return;
    const host = (event.currentTarget as SVGElement).closest('ck-chart-radial-days')
      ?? (event.target as Element | null)?.closest('ck-chart-radial-days');
    if (event instanceof PointerEvent) {
      const origin = host instanceof HTMLElement ? host : undefined;
      const pt = origin
        ? hostPointerPoint(origin, event.clientX, event.clientY)
        : { x: spoke.tipX, y: spoke.tipY };
      this.tipX = pt.x;
      this.tipY = pt.y;
    } else {
      this.tipX = spoke.tipX;
      this.tipY = spoke.tipY;
    }
    this.tipTitle = day.tip?.title || day.dateLabel || day.shortLabel || '';
    this.tipLines = day.tip ? [...day.tip.lines] : spokeTipLines(day, this.peakLabel(spoke.total));
    this.tipOpen = true;
  }

  private layout(): RadialLayout {
    return this.built ?? (this.built = this.build());
  }

  private build(): RadialLayout {
    const days = this.days;
    const n = days.length;
    const max = this.resolvedMax();
    const spokes: RadialSpoke[] = [];
    const peaks: CkRadialMark[] = [];
    let peakIndex = -1;
    let peakTotal = 0;
    for (let i = 0; i < n; i += 1) {
      const day = days[i]!;
      const measured = Math.max(0, day.measured);
      const declared = Math.max(0, day.declared);
      const total = measured + declared;
      const angle = radialDayAngle(i, n || 30);
      const length = total > 0
        ? radialSpokeLength(total, max, this.innerRadius, this.outerRadius)
        : 8;
      const ends = radialSpokeEndpoints({
        cx: this.cx,
        cy: this.cy,
        angle,
        innerRadius: this.innerRadius,
        length,
        measuredShare: total > 0 ? measured / total : 0,
      });
      const start = `M${ends.start.x.toFixed(1)},${ends.start.y.toFixed(1)}`;
      const ink = measured > 0
        ? `${start}L${ends.mid.x.toFixed(1)},${ends.mid.y.toFixed(1)}`
        : '';
      const teal = declared > 0
        ? `M${ends.mid.x.toFixed(1)},${ends.mid.y.toFixed(1)}L${ends.end.x.toFixed(1)},${ends.end.y.toFixed(1)}`
        : '';
      const hitEnd = ends.end;
      const hit = `M${ends.start.x.toFixed(1)},${ends.start.y.toFixed(1)}L${hitEnd.x.toFixed(1)},${hitEnd.y.toFixed(1)}`;
      const tipX = this.cx + (this.innerRadius + length + HIT_PAD) * Math.cos(angle);
      const tipY = this.cy + (this.innerRadius + length + HIT_PAD) * Math.sin(angle);
      if (total > peakTotal) {
        peakTotal = total;
        peakIndex = i;
      }
      const isPeak = total > 0 && total >= CK_RADIAL_PEAK_SHARE * max;
      if (isPeak) {
        peaks.push({
          x: this.cx + (this.innerRadius + length + 13) * Math.cos(angle),
          y: this.cy + (this.innerRadius + length + 13) * Math.sin(angle) + 3,
          label: this.peakLabel(total),
          index: i,
        });
      }
      const aria = day.aria || [day.dateLabel, this.peakLabel(total)].filter(Boolean).join(' · ');
      spokes.push({
        index: i,
        weekend: Boolean(day.weekend),
        peak: false,
        len: Math.max(1, Math.hypot(hitEnd.x - ends.start.x, hitEnd.y - ends.start.y)),
        ink,
        teal,
        tealDash: teal ? CK_DECLARED_DASH_BOLD : null,
        hit,
        tipX,
        tipY,
        total,
        aria,
      });
    }
    if (peakIndex >= 0) spokes[peakIndex]!.peak = true;
    const tickCount = n || 30;
    return {
      spokes,
      peaks,
      tickMarks: this.ticks.map((tick) => {
        const angle = radialDayAngle(tick.index, tickCount);
        return {
          x: this.cx + (this.outerRadius + 13) * Math.cos(angle),
          y: this.cy + (this.outerRadius + 13) * Math.sin(angle) + 3,
          label: tick.label,
          index: tick.index,
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

/** Arrow keys walk the days (the dial reads clockwise), Home and End jump to the ends. */
export function rovingTarget(key: string, index: number, count: number): number | null {
  if (count <= 0) return null;
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (index + 1) % count;
    case 'ArrowLeft':
    case 'ArrowUp':
      return (index - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}

function spokeTipLines(day: CkRadialDay, totalLabel: string): CkChartTipLine[] {
  const lines: CkChartTipLine[] = [{ label: '', value: totalLabel }];
  if (day.measured > 0) lines.push({ label: '●', value: String(day.measured) });
  if (day.declared > 0) lines.push({ label: '◐', value: String(day.declared) });
  if (day.runs != null) lines.push({ label: '', value: String(day.runs) });
  if (day.systems != null) lines.push({ label: '', value: String(day.systems) });
  return lines;
}
