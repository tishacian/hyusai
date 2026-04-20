import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { NgClass } from '@angular/common';
import { IconComponent } from './icon.component';
import { SparklineComponent } from './sparkline.component';

export type StatTrend = 'up' | 'down' | 'flat' | null;

@Component({
  selector: 'app-stat-tile',
  standalone: true,
  imports: [NgClass, IconComponent, SparklineComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="t-card rounded-md p-4 flex flex-col gap-2 relative overflow-hidden group"
      [class.cursor-pointer]="interactive"
    >
      <div class="flex items-center justify-between">
        <span class="text-[10px] uppercase tracking-[0.14em] font-semibold text-gray-500 dark:text-gray-400">
          {{ label }}
        </span>
        @if (icon) {
          <div
            class="w-7 h-7 rounded-md flex items-center justify-center text-brand-500 bg-brand-500/10 group-hover:bg-brand-500/20 transition-colors"
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
            @if (delta) {
              {{ delta }}
            }
          </span>
        }
      </div>
      @if (sparkline && sparkline.length >= 2) {
        <div class="-mx-1 -mb-1" [class.text-emerald-400]="sparklineTone === 'positive'"
          [class.text-red-400]="sparklineTone === 'negative'"
          [class.text-brand-400]="!sparklineTone || sparklineTone === 'neutral'"
        >
          <app-sparkline [data]="sparkline" [width]="140" [height]="28" />
        </div>
      }
      @if (hint && (!sparkline || sparkline.length < 2)) {
        <div class="text-[11px] text-gray-500 dark:text-gray-400">{{ hint }}</div>
      } @else if (hint) {
        <div class="text-[10px] text-gray-500 dark:text-gray-400">{{ hint }}</div>
      }
      <div class="absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-transparent via-brand-500/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
    </div>
  `,
})
export class StatTileComponent {
  @Input({ required: true }) label!: string;
  @Input({ required: true }) value!: string | number;
  @Input() unit?: string;
  @Input() delta?: string;
  @Input() trend: StatTrend = null;
  /** 'negative' means "up is bad" (e.g. errors, latency), 'positive' means "up is good" (e.g. quality) */
  @Input() trendSentiment: 'positive' | 'negative' | 'neutral' = 'positive';
  @Input() hint?: string;
  @Input() icon?: string;
  @Input() interactive = false;
  @Input() sparkline: number[] | null = null;
  @Input() sparklineTone: 'positive' | 'negative' | 'neutral' = 'neutral';
}
