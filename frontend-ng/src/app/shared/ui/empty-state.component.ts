import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { IconComponent } from './icon.component';

@Component({
  selector: 'app-empty-state',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex flex-col items-center justify-center text-center py-12 px-6">
      <div
        class="w-16 h-16 rounded-2xl flex items-center justify-center bg-gradient-to-br from-brand-500/10 via-violet-500/10 to-indigo-500/10 ring-1 ring-brand-500/20 text-brand-400 shadow-glow-sm mb-4"
      >
        <app-icon [name]="icon" [size]="28" />
      </div>
      <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-1">{{ title }}</h3>
      @if (description) {
        <p class="text-sm text-gray-500 dark:text-gray-400 max-w-sm mb-4">{{ description }}</p>
      }
      <ng-content />
    </div>
  `,
})
export class EmptyStateComponent {
  @Input() icon: string = 'sparkles';
  @Input({ required: true }) title!: string;
  @Input() description?: string;
}
