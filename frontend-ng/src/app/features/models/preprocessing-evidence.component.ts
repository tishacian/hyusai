import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { fittedPreparation, preparationRows, preparationWidth, type PreprocessingEvidence } from './preprocessing-evidence.vm';

@Component({
  selector: 'ck-preprocessing-evidence', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ck-preparation" data-testid="preprocessing-evidence">
      <h3>{{ i18n.t('models.preparation.title') }}</h3>
      @if (record(); as value) {
        <p>{{ i18n.t('models.preparation.scope') }}</p>
        <p data-testid="preprocessing-counts">{{ i18n.t('models.preparation.counts', { inputs: value.input_count, retained: value.retained_count, excluded: value.excluded_count }) }}</p>
        @if (width() !== null) { <p>{{ i18n.t('models.preparation.width', { count: width()! }) }}</p> }
        <div class="ck-table-scroll"><table>
          <thead><tr><th>{{ i18n.t('models.preparation.column') }}</th><th>{{ i18n.t('models.preparation.result') }}</th><th>{{ i18n.t('models.preparation.operations') }}</th></tr></thead>
          <tbody>@for (column of rows(); track column.name) {
            <tr><th scope="row">{{ column.name }}</th>
              <td>{{ i18n.t(column.excluded ? 'models.preparation.excluded' : 'models.preparation.retained') }}
                @if (column.excluded) { <span> · {{ reason(column.reason) }}</span> }
              </td>
              <td>@for (operation of column.transformers; track $index) { <span class="ck-operation">{{ operationName(operation) }}</span> } @empty { <span>—</span> }</td>
            </tr>
          }</tbody>
        </table></div>
        @if (value.truncated) { <p>{{ i18n.t('models.preparation.truncated') }}</p> }
      } @else { <p data-testid="preprocessing-unavailable">{{ i18n.t('models.preparation.unavailable') }}</p> }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .ck-preparation { padding: 16px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; }
    h3 { font-size: 13px; color: var(--ck-fg-2); }
    p, table { font-size: 12px; line-height: 1.5; color: var(--ck-fg-3); }
    .ck-table-scroll { max-width: 100%; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 6px 8px; text-align: start; border-bottom: 1px solid var(--ck-stroke-2); overflow-wrap: anywhere; }
    .ck-operation { display: inline-block; margin-inline-end: 8px; }
  `],
})
export class PreprocessingEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly evidence = input<PreprocessingEvidence | null | undefined>();
  protected readonly record = computed(() => fittedPreparation(this.evidence()));
  protected readonly rows = computed(() => preparationRows(this.evidence()));
  protected readonly width = computed(() => preparationWidth(this.evidence()));
  protected operationName(value: string): string { return value.split('.').at(-1) || value; }
  protected reason(value: string | null): string {
    return this.i18n.t('models.preparation.reason.' + (['constant', 'all_missing', 'uninformative'].includes(value ?? '') ? value : 'unknown'));
  }
}
