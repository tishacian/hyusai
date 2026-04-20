import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { IconComponent } from './icon.component';

export type EmptyStateSize = 'sm' | 'md' | 'lg';

/**
 * Standardized empty state. Three density variants:
 * - `sm` fits inside charts / cards with fixed heights
 * - `md` (default) is for list / table containers
 * - `lg` for first-run zero states where we want to fill the page
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  imports: [NgClass, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="flex flex-col items-center justify-center text-center"
      [ngClass]="{
        'py-6 px-4': size === 'sm',
        'py-12 px-6': size === 'md',
        'py-16 px-8': size === 'lg'
      }"
    >
      <div
        class="rounded-2xl flex items-center justify-center bg-gradient-to-br from-brand-500/10 via-violet-500/10 to-indigo-500/10 ring-1 ring-brand-500/20 text-brand-400 shadow-glow-sm mb-3"
        [ngClass]="{
          'w-10 h-10': size === 'sm',
          'w-16 h-16': size === 'md',
          'w-20 h-20': size === 'lg'
        }"
      >
        <app-icon [name]="icon" [size]="iconSize()" />
      </div>
      <h3
        class="font-semibold text-gray-900 dark:text-white mb-1"
        [ngClass]="{
          'text-sm': size === 'sm',
          'text-base': size === 'md',
          'text-lg': size === 'lg'
        }"
      >
        {{ title }}
      </h3>
      @if (description) {
        <p
          class="text-gray-500 dark:text-gray-400 max-w-sm mb-3"
          [ngClass]="{
            'text-[11px] leading-relaxed': size === 'sm',
            'text-sm': size === 'md' || size === 'lg'
          }"
        >
          {{ description }}
        </p>
      }
      <ng-content />
    </div>
  `,
})
export class EmptyStateComponent {
  @Input() icon: string = 'sparkles';
  @Input({ required: true }) title!: string;
  @Input() description?: string;
  @Input() size: EmptyStateSize = 'md';

  iconSize() {
    return this.size === 'sm' ? 18 : this.size === 'lg' ? 32 : 28;
  }
}
