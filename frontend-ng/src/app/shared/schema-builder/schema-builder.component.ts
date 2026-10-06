/**
 * `<ck-schema-builder>` — declare an input or output contract without writing
 * JSON, and keep writing JSON when the contract asks for more.
 *
 * The schema object is the model, not the rows: every edit goes through
 * {@link applyFields}, which rebuilds `properties` and `required` and leaves
 * every other key of the stored schema untouched. So the two tabs are one
 * document seen twice, and switching between them loses nothing.
 *
 * When the schema uses a construct no row can hold (`$ref`, `oneOf`, a third
 * nesting level…), the rows step aside and name the reason instead of
 * flattening it. That is the whole bargain: JSON stops being mandatory, it
 * does not stop being available.
 *
 * Edits commit on `change` (blur), never per keystroke — a half-typed field
 * name is not a contract, and re-keying `properties` on every character would
 * make the form fight the author.
 *
 * The keys are filed under `skills.` because this builder is the contract
 * editor of the Skill authoring surface; the Flow inspector reuses the
 * component, and reusing its wording with it is the point.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import type { I18nKey } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import {
  SCHEMA_FIELD_TYPES,
  type SchemaField,
  type SchemaFieldType,
  applyFields,
  blankField,
  projectSchema,
} from './schema-builder.vm';

type SchemaObject = Record<string, unknown>;

@Component({
  selector: 'ck-schema-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './schema-builder.component.scss',
  template: `
    <div class="ck-sb">
      @if (label(); as text) {
        <span class="ck-sb__label">{{ text }}</span>
      }
      @if (hint(); as text) {
        <p class="ck-sb__hint">{{ text }}</p>
      }

      <div class="ck-sb__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          class="ck-sb__tab"
          [class.ck-sb__tab--on]="tab() === 'fields'"
          [attr.aria-selected]="tab() === 'fields'"
          (click)="tab.set('fields')"
        >
          {{ i18n.t('skills.schema.tab.fields') }}
        </button>
        <button
          type="button"
          role="tab"
          class="ck-sb__tab"
          [class.ck-sb__tab--on]="tab() === 'json'"
          [attr.aria-selected]="tab() === 'json'"
          (click)="openJson()"
        >
          {{ i18n.t('skills.schema.tab.json') }}
        </button>
      </div>

      @if (tab() === 'fields') {
        @if (unsupported().length) {
          <div class="ck-sb__locked" role="note">
            <span class="ck-sb__locked-title">{{ i18n.t('skills.schema.locked.title') }}</span>
            <ul class="ck-sb__reasons">
              @for (reason of unsupported(); track reason) {
                <li>{{ reason }}</li>
              }
            </ul>
            <p class="ck-sb__hint">{{ i18n.t('skills.schema.locked.body') }}</p>
            <button type="button" class="ck-sb__btn" (click)="openJson()">
              {{ i18n.t('skills.schema.tab.json') }}
            </button>
          </div>
        } @else {
          @if (!fields().length) {
            <p class="ck-sb__hint">{{ i18n.t('skills.schema.empty') }}</p>
          }
          @for (field of fields(); track $index) {
            <div class="ck-sb__row">
              <div class="ck-sb__grid">
                <label class="ck-sb__cell">
                  <span class="ck-sb__cell-label">{{ i18n.t('skills.schema.field.name') }}</span>
                  <input
                    type="text"
                    class="ck-sb__input ck-mono"
                    [value]="field.name"
                    (change)="patch($index, { name: text($event) })"
                  />
                </label>
                <label class="ck-sb__cell">
                  <span class="ck-sb__cell-label">{{ i18n.t('skills.schema.field.type') }}</span>
                  <select
                    class="ck-sb__input ck-mono"
                    [value]="field.type"
                    (change)="patch($index, { type: type($event) })"
                  >
                    @for (option of types; track option) {
                      <option [value]="option">{{ typeLabel(option) }}</option>
                    }
                  </select>
                </label>
                <label class="ck-sb__cell ck-sb__cell--tight">
                  <span class="ck-sb__cell-label">{{ i18n.t('skills.schema.field.required') }}</span>
                  <input
                    type="checkbox"
                    class="ck-sb__check"
                    [checked]="field.required"
                    (change)="patch($index, { required: checked($event) })"
                  />
                </label>
                <button
                  type="button"
                  class="ck-sb__btn ck-sb__btn--danger"
                  (click)="removeField($index)"
                >
                  {{ i18n.t('skills.schema.remove') }}
                </button>
              </div>

              <div class="ck-sb__grid">
                <label class="ck-sb__cell ck-sb__cell--wide">
                  <span class="ck-sb__cell-label">
                    {{ i18n.t('skills.schema.field.description') }}
                  </span>
                  <input
                    type="text"
                    class="ck-sb__input"
                    [value]="field.description"
                    (change)="patch($index, { description: text($event) })"
                  />
                </label>
                <label class="ck-sb__cell">
                  <span class="ck-sb__cell-label">{{ i18n.t('skills.schema.field.default') }}</span>
                  <input
                    type="text"
                    class="ck-sb__input ck-mono"
                    [value]="field.defaultValue"
                    (change)="patch($index, { defaultValue: text($event) })"
                  />
                </label>
              </div>

              @if (field.type === 'array') {
                <div class="ck-sb__grid">
                  <label class="ck-sb__cell">
                    <span class="ck-sb__cell-label">{{ i18n.t('skills.schema.field.items') }}</span>
                    <select
                      class="ck-sb__input ck-mono"
                      [value]="field.itemType ?? ''"
                      (change)="patch($index, { itemType: itemType($event) })"
                    >
                      <option value=""></option>
                      @for (option of itemTypes; track option) {
                        <option [value]="option">{{ typeLabel(option) }}</option>
                      }
                    </select>
                  </label>
                  <label class="ck-sb__cell">
                    <span class="ck-sb__cell-label">
                      {{ i18n.t('skills.schema.field.exact_count') }}
                    </span>
                    <input
                      type="number"
                      min="0"
                      step="1"
                      class="ck-sb__input ck-mono"
                      [value]="field.exactCount ?? ''"
                      (change)="patch($index, { exactCount: exactCount($event) })"
                    />
                  </label>
                </div>
              }

              @if (field.type !== 'object') {
                <label class="ck-sb__cell ck-sb__cell--wide">
                  <span class="ck-sb__cell-label">{{ i18n.t('skills.schema.field.enum') }}</span>
                  <input
                    type="text"
                    class="ck-sb__input ck-mono"
                    [value]="field.enumValues.join(', ')"
                    (change)="patch($index, { enumValues: list($event) })"
                  />
                  <span class="ck-sb__hint">{{ i18n.t('skills.schema.field.enum.hint') }}</span>
                </label>
              }

              @if (field.type === 'object') {
                <div class="ck-sb__nest">
                  @for (child of field.children; track $index) {
                    <div class="ck-sb__grid">
                      <label class="ck-sb__cell">
                        <span class="ck-sb__cell-label">
                          {{ i18n.t('skills.schema.field.name') }}
                        </span>
                        <input
                          type="text"
                          class="ck-sb__input ck-mono"
                          [value]="child.name"
                          (change)="patchChild(field, $index, { name: text($event) })"
                        />
                      </label>
                      <label class="ck-sb__cell">
                        <span class="ck-sb__cell-label">
                          {{ i18n.t('skills.schema.field.type') }}
                        </span>
                        <select
                          class="ck-sb__input ck-mono"
                          [value]="child.type"
                          (change)="patchChild(field, $index, { type: type($event) })"
                        >
                          @for (option of childTypes; track option) {
                            <option [value]="option">{{ typeLabel(option) }}</option>
                          }
                        </select>
                      </label>
                      <label class="ck-sb__cell ck-sb__cell--tight">
                        <span class="ck-sb__cell-label">
                          {{ i18n.t('skills.schema.field.required') }}
                        </span>
                        <input
                          type="checkbox"
                          class="ck-sb__check"
                          [checked]="child.required"
                          (change)="patchChild(field, $index, { required: checked($event) })"
                        />
                      </label>
                      <button
                        type="button"
                        class="ck-sb__btn ck-sb__btn--danger"
                        (click)="removeChild(field, $index)"
                      >
                        {{ i18n.t('skills.schema.remove') }}
                      </button>
                    </div>
                  }
                  <button type="button" class="ck-sb__btn" (click)="addChild(field)">
                    {{ i18n.t('skills.schema.add_nested') }}
                  </button>
                </div>
              }
            </div>
          }
          <button type="button" class="ck-sb__btn" (click)="addField()">
            {{ i18n.t('skills.schema.add') }}
          </button>
        }
      } @else {
        <textarea
          class="ck-sb__editor ck-mono"
          rows="10"
          spellcheck="false"
          autocomplete="off"
          [attr.aria-label]="label() || i18n.t('skills.schema.tab.json')"
          [attr.aria-invalid]="jsonError() !== null"
          [value]="jsonText()"
          (change)="commitJson($event)"
        ></textarea>
        @if (jsonError(); as message) {
          <p class="ck-sb__hint ck-sb__hint--error" role="alert">{{ message }}</p>
        }
      }
    </div>
  `,
})
export class SchemaBuilderComponent {
  readonly i18n = inject(I18nService);

  /** The stored contract. `null` means "no contract declared". */
  readonly value = input<SchemaObject | null>(null);
  readonly label = input('');
  readonly hint = input<string | null>(null);

  /** Emitted on every committed edit; `null` when the author clears the JSON. */
  readonly valueChange = output<SchemaObject | null>();

  protected readonly types = SCHEMA_FIELD_TYPES;
  protected readonly childTypes = SCHEMA_FIELD_TYPES.filter((type) => type !== 'object');
  protected readonly itemTypes = ['string', 'number', 'integer', 'boolean'] as const;

  readonly tab = signal<'fields' | 'json'>('fields');
  /** Rejected text kept on screen so an invalid edit is never silently lost. */
  private readonly jsonDraft = signal<string | null>(null);
  readonly jsonError = signal<string | null>(null);

  private readonly projection = computed(() => projectSchema(this.value() ?? {}));
  readonly fields = computed(() => this.projection().fields);
  readonly unsupported = computed(() => this.projection().unsupported);

  readonly jsonText = computed(() => {
    const draft = this.jsonDraft();
    if (draft !== null) return draft;
    const value = this.value();
    return value ? JSON.stringify(value, null, 2) : '';
  });

  openJson(): void {
    this.tab.set('json');
  }

  addField(): void {
    this.commitFields([...this.fields(), blankField()]);
  }

  removeField(index: number): void {
    this.commitFields(this.fields().filter((_, position) => position !== index));
  }

  patch(index: number, change: Partial<SchemaField>): void {
    this.commitFields(
      this.fields().map((field, position) =>
        position === index ? { ...field, ...change } : field,
      ),
    );
  }

  addChild(parent: SchemaField): void {
    this.replaceChildren(parent, [...parent.children, blankField()]);
  }

  removeChild(parent: SchemaField, index: number): void {
    this.replaceChildren(
      parent,
      parent.children.filter((_, position) => position !== index),
    );
  }

  patchChild(parent: SchemaField, index: number, change: Partial<SchemaField>): void {
    this.replaceChildren(
      parent,
      parent.children.map((child, position) =>
        position === index ? { ...child, ...change } : child,
      ),
    );
  }

  commitJson(event: Event): void {
    const raw = (event.target as HTMLTextAreaElement).value;
    const trimmed = raw.trim();
    if (!trimmed) {
      this.jsonDraft.set(null);
      this.jsonError.set(null);
      this.valueChange.emit(null);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      this.jsonDraft.set(raw);
      this.jsonError.set(this.i18n.t('skills.schema.json.invalid'));
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      this.jsonDraft.set(raw);
      this.jsonError.set(this.i18n.t('skills.schema.json.not_object'));
      return;
    }
    this.jsonDraft.set(null);
    this.jsonError.set(null);
    this.valueChange.emit(parsed as SchemaObject);
  }

  typeLabel(type: string): string {
    const key = `skills.schema.type.${type}` as I18nKey;
    const label = this.i18n.t(key);
    return label === key ? type : label;
  }

  text(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  checked(event: Event): boolean {
    return (event.target as HTMLInputElement).checked;
  }

  type(event: Event): SchemaFieldType {
    return this.text(event) as SchemaFieldType;
  }

  itemType(event: Event): SchemaField['itemType'] {
    const value = this.text(event);
    return value ? (value as SchemaField['itemType']) : null;
  }

  exactCount(event: Event): number | null {
    const value = Number((event.target as HTMLInputElement).value);
    return Number.isInteger(value) && value >= 0 ? value : null;
  }

  list(event: Event): string[] {
    return this.text(event)
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean);
  }

  private replaceChildren(parent: SchemaField, children: SchemaField[]): void {
    this.commitFields(
      this.fields().map((field) => (field === parent ? { ...field, children } : field)),
    );
  }

  private commitFields(fields: readonly SchemaField[]): void {
    this.jsonDraft.set(null);
    this.jsonError.set(null);
    this.valueChange.emit(applyFields(this.value() ?? {}, fields));
  }
}
