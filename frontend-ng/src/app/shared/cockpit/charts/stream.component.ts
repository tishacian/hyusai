import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  booleanAttribute,
  inject,
} from '@angular/core';

import {
  attrFromTarget,
  hostPointerPoint,
  measureLabelWidth,
  nearestDayIndex,
  observeHostWidth,
  shouldRebuildLayout,
  svgPointerPoint,
} from './chart-interact';
import { CkChartTipComponent, type CkChartTipLine } from './chart-tip.component';
import {
  CK_DECLARED_HATCH_PERIOD,
  CK_DECLARED_HATCH_WIDTH,
  ckChartIsDeclared,
  ckChartToneVar,
  ckChartUid,
  type CkChartTick,
  type CkStreamTone,
} from './chart.types';
import { accumulateStackedSeries, cubicSmoothAreaPath, cubicSmoothPath, niceStep, spreadLabelRows } from './svg-path';

export interface CkStreamSeries {
  id?: string;
  label: string;
  detail?: string;
  values: number[];
  tone?: CkStreamTone;
}

export interface CkStreamGridLine {
  value: number;
  label: string;
}

export interface CkStreamPeak {
  index: number;
  label: string;
}

interface StreamArea {
  d: string;
  fill: string;
  /** Declared areas: `url(#hatch)` painted over the tint, so the estimate reads without colour. */
  hatch: string | null;
  /** Upper boundary alone: the declared layer's 1 px top edge. */
  top: string;
  /** Lower boundary alone, or null on the baseline: where the 1 px gap is cut. */
  base: string | null;
  id?: string;
}

interface StreamText {
  x: number;
  y: number;
  text: string;
  fill: string;
  size: number;
  anchor: 'start' | 'middle' | 'end';
  font: 'sans' | 'mono';
  weight?: number;
  opacity?: number;
  id?: string;
}

