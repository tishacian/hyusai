import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { UsageSummary } from './usage.models';
import { usageAmount, usageCostCoverage, usageNumber } from './usage.vm';

@Component({
  selector: 'app-usage-summary', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="metrics">
      <article><span>{{ t('calls') }}</span><strong>{{ number(data().counts.dispatched) }}</strong>
        <small>{{ i18n.t('observability.usage.call_statuses', { completed: number(data().counts.completed), failed: number(data().counts.failed), blocked: number(data().counts.blocked) }) }}</small></article>
      <article><span>{{ t('input_tokens') }}</span><strong>{{ number(data().tokens.input) }}</strong>
        <small>{{ t('cached_input') }} {{ number(data().tokens.cached_input) }} · {{ t('cache_write') }} {{ number(data().tokens.cache_write) }}</small></article>
      <article><span>{{ t('output_tokens') }}</span><strong>{{ number(data().tokens.output) }}</strong>
        <small>{{ t('reasoning') }} {{ number(data().tokens.reasoning) }}</small></article>
      <article><span>{{ t('calculated_cost') }}</span>
        @for (cost of data().costs; track cost.currency) { <strong class="money">{{ cost.known_calls ? amount(cost.known_amount, cost.currency) : '— ' + cost.currency }}</strong> }
        @if (!data().costs.length) { <strong>—</strong> }
        <small>{{ i18n.t('observability.usage.cost_coverage', { known: number(coverage().known), total: number(coverage().total) }) }}</small></article>
    </div>
    <p class="basis">{{ t('cost_basis') }} <span>{{ t('history_note') }}</span>
      @if (data().tokens.unknown_calls) { <span>{{ i18n.t('observability.usage.unknown_tokens', { count: number(data().tokens.unknown_calls) }) }}</span> }
      @if (!data().coverage.complete) { <span class="limited">{{ t('limited_coverage') }}</span> }
    </p>
  `,
  styles: [`.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-block:1px solid var(--ck-stroke-2);margin:16px 0 0}.metrics article{min-width:0;padding:18px 20px;border-right:1px solid var(--ck-stroke-2);display:flex;flex-direction:column;gap:8px}.metrics article:first-child{padding-left:0}.metrics article:last-child{border:0}.metrics span,.metrics small,.basis{color:var(--ck-fg-3);font-size:12px;line-height:1.5}.metrics strong{font:600 28px var(--ck-font-mono);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.metrics strong.money{font-size:24px}.basis{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0 22px}.limited{color:var(--ck-status-warn-fg)}@media(max-width:850px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics article:nth-child(2){border:0}.metrics article:nth-child(3){padding-left:0;border-top:1px solid var(--ck-stroke-2)}.metrics article:nth-child(4){border-top:1px solid var(--ck-stroke-2)}}@media(max-width:420px){.metrics strong{font-size:22px}.metrics article{padding:14px 12px}.metrics strong.money{font-size:20px}}`],
})
export class UsageSummaryComponent {
  readonly data = input.required<UsageSummary>();
  readonly i18n = inject(I18nService);
  readonly coverage = computed(() => usageCostCoverage(this.data()));
  t(key: string): string { return this.i18n.t('observability.usage.' + key); }
  number(value: unknown): string { return usageNumber(value, this.i18n.locale()); }
  amount(value: unknown, currency: string | null): string { return usageAmount(value, currency, this.i18n.locale()); }
}
