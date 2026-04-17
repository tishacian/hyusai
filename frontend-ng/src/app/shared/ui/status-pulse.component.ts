import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { NgClass } from '@angular/common';

export type PulseTone = 'accent' | 'success' | 'warning' | 'danger';

@Component({
  selector: 'app-status-pulse',
  standalone: true,
  imports: [NgClass],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="inline-flex items-center gap-1.5">
      <span
        class="pulse-dot"
        [ngClass]="{
          'success': tone === 'success',
          'warning': tone === 'warning',
          'danger': tone === 'danger'
        }"
      ></span>
      @if (label) {
        <span class="text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">
          {{ label }}
        </span>
      }
    </span>
  `,
})
export class StatusPulseComponent {
  @Input() tone: PulseTone = 'accent';
  @Input() label?: string;
}
