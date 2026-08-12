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
        class="ck-tone-info rounded-2xl flex items-center justify-center mb-3"
        [ngClass]="{
          'w-10 h-10': size === 'sm',
          'w-16 h-16': size === 'md',
          'w-20 h-20': size === 'lg'
        }"
      >
        <app-icon [name]="icon" [size]="iconSize()" />
      </div>
      <h3
        class="font-semibold mb-1"
        [style.color]="'var(--ck-fg-1)'"
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
          class="max-w-sm mb-3"
          [style.color]="'var(--ck-fg-4)'"
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
