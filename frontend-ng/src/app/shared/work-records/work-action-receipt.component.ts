import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';

/** A recorded action is evidence, not a claim that its parent record is closed. */
export interface WorkActionReceipt {
  reference: string;
  label: string;
  value?: string;
  notice?: string;
  recordedAt?: string;
}

@Component({
  selector: 'app-work-action-receipt', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [`
    :host { display: block; min-width: 0; }
    .receipt { border-inline-start: 3px solid var(--ck-signal-cool); padding-inline-start: 14px; }
    h3 { margin: 0 0 8px; color: var(--ck-fg-1); font-size: 14px; font-weight: 600; }
    p { margin: 6px 0; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
    .notice, time { color: var(--ck-fg-2); font-size: 12px; }
    time { display: block; margin-block: 8px; }
    details { margin-block-start: 12px; font-size: 12px; }
    summary { cursor: pointer; width: fit-content; padding-block: 6px; color: var(--ck-signal-cool); }
    summary:focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 3px; }
    code { display: block; margin-block-start: 8px; font-size: 11px; overflow-wrap: anywhere; user-select: all; }
  `],
  template: `
    <section class="receipt" [attr.aria-label]="i18n.t('experience.work_receipt.recorded')">
      <h3>{{ i18n.t('experience.work_receipt.recorded') }}</h3>
      <p>{{ receipt().label }} @if (receipt().value) { · <strong>{{ receipt().value }}</strong> }</p>
      @if (receipt().notice) { <p class="notice">{{ receipt().notice }}</p> }
      @if (receipt().recordedAt; as date) { <time [attr.datetime]="date">{{ recordedDate(date) }}</time> }
      <details>
        <summary>{{ i18n.t('experience.work_receipt.reference') }}</summary>
        <code>{{ receipt().reference }}</code>
      </details>
    </section>
  `,
})
export class WorkActionReceiptComponent {
  readonly i18n = inject(I18nService);
  readonly receipt = input.required<WorkActionReceipt>();

  recordedDate(value: string): string {
    const date = new Date(value);
    return Number.isFinite(date.getTime())
      ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(date)
      : this.i18n.t('state.availability.unknown');
  }
}
