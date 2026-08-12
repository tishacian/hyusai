import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IconComponent } from './icon.component';

/**
 * Centered modal for destructive confirmations. Supports "type-to-confirm"
 * pattern (used by danger zones): set `confirmPhrase` to the workspace/project
 * name and the button stays disabled until the user types it verbatim.
 */
@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div class="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" (click)="onCancel()"></div>
        <div
          class="relative ck-surface rounded-lg border border-white/10 shadow-elevated max-w-md w-full p-6 animate-slide-up"
          (click)="$event.stopPropagation()"
        >
          <div class="flex items-start gap-4">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center shrink-0"
              [class.ck-tone-neg]="tone === 'danger'"
              [class.ck-tone-info]="tone !== 'danger'"
            >
              <app-icon [name]="icon" [size]="20" />
            </div>
            <div class="flex-1 min-w-0">
              <h2 class="text-base font-semibold text-white mb-1">{{ title }}</h2>
              @if (description) {
                <p class="text-sm text-gray-400 leading-relaxed">{{ description }}</p>
              }
            </div>
          </div>

          @if (confirmPhrase) {
            <div class="mt-5 space-y-2">
              <label class="block text-xs text-gray-400">
                Type <span class="font-mono font-semibold" [style.color]="'var(--ck-status-neg-fg)'">{{ confirmPhrase }}</span> to confirm:
              </label>
              <input
                [(ngModel)]="typed"
                type="text"
                class="w-full px-3 py-2 bg-black/30 border border-white/10 rounded text-white font-mono text-sm focus:outline-none focus:ring-2 focus:ring-red-500/60"
                [placeholder]="confirmPhrase"
              />
            </div>
          }

          <div class="mt-6 flex justify-end gap-2">
            <button
              type="button"
              (click)="onCancel()"
              class="px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-white/5 rounded transition"
            >
              {{ cancelLabel }}
            </button>
            <button
              type="button"
              (click)="onConfirm()"
              [disabled]="!canConfirm()"
              class="px-4 py-2 text-sm font-medium rounded transition disabled:opacity-40 disabled:cursor-not-allowed"
              [class.ck-cta]="tone !== 'danger'"
              [style.background]="tone === 'danger' ? 'var(--ck-signal-neg)' : null"
              [style.color]="tone === 'danger' ? 'var(--ck-on-signal)' : null"
            >
              {{ confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class ConfirmDialogComponent {
  @Input() open: boolean = false;
  @Input({ required: true }) title!: string;
  @Input() description?: string;
  @Input() confirmLabel: string = 'Confirm';
  @Input() cancelLabel: string = 'Cancel';
  @Input() tone: 'danger' | 'brand' = 'brand';
  @Input() icon: string = 'alert-triangle';
  /** If set, user must type this exact phrase to enable the confirm button. */
  @Input() confirmPhrase?: string;

  @Output() confirm = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();

  typed = '';

  canConfirm(): boolean {
    if (!this.confirmPhrase) return true;
    return this.typed.trim() === this.confirmPhrase;
  }

  onConfirm(): void {
    if (this.canConfirm()) {
      this.confirm.emit();
      this.typed = '';
    }
  }

  onCancel(): void {
    this.cancel.emit();
    this.typed = '';
  }
}
