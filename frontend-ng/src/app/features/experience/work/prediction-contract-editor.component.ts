import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { predictionContract } from './prediction-contract';

@Component({
  selector: 'xp-prediction-contract-editor', standalone: true, imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="prediction-editor">
      <label>{{ t('task') }}
        <select [ngModel]="fields()['task'] || 'classification'" (ngModelChange)="task($event)">
          @for (kind of tasks; track kind) { <option [value]="kind">{{ t(kind) }}</option> }
        </select>
      </label>
      @for (key of textFields(); track key) {
        <label>{{ t(key) }}<input type="text" [ngModel]="fields()[key] || ''" (ngModelChange)="update(key, $event)" /></label>
      }
      <div class="prediction-editor__pair">
        @for (key of numericFields; track key) {
          <label>{{ t(key) }}<input type="number" min="1" step="1" [ngModel]="fields()[key]" (ngModelChange)="update(key, $event)" /></label>
        }
      </div>
      @if (fields()['task'] !== 'clustering') {
        <label>{{ t('order') }}<select [ngModel]="fields()['order'] || 'none'" (ngModelChange)="update('order', $event)">
          @for (direction of directions; track direction) { <option [value]="direction">{{ t(direction) }}</option> }
        </select></label>
        <fieldset><legend>{{ t('bands') }}</legend>
          @for (band of bands(); track $index; let index = $index) {
            <div class="prediction-editor__band">
              <label>{{ t('band_key') }}<input [ngModel]="band['key']" (ngModelChange)="bandValue(index, 'key', $event)" /></label>
              <label>{{ t('band_label') }}<input [ngModel]="band['label']" (ngModelChange)="bandValue(index, 'label', $event)" /></label>
              <label>{{ t('band_min') }}<input type="number" step="any" [ngModel]="band['min']" (ngModelChange)="bandValue(index, 'min', $event)" /></label>
              <button type="button" class="ck-btn ck-btn--sm" (click)="removeBand(index)" [attr.aria-label]="t('remove_band')">×</button>
            </div>
          }
          <button type="button" class="ck-btn ck-btn--sm" [disabled]="bands().length >= 12" (click)="addBand()">{{ t('add_band') }}</button>
          <p>{{ t('bands_hint') }}</p>
        </fieldset>
      }
      @if (!valid()) { <p role="status">{{ t('invalid') }}</p> }
    </div>
  `,
  styles: [`
    .prediction-editor { display: grid; gap: 12px; min-width: 0; }
    label { display: grid; gap: 4px; font-size: 12px; color: var(--ck-fg-2); min-width: 0; }
    input, select { width: 100%; min-width: 0; box-sizing: border-box; background: var(--ck-bg-panel); color: var(--ck-fg-1); border: 1px solid var(--ck-stroke-2); border-radius: 4px; padding: 6px 8px; font: inherit; }
    input:focus, select:focus { outline: 2px solid var(--ck-primary); outline-offset: 1px; }
    .prediction-editor__pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    fieldset { margin: 0; padding: 10px; border: 1px solid var(--ck-stroke-2); min-width: 0; }
    legend, p { color: var(--ck-fg-2); font-size: 12px; line-height: 1.5; }
    .prediction-editor__band { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; margin-bottom: 8px; }
    .prediction-editor__band button { justify-self: end; align-self: end; }
  `],
})
export class PredictionContractEditorComponent {
  readonly value = input<unknown>();
  readonly changed = output<Record<string, unknown>>();
  readonly i18n = inject(I18nService);
  readonly tasks = ['classification', 'regression', 'clustering'];
  readonly directions = ['none', 'descending', 'ascending'];
  readonly numericFields = ['model_version', 'max_age_seconds'];
  readonly fields = computed<Record<string, unknown>>(() => {
    const value = this.value();
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {
      schema_version: 1, task: 'classification', model_version: 1, max_age_seconds: 3600,
      value_column: 'prediction', score_column: 'score', unit: 'probability', order: 'none', bands: [],
    };
  });
  readonly valid = computed(() => !!predictionContract(this.fields()));
  readonly bands = computed<Record<string, unknown>[]>(() => Array.isArray(this.fields()['bands']) ? this.fields()['bands'] as Record<string, unknown>[] : []);
  readonly textFields = computed(() => [
    'label', 'model_id', ...(this.fields()['task'] === 'clustering' ? [] : ['target']), 'value_column',
    ...(this.fields()['task'] === 'classification' ? ['positive_label', 'score_column'] : []),
    ...(this.fields()['task'] === 'regression' ? ['unit', 'lower_column', 'upper_column'] : []),
  ]);
  t(key: string): string { return this.i18n.t('experience.prediction.' + key); }
  update(key: string, value: unknown): void { this.changed.emit({ ...this.fields(), [key]: value }); }
  task(task: string): void {
    const next = { ...this.fields(), task, bands: [], order: 'none', unit: task === 'classification' ? 'probability' : task === 'clustering' ? 'segment' : '' };
    for (const key of ['positive_label', 'score_column', 'lower_column', 'upper_column']) delete (next as Record<string, unknown>)[key];
    if (task === 'classification') Object.assign(next, { score_column: 'score', positive_label: '' });
    if (task === 'clustering') delete (next as Record<string, unknown>)['target'];
    this.changed.emit(next);
  }
  bandValue(index: number, key: string, value: unknown): void {
    this.update('bands', this.bands().map((band, i) => i === index ? { ...band, [key]: value } : band));
  }
  addBand(): void { this.update('bands', [...this.bands(), { key: '', label: '', min: 0 }]); }
  removeBand(index: number): void { this.update('bands', this.bands().filter((_, i) => i !== index)); }
}
