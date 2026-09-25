import {
  ChangeDetectionStrategy,
  Component,
  inject,
  input,
  output,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';

/**
 * Cockpit filter / provenance chip (L10).
 *
 * - provenance: clickable back (or forward « Voir dans Impact »)
 * - filter: dismissible « Filtré sur {name} × »
 *
 * Grammar matches runs-list filters / run-view arrival chips: ck-mono, 10px,
 * radius 3px, tokens v2 — no glow, no full-round caps.
 */
@Component({
  selector: 'ck-filter-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (kind() === 'provenance') {
      <a
        class="ck-filter-chip"
        [class.ck-filter-chip-forward]="forward()"
        [attr.href]="href() || null"
        [attr.data-testid]="testId() || null"
        (click)="onProvenanceClick($event)"
      >{{ label() }}</a>
    } @else {
      <button
        type="button"
        class="ck-filter-chip"
        [attr.data-testid]="testId() || null"
        (click)="dismiss.emit()"
      >
        <span>{{ i18n.t('nav.filter.filtered_on', { name: label() }) }}</span>
        <span aria-hidden="true">×</span>
      </button>
    }
  `,
  styles: [
    `
      :host {
        display: inline-flex;
      }
      .ck-filter-chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 8px;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        line-height: 1.2;
        color: var(--ck-fg-2);
        background: var(--ck-bg-inset);
        border: 1px solid var(--ck-stroke-2);
        border-radius: 3px;
        text-decoration: none;
        cursor: pointer;
      }
      .ck-filter-chip:hover {
        color: var(--ck-fg-1);
        border-color: var(--ck-stroke-3);
      }
      .ck-filter-chip:focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 2px;
      }
      .ck-filter-chip-forward {
        color: var(--ck-signal-cool);
        background: transparent;
      }
    `,
  ],
})
export class FilterChipComponent {
  readonly i18n = inject(I18nService);

  readonly kind = input.required<'provenance' | 'filter'>();
  readonly label = input.required<string>();
  /** Provenance: back or forward destination. */
  readonly href = input<string | null>(null);
  /** When true, provenance is a forward affordance (no back semantics). */
  readonly forward = input(false);
  readonly testId = input<string | null>(null);
  readonly dismiss = output<void>();
  readonly navigate = output<MouseEvent>();

  onProvenanceClick(event: MouseEvent): void {
    if (
      event.defaultPrevented
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) {
      return;
    }
    const href = this.href();
    if (!href) return;
    event.preventDefault();
    this.navigate.emit(event);
  }
}
