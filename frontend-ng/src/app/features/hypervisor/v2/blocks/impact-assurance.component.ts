import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ASSURANCE_MESSAGES, assuranceTraffic, knownSpend, qualityPassFraction, type AssuranceQuality, type AssuranceUsage } from '../impact-assurance';
import type { HypervisorBlockRef } from '../hypervisor-v2-views';

@Component({
  selector: 'app-impact-assurance', standalone: true, imports: [NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="assurance" [attr.data-testid]="'impact-' + block().type" [attr.aria-busy]="busy()">
      <header><div><h2>{{ block().title || (qualityMode() ? labels().quality : labels().ai_usage) }}</h2><p>{{ scopeLabel() }} · {{ labels()[traffic()] }}</p></div>
        <div class="actions">@if(canEdit()) { <button type="button" (click)="configure.emit()">{{ i18n.t('hypervisor.v2.product.configure') }}</button> }<button type="button" [disabled]="busy()" (click)="refresh()">{{ i18n.t('hypervisor.v2.product.refresh') }}</button></div>
      </header>
      @if(problem()) { <p role="alert">{{ i18n.t('hypervisor.v2.product.unavailable') }}</p> }
      @else if(busy()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
      @else if(quality(); as value) {
        <dl class="metrics">
          <div><dt>{{ labels().runs }}</dt><dd>{{ number(value.totals.distinct_runs) }}</dd></div>
          <div><dt>{{ labels().valid }}</dt><dd>{{ number(value.totals.assessed) }}<small> / {{ number(value.totals.evaluations) }}</small></dd></div>
          <div><dt>{{ labels().pass }}</dt><dd><span>{{ fraction() == null ? '—' : number(fraction()! * 100, 1) + ' %' }}</span><small class="metric-note">{{ labels().passBasis }}</small></dd></div>
          <div><dt>{{ labels().failures }}</dt><dd [class.warning]="value.totals.technical_failures > 0">{{ number(value.totals.technical_failures) }}</dd></div>
        </dl>
        <p>{{ labels().unknown }} : {{ number(value.totals.unassessed) }} · {{ labels().reviewed }} : {{ number(value.totals.reviewed) }}</p>
        <p class="note">{{ labels().qualityNote }}</p>
        @if(!value.totals.evaluations) { <p>{{ labels().empty }}</p> }
      }
      @else if(usage(); as value) {
        <dl class="metrics">
          <div><dt>{{ labels().calls }}</dt><dd>{{ number(value.counts.dispatched) }}</dd></div>
          <div><dt>{{ labels().input }}</dt><dd>{{ value.tokens.known_calls ? number(value.tokens.input) : '—' }}</dd></div>
          <div><dt>{{ labels().output }}</dt><dd>{{ value.tokens.known_calls ? number(value.tokens.output) : '—' }}</dd></div>
          <div><dt>{{ labels().costs }}</dt><dd class="money">@for(cost of spend(); track cost.currency) { <span>{{ money(cost.amount, cost.currency) }}</span> } @empty { — }</dd></div>
        </dl>
        <p>{{ labels().coverage }} : {{ number(value.tokens.known_calls) }} / {{ number(value.counts.dispatched) }}</p>
        <p class="note">{{ labels().costsNote }}</p>
        @if(!value.counts.calls) { <p>{{ labels().empty }}</p> }
      }
      @if(quality()?.has_more || usage()?.coverage?.complete === false) { <p class="note">{{ labels().limited }}</p> }
      <footer><a [navLink]="{surface:'observability',facet:qualityMode() ? 'quality' : 'usage',systemId:systemId(),params:destination()}">{{ labels().detail }} →</a><span>{{ labels().observedAt }} <time>{{ timestamp() }}</time></span></footer>
    </section>
  `,
  styles: `:host{display:block;min-width:0}.assurance{padding:24px clamp(16px,3vw,32px);border:1px solid var(--ck-stroke-2);border-radius:6px;background:var(--ck-bg-panel);color:var(--ck-fg-1)}header,footer,.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}h2{font-size:18px;font-weight:600;margin:0 0 8px}p{color:var(--ck-fg-2);font-size:13px;line-height:1.6;margin:6px 0}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;margin:24px 0}.metrics div{min-width:0}dt{font-size:12px;color:var(--ck-fg-2);margin-bottom:10px}dd{margin:0;font-size:28px;font-weight:600;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}dd small,small{font-size:12px;color:var(--ck-fg-3);font-weight:400}.metric-note{display:block;margin-top:6px}.money{font-size:23px;display:grid;gap:4px}.warning{color:var(--ck-status-warn-fg)}.note{font-size:12px;color:var(--ck-fg-3)}footer{margin-top:20px;padding-top:14px;border-top:1px solid var(--ck-stroke-2);font-size:12px}footer span{color:var(--ck-fg-3)}a{color:var(--ck-signal-cool)}button{font:inherit;font-size:12px;color:var(--ck-fg-2);border:1px solid var(--ck-stroke-2);background:transparent;border-radius:4px;padding:6px 10px;cursor:pointer}button:disabled{opacity:.5;cursor:default}button:focus-visible,a:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}@media(max-width:700px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 12px}dd{font-size:24px}header{align-items:flex-start}}`,
})
export class ImpactAssuranceComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  readonly block = input.required<HypervisorBlockRef>();
  readonly systemId = input<string | null>(null);
  readonly scopeLabel = input('');
  readonly period = input('30d');
  readonly asOf = input<string | null>(null);
  readonly canEdit = input(false);
  readonly configure = output<void>();
  readonly quality = signal<AssuranceQuality | null>(null);
  readonly usage = signal<AssuranceUsage | null>(null);
  readonly busy = signal(true);
  readonly problem = signal(false);
  private readonly localAnchor = signal(new Date().toISOString());
  readonly anchor = computed(() => this.localAnchor());
  readonly labels = computed(() => ASSURANCE_MESSAGES[this.i18n.locale().startsWith('fr') ? 'fr' : 'en']);
  readonly qualityMode = computed(() => this.block().type === 'quality');
  readonly traffic = computed(() => assuranceTraffic(this.block().settings));
  readonly fraction = computed(() => qualityPassFraction(this.quality()));
  readonly spend = computed(() => knownSpend(this.usage()));
  readonly destination = computed(() => ({facet: this.qualityMode() ? 'quality' : 'usage', systemId: this.systemId(), since: this.period(), as_of: this.anchor(), traffic: this.traffic()}));
  readonly timestamp = computed(() => new Intl.DateTimeFormat(this.i18n.locale(), {dateStyle: 'short', timeStyle: 'short'}).format(new Date(this.anchor())));
  private readonly reload = signal(0);
  constructor() {
    effect(() => { this.localAnchor.set(this.asOf() || new Date().toISOString()); });
    effect(cleanup => {
      const workspaceId = this.workspace.current()?.id;
      this.auth.authEpoch(); this.reload();
      const qualityMode = this.qualityMode(), period = this.period(), systemId = this.systemId(), asOf = this.anchor(), traffic = this.traffic();
      this.quality.set(null); this.usage.set(null); this.busy.set(true); this.problem.set(false);
      if (!workspaceId) return;
      const params = {...(qualityMode ? {since: period} : {window: period}), ...(systemId ? {system_id: systemId} : {}), as_of: asOf, traffic};
      const subscription = this.api.get<AssuranceQuality | AssuranceUsage>(qualityMode ? '/evaluation/summary' : '/observability/usage/summary', params).subscribe({
        next: value => { if (qualityMode) this.quality.set(value as AssuranceQuality); else this.usage.set(value as AssuranceUsage); this.busy.set(false); },
        error: () => { this.problem.set(true); this.busy.set(false); },
      });
      cleanup(() => subscription.unsubscribe());
    });
  }
  refresh(): void { this.localAnchor.set(new Date().toISOString()); this.reload.update(value => value + 1); }
  number(value: number | null | undefined, digits = 0): string { return value == null ? '—' : new Intl.NumberFormat(this.i18n.locale(), {maximumFractionDigits: digits}).format(value); }
  money(value: number, currency: string): string { return new Intl.NumberFormat(this.i18n.locale(), {style:'currency', currency, maximumFractionDigits: 4}).format(value); }
}
