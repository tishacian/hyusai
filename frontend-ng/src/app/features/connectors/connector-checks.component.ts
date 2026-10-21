import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { connectionChecks } from './connector-capabilities';

@Component({
  selector: 'app-connector-checks', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section role="status" aria-live="polite" data-testid="connector-checks">
      <h3>{{ i18n.t('connectors.checks.title') }}</h3>
      <ol>
        @for (phase of phases; track phase) {
          <li [attr.data-phase]="phase" [attr.data-state]="checks()[phase]">
            {{ i18n.t('connectors.checks.' + phase) }} : {{ i18n.t('connectors.checks.' + checks()[phase]) }}
          </li>
        }
      </ol>
      @if (result()) { <p>{{ i18n.t('connectors.checks.hint.' + checks().reason) }}</p> }
    </section>
  `,
  styles: [`:host{display:block;margin:12px 0} section{padding:12px;border:1px solid var(--ck-stroke-1);border-radius:var(--ck-radius-sm)}h3{font-size:14px;margin:0 0 8px}ol{margin:0;padding-inline-start:20px}li,p{font-size:13px;color:var(--ck-fg-2);overflow-wrap:anywhere}p{margin:8px 0 0}`],
})
export class ConnectorChecksComponent {
  readonly i18n = inject(I18nService);
  readonly configured = input<boolean | null>(null);
  readonly result = input<unknown>(null);
  readonly phases = ['configuration', 'authentication', 'resource'] as const;
  readonly checks = computed(() => connectionChecks(this.result(), this.configured()));
}
