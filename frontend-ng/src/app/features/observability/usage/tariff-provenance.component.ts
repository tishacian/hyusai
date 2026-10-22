import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { UsageRateKey, UsageTariffProvenance } from './usage.models';

@Component({ selector: 'app-tariff-provenance', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `@if (provenance(); as source) {
    <details class="tariff-provenance"><summary>{{ t(source.conversion ? 'declared_conversion' : 'declared_source') }}</summary>
      <dl><dt>{{ t('price_reference') }}</dt><dd>{{ source.reference }}</dd><dt>{{ t('observed_on') }}</dt><dd>{{ date(source.observed_on) }}</dd>
      @if (source.conversion; as conversion) {
        <dt>{{ t('declared_rate') }}</dt><dd>1 {{ conversion.source_currency }} = {{ rateText(conversion.rate) }} {{ currency() }}</dd>
        @for (entry of sourceRates(conversion.source_rates); track entry.key) {<dt>{{ entry.label }} · {{ conversion.source_currency }}</dt><dd>{{ rateText(entry.value) }}</dd>}
        <dt>{{ t('rate_reference') }}</dt><dd>{{ conversion.reference }}</dd><dt>{{ t('rate_observed_on') }}</dt><dd>{{ date(conversion.observed_on) }}</dd>
      }</dl><p>{{ t('provenance_declaration') }}</p>
    </details>
  } @else { <span class="muted">{{ t('source_not_recorded') }}</span> }`,
  styles: `:host{display:block;max-width:360px;font-size:12px}.tariff-provenance{margin:0}.tariff-provenance summary{cursor:pointer}.tariff-provenance dl{display:grid;grid-template-columns:1fr;gap:4px;margin:12px 0}.tariff-provenance dt,.muted,p{color:var(--ck-fg-3)}.tariff-provenance dd{margin:0 0 8px;overflow-wrap:anywhere}p{line-height:1.5}summary:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}`,
})
export class TariffProvenanceComponent {
  readonly provenance = input<UsageTariffProvenance | null | undefined>(null);
  readonly currency = input('');
  readonly i18n = inject(I18nService);
  t(key: string): string { return this.i18n.t('observability.usage.' + key); }
  sourceRates(rates: Partial<Record<UsageRateKey, string>>): Array<{key: string; label: string; value: string}> { const labels = {input_per_million:'input_rate',output_per_million:'output_rate',cached_input_per_million:'cached_rate',cache_write_per_million:'cache_write_rate'};return Object.entries(rates).filter(([,value]) => value != null).map(([key,value]) => ({key,label:this.t(labels[key as UsageRateKey]),value:value!})); }
  rateText(value: string): string { const number=Number(value); return Number.isFinite(number) ? new Intl.NumberFormat(this.i18n.locale(), {maximumFractionDigits:12}).format(number) : this.t('unknown'); }
  date(value: string): string { const date = new Date(value + 'T00:00:00Z'); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'medium', timeZone: 'UTC' }).format(date) : this.t('unknown'); }
}
