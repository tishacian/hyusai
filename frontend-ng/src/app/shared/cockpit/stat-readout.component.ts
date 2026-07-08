import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SparklineComponent } from '@app/shared/ui/sparkline.component';

export type CkReadoutTone = 'neutral' | 'pos' | 'neg' | 'cool' | 'violet' | 'warn';
export type CkReadoutAlign = 'start' | 'end';
export type CkReadoutVariant = 'readout' | 'tile';
export type CkReadoutTrend = 'up' | 'down' | 'flat' | null;
export type CkReadoutSentiment = 'positive' | 'negative' | 'neutral';

/**
 * Canonical cockpit readout primitive. Two variants share the same public API:
 *
 *  - `readout` (default): mono ALL-CAPS label above a tabular-numeric value,
 *    optional delta — used in title bars, Hypervisor surfaces, Run Outcome card.
 *
 *  - `tile`: full-bleed stat card with icon chip, sparkline, trend arrow and
 *    optional hint — used on dashboards (observability, resources, tasks…).
 *
 * Replaces the previous `app-stat-tile` component; both patterns are now a
 * single cockpit grammar.
 */
@Component({
  selector: 'ck-stat-readout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgClass, IconComponent, SparklineComponent],
  template: `
    @if (variant === 'tile') {
      <div
        class="ck-surface rounded-md p-4 flex flex-col gap-2 relative overflow-hidden group"
        [class.cursor-pointer]="interactive"
      >
        <div class="flex items-center justify-between">
          <span class="text-[10px] uppercase tracking-[0.14em] font-semibold text-gray-500 dark:text-gray-400">
            {{ label }}
          </span>
          @if (icon) {
            <div
              class="w-7 h-7 rounded-md flex items-center justify-center text-cyan-500 bg-cyan-500/10 group-hover:bg-cyan-500/20 transition-colors"
            >
              <app-icon [name]="icon" [size]="14" />
            </div>
          }
        </div>
        <div class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold text-gray-900 dark:text-white tabular-nums">{{ value }}</span>
          @if (unit) {
            <span class="text-xs text-gray-500 dark:text-gray-400">{{ unit }}</span>
          }
          @if (trend) {
            <span
              class="inline-flex items-center gap-0.5 text-[10px] font-semibold ml-auto tabular-nums"
              [ngClass]="{
                'text-emerald-500': trend === 'up' && trendSentiment !== 'negative',
                'text-red-500': trend === 'up' && trendSentiment === 'negative',
                'text-emerald-500 flip': trend === 'down' && trendSentiment === 'negative',
                'text-red-500 flip2': trend === 'down' && trendSentiment !== 'negative',
                'text-gray-500': trend === 'flat'
              }"
            >
              @if (trend === 'up') {
                <app-icon name="trending-up" [size]="10" />
              } @else if (trend === 'down') {
                <app-icon name="trending-down" [size]="10" />
              } @else {
                <app-icon name="minus" [size]="10" />
              }
              @if (delta !== null && delta !== undefined && delta !== '') {
                {{ delta }}
              }
            </span>
          }
        </div>
        @if (sparkline && sparkline.length >= 2) {
          <div
            class="-mx-1 -mb-1"
            [class.text-emerald-400]="sparklineTone === 'positive'"
            [class.text-red-400]="sparklineTone === 'negative'"
            [class.text-cyan-400]="!sparklineTone || sparklineTone === 'neutral'"
          >
            <app-sparkline [data]="sparkline" [width]="140" [height]="28" />
          </div>
        }
        @if (hint && (!sparkline || sparkline.length < 2)) {
          <div class="text-[11px] text-gray-500 dark:text-gray-400">{{ hint }}</div>
        } @else if (hint) {
          <div class="text-[10px] text-gray-500 dark:text-gray-400">{{ hint }}</div>
        }
        <div class="absolute inset-x-0 bottom-0 h-0.5 bg-cyan-500/40 opacity-0 group-hover:opacity-100 transition-opacity"></div>
      </div>
    } @else {
      <div
        [style.display]="'flex'"
        [style.flexDirection]="'column'"
        [style.gap.px]="2"
        [style.alignItems]="align === 'end' ? 'flex-end' : 'flex-start'"
      >
        <span
          class="ck-mono"
          [style.fontSize.px]="9"
          [style.letterSpacing]="'0.14em'"
          [style.textTransform]="'uppercase'"
          [style.color]="'var(--ck-fg-4)'"
        >{{ label }}</span>
        <span
          class="ck-mono ck-tnum"
          [style.fontSize.px]="size"
          [style.fontWeight]="500"
          [style.letterSpacing]="'-0.01em'"
          [style.color]="toneColor"
          [style.lineHeight]="'1'"
        >{{ value }}</span>
        @if (delta !== null && delta !== undefined && delta !== '') {
          <span
            class="ck-mono ck-tnum"
            [style.fontSize.px]="9"
            [style.color]="deltaColor"
          >{{ delta }}</span>
        }
      </div>
    }
  `,
})
export class StatReadoutComponent {
  /** Label text (rendered ALL-CAPS in both variants). */
  @Input() label = '';
  /** Primary value. */
  @Input() value: string | number = '—';
  /** Optional delta string (e.g. "+12"). */
  @Input() delta: string | number | null = null;
  /** Semantic tone for the primary value (readout variant). */
  @Input() tone: CkReadoutTone = 'neutral';
  /** Optional explicit tone for the delta (readout variant). */
  @Input() deltaTone: CkReadoutTone | null = null;
  /** Font-size of the value in the readout variant. */
  @Input() size = 14;
  /** Alignment for the readout variant (right-aligned readouts use 'end'). */
  @Input() align: CkReadoutAlign = 'start';

  /** Visual variant. `readout` (default) keeps the lean cockpit stack; `tile` renders a full stat card. */
  @Input() variant: CkReadoutVariant = 'readout';
  /** Optional unit suffix displayed next to the value (tile variant). */
  @Input() unit?: string;
  /** Optional hint displayed beneath the value / sparkline (tile variant). */
  @Input() hint?: string;
  /** Optional lucide icon name displayed in the corner chip (tile variant). */
  @Input() icon?: string;
  /** Optional trend direction (tile variant). */
  @Input() trend: CkReadoutTrend = null;
  /** Whether an up trend should be treated as good (positive) or bad (negative). */
  @Input() trendSentiment: CkReadoutSentiment = 'positive';
  /** Optional sparkline data series (tile variant). */
  @Input() sparkline: number[] | null = null;
  /** Tint used for the sparkline fill (tile variant). */
  @Input() sparklineTone: CkReadoutSentiment = 'neutral';
  /** Apply the interactive cursor affordance (tile variant). */
  @Input() interactive = false;

  get toneColor(): string {
    return resolveTone(this.tone, 'var(--ck-fg-1)');
  }

  get deltaColor(): string {
    return resolveTone(this.deltaTone ?? this.tone, 'var(--ck-fg-3)');
  }
}

function resolveTone(tone: CkReadoutTone, fallback: string): string {
  switch (tone) {
    case 'pos':    return 'var(--ck-signal-pos)';
    case 'neg':    return 'var(--ck-signal-neg)';
    case 'cool':   return 'var(--ck-signal-cool)';
    case 'violet': return 'var(--ck-signal-violet)';
    case 'warn':   return 'var(--ck-signal-warn)';
    case 'neutral':
    default:       return fallback;
  }
}
