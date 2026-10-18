/**
 * "What would change the answer?" on the Play tab.
 *
 * The person picks one to three fields they can act on and, for a regression,
 * the range they want; the server searches the fewest and nearest changes to
 * those fields, drawn from the training contract, and returns at most a few.
 * The panel scores the row currently in the form, so a "what if" always starts
 * from the answer just shown. Nothing it sends is stored.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ModelsService } from './models.service';
import type { ModelTask, SignatureField } from './models.vm';
import {
  MAX_COUNTERFACTUAL_FIELDS,
  counterfactualRequest,
  counterfactualRows,
  counterfactualStatusKey,
  refusalReasonKey,
  searchableFields,
  toggleField,
  type CounterfactualAnswer,
} from './explanations.vm';

@Component({
  selector: 'ck-counterfactual-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ck-panel mt-3" data-testid="counterfactual-panel">
      <div class="ck-section-label">{{ i18n.t('models.play.cf.title') }}</div>
      <p class="ck-hint">{{ i18n.t('models.play.cf.hint', { max: max }) }}</p>
      <div class="ck-cf__fields" role="group" [attr.aria-label]="i18n.t('models.play.cf.fields')">
        @for (field of searchable(); track field.name) {
          <label class="ck-cf__field" [class.ck-cf__field--off]="!field.usable"
            [attr.title]="field.usable ? null : i18n.t(refusalKey(field.reason ?? 'no_alternative'))">
            <input
              type="checkbox"
              [checked]="selected().includes(field.name)"
              [disabled]="!field.usable || busy() || (!selected().includes(field.name) && selected().length >= max)"
              (change)="toggle(field.name)"
            />
            <span class="ck-mono">{{ field.name }}</span>
          </label>
        }
      </div>
      <div class="ck-cf__target">
        @if (task() === 'regression') {
          <label class="ck-field">
            <span class="ck-field__name">{{ i18n.t('models.play.cf.min') }}</span>
            <input class="ck-field__input" type="number" [value]="min()" (input)="min.set($any($event.target).value)" />
          </label>
          <label class="ck-field">
            <span class="ck-field__name">{{ i18n.t('models.play.cf.max') }}</span>
            <input class="ck-field__input" type="number" [value]="maxValue()" (input)="maxValue.set($any($event.target).value)" />
          </label>
        } @else {
          <label class="ck-field">
            <span class="ck-field__name">{{ i18n.t('models.play.cf.class') }}</span>
            <select class="ck-field__input" [value]="targetClass()" (change)="targetClass.set($any($event.target).value)">
              <option value="">{{ i18n.t('models.play.cf.class.any') }}</option>
              @for (label of classes(); track label) { <option [value]="label">{{ label }}</option> }
            </select>
          </label>
        }
        <button type="button" class="ck-btn-soft" data-testid="counterfactual-search"
          [disabled]="busy() || !selected().length" (click)="search()">
          {{ i18n.t(busy() ? 'models.play.cf.searching' : 'models.play.cf.search') }}
        </button>
      </div>
      @if (error()) { <p class="ck-hint ck-cf__error" data-testid="counterfactual-error">{{ i18n.t(error()) }}</p> }
      @if (answer(); as found) {
        <p class="ck-hint" data-testid="counterfactual-status">
          {{ i18n.t(statusKey(found)) }}
          · {{ i18n.t('models.play.cf.evaluated', { count: found.evaluated, budget: found.budget }) }}
          @if (found.exhausted) { · {{ i18n.t('models.play.cf.exhausted') }} }
        </p>
        @for (item of found.refused; track item.field) {
          <p class="ck-hint">{{ item.field }} — {{ i18n.t(refusalKey(item.reason)) }}</p>
        }
        @if (rows().length) {
          <div class="ck-cf__table"><table data-testid="counterfactual-results">
            <thead><tr>
              <th>#</th><th>{{ i18n.t('models.play.cf.changes') }}</th>
              <th>{{ i18n.t('models.play.cf.answer') }}</th>
              @if (task() !== 'regression') { <th>{{ i18n.t('models.play.cf.probability') }}</th> }
              <th>{{ i18n.t('models.play.cf.distance') }}</th>
            </tr></thead>
            <tbody>@for (row of rows(); track row.rank) {
              <tr>
                <td>{{ row.rank }}</td>
                <td>@for (change of row.changes; track change.field) {
                  <div class="ck-mono">{{ change.field }}: {{ change.from }} → {{ change.to }}</div>
                }</td>
                <td class="ck-mono">{{ row.answer }}</td>
                @if (task() !== 'regression') { <td class="ck-mono">{{ row.probability ?? '—' }}</td> }
                <td class="ck-mono">{{ row.distance }}</td>
              </tr>
            }</tbody>
          </table></div>
          <p class="ck-hint">{{ i18n.t('models.play.cf.footnote') }}</p>
        }
      }
    </section>
  `,
  styles: [`
    .ck-section-label { color: var(--ck-fg-2); font-size: 12px; }
    .ck-hint { color: var(--ck-fg-4); font-size: 11px; line-height: 1.5; margin: 6px 0; }
    .ck-cf__fields { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 10px 0; }
    .ck-cf__field { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ck-fg-2); }
    .ck-cf__field--off { color: var(--ck-fg-4); }
    .ck-cf__target { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
    .ck-cf__error { color: var(--ck-fg-2); }
    .ck-cf__table { overflow-x: auto; margin-top: 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 11.5px; color: var(--ck-fg-2); }
    th, td { text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--ck-stroke-2); vertical-align: top; font-variant-numeric: tabular-nums; }
    th { font-weight: 400; color: var(--ck-fg-3); }
  `],
})
export class CounterfactualPanelComponent {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);

  readonly modelId = input.required<string>();
  readonly task = input.required<ModelTask>();
  readonly fields = input.required<SignatureField[]>();
  readonly classes = input<string[]>([]);
  /** The row in the form right now, typed like the predict request. */
  readonly row = input.required<Record<string, unknown>>();
  readonly version = input<number | null>(null);

  protected readonly max = MAX_COUNTERFACTUAL_FIELDS;
  readonly selected = signal<string[]>([]);
  readonly targetClass = signal('');
  readonly min = signal('');
  readonly maxValue = signal('');
  readonly busy = signal(false);
  readonly error = signal('');
  readonly answer = signal<CounterfactualAnswer | null>(null);
  protected readonly searchable = computed(() => searchableFields(this.fields()));
  protected readonly rows = computed(() => counterfactualRows(this.answer(), this.i18n.locale()));
  protected readonly statusKey = counterfactualStatusKey;
  protected readonly refusalKey = refusalReasonKey;
  private generation = 0;

  constructor() {
    // A new version or workspace starts the question over.
    effect(() => {
      this.modelId();
      this.workspace.current()?.id;
      untracked(() => this.clear());
    });
    this.destroy.onDestroy(() => { this.generation++; });
  }

  toggle(name: string): void {
    this.selected.set(toggleField(this.selected(), name));
  }

  async search(): Promise<void> {
    if (this.busy()) return;
    const built = counterfactualRequest(
      this.row(),
      this.selected(),
      this.task(),
      { class: this.targetClass(), min: this.min(), max: this.maxValue() },
      this.version(),
    );
    if ('error' in built) {
      this.error.set(built.error);
      return;
    }
    const id = this.modelId(), generation = ++this.generation;
    const scope = this.workspace.captureRequestScope();
    const current = () =>
      generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
    this.busy.set(true);
    this.error.set('');
    try {
      const answer = await this.models.counterfactuals(id, built.body);
      if (current()) this.answer.set(answer);
    } catch (failure) {
      if (current()) {
        this.answer.set(null);
        this.error.set(errorKey(failure));
      }
    } finally {
      if (current()) this.busy.set(false);
    }
  }

  private clear(): void {
    this.generation++;
    this.selected.set([]);
    this.targetClass.set('');
    this.min.set('');
    this.maxValue.set('');
    this.busy.set(false);
    this.error.set('');
    this.answer.set(null);
  }
}

export function errorKey(failure: unknown): string {
  const code = failure instanceof HttpErrorResponse ? String(failure.error?.detail?.code ?? '') : '';
  const known: Record<string, string> = {
    ML_COUNTERFACTUAL_FIELDS_UNSUPPORTED: 'models.play.cf.error.unsupported',
    ML_COUNTERFACTUAL_UNSUPPORTED: 'models.play.cf.error.unsupported',
    ML_COUNTERFACTUAL_TARGET_INVALID: 'models.play.cf.error.target',
    ML_RATE_LIMITED: 'models.play.cf.error.rate',
    ML_FORBIDDEN_ACTION: 'models.play.cf.error.forbidden',
  };
  return known[code] ?? 'models.play.cf.error.failed';
}
