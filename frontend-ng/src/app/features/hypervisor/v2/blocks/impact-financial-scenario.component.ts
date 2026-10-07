import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { financialScenario, SCENARIO_FIELDS } from '../impact-product-blocks';
import type { HypervisorBlockRef } from '../hypervisor-v2-views';

@Component({
  selector: 'app-impact-financial-scenario', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './impact-product-blocks.scss',
  template: `
    <section class="impact-product" data-testid="impact-financial-scenario">
      <header class="product-head">
        <div><h2>{{ block().title || i18n.t('hypervisor.v2.block.financial_scenario') }}</h2><p>{{ scopeLabel() }} · {{ i18n.t('hypervisor.v2.scenario.declared') }}</p></div>
        @if (canEdit()) { <button type="button" (click)="configure.emit()">{{ i18n.t('hypervisor.v2.product.configure') }}</button> }
      </header>
      @if (projection(); as result) {
        <dl class="product-metrics">
          <div><dt>{{ i18n.t('hypervisor.v2.scenario.net') }}</dt><dd data-testid="impact-projected-net">{{ money(result.net, result.currency) }}</dd></div>
          <div><dt>{{ i18n.t('hypervisor.v2.scenario.roi') }}</dt><dd data-testid="impact-projected-roi">{{ percent(result.roi) }}</dd></div>
          <div><dt>{{ i18n.t('hypervisor.v2.scenario.threshold') }}</dt><dd>{{ number(result.breakEvenMinutes) }} <small>min</small></dd></div>
          <div><dt>{{ i18n.t('hypervisor.v2.scenario.monthly') }}</dt><dd>{{ money(result.monthlyNet, result.currency) }}</dd></div>
        </dl>
      } @else { <p>{{ i18n.t('hypervisor.v2.scenario.incomplete') }}</p> }
      <details open><summary>{{ i18n.t('hypervisor.v2.scenario.assumptions') }}</summary>
        <dl class="product-assumptions">
          @for (field of fields; track field) { <div><dt>{{ i18n.t('hypervisor.v2.scenario.' + field) }}</dt><dd>{{ assumption(field) }}</dd></div> }
        </dl>
        @if (block().settings['unit_label']; as unit) { <p>{{ i18n.t('hypervisor.v2.scenario.unit_label') }} : {{ unit }}</p> }
        @if (block().settings['note']; as note) { <p>{{ note }}</p> }
      </details>
      <p class="product-note">{{ i18n.t('hypervisor.v2.scenario.note') }}</p>
    </section>
  `,
})
export class ImpactFinancialScenarioComponent {
  readonly i18n = inject(I18nService);
  readonly block = input.required<HypervisorBlockRef>();
  readonly scopeLabel = input('');
  readonly canEdit = input(false);
  readonly configure = output<void>();
  readonly fields = SCENARIO_FIELDS;
  readonly projection = computed(() => financialScenario(this.block().settings));
  assumption(field: string): string {
    const value = this.block().settings[field];
    const currency = this.block().settings['currency'];
    if (typeof value !== 'number') return '—';
    return ['unit_budget', 'hourly_cost'].includes(field) && typeof currency === 'string' && /^[A-Z]{3}$/.test(currency)
      ? this.money(value, currency) : this.number(value);
  }
  money(value: number | null, currency: string): string {
    return value == null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(value);
  }
  number(value: number | null): string {
    return value == null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 2 }).format(value);
  }
  percent(value: number | null): string {
    return value == null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 0 }).format(value);
  }
}
