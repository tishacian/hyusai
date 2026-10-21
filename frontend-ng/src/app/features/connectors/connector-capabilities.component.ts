import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { CONNECTOR_ACTIONS, connectorCapabilities, type ConnectorCapabilities } from './connector-capabilities';

@Component({
  selector: 'app-connector-capabilities',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="connector-capabilities" data-testid="connector-capabilities" [attr.aria-label]="i18n.t('connectors.capabilities.title')">
      <h2>{{ i18n.t('connectors.capabilities.title') }}</h2>
      <p>{{ i18n.t('connectors.capabilities.help') }}</p>
      <dl>
        @for (action of actions; track action) {
          <div [attr.data-capability]="action" [attr.data-supported]="supported()[action]">
            <dt>{{ i18n.t('connectors.capabilities.' + action) }}</dt>
            <dd>{{ i18n.t(supported()[action] ? 'connectors.capabilities.supported' : 'connectors.capabilities.unsupported') }}</dd>
          </div>
        }
      </dl>
    </section>
  `,
  styles: [`
    :host { display:block; margin:0 0 20px; }
    section { padding:16px; border:1px solid var(--ck-stroke-1); border-radius:var(--ck-radius-sm); background:var(--ck-bg-panel); }
    h2 { font-size:14px; font-weight:600; color:var(--ck-fg-1); margin:0; }
    p { font-size:12px; color:var(--ck-fg-3); margin:6px 0 12px; }
    dl { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:0; }
    dt { font-size:13px; color:var(--ck-fg-2); } dd { margin:4px 0 0; font-size:12px; color:var(--ck-fg-3); }
  `],
})
export class ConnectorCapabilitiesComponent {
  readonly i18n = inject(I18nService);
  readonly connector = input.required<string>();
  readonly available = input(false);
  readonly testable = input(false);
  readonly capabilities = input<ConnectorCapabilities | null>(null);
  readonly actions = CONNECTOR_ACTIONS;
  readonly supported = computed(() => this.capabilities() ?? connectorCapabilities(this.connector(), { available: this.available(), testable: this.testable() }));
}
