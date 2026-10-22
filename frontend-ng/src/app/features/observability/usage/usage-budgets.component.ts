import { ChangeDetectionStrategy, Component, OnDestroy, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { UsageApiError, UsageApiService } from './usage-api.service';
import type { UsageBudget, UsageBudgetPage, UsageSystemOption, UsageTariffPage, UsageTariffWrite, UsageRateKey } from './usage.models';
import { TariffProvenanceComponent } from './tariff-provenance.component';
import { declaredConversionRates, tariffProvenanceDraft, validateTariffProvenance } from './tariff-provenance.vm';
import { budgetAvailable, budgetDraft, budgetPercent, usageAmount, usageNumber, validateBudgetDraft, type BudgetDraft } from './usage.vm';

@Component({
  selector: 'app-usage-budgets', standalone: true, imports: [FormsModule, TariffProvenanceComponent], changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section [attr.aria-busy]="loading()">
      <div class="section-heading"><div><h2>{{ t('budgets') }}</h2><p>{{ t('budget_intro') }}</p></div>
        @if (data()?.can_manage) { <button type="button" (click)="edit()" [disabled]="saving()">{{ t('new_budget') }}</button> }</div>
      @if (error()) { <p class="notice error" role="alert">{{ errorText(error()) }} <button type="button" (click)="reload()">{{ i18n.t('common.refresh') }}</button></p> }
      @if (notice()) { <p class="notice" role="status">{{ notice() }}</p> }
      @if (loading() && !data()) { <p class="notice" role="status">{{ t('loading') }}</p> }
      @if (data(); as result) {
        @if (!result.readiness.ready) { <p class="notice">{{ t('budget_not_ready') }}
          @if (result.readiness.missing_transports.length) { <span>{{ t('routes_pending') }} {{ result.readiness.missing_transports.join(', ') }}</span> }
        </p> }
        @if (result.can_manage) { <p class="muted helper">{{ t('budget_coverage_note') }} {{ t('budget_unsupported_note') }}</p> }
        @if (!result.can_manage) { <p class="muted permission">{{ t('admin_required') }}</p> }
        <div class="budget-grid">
          @for (budget of result.items; track budget.id) {
            <article class="budget-card">
              <header><div><h3>{{ budget.scope === 'workspace' ? t('workspace') : systemName(budget.system_id) }}</h3>
                <p>{{ budget.timezone }} · {{ date(budget.current_period.start) }} — {{ date(budget.current_period.end) }}</p></div>
                <span class="badge" [class.positive]="budget.enabled">{{ t(budget.enabled ? 'budget_active' : 'budget_inactive') }}</span></header>
              @if (budget.max_tokens !== null) {
                <div class="budget-line"><span>{{ t('tokens') }}</span><strong>{{ number(available(budget.max_tokens, budget.current_period.consumed_tokens, budget.current_period.reserved_tokens)) }} <small>{{ t('available') }}</small></strong></div>
                <progress max="100" [value]="percent(budget.max_tokens, budget.current_period.consumed_tokens, budget.current_period.reserved_tokens)" [attr.aria-label]="t('token_consumption')"></progress>
                <div class="budget-figures"><span>{{ t('consumed') }} {{ number(budget.current_period.consumed_tokens) }}</span><span>{{ t('reserved') }} {{ number(budget.current_period.reserved_tokens) }}</span><span>{{ t('limit') }} {{ number(budget.max_tokens) }}</span></div>
              }
              @for (currency of budget.current_period.amounts; track currency.currency) {
                <div class="budget-line"><span>{{ currency.currency }}</span><strong>{{ amount(available(currency.limit, currency.consumed, currency.reserved), currency.currency) }} <small>{{ t('available') }}</small></strong></div>
                <progress max="100" [value]="percent(currency.limit, currency.consumed, currency.reserved)" [attr.aria-label]="t('cost_consumption') + ' ' + currency.currency"></progress>
                <div class="budget-figures"><span>{{ t('consumed') }} {{ amount(currency.consumed, currency.currency) }}</span><span>{{ t('reserved') }} {{ amount(currency.reserved, currency.currency) }}</span><span>{{ t('limit') }} {{ amount(currency.limit, currency.currency) }}</span></div>
              }
              @if (budget.reconciliation_required) { <p class="notice">{{ t('reconciliation') }}</p> }
              <footer><span class="muted">{{ t('revision') }} {{ budget.revision }}</span>
                @if (result.can_manage) { <div class="actions"><button type="button" (click)="edit(budget)" [disabled]="saving()">{{ t('edit') }}</button>
                  <button type="button" [disabled]="saving() || (!budget.enabled && !result.readiness.ready)" (click)="toggle(budget)">{{ t(budget.enabled ? 'pause_budget' : 'activate_budget') }}</button></div> }
              </footer>
              @if (budget.history?.length) { <details><summary>{{ t('history') }}</summary><ol class="history">@for (entry of budget.history; track entry.revision) { <li>{{ t('revision') }} {{ entry.revision }} <time [attr.datetime]="entry.at">{{ date(entry.at) }}</time></li> }</ol></details> }
            </article>
          } @empty { @if (result.can_manage) { <p class="empty">{{ t('no_budget') }}</p> } }
        </div>
        @if (editorOpen() && result.can_manage) {
          <form class="editor" (ngSubmit)="save()" aria-labelledby="usage-budget-editor-title">
            <div class="section-heading"><h3 id="usage-budget-editor-title">{{ t(editing() ? 'edit_budget' : 'new_budget') }}</h3><button type="button" (click)="closeEditor()" [disabled]="saving()">{{ t('cancel') }}</button></div>
            <div class="form-grid">
              <label>{{ t('scope') }}<select name="budgetScope" [(ngModel)]="draft.scope" [disabled]="!!editing()"><option value="workspace">{{ t('workspace') }}</option><option value="system">{{ t('system') }}</option></select></label>
              @if (draft.scope === 'system') { <label>{{ t('system') }}<select name="budgetSystem" [(ngModel)]="draft.systemId" [disabled]="!!editing()" required><option value="">{{ t('select_system') }}</option>@for (system of systems(); track system.id) { <option [value]="system.id">{{ system.name }}</option> }</select></label> }
              <label>{{ t('timezone') }}<input name="budgetTimezone" [(ngModel)]="draft.timezone" [readOnly]="!!editing()?.activated_at" required /></label>
              <label>{{ t('monthly_tokens') }}<input name="budgetTokens" [(ngModel)]="draft.tokenLimit" inputmode="numeric" type="number" min="0" step="1" [placeholder]="t('not_configured')" /></label>
            </div>
            <p class="muted helper">{{ t('timezone_note') }}</p>
            @for (row of draft.currencies; track $index; let index = $index) {
              <div class="currency-row"><label>{{ t('currency') }}<input [name]="'currency-' + index" [(ngModel)]="row.currency" maxlength="3" pattern="[A-Za-z]{3}" required /></label>
                <label>{{ t('monthly_amount') }}<input [name]="'amount-' + index" [(ngModel)]="row.limit" inputmode="decimal" required /></label>
                <button type="button" (click)="removeCurrency(index)" [attr.aria-label]="t('remove_currency') + ' ' + row.currency">{{ t('remove') }}</button></div>
            }
            <button type="button" (click)="addCurrency()">{{ t('add_currency') }}</button>
            <p class="muted helper">{{ t('budget_activation_note') }}</p>
            @if (formError()) { <p class="notice error" role="alert">{{ t('validation.' + formError()) }}</p> }
            <div class="actions"><button class="primary" type="submit" [disabled]="saving()">{{ t('save_budget') }}</button>
              @if (!editing()?.enabled) { <button type="button" [disabled]="saving() || !result.readiness.ready" (click)="save(true)">{{ t('save_activate') }}</button> }</div>
          </form>
        }
      }
      <details class="tariffs" (toggle)="tariffsOpen.set($any($event.target).open)">
        <summary>{{ t('tariffs') }} <span>{{ t('tariff_note') }}</span></summary>
        @if (tariffsOpen()) {
          @if (tariffs(); as table) {
            <div class="section-heading"><p>{{ t('tariff_immutable') }}</p>@if (table.can_manage) { <button type="button" (click)="tariffEditor.set(!tariffEditor())">{{ t('new_tariff') }}</button> }</div>
            <div class="table-wrap" tabindex="0" role="region" [attr.aria-label]="t('tariffs')"><table><thead><tr><th scope="col">{{ t('model') }}</th><th scope="col">{{ t('revision') }}</th><th scope="col">{{ t('currency') }}</th><th scope="col">{{ t('input_output') }}</th><th scope="col">{{ t('cached_input') }}</th><th scope="col">{{ t('cache_write') }}</th><th scope="col">{{ t('price_basis') }}</th></tr></thead><tbody>
              @for (tariff of table.items; track tariff.id) { <tr><td>{{ tariff.provider }} / {{ tariff.model }}</td><td>{{ tariff.version ?? tariff.revision ?? '—' }}</td><td>{{ tariff.currency }}</td><td>{{ amount(tariff.input_per_million, tariff.currency) }} / {{ amount(tariff.output_per_million, tariff.currency) }}</td><td>{{ amount(tariff.cached_input_per_million, tariff.currency) }}</td><td>{{ amount(tariff.cache_write_per_million, tariff.currency) }}</td><td><app-tariff-provenance [provenance]="tariff.provenance" [currency]="tariff.currency" /></td></tr> }
              @empty { <tr><td colspan="7" class="empty">{{ t('no_tariffs') }}</td></tr> }
            </tbody></table></div>
            @if (tariffEditor() && table.can_manage) {
              <form class="editor" (ngSubmit)="saveTariff()" aria-labelledby="usage-tariff-editor-title"><h3 id="usage-tariff-editor-title">{{ t('new_tariff') }}</h3>
                <div class="form-grid"><label>{{ t('provider') }}<input name="tariffProvider" [(ngModel)]="tariff.provider" required /></label><label>{{ t('model') }}<input name="tariffModel" [(ngModel)]="tariff.model" required /></label>
                  <label>{{ t('currency') }}<input name="tariffCurrency" [(ngModel)]="tariff.currency" maxlength="3" pattern="[A-Za-z]{3}" required /></label>
                  <label>{{ t('input_rate') }}<input name="tariffInput" [(ngModel)]="tariff.input_per_million" type="number" min="0" step="any" required /></label>
                  <label>{{ t('output_rate') }}<input name="tariffOutput" [(ngModel)]="tariff.output_per_million" type="number" min="0" step="any" required /></label>
                  <label>{{ t('cached_rate') }}<input name="tariffCached" [(ngModel)]="tariff.cached_input_per_million" type="number" min="0" step="any" [placeholder]="t('unknown')" /></label>
                  <label>{{ t('cache_write_rate') }}<input name="tariffWrite" [(ngModel)]="tariff.cache_write_per_million" type="number" min="0" step="any" [placeholder]="t('unknown')" /></label></div>
                <details class="tariff-advanced"><summary>{{ t('provenance_optional') }}</summary>
                  <p class="helper">{{ t('provenance_declaration') }}</p>
                  <div class="form-grid"><label>{{ t('price_reference') }}<input name="priceReference" [(ngModel)]="provenance.reference" maxlength="500" /></label>
                    <label>{{ t('observed_on') }}<input name="priceObservedOn" [(ngModel)]="provenance.observedOn" type="date" /></label></div>
                  <label class="conversion-check"><input name="conversionEnabled" type="checkbox" [(ngModel)]="provenance.conversionEnabled" />{{ t('declare_conversion') }}</label>
                  @if (provenance.conversionEnabled) {
                    <p class="helper">{{ t('conversion_hint') }}</p>
                    <div class="form-grid"><label>{{ t('source_currency') }}<input name="sourceCurrency" [(ngModel)]="provenance.sourceCurrency" maxlength="3" pattern="[A-Za-z]{3}" /></label>
                      <label>{{ t('declared_rate') }}<input name="conversionRate" [(ngModel)]="provenance.rate" inputmode="decimal" maxlength="40" /></label>
                      <label>{{ t('rate_reference') }}<input name="rateReference" [(ngModel)]="provenance.rateReference" maxlength="500" /></label>
                      <label>{{ t('rate_observed_on') }}<input name="rateObservedOn" [(ngModel)]="provenance.rateObservedOn" type="date" /></label></div>
                    <p class="conversion-equation">1 {{ provenance.sourceCurrency || '—' }} = {{ provenance.rate || '—' }} {{ tariff.currency || '—' }}</p>
                    <fieldset><legend>{{ t('source_rates') }}</legend><div class="form-grid">
                      @for (key of rateKeys; track key) {<label>{{ rateLabel(key) }}<input [name]="'sourceRate-' + key" [(ngModel)]="provenance.sourceRates[key]" inputmode="decimal" maxlength="40" [placeholder]="key === 'input_per_million' || key === 'output_per_million' ? '' : t('unknown')" /></label>}
                    </div></fieldset>
                    <button type="button" (click)="applyConversion()" [disabled]="saving()">{{ t('apply_conversion') }}</button>
                    <p class="helper">{{ t('conversion_rounding') }}</p>
                  }
                </details>
                <div class="actions"><button class="primary" type="submit" [disabled]="saving()">{{ t('save_tariff') }}</button><button type="button" (click)="tariffEditor.set(false)" [disabled]="saving()">{{ t('cancel') }}</button></div>
              </form>
            }
          }
        }
      </details>
    </section>
  `,
  styleUrls: ['./usage-shared.css', './usage-budgets.component.css'],
})
export class UsageBudgetsComponent implements OnDestroy {
  readonly systems = input<UsageSystemOption[]>([]);
  readonly i18n = inject(I18nService);
  private readonly api = inject(UsageApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  readonly data = signal<UsageBudgetPage | null>(null);
  readonly tariffs = signal<UsageTariffPage | null>(null);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal('');
  readonly notice = signal('');
  readonly formError = signal('');
  readonly editorOpen = signal(false);
  readonly editing = signal<UsageBudget | null>(null);
  readonly tariffsOpen = signal(false);
  readonly tariffEditor = signal(false);
  draft: BudgetDraft = budgetDraft();
  tariff: UsageTariffWrite = this.emptyTariff();
  provenance = tariffProvenanceDraft();
  readonly rateKeys: UsageRateKey[] = ['input_per_million', 'output_per_million', 'cached_input_per_million', 'cache_write_per_million'];
  readonly available = budgetAvailable;
  readonly percent = budgetPercent;
  private controller?: AbortController;
  private generation = 0;
  private resetters: Array<() => void> = [];
  constructor() {
    const clear = () => { this.generation++; this.controller?.abort(); this.data.set(null); this.tariffs.set(null); this.closeEditor(); this.tariffEditor.set(false); this.tariff = this.emptyTariff(); this.provenance = tariffProvenanceDraft(); this.notice.set(''); this.error.set(''); this.saving.set(false); };
    this.resetters.push(this.workspace.registerContextReset(() => { clear(); queueMicrotask(() => this.reload()); }), this.auth.registerContextReset(clear));
    this.reload();
  }
  t(key: string): string { return this.i18n.t('observability.usage.' + key); }
  number(value: unknown): string { return usageNumber(value, this.i18n.locale()); }
  amount(value: unknown, currency: string | null): string { return usageAmount(value, currency, this.i18n.locale()); }
  date(value: string): string { const date = new Date(value); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'medium' }).format(date) : this.t('unknown'); }
  systemName(id: string | null): string { return this.systems().find(system => system.id === id)?.name || this.t('system'); }
  errorText(code: string): string { const key = 'observability.usage.error.' + code, text = this.i18n.t(key); return text === key ? this.t('load_error') : text; }
  reload(): void { if (this.error() === 'USAGE_BUDGET_REVISION_CONFLICT') this.closeEditor(); void this.load(); }
  private async load(): Promise<void> {
    this.controller?.abort(); const controller = this.controller = new AbortController(), generation = ++this.generation;
    this.loading.set(true); this.error.set('');
    try { const [data, tariffs] = await Promise.all([this.api.budgets(controller.signal), this.api.tariffs(controller.signal)]); if (generation === this.generation) { this.data.set(data); this.tariffs.set(tariffs); } }
    catch (error) { if (generation === this.generation && !controller.signal.aborted) this.error.set(error instanceof UsageApiError ? error.code : 'USAGE_REQUEST_FAILED'); }
    finally { if (generation === this.generation) this.loading.set(false); }
  }
  edit(budget?: UsageBudget): void { this.editing.set(budget || null); this.draft = budgetDraft(budget); this.formError.set(''); this.editorOpen.set(true); }
  closeEditor(): void { this.editorOpen.set(false); this.editing.set(null); this.draft = budgetDraft(); this.formError.set(''); }
  addCurrency(): void { this.draft.currencies = [...this.draft.currencies, { currency: '', limit: '' }]; }
  removeCurrency(index: number): void { this.draft.currencies = this.draft.currencies.filter((_, i) => i !== index); }
  async save(activate = false): Promise<void> {
    if (this.saving() || !this.data()?.can_manage || (activate && !this.data()?.readiness.ready)) return;
    if (!this.editing() && this.data()?.items.some(item => item.scope === this.draft.scope && (item.scope === 'workspace' || item.system_id === this.draft.systemId))) { this.formError.set('scope_exists'); return; }
    const current = this.editing(), validated = validateBudgetDraft(this.draft, activate || current?.enabled === true, current?.revision || 0);
    this.formError.set(validated.error || ''); if (!validated.body) return;
    await this.mutate(async () => { await this.api.saveBudget(validated.body!); this.closeEditor(); this.notice.set(this.t(activate ? 'budget_activated' : 'budget_saved')); });
  }
  async toggle(budget: UsageBudget): Promise<void> {
    if (this.saving() || !this.data()?.can_manage || (!budget.enabled && !this.data()?.readiness.ready)) return;
    const validated = validateBudgetDraft(budgetDraft(budget), !budget.enabled, budget.revision);
    if (!validated.body) return;
    await this.mutate(async () => { await this.api.saveBudget(validated.body!); this.notice.set(this.t(budget.enabled ? 'budget_paused' : 'budget_activated')); });
  }
  rateLabel(key: UsageRateKey): string { return this.t({input_per_million:'input_rate',output_per_million:'output_rate',cached_input_per_million:'cached_rate',cache_write_per_million:'cache_write_rate'}[key]); }
  applyConversion(): void {
    try { const rates = declaredConversionRates(this.provenance, this.tariff); this.tariff = { ...this.tariff, ...rates }; this.error.set(''); this.notice.set(this.t('conversion_applied')); }
    catch { this.error.set('USAGE_TARIFF_PROVENANCE_INVALID'); }
  }
  async saveTariff(): Promise<void> {
    if (this.saving() || !this.tariffs()?.can_manage) return;
    const body: UsageTariffWrite = { provider: this.tariff.provider.trim(), model: this.tariff.model.trim(), currency: this.tariff.currency.trim().toUpperCase(),
      input_per_million: String(this.tariff.input_per_million), output_per_million: String(this.tariff.output_per_million) };
    for (const field of ['cached_input_per_million', 'cache_write_per_million'] as const) { if (this.tariff[field] !== '' && this.tariff[field] != null) body[field] = String(this.tariff[field]); }
    if (!body.provider || !body.model || !/^[A-Z]{3}$/.test(body.currency) || ['input_per_million','output_per_million','cached_input_per_million','cache_write_per_million'].some(field => {
      const value = body[field as UsageRateKey]; return value !== undefined && (value.trim() === '' || !Number.isFinite(Number(value)) || Number(value) < 0);
    })) { this.error.set('USAGE_TARIFF_INVALID'); return; }
    const metadata = validateTariffProvenance(this.provenance, body);
    if (metadata.error) { this.error.set(metadata.error); return; }
    if (metadata.provenance) body.provenance = metadata.provenance;
    await this.mutate(async () => { await this.api.saveTariff(body); this.tariffEditor.set(false); this.tariff = this.emptyTariff(); this.provenance = tariffProvenanceDraft(); this.notice.set(this.t('tariff_saved')); });
  }
  private async mutate(action: () => Promise<void>): Promise<void> {
    this.saving.set(true); this.error.set(''); this.notice.set(''); const generation = this.generation;
    try { await action(); if (generation === this.generation) await this.load(); }
    catch (error) { if (generation === this.generation && !(error instanceof DOMException && error.name === 'AbortError')) this.error.set(error instanceof UsageApiError ? error.code : 'USAGE_REQUEST_FAILED'); }
    finally { if (generation <= this.generation) this.saving.set(false); }
  }
  private emptyTariff(): UsageTariffWrite { return { provider: '', model: '', currency: '', input_per_million: '', output_per_million: '', cached_input_per_million: '', cache_write_per_million: '' }; }
  ngOnDestroy(): void { this.generation++; this.controller?.abort(); this.resetters.forEach(reset => reset()); }
}
