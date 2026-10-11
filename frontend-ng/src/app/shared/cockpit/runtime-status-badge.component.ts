import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import { I18nService } from '@app/core/i18n.service';

import { TagComponent, type CkTagTone } from './tag.component';

export type RuntimeStatus = 'bound' | 'stub' | 'unbound' | 'catalog_only' | string;

/** The API values this badge knows how to speak about in plain words. */
const KNOWN: readonly string[] = ['bound', 'stub', 'unbound', 'catalog_only'];

/**
 * `<ck-runtime-status>` — single source of truth for the runtime badge used
 * wherever skills surface in the UI.
 *
 * The API values (`bound`, `stub`, `unbound`, `catalog_only`) never reach the
 * screen: the label is the plain-language wording from `skills.runtime.status.*`
 * and the raw value stays on the `title`, per the two-register rule. An
 * unrecognised value degrades to "Unknown" rather than leaking itself.
 */
@Component({
  selector: 'ck-runtime-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TagComponent],
  template: `
    <ck-tag [tone]="tone()" [variant]="variant()" [title]="title()">
      {{ label() }}
    </ck-tag>
  `,
})
export class RuntimeStatusBadgeComponent {
  private readonly i18n = inject(I18nService);

  readonly status = input.required<RuntimeStatus | null | undefined>();
  readonly variant = input<'solid' | 'soft' | 'outline'>('soft');

  private readonly known = computed(() => {
    const status = this.status();
    return status && KNOWN.includes(status) ? status : 'unknown';
  });

  readonly label = computed(() =>
    this.i18n.t(`skills.runtime.status.${this.known()}` as never),
  );

  readonly tone = computed<CkTagTone>(() => {
    switch (this.status()) {
      case 'bound':
        return 'pos';
      case 'stub':
        return 'warn';
      case 'unbound':
        return 'neg';
      case 'catalog_only':
        return 'violet';
      default:
        return 'neutral';
    }
  });

  /** Plain explanation first, raw API value second — the support line. */
  readonly title = computed(() => {
    const hint = this.i18n.t(`skills.runtime.status.${this.known()}.hint` as never);
    const raw = this.status();
    return raw && this.known() !== 'unknown' ? `${hint} (${raw})` : hint;
  });
}
