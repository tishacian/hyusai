import { ChangeDetectionStrategy, Component, Input, computed } from '@angular/core';
import { NgClass } from '@angular/common';
import { IconComponent } from './icon.component';

export type StatTrend = 'up' | 'down' | 'flat' | null;

@Component({
  selector: 'app-stat-tile',
  standalone: true,
  imports: [NgClass, IconComponent],
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
      </div>
      @if (delta || hint) {
        <div class="flex items-center gap-2 text-xs">
          @if (delta) {
            <span
              class="inline-flex items-center gap-0.5 font-medium"
              [ngClass]="{
                'text-emerald-500': trend === 'up',
                'text-red-500': trend === 'down',
                'text-gray-500': !trend || trend === 'flat'
              }"
            >
              @if (trend === 'up') {
                <app-icon name="trending-up" [size]="12" />
              } @else if (trend === 'down') {
                <app-icon name="trending-down" [size]="12" />
              }
              {{ delta }}
            </span>
          }
          @if (hint) {
            <span class="text-gray-500 dark:text-gray-400">{{ hint }}</span>
          }
        </div>
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
  @Input() hint?: string;
  @Input() icon?: string;
  @Input() interactive = false;
}
