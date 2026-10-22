import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import type { UsageCallPage } from './usage.models';
import { TariffProvenanceComponent } from './tariff-provenance.component';
import { diagnosticCode, usageAmount, usageNumber } from './usage.vm';

@Component({
  selector: 'app-usage-calls', standalone: true, imports: [NavLinkDirective, TariffProvenanceComponent], changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="table-wrap" tabindex="0" role="region" [attr.aria-label]="t('call_log')">
      <table><caption>{{ t('call_log') }} <span>{{ number(page().total) }}</span></caption>
        <thead><tr><th scope="col">{{ t('started') }}</th><th scope="col">{{ t('model') }}</th><th scope="col">{{ t('purpose') }}</th><th scope="col">{{ t('status') }}</th><th scope="col" class="numeric">{{ t('input_output') }}</th><th scope="col" class="numeric">{{ t('calculated_cost') }}</th><th scope="col">{{ t('evidence') }}</th></tr></thead>
        <tbody>
          @for (call of page().items; track call.id) {
            <tr><td><time [attr.datetime]="call.started_at">{{ date(call.started_at) }}</time></td>
              <td><strong>{{ call.model || t('unknown') }}</strong><small>{{ call.provider || t('unknown') }}</small>
                @if (call.returned_model && call.returned_model !== call.model) { <small>{{ t('served_model') }} {{ call.returned_model }}</small> }</td>
              <td>{{ label('purpose', call.purpose) }}<small>{{ label('traffic', call.traffic) }}</small></td>
              <td><span class="status" [class.negative]="call.status === 'failed' || call.status === 'blocked'">{{ label('status', call.status) }}</span>
                @if (diagnostic(call.diagnostic)) { <details><summary>{{ t('reason') }}</summary><p>{{ reason(diagnostic(call.diagnostic)) }}</p><code>{{ diagnostic(call.diagnostic) }}</code></details> }</td>
              <td class="numeric">{{ number(call.input_tokens) }} / {{ number(call.output_tokens) }}
                @if (call.cached_input_tokens !== null || call.reasoning_tokens !== null || call.cache_write_tokens !== null) {
                  <details><summary>{{ t('token_detail') }}</summary><dl><dt>{{ t('cached_input') }}</dt><dd>{{ number(call.cached_input_tokens) }}</dd><dt>{{ t('cache_write') }}</dt><dd>{{ number(call.cache_write_tokens) }}</dd><dt>{{ t('reasoning') }}</dt><dd>{{ number(call.reasoning_tokens) }}</dd></dl></details>
                }
              </td>
              <td class="numeric">{{ amount(call.amount, call.currency) }}
                @if (call.amount === null) { <small>{{ t('unpriced') }}</small> }
                @if (call.tariff_snapshot; as tariff) { <small>{{ t('revision') }} {{ tariff.revision ?? tariff.version ?? '—' }}</small><app-tariff-provenance [provenance]="tariff.provenance" [currency]="tariff.currency" /> }</td>
              <td>@if (call.run_id && call.invocation_id) { <a [navLink]="{type:'skill_invocation',runId:call.run_id,ref:call.invocation_id}">{{ t('invocation') }}</a> }
                @else if (call.run_id) { <a [navLink]="{type:'run',ref:call.run_id}">{{ t('run') }}</a> }
                @else { <span class="muted">{{ t('no_run') }}</span> }</td>
            </tr>
          } @empty { <tr><td colspan="7" class="empty">{{ t('no_calls') }}</td></tr> }
        </tbody>
      </table>
    </div>
    <nav class="pagination" [attr.aria-label]="t('pagination')">
      <span>{{ i18n.t(page().total === null ? 'observability.usage.page_range_unknown' : 'observability.usage.page_range', { from: number(page().items.length ? page().offset + 1 : 0), to: number(page().offset + page().items.length), total: number(page().total) }) }}</span>
      <div><button type="button" [disabled]="busy() || page().offset === 0" (click)="pageChange.emit(Math.max(0, page().offset - page().limit))">{{ t('previous') }}</button>
      <button type="button" [disabled]="busy() || !hasNext()" (click)="pageChange.emit(page().offset + page().limit)">{{ t('next') }}</button></div>
    </nav>
  `,
  styleUrl: './usage-shared.css',
})
export class UsageCallsComponent {
  readonly page = input.required<UsageCallPage>();
  readonly busy = input(false);
  readonly pageChange = output<number>();
  readonly i18n = inject(I18nService);
  readonly Math = Math;
  readonly diagnostic = diagnosticCode;
  hasNext(): boolean { const page = this.page(); return page.total === null ? page.items.length === page.limit : page.offset + page.items.length < page.total; }
  t(key: string): string { return this.i18n.t('observability.usage.' + key); }
  label(group: string, value: string): string {
    const key = 'observability.usage.' + group + '.' + value, translated = this.i18n.t(key);
    return translated === key ? value || this.t('unknown') : translated;
  }
  reason(code: string): string { const key = 'observability.usage.error.' + code, text = this.i18n.t(key); return text === key ? this.t('call_refused') : text; }
  number(value: unknown): string { return usageNumber(value, this.i18n.locale()); }
  amount(value: unknown, currency: string | null): string { return usageAmount(value, currency, this.i18n.locale()); }
  date(value: string): string { const date = new Date(value); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'short', timeStyle: 'short' }).format(date) : this.t('unknown'); }
}
