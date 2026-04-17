import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { IconComponent } from './icon.component';

/**
 * Page-level section header. Applies the gradient title treatment and an
 * animated underline so every page feels consistent with the legacy chrome.
 */
@Component({
  selector: 'app-section-header',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="header-underline pb-5 mb-6 flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0 flex-1">
        @if (breadcrumb) {
          <div class="text-xs text-gray-500 dark:text-gray-400 mb-1 flex items-center gap-1 font-medium">
            <span>Platform</span>
            <app-icon name="chevron-right" [size]="12" class="opacity-60" />
            <span>{{ breadcrumb }}</span>
          </div>
        }
        <h1 class="gradient-title text-2xl md:text-[28px] font-semibold tracking-tight leading-tight flex items-center gap-3">
          @if (icon) {
            <span class="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-brand-500/20 to-violet-500/20 text-brand-400 ring-1 ring-brand-500/30 shadow-glow-sm">
              <app-icon [name]="icon" [size]="20" />
            </span>
          }
          {{ title }}
          @if (pill) {
            <span class="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
              {{ pill }}
            </span>
          }
        </h1>
        @if (subtitle) {
          <p class="text-sm text-gray-500 dark:text-gray-400 mt-1.5 max-w-2xl">{{ subtitle }}</p>
        }
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <ng-content />
      </div>
    </header>
  `,
})
export class SectionHeaderComponent {
  @Input({ required: true }) title!: string;
  @Input() subtitle?: string;
  @Input() breadcrumb?: string;
  @Input() icon?: string;
  @Input() pill?: string;
}
