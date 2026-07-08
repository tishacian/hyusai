import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { IconComponent } from './icon.component';

/**
 * Right-side slide-over panel with ck-surface backdrop. Used for contextual config
 * (feeds/targets in News Lab, block config in system design, etc.).
 */
@Component({
  selector: 'app-drawer',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div class="fixed inset-0 z-50 flex justify-end animate-fade-in">
        <div
          class="absolute inset-0 bg-black/40 backdrop-blur-sm"
          (click)="dismiss($event)"
        ></div>
        <aside
          class="relative h-full ck-surface border-l border-white/10 shadow-elevated animate-slide-up overflow-y-auto"
          [style.width.px]="width"
          (click)="$event.stopPropagation()"
        >
          <header
            class="sticky top-0 z-10 px-6 py-4 flex items-center justify-between border-b border-white/10 bg-gray-900/60 backdrop-blur-xl"
          >
            <div class="flex items-center gap-3 min-w-0">
              @if (icon) {
                <div class="w-8 h-8 rounded-md flex items-center justify-center bg-cyan-500/15 text-cyan-400">
                  <app-icon [name]="icon" [size]="16" />
                </div>
              }
              <div class="min-w-0">
                <h2 class="text-base font-semibold text-white truncate">{{ title }}</h2>
                @if (subtitle) {
                  <p class="text-xs text-gray-400 truncate">{{ subtitle }}</p>
                }
              </div>
            </div>
            <button
              type="button"
              (click)="close.emit()"
              class="w-8 h-8 rounded-md flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition"
              aria-label="Close"
            >
              <app-icon name="x" [size]="18" />
            </button>
          </header>
          <div class="p-6">
            <ng-content />
          </div>
        </aside>
      </div>
    }
  `,
})
export class DrawerComponent {
  @Input() open: boolean = false;
  @Input({ required: true }) title!: string;
  @Input() subtitle?: string;
  @Input() icon?: string;
  @Input() width: number = 460;
  @Input() dismissOnBackdrop: boolean = true;

  @Output() close = new EventEmitter<void>();

  dismiss(ev: MouseEvent): void {
    if (this.dismissOnBackdrop) this.close.emit();
  }
}