interface StreamBand {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface StreamLayout {
  areas: StreamArea[];
  labels: StreamText[];
  upperY: number[][];
  totals: number[];
  plotRight: number;
}

/** Vertical room one ribbon label (name + mono total) needs. */
const LABEL_ROW = 24;
const LABEL_MIN = 150;

@Component({
  selector: 'ck-chart-stream',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkChartTipComponent],
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + width + ' ' + height"
      [attr.width]="fluid ? '100%' : width"
      [attr.height]="fluid ? null : height"
      [style.width]="fluid ? '100%' : null"
      [style.height]="fluid ? 'auto' : null"
      style="display:block;overflow:visible"
      data-testid="ck-stream-plot"
      (pointerdown)="onPointer($event)"
      (pointermove)="onPointer($event)"
      (pointerleave)="onLeave()"
      (focusin)="onFocus($event)"
      (focusout)="onLeave()"
      (click)="onClick($event)"
      (keydown)="onKeydown($event)"
    >
      <defs>
        <linearGradient [attr.id]="inkId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-data-measured)" stop-opacity="0.92" />
          <stop offset="1" stop-color="var(--ck-data-measured)" stop-opacity="0.7" />
        </linearGradient>
        <!-- Declared tints stay at or below 0.18 so the hatch lines keep 3:1 on them. -->
        <linearGradient [attr.id]="declaredId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-data-declared)" stop-opacity="0.18" />
          <stop offset="1" stop-color="var(--ck-data-declared)" stop-opacity="0.1" />
        </linearGradient>
        <linearGradient [attr.id]="declaredSoftId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-data-declared)" stop-opacity="0.1" />
          <stop offset="1" stop-color="var(--ck-data-declared)" stop-opacity="0.05" />
        </linearGradient>
        <linearGradient [attr.id]="inkSoftId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--ck-data-measured)" stop-opacity="0.42" />
          <stop offset="1" stop-color="var(--ck-data-measured)" stop-opacity="0.18" />
        </linearGradient>
        <!-- One direction and one phase for every declared layer; the soft
             neighbour only carries a lighter ink. -->
        <pattern
          [attr.id]="hatchId"
          patternUnits="userSpaceOnUse"
          [attr.width]="hatchPeriod"
          [attr.height]="hatchPeriod"
          patternTransform="rotate(45)"
        >
          <rect [attr.width]="hatchWidth" [attr.height]="hatchPeriod" fill="var(--ck-data-declared)" fill-opacity="0.75" />
        </pattern>
        <pattern
          [attr.id]="hatchSoftId"
          patternUnits="userSpaceOnUse"
          [attr.width]="hatchPeriod"
          [attr.height]="hatchPeriod"
          patternTransform="rotate(45)"
        >
          <rect [attr.width]="hatchWidth" [attr.height]="hatchPeriod" fill="var(--ck-data-declared)" fill-opacity="0.5" />
        </pattern>
        <!-- Declared layer mask: keeps the layer's own shape (so its 2-unit top
             stroke shows as a 1 px inner edge) and cuts a 1 px gap along its
             lower boundary, where the page shows through between stacked layers. -->
        @for (area of areas; track $index) {
          @if (area.hatch) {
            <mask [attr.id]="layerMaskId + '-' + $index">
              <path [attr.d]="area.d" fill="#fff" />
              @if (area.base) {
                <path [attr.d]="area.base" fill="none" stroke="#000" stroke-width="2" />
              }
            </mask>
          }
        }
      </defs>
      @for (line of grid; track $index) {
        <line
          [attr.x1]="plotLeft"
          [attr.y1]="line.y"
          [attr.x2]="plotLeft + plotWidth"
          [attr.y2]="line.y"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.12"
          stroke-width="1"
          stroke-dasharray="2 4"
        />
        <text
          [attr.x]="plotLeft + plotWidth + 6"
          [attr.y]="line.y + 3"
          fill="var(--ck-fg-3)"
          font-family="var(--ck-font-mono)"
          font-size="8"
        >{{ line.label }}</text>
      }
      @for (band of weekendBands; track $index) {
        <rect
          [attr.x]="band.x"
          [attr.y]="band.y"
          [attr.width]="band.w"
          [attr.height]="band.h"
          fill="var(--ck-fg-1)"
          fill-opacity="0.04"
        />
      }
      @for (area of areas; track $index) {
        <g
          class="ck-layer"
          [class.is-lit]="isSeriesLit(area.id)"
          [class.is-dim]="isSeriesDimmed() && !isSeriesLit(area.id)"
          [style.--i]="$index"
          [attr.mask]="area.hatch ? 'url(#' + layerMaskId + '-' + $index + ')' : null"
        >
          <path class="ck-area" [attr.d]="area.d" [attr.fill]="area.fill" />
          @if (area.hatch) {
            <path
              class="ck-area ck-area-hatch"
              [attr.d]="area.d"
              [attr.fill]="area.hatch"
              pointer-events="none"
            />
            <path
              class="ck-area-edge"
              [attr.d]="area.top"
              fill="none"
              stroke="var(--ck-data-declared)"
              stroke-width="2"
              pointer-events="none"
            />
          }
        </g>
      }
      @for (i of dayHits; track i) {
        <rect
          class="ck-day-hit"
          role="button"
          [attr.data-day]="i"
          [attr.data-testid]="'ck-stream-day-' + i"
          [attr.x]="dayHitX(i)"
          [attr.y]="plotTop"
          [attr.width]="dayHitW()"
          [attr.height]="plotHeight"
          [attr.tabindex]="i === rovingDay() ? 0 : -1"
          [attr.aria-pressed]="i === lockedDay"
          [attr.aria-label]="dayAria(i)"
        />
      }
      @if (crosshairX != null) {
        <line
          class="ck-crosshair"
          [class.is-locked]="crosshairLocked"
          [attr.x1]="crosshairX"
          [attr.y1]="plotTop"
          [attr.x2]="crosshairX"
          [attr.y2]="plotTop + plotHeight"
          [attr.stroke]="crosshairLocked ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)'"
          stroke-width="1"
          [attr.stroke-dasharray]="crosshairLocked ? null : '2 3'"
          pointer-events="none"
        />
        @for (dot of crosshairDots; track $index) {
          <circle [attr.cx]="crosshairX" [attr.cy]="dot" r="3" fill="var(--ck-fg-1)" />
        }
      }
      @for (label of seriesLabels; track $index) {
        <text
          class="ck-stream-label"
          [class.is-lit]="isSeriesLit(label.id)"
          [class.is-dim]="isSeriesDimmed() && !isSeriesLit(label.id)"
          [attr.x]="label.x"
          [attr.y]="label.y"
          [attr.fill]="label.fill"
          [attr.fill-opacity]="label.opacity ?? 1"
          [attr.font-family]="label.font === 'mono' ? 'var(--ck-font-mono)' : 'var(--ck-font-sans)'"
          [attr.font-size]="label.size"
          [attr.font-weight]="label.weight ?? 400"
          [attr.text-anchor]="label.anchor"
          [attr.data-system]="label.id || null"
          [attr.tabindex]="label.id && label.font === 'sans' ? 0 : -1"
          [attr.aria-label]="label.text"
        >{{ label.text }}</text>
      }
      @if (peakMark; as mark) {
        <circle
          [attr.cx]="mark.x"
          [attr.cy]="mark.y"
          r="3.5"
          fill="var(--ck-bg-base)"
          stroke="var(--ck-fg-1)"
          stroke-width="1.5"
        />
        <text
          [attr.x]="mark.x + 9"
          [attr.y]="mark.y + 3.5"
          fill="var(--ck-fg-1)"
          font-family="var(--ck-font-mono)"
          font-size="9"
          [attr.text-anchor]="mark.anchor"
        >{{ mark.label }}</text>
      }
      @for (tick of axisTicks; track $index) {
        <text
          [attr.x]="tick.x"
          [attr.y]="tick.y"
          [attr.fill]="tick.fill"
          [attr.fill-opacity]="tick.opacity ?? 1"
          [attr.font-family]="'var(--ck-font-mono)'"
          [attr.font-size]="tick.size"
          [attr.text-anchor]="tick.anchor"
        >{{ tick.text }}</text>
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
    :host { display: block; position: relative; width: 100%; }
    .ck-layer, .ck-stream-label { transition: opacity 160ms var(--ck-ease-out, ease-out); }
    svg:has(.ck-day-hit:focus-visible) .ck-layer, svg:has(.ck-day-hit:focus-visible) .ck-stream-label { transition: none; }
    .is-dim { opacity: 0.35; }
    .is-lit { opacity: 1; }
    .ck-day-hit { fill: transparent; cursor: pointer; }
    .ck-day-hit:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: -2px; }
    .ck-stream-label { cursor: pointer; }
    /* The entrance grows each layer as one group, so its edge and mask follow its fill. */
    :host-context(.hv2-enter) .ck-layer {
      transform: scaleY(0);
      transform-box: fill-box;
      transform-origin: 50% 100%;
      animation: ckAreaIn 600ms var(--ck-ease-out, ease-out) forwards;
      animation-delay: calc(var(--i, 0) * 50ms);
    }
    @keyframes ckAreaIn { to { transform: none; } }
    @media (prefers-reduced-motion: reduce) {
      .ck-layer, .ck-stream-label { transition: none; }
      :host-context(.hv2-enter) .ck-layer { animation: none; transform: none; }
    }
  `],
})
export class CkChartStreamComponent implements OnChanges, AfterViewInit, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly cdr = inject(ChangeDetectorRef);

  @Input() series: CkStreamSeries[] = [];
  @Input() weekendStarts: number[] = [];
  @Input() dayLabels: string[] = [];
  /** Explicit gridlines; when empty, round steps are derived from the maximum. */
  @Input() gridLines: CkStreamGridLine[] = [];
  /** Formats a derived gridline value (e.g. `40 h`). */
  @Input() gridLabel: (value: number) => string = (value) => String(value);
  @Input() ticks: CkChartTick[] = [];
  @Input() peak: CkStreamPeak | null = null;
  @Input() width = 612;
  @Input() height = 196;
  @Input() maxValue: number | null = null;
  /** Scale the drawing to the host width (keeps the composition, grows the label column). */
  @Input({ transform: booleanAttribute }) fluid = false;
  @Input() hoverDay: number | null = null;
  @Input() hoverSystem: string | null = null;
  /** The day the page locked: solid crosshair, keyboard entry point, `aria-pressed`. */
  @Input() lockedDay: number | null = null;
  /**
   * Dock the day tooltip on the crosshair when the day comes from the page
   * (another chart, a lock) rather than from this chart's own pointer.
   */
  @Input({ transform: booleanAttribute }) followTip = false;
  /** Formats the accessible name of a day (defaults to its label and total). */
  @Input() dayAriaLabel: ((index: number) => string) | null = null;
  @Output() readonly dayHover = new EventEmitter<number | null>();
  /** Click, Enter or Space on a day: the page toggles its lock on that day. */
  @Output() readonly dayLock = new EventEmitter<number>();
  @Output() readonly systemHover = new EventEmitter<string | null>();

  readonly inkId = ckChartUid('ck-stream-ink');
  readonly inkSoftId = ckChartUid('ck-stream-ink-soft');
  readonly declaredId = ckChartUid('ck-stream-teal');
  readonly declaredSoftId = ckChartUid('ck-stream-teal-soft');
  readonly hatchId = ckChartUid('ck-stream-hatch');
  readonly hatchSoftId = ckChartUid('ck-stream-hatch-soft');
  readonly layerMaskId = ckChartUid('ck-stream-layer');
  readonly hatchPeriod = CK_DECLARED_HATCH_PERIOD;
  readonly hatchWidth = CK_DECLARED_HATCH_WIDTH;

  readonly plotTop = 12;
  readonly plotBottom = 26;
  readonly plotLeft = 6;

  tipOpen = false;
  tipTitle = '';
  tipLines: CkChartTipLine[] = [];
  tipX = 0;
  tipY = 0;
  private localDay: number | null = null;
  private localSystem: string | null = null;
  /** Roving tab stop among the day columns. */
  private focusDay: number | null = null;
  private built: StreamLayout | null = null;
  private stopWidth: (() => void) | null = null;

  get plotRight(): number {
    return this.layout().plotRight;
  }

  get plotWidth(): number {
    return this.width - this.plotLeft - this.plotRight;
  }

  get plotHeight(): number {
    return this.height - this.plotTop - this.plotBottom;
  }

  get dayHits(): number[] {
    const n = this.pointCount();
    return n ? Array.from({ length: n }, (_, i) => i) : [];
  }

  get grid(): Array<{ y: number; label: string }> {
    const max = this.resolvedMax();
    return this.gridValues().map((line) => ({ y: this.yOf(line.value, max), label: line.label }));
  }

  get weekendBands(): StreamBand[] {
    const n = this.pointCount();
    if (n < 2) return [];
    const dx = this.plotWidth / (n - 1);
    return this.weekendStarts.map((start) => {
      const x = this.xOf(start) - dx / 2;
      return { x, y: this.plotTop, w: 2 * dx, h: this.plotHeight };
    });
  }

  get areas(): StreamArea[] {
    return this.layout().areas;
  }

  get seriesLabels(): StreamText[] {
    return this.layout().labels;
  }

  get peakMark(): { x: number; y: number; label: string; anchor: 'start' | 'end' } | null {
    const peak = this.peak;
    if (!peak) return null;
    const totals = this.layout().totals;
    if (peak.index < 0 || peak.index >= totals.length) return null;
    const x = this.xOf(peak.index);
    return {
      x,
      y: this.yOf(totals[peak.index]!, this.resolvedMax()),
      label: peak.label,
      anchor: x > this.plotLeft + this.plotWidth * 0.78 ? 'end' : 'start',
    };
  }

  get axisTicks(): StreamText[] {
    const n = this.pointCount();
    const last = Math.max(0, n - 1);
    return this.ticks.map((tick) => ({
      x: this.xOf(tick.index),
      y: this.height - 8,
      text: tick.label,
      fill: 'var(--ck-fg-3)',
      size: 8.5,
      anchor: tick.anchor ?? (tick.index === 0 ? 'start' : tick.index === last ? 'end' : 'middle'),
      font: 'mono',
    }));
  }

  get crosshairX(): number | null {
    const day = this.activeDay();
    return day == null ? null : this.xOf(day);
  }

  get crosshairLocked(): boolean {
    const day = this.activeDay();
    return day != null && day === this.lockedDay;
  }

  get crosshairDots(): number[] {
    const day = this.activeDay();
    if (day == null) return [];
    return this.layout().upperY.map((row) => row[day] ?? this.plotTop + this.plotHeight);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (shouldRebuildLayout(Object.keys(changes)) || !this.built) {
      this.built = this.build();
    }
    if (this.focusDay != null && this.focusDay >= this.pointCount()) this.focusDay = null;
    if (this.followTip && (changes['hoverDay'] || changes['series'])) this.syncDockedTip();
  }

  /** The one day column in the tab order: the last reached by arrows, else the lock, else the peak. */
  rovingDay(): number {
    const n = this.pointCount();
    const pick = this.focusDay ?? this.lockedDay ?? this.peak?.index ?? null;
    return pick != null && pick >= 0 && pick < n ? pick : Math.max(0, n - 1);
  }

  dayAria(index: number): string {
    if (this.dayAriaLabel) return this.dayAriaLabel(index);
    const total = this.layout().totals[index] ?? 0;
    return [this.dayLabels[index], this.gridLabel(total)].filter(Boolean).join(' · ');
  }

  onClick(event: MouseEvent): void {
    if (attrFromTarget(event.target, 'data-system')) return;
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
    const n = this.pointCount();
    let next: number | null = null;
    if (event.key === 'ArrowRight') next = Math.min(n - 1, index + 1);
    else if (event.key === 'ArrowLeft') next = Math.max(0, index - 1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = n - 1;
    if (next == null || next === index) return;
    event.preventDefault();
    const svg = event.currentTarget;
    if (!(svg instanceof Element)) return;
    const target = svg.querySelector(`[data-day="${next}"]`);
    if (!(target instanceof SVGElement)) return;
    // The global ring skips [tabindex="-1"]; the stop moves before focus does.
    svg.querySelectorAll('.ck-day-hit[tabindex="0"]').forEach((node) => node.setAttribute('tabindex', '-1'));
    target.setAttribute('tabindex', '0');
    this.focusDay = next;
    target.focus();
  }

  ngAfterViewInit(): void {
    if (!this.fluid) return;
    this.stopWidth = observeHostWidth(this.host.nativeElement, (width) => {
      const next = Math.max(360, Math.round(width));
      if (next === this.width) return;
      this.width = next;
      this.built = this.build();
      this.cdr.markForCheck();
    });
  }

  ngOnDestroy(): void {
    this.stopWidth?.();
  }

  dayHitX(index: number): number {
    return this.xOf(index) - this.dayHitW() / 2;
  }

  dayHitW(): number {
    const n = this.pointCount();
    return n <= 1 ? this.plotWidth : this.plotWidth / (n - 1);
  }

  isSeriesLit(id: string | undefined): boolean {
    const system = this.activeSystem();
    return Boolean(system && id === system);
  }

  isSeriesDimmed(): boolean {
    return this.activeSystem() != null;
  }

  onPointer(event: PointerEvent): void {
    if (event.pointerType === 'touch' && event.type === 'pointermove') return;
    const system = attrFromTarget(event.target, 'data-system');
    if (system) {
      if (event.pointerType === 'touch' && event.type === 'pointerdown') this.toggleSystem(system);
      else this.setSystem(system);
      this.setDay(null);
      this.tipOpen = false;
      return;
    }
    const svg = event.currentTarget as SVGSVGElement;
    const pt = svgPointerPoint(svg, event.clientX, event.clientY);
    const index = nearestDayIndex(pt.x, this.plotLeft, this.plotWidth, this.pointCount());
    if (event.pointerType === 'touch' && event.type === 'pointerdown') this.toggleDay(index);
    else this.setDay(index);
    this.setSystem(null);
    this.showDayTip(index, event);
  }

  onFocus(event: FocusEvent): void {
    const system = attrFromTarget(event.target, 'data-system');
    if (system) {
      this.setSystem(system);
      return;
    }
    const dayAttr = attrFromTarget(event.target, 'data-day');
    if (dayAttr == null) return;
    const index = Number(dayAttr);
    this.setDay(index);
    this.showDockedTip(index);
  }

  onLeave(): void {
    this.setDay(null);
    this.setSystem(null);
    this.tipOpen = false;
    if (this.followTip) this.syncDockedTip();
  }

  private syncDockedTip(): void {
    if (this.localDay != null) return;
    const day = this.hoverDay;
    if (day == null || day < 0 || day >= this.pointCount()) {
      this.tipOpen = false;
      return;
    }
    this.showDockedTip(day);
  }

  /** Tip beside the crosshair, for a day that did not come from this chart's pointer. */
  private showDockedTip(index: number): void {
    // Fluid or fixed, one viewBox unit is one CSS pixel of the host.
    this.tipX = this.xOf(index);
    this.tipY = this.plotTop + 8;
    this.fillTip(index);
  }

  private activeDay(): number | null {
    return this.localDay ?? this.hoverDay;
  }

  private activeSystem(): string | null {
    return this.localSystem ?? this.hoverSystem;
  }

  private toggleDay(index: number): void {
    this.setDay(this.localDay === index ? null : index);
    if (this.localDay == null) this.tipOpen = false;
  }

  private toggleSystem(id: string): void {
    this.setSystem(this.localSystem === id ? null : id);
  }

  private setDay(index: number | null): void {
    if (this.localDay === index) return;
    this.localDay = index;
    this.dayHover.emit(index);
  }

  private setSystem(id: string | null): void {
    if (this.localSystem === id) return;
    this.localSystem = id;
    this.systemHover.emit(id);
  }

  private showDayTip(index: number, event: PointerEvent): void {
    const pt = hostPointerPoint(this.host.nativeElement, event.clientX, event.clientY);
    this.tipX = pt.x;
    this.tipY = pt.y;
    this.fillTip(index);
  }

  private fillTip(index: number): void {
    this.tipTitle = this.dayLabels[index] || '';
    const lines: CkChartTipLine[] = this.series.map((row) => ({
      label: row.label,
      value: `${this.gridLabel(row.values[index] ?? 0)} ${ckChartIsDeclared(row.tone) ? '◐' : '●'}`,
    }));
    const total = this.layout().totals[index] ?? 0;
    lines.push({ label: '', value: this.gridLabel(total) });
    this.tipLines = lines;
    this.tipOpen = true;
  }

  private layout(): StreamLayout {
    return this.built ?? (this.built = this.build());
  }

  private build(): StreamLayout {
    const series = this.series;
    const n = this.pointCount();
    const plotRight = this.labelColumn();
    const plotWidth = this.width - this.plotLeft - plotRight;
    const areas: StreamArea[] = [];
    const labels: StreamText[] = [];
    const upperY: number[][] = [];
    if (n < 2 || !series.length) {
      return { areas, labels, upperY, totals: [], plotRight };
    }
    const max = this.resolvedMax();
    const stacked = accumulateStackedSeries(series.map((row) => row.values));
    const desired: number[] = [];
    const xOf = (index: number): number => {
      if (n <= 1) return this.plotLeft;
      return this.plotLeft + index * (plotWidth / (n - 1));
    };
    stacked.forEach((band, index) => {
      const row = series[index]!;
      const tone = row.tone ?? 'ink';
      const upper = band.upper.map((value, i) => ({ x: xOf(i), y: this.yOf(value, max) }));
      const lower = band.lower.map((value, i) => ({ x: xOf(i), y: this.yOf(value, max) }));
      const onBaseline = band.lower.every((value) => value === 0);
      areas.push({
        d: onBaseline ? cubicSmoothAreaPath(upper, null, this.yOf(0, max)) : cubicSmoothAreaPath(upper, lower),
        fill: this.fillFor(tone),
        hatch: this.hatchFor(tone),
        top: cubicSmoothPath(upper),
        base: onBaseline ? null : cubicSmoothPath(lower),
        id: row.id,
      });
      upperY.push(upper.map((point) => point.y));
      desired.push((upper[n - 1]!.y + lower[n - 1]!.y) / 2);
    });
    const rows = spreadLabelRows(desired, LABEL_ROW, this.plotTop + 6, this.plotTop + this.plotHeight - 12);
    const labelX = this.plotLeft + plotWidth + 16 + this.gridGutter();
    series.forEach((row, index) => {
      const tone = row.tone ?? 'ink';
      const midY = rows[index]!;
      labels.push({
        x: labelX,
        y: midY + 3,
        text: row.label,
        fill: ckChartToneVar(tone),
        size: 10.5,
        anchor: 'start',
        font: 'sans',
        weight: 500,
        id: row.id,
      });
      if (row.detail) {
        labels.push({
          x: labelX,
          y: midY + 14,
          text: row.detail,
          fill: ckChartToneVar(tone),
          size: 9,
          anchor: 'start',
          font: 'mono',
          opacity: 0.75,
          id: row.id,
        });
      }
    });
    return { areas, labels, upperY, totals: this.totals(), plotRight };
  }

  private labelColumn(): number {
    const names = this.series.flatMap((row) => [row.label, row.detail ?? '']);
    const longest = names.reduce((max, text) => Math.max(max, measureLabelWidth(text)), 0);
    return Math.max(LABEL_MIN, Math.ceil(longest) + 28) + this.gridGutter();
  }

  private gridValues(): CkStreamGridLine[] {
    if (this.gridLines.length) return this.gridLines;
    if (!this.series.length) return [];
    const max = this.resolvedMax();
    const step = niceStep(max);
    const lines: CkStreamGridLine[] = [];
    for (let value = step; value < max * 0.98 && lines.length < 6; value += step) {
      lines.push({ value, label: this.gridLabel(value) });
    }
    return lines;
  }

  /** Room for the gridline values right of the plot, so ribbon names never sit on them. */
  private gridGutter(): number {
    const widest = this.gridValues().reduce(
      (max, line) => Math.max(max, measureLabelWidth(line.label, '400 8px ui-monospace, monospace')),
      0,
    );
    return widest > 0 ? Math.ceil(widest) + 4 : 0;
  }

  private fillFor(tone: CkStreamTone): string {
    if (tone === 'declared') return `url(#${this.declaredId})`;
    if (tone === 'declared-soft') return `url(#${this.declaredSoftId})`;
    if (tone === 'ink-soft') return `url(#${this.inkSoftId})`;
    return `url(#${this.inkId})`;
  }

  private hatchFor(tone: CkStreamTone): string | null {
    if (tone === 'declared') return `url(#${this.hatchId})`;
    if (tone === 'declared-soft') return `url(#${this.hatchSoftId})`;
    return null;
  }

  private pointCount(): number {
    return this.series.reduce((len, row) => Math.max(len, row.values.length), 0);
  }

  private totals(): number[] {
    const n = this.pointCount();
    const totals = Array.from({ length: n }, () => 0);
    for (const row of this.series) {
      row.values.forEach((value, i) => {
        totals[i] += Number.isFinite(value) ? value : 0;
      });
    }
    return totals;
  }

  private resolvedMax(): number {
    if (this.maxValue != null && this.maxValue > 0) return this.maxValue;
    const peak = Math.max(0, ...this.totals());
    return peak || 1;
  }

  private xOf(index: number): number {
    const n = this.pointCount();
    if (n <= 1) return this.plotLeft;
    return this.plotLeft + index * (this.plotWidth / (n - 1));
  }

  private yOf(value: number, max: number): number {
    return this.plotTop + this.plotHeight - (this.plotHeight * Math.max(0, value)) / max;
  }
}
