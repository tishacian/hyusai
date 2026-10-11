import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { IconComponent } from './icon.component';

/**
 * Page-level section header for generic Agentium surfaces.
 *
 * Keep this aligned with the Cockpit Workbench chrome used by Systems and
 * Capabilities: small cyan eyebrow, white title, restrained icon treatment.
 * Workspace-specific showcase surfaces such as Sentinel-CI own their chrome.
 */
@Component({
  selector: 'app-section-header',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="ck-section-header pb-5 mb-6 flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0 flex-1">
        @if (breadcrumb) {
          <div class="ck-mono ck-accent text-[10px] uppercase tracking-[0.18em] mb-1.5 font-semibold">
            {{ breadcrumb }}
          </div>
        }
        <h1 class="text-2xl md:text-[28px] font-medium tracking-tight leading-tight text-white flex items-center gap-3">
          @if (icon) {
            <span class="ck-tone-info inline-flex items-center justify-center w-8 h-8 rounded-md">
              <app-icon [name]="icon" [size]="20" />
            </span>
          }
          {{ title }}
          @if (pill) {
            <span class="ck-pill ck-tone-warn rounded-full">
              {{ pill }}
            </span>
          }
        </h1>
        @if (subtitle) {
          <p class="text-sm mt-1.5 max-w-2xl" [style.color]="'var(--ck-fg-4)'">{{ subtitle }}</p>
        }
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <ng-content />
      </div>
    </header>
  `,
  styles: [`
    .ck-section-header {
      border-bottom: 1px solid var(--ck-stroke-2);
    }
  `],
})
export class SectionHeaderComponent {
  @Input({ required: true }) title!: string;
  @Input() subtitle?: string;
  @Input() breadcrumb?: string;
  @Input() icon?: string;
  @Input() pill?: string;
}
