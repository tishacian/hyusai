import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from './icon.component';
import { writeFailureCause, type WriteOutcome } from './load-state';

/**
 * The outcome of a write, said next to the action that sent it (see
 * `WriteOutcome` in `./load-state.ts`).
 *
 * Nothing reads as saved before the server confirms it. A failure says what
 * the server answered; an unknown result says the answer never came and
 * offers "Check" (the `verify` output) instead of sending again.
 *
 * Each outcome carries `data-testid="write-outcome-<outcome>"`.
 */
@Component({
  selector: 'app-write-outcome',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (outcome(); as current) {
      <div
        class="flex flex-wrap items-center gap-2 text-xs"
        [attr.data-testid]="'write-outcome-' + current.s"
        [attr.data-state]="current.s"
        [attr.role]="current.s === 'failed' || current.s === 'unknown' ? 'alert' : 'status'"
        [style.color]="color()"
      >
        <app-icon [name]="icon()" [size]="14" aria-hidden="true" />
        <span>{{ message() }}</span>
        @if (current.s === 'unknown' && verifiable()) {
          <button
            type="button"
            class="ck-btn ck-btn--sm ck-btn-quiet"
            data-testid="write-outcome-verify"
            (click)="verify.emit()"
          >
            {{ i18n.t('state.write.verify') }}
          </button>
        }
      </div>
    }
  `,
})
export class WriteOutcomeComponent {
  readonly i18n = inject(I18nService);

  readonly outcome = input<WriteOutcome | null>(null);
  /** Said once the server confirmed, e.g. "Preset saved". */
  readonly confirmedLabel = input<string | null>(null);
  /** Said when the server refused, before its cause, e.g. "The preset was not saved". */
  readonly failedLabel = input<string | null>(null);
  /** Offer "Check" on an unknown result. */
  readonly verifiable = input(false);

  readonly verify = output<void>();

  readonly icon = computed(() => {
    switch (this.outcome()?.s) {
      case 'sent': return 'loader';
      case 'accepted': return 'clock';
      case 'confirmed': return 'check-circle';
      case 'failed': return 'alert-triangle';
      case 'unknown': return 'help-circle';
      default: return '';
    }
  });

  readonly color = computed(() => {
    switch (this.outcome()?.s) {
      case 'confirmed': return 'var(--ck-status-ok-fg)';
      case 'failed': return 'var(--ck-status-neg-fg)';
      case 'unknown': return 'var(--ck-status-warn-fg)';
      default: return 'var(--ck-fg-3)';
    }
  });

  readonly message = computed(() => {
    const outcome = this.outcome();
    if (!outcome) return '';
    switch (outcome.s) {
      case 'sent': return this.i18n.t('state.write.sent');
      case 'accepted': return this.i18n.t('state.write.accepted');
      case 'confirmed': return this.confirmedLabel() ?? this.i18n.t('state.write.confirmed');
      case 'failed': {
        const lead = this.failedLabel() ?? this.i18n.t('state.write.failed');
        const cause = writeFailureCause(outcome);
        return `${lead} ${this.i18n.t(cause.key, cause.params)}`;
      }
      case 'unknown': return this.i18n.t('state.write.unknown');
    }
  });

}
