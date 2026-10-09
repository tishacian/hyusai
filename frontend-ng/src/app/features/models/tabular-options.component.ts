/** One catalog contract for tabular options in the studio and on a Flow node. */
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import type { ModelTask, PlanColumn, SpecFieldDescriptor } from './models.vm';
import { shownSpecFields, specColumns, specValues } from './tabular-options.vm';

@Component({
  selector: 'ck-tabular-options',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    @if (visibleFields().length) {
      <details class="ck-options" data-testid="tabular-options">
        <summary>{{ i18n.t('models.tabular.options') }}</summary>
        <div class="ck-options__fields">
          @if (textColumns().length) {
            <p class="ck-hint" data-testid="tabular-text-columns">{{ i18n.t('models.tabular.text_columns', { columns: textColumns().join(', ') }) }}</p>
          }
          @if (values()['text_encoder'] === 'embedding') {
            <p class="ck-hint" data-testid="embedding-scope">{{ i18n.t('models.embedding.scope') }}</p>
          }
          @for (field of visibleFields(); track field.key) {
            <div class="ck-field" [attr.data-spec-field]="field.key">
              <label class="ck-label" [for]="'tabular-' + field.key">{{ label(field.key) }}</label>
              @switch (field.kind) {
                @case ('enum') {
                  <select class="ck-input" [id]="'tabular-' + field.key" [ngModel]="values()[field.key]" (ngModelChange)="patch(field, $event)">
                    @for (choice of field.choices ?? []; track choice) {
                      <option [value]="choice">{{ label(field.key + '.' + choice, choice) }}</option>
                    }
                  </select>
                }
                @case ('bool') {
                  <input type="checkbox" [id]="'tabular-' + field.key" [ngModel]="values()[field.key]" (ngModelChange)="patch(field, $event)" />
                }
                @case ('column') {
                  <select class="ck-input" [id]="'tabular-' + field.key" [ngModel]="values()[field.key] ?? ''" (ngModelChange)="patch(field, $event)">
                    <option value="">—</option>
                    @for (column of candidates(field); track column.name) { <option [value]="column.name">{{ column.name }}</option> }
                  </select>
                }
                @case ('columns') {
                  <div class="ck-options__columns" role="group" [attr.aria-label]="label(field.key)">
                    @for (column of candidates(field); track column.name) {
                      <label class="ck-check">
                        <input type="checkbox" [checked]="selected(field, column.name)" [disabled]="full(field) && !selected(field, column.name)" (change)="toggleColumn(field, column.name)" />
                        {{ column.name }}
                      </label>
                    }
                    @for (name of unavailableSelections(field); track name) {
                      <div class="ck-field">
                        <span class="ck-hint">{{ i18n.t('models.tabular.unavailable_column', { column: name }) }}</span>
                        <button type="button" class="ck-input" (click)="toggleColumn(field, name)">{{ i18n.t('models.tabular.remove_column', { column: name }) }}</button>
                      </div>
                    }
                  </div>
                }
                @case ('column_roles') {
                  @for (column of candidates(field); track column.name) {
                    <label class="ck-check">{{ column.name }}
                      <select class="ck-input" [attr.aria-label]="label(field.key) + ': ' + column.name" [ngModel]="roles(field)[column.name] ?? ''" (ngModelChange)="setRole(field, column.name, $event)">
                        <option value="">—</option>
                        @for (choice of field.choices ?? []; track choice) { <option [value]="choice">{{ label(field.key + '.' + choice, choice) }}</option> }
                      </select>
                    </label>
                  }
                }
                @case ('int_list') {
                  <input class="ck-input" type="text" [id]="'tabular-' + field.key" [value]="listText(field)" (change)="onList(field, $event)" />
                }
                @default {
                  <input class="ck-input" type="number" [id]="'tabular-' + field.key" [min]="field.min ?? null" [max]="field.max ?? null" [step]="field.kind === 'int' ? 1 : 'any'" [ngModel]="values()[field.key]" (ngModelChange)="patch(field, $event)" />
                }
              }
              <div class="ck-hint">{{ hint(field) }}</div>
            </div>
          }
        </div>
      </details>
    }
    @if (refusal()) { <p class="ck-refusal" role="alert" data-testid="tabular-options-refusal">{{ refusal() }}</p> }
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .ck-options { border-top: 1px solid var(--ck-stroke-2); padding-top: 10px; }
    summary { cursor: pointer; font-size: 12px; color: var(--ck-fg-2); }
    .ck-options__fields { display: flex; flex-direction: column; gap: 14px; padding-top: 12px; }
    .ck-field { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
    .ck-label { font-size: 11px; color: var(--ck-fg-2); }
    .ck-hint { font-size: 10.5px; line-height: 1.45; color: var(--ck-fg-4); }
    .ck-input { width: 100%; padding: 7px 9px; font-size: 12px; border-radius: 4px; border: 1px solid var(--ck-stroke-2); background: var(--ck-bg-panel-hi); color: var(--ck-fg-1); }
    .ck-input:focus-visible, summary:focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 2px; }
    .ck-options__columns { display: flex; flex-wrap: wrap; gap: 8px; }
    .ck-check { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--ck-fg-2); }
    .ck-refusal { font-size: 11px; color: var(--ck-signal-neg); }
  `],
})
export class TabularOptionsComponent {
  readonly i18n = inject(I18nService);
  readonly fields = input<readonly SpecFieldDescriptor[]>([]);
  readonly spec = input<Record<string, unknown> | null>(null);
  readonly task = input.required<ModelTask>();
  readonly columns = input<readonly PlanColumn[]>([]);
  readonly target = input('');
  readonly refusal = input<string | null>(null);
  readonly specChange = output<Record<string, unknown>>();
  protected readonly textColumns = computed(() => this.columns()
    .filter((column) => column.role === 'text' && column.name !== this.target()).map((column) => column.name));
  protected readonly values = computed(() => specValues(this.fields(), this.spec(), this.task()));
  protected readonly visibleFields = computed(() => shownSpecFields(this.fields(), this.spec(), this.task()));

  protected label(key: string, fallback = key): string {
    const translated = this.i18n.t('models.spec.' + key);
    return translated === 'models.spec.' + key ? fallback.replaceAll('_', ' ') : translated;
  }
  protected hint(field: SpecFieldDescriptor): string {
    const key = 'models.spec.' + field.key + '.hint';
    const translated = this.i18n.t(key);
    return translated === key ? this.i18n.t('models.tabular.option.hint', { field: this.label(field.key) }) : translated;
  }
  protected candidates(field: SpecFieldDescriptor): PlanColumn[] { return specColumns(field, this.columns(), this.target()); }
  protected patch(field: SpecFieldDescriptor, value: unknown): void { this.specChange.emit({ ...this.spec(), [field.key]: value }); }
  protected unavailableSelections(field: SpecFieldDescriptor): string[] {
    const candidates = new Set(this.candidates(field).map((column) => column.name));
    return this.names(field).filter((name) => !candidates.has(name));
  }
  protected selected(field: SpecFieldDescriptor, name: string): boolean { return this.names(field).includes(name); }
  private names(field: SpecFieldDescriptor): string[] { const value = this.values()[field.key]; return Array.isArray(value) ? value : []; }
  protected full(field: SpecFieldDescriptor): boolean { return !!field.max_items && this.names(field).length >= field.max_items; }
  protected toggleColumn(field: SpecFieldDescriptor, name: string): void {
    const names = this.names(field);
    this.patch(field, names.includes(name) ? names.filter((item) => item !== name) : [...names, name]);
  }
  protected roles(field: SpecFieldDescriptor): Partial<Record<string, string>> { return (this.values()[field.key] ?? {}) as Partial<Record<string, string>>; }
  protected setRole(field: SpecFieldDescriptor, name: string, role: string): void {
    const roles = { ...this.roles(field) };
    if (role) roles[name] = role; else delete roles[name];
    this.patch(field, roles);
  }
  protected listText(field: SpecFieldDescriptor): string { const value = this.values()[field.key]; return Array.isArray(value) ? value.join(', ') : ''; }
  protected onList(field: SpecFieldDescriptor, event: Event): void {
    const value = (event.target as HTMLInputElement).value.trim();
    this.patch(field, value ? value.split(/[\s,]+/).map(Number) : []);
  }
}
