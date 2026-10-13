import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { firstValueFrom } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { SecretsApi, isValidSecretName, secretErrorCode } from '@app/shared/secrets/secrets.api';
import { DataOpsApi } from './dataops.api';

import { functions, prepFields, prepFieldDefault, prepNumber, prepParamChange, prepStepParamChange, hashSaltOptions } from './prep-fields';

@Component({
  selector: 'app-prep-params', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './dataops-editor.scss',
  template: `
    <div class="dp-grid">
      @for (field of fields(); track field.key) {
        <label class="dp-field"><span>{{ i18n.t('dataops.param.' + field.key) }}</span>
          @switch (field.kind) {
            @case ('column') { <select class="dp-input" [value]="string(field.key)" (change)="set(field.key, val($event) || undefined)"><option value="">{{ i18n.t('dataops.choose') }}</option>@for (col of columns(); track col) { <option [value]="col">{{ col }}</option> }</select> }
            @case ('columns') { <select class="dp-input" multiple [attr.aria-label]="i18n.t('dataops.param.' + field.key)" (change)="set(field.key, selected($event))">@for (col of columns(); track col) { <option [value]="col" [selected]="includes(field.key, col)">{{ col }}</option> }</select> }
            @case ('select') { <select class="dp-input" [value]="string(field.key)" (change)="set(field.key, val($event) || undefined)"><option value="">{{ i18n.t('dataops.choose') }}</option>@for (option of field.options; track option) { <option [value]="option">{{ option }}</option> }</select> }
            @case ('secret') { <select class="dp-input" [value]="string(field.key)" (change)="set(field.key,val($event) || undefined)"><option value="">{{i18n.t('dataops.choose')}}</option>@for (secret of secrets(); track secret.ref) { <option [value]="secret.ref">{{secret.name}} · v{{secret.version}}</option> }</select>@if (secretError()) { <small class="dp-error">{{i18n.t('dataops.error.load')}}</small> } }
            @case ('boolean') { <input type="checkbox" [checked]="value(field.key) === true" [disabled]="kind() === 'replace_values' && field.key === 'normalize_accents' && string('match') !== 'exact'" (change)="set(field.key, checked($event))" /> }
            @case ('number') { <input class="dp-input" type="number" [value]="value(field.key) ?? ''" [attr.min]="field.min ?? null" [attr.max]="field.max ?? null" [attr.step]="field.integer === false ? 'any' : 1" (input)="set(field.key, number($event))" /> }
            @case ('collection') { <div>@for (row of rows(field.key); track $index; let n=$index) {
              <div class="dp-grid">@for (child of field.children; track child.key) {
                <label class="dp-field"><span>{{ i18n.t('dataops.param.'+child.key) }}</span>
                @if (child.kind === 'column' || child.kind === 'select') {
                  <select class="dp-input" [value]="row[child.key] ?? ''" (change)="rowSet(field.key,n,child.key,val($event) || undefined)"><option value="">{{i18n.t('dataops.choose')}}</option>@for (option of child.kind === 'column' ? columns() : child.options; track option) { <option [value]="option">{{option}}</option> }</select>
                } @else if (child.kind === 'literal') {
                  <select class="dp-input" [value]="valueType(row[child.key])" (change)="rowSet(field.key,n,child.key,emptyLiteral(val($event)))">@for (type of literalTypes;track type) { <option [value]="type">{{i18n.t('dataops.literal.'+type)}}</option> }</select>
                  @if (valueType(row[child.key]) === 'boolean') { <input type="checkbox" [checked]="row[child.key] === true" (change)="rowSet(field.key,n,child.key,checked($event))" /> }
                  @else if (valueType(row[child.key]) !== 'null') { <input class="dp-input" [type]="valueType(row[child.key]) === 'number' ? 'number' : 'text'" [value]="row[child.key] ?? ''" (input)="rowSet(field.key,n,child.key,valueType(row[child.key]) === 'number' ? number($event) : val($event))" /> }
                } @else { <input class="dp-input" [type]="child.kind === 'number' ? 'number':'text'" [value]="row[child.key] ?? ''" (input)="rowSet(field.key,n,child.key,child.kind === 'number' ? number($event) : val($event))" /> }
                </label>
              }<button type="button" class="dp-button" (click)="removeRow(field.key,n)">{{i18n.t('dataops.remove')}}</button></div>
            }<button type="button" class="dp-button" [disabled]="rows(field.key).length >= 1000" (click)="addRow(field.key,{})">{{i18n.t('dataops.add_item')}}</button></div> }
            @case ('literals') { <div>@for (item of literals(field.key); track $index; let n=$index) {
              <div class="dp-row"><select class="dp-input" [value]="valueType(item)" (change)="literalListSet(field.key,n,emptyLiteral(val($event)))">@for (type of literalTypes;track type) { <option [value]="type">{{i18n.t('dataops.literal.'+type)}}</option> }</select>
              @if (valueType(item) === 'boolean') { <input type="checkbox" [checked]="item === true" (change)="literalListSet(field.key,n,checked($event))" /> }
              @else if (item !== null) { <input class="dp-input" [type]="valueType(item) === 'number' ? 'number' : 'text'" [value]="item ?? ''" (input)="literalListSet(field.key,n,valueType(item) === 'number' ? number($event) : val($event))" /> }
              <button type="button" class="dp-button" (click)="removeLiteral(field.key,n)">{{i18n.t('dataops.remove')}}</button></div>
            }<button type="button" class="dp-button" [disabled]="literals(field.key).length >= 100" (click)="set(field.key, literals(field.key).concat(['']))">{{i18n.t('dataops.add_item')}}</button></div> }
            @case ('options') { <select class="dp-input" multiple (change)="set(field.key,selected($event))">@for (option of field.options; track option) { <option [value]="option" [selected]="includes(field.key,option)">{{option}}</option> }</select> }
            @case ('numbers') { <textarea class="dp-input" [value]="list(field.key)" (change)="setNumbers(field.key,val($event))"></textarea> }
            @case ('list') { <textarea class="dp-input" rows="3" [value]="list(field.key)" (change)="set(field.key, val($event).split('\n').filter(nonempty))"></textarea><small class="dp-note">{{ i18n.t('dataops.one_per_line') }}</small> }
            @case ('literal') { <select class="dp-input" [value]="literalType(field.key)" (change)="literalKind(field.key, val($event))">@for (type of literalTypes; track type) { <option [value]="type">{{ i18n.t('dataops.literal.' + type) }}</option> }</select>@if (literalType(field.key) === 'boolean') { <input type="checkbox" [checked]="value(field.key) === true" [disabled]="kind() === 'replace_values' && field.key === 'normalize_accents' && string('match') !== 'exact'" (change)="set(field.key, checked($event))" /> } @else if (literalType(field.key) !== 'null') { <input class="dp-input" [type]="literalType(field.key) === 'number' ? 'number' : 'text'" [value]="string(field.key)" (input)="set(field.key, literalType(field.key) === 'number' ? number($event) : val($event))" /> } }
            @default { <input class="dp-input" [value]="string(field.key)" (input)="set(field.key, val($event))" /> }
          }
        </label>
      }
    </div>
    @if (kind() === 'hash' && workspace.isAdmin()) { <div class="dp-row"><label class="dp-field"><span>{{i18n.t('dataops.salt_name')}}</span><input class="dp-input" maxlength="120" [value]="saltName()" (input)="saltName.set(val($event))" /></label><button type="button" class="dp-button" [disabled]="!canCreateSalt()" (click)="createSalt()">{{i18n.t('dataops.create_salt')}}</button></div><p class="dp-note">{{i18n.t('dataops.salt_hint')}}</p>@if (saltError()) { <p class="dp-error" role="alert">{{i18n.t(saltError())}}</p> } }
    @if (kind() === 'filter' || kind() === 'derive' || kind() === 'formula' || kind() === 'filter_expression') { <div class="dp-row"><button type="button" class="dp-button" [disabled]="validating() || !string('expression').trim()" (click)="validate()">{{ i18n.t('dataops.validate_expression') }}</button>@if (expressionResult(); as result) { <span role="status" class="dp-note">{{ i18n.t(result) }}</span> }</div> }
    @if (kind() === 'join') {
      @for (pair of rows('keys'); track $index; let n = $index) {
        <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.left_key') }}</span><select class="dp-input" [value]="pair['left']" (change)="rowSet('keys', n, 'left', val($event))"><option value="">{{ i18n.t('dataops.choose') }}</option>@for (col of columns(); track col) { <option [value]="col">{{ col }}</option> }</select></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.right_key') }}</span><select class="dp-input" [value]="pair['right']" (change)="rowSet('keys', n, 'right', val($event))"><option value="">{{ i18n.t('dataops.choose') }}</option>@for (col of rightColumns(); track col) { <option [value]="col">{{ col }}</option> }</select></label>
        <button type="button" class="dp-button" (click)="removeRow('keys', n)">{{ i18n.t('dataops.remove') }}</button></div>
      }
      <button type="button" class="dp-button" (click)="addRow('keys', {left: '', right: ''})">{{ i18n.t('dataops.add_key') }}</button>
    }
    @if (kind() === 'aggregate') {
      @for (item of rows('aggregates'); track $index; let n = $index) {
        <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.param.function') }}</span><select class="dp-input" [value]="item['function']" (change)="rowSet('aggregates', n, 'function', val($event))">@for (fn of functions; track fn) { <option [value]="fn">{{ fn }}</option> }</select></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.param.column') }}</span><select class="dp-input" [value]="item['column'] ?? ''" (change)="rowSet('aggregates', n, 'column', val($event) || null)"><option value="">{{ i18n.t('dataops.all_rows') }}</option>@for (col of columns(); track col) { <option [value]="col">{{ col }}</option> }</select></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.param.name') }}</span><input class="dp-input" [value]="item['name']" (input)="rowSet('aggregates', n, 'name', val($event))" /></label>
        <button type="button" class="dp-button" (click)="removeRow('aggregates', n)">{{ i18n.t('dataops.remove') }}</button></div>
      }
      <button type="button" class="dp-button" (click)="addRow('aggregates', {function: 'count', column: null, name: ''})">{{ i18n.t('dataops.add_aggregate') }}</button>
    }
    @if (kind() === 'rename' || kind() === 'rename_columns') {
      @for (entry of mapping(); track $index; let n = $index) {
        <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.param.column') }}</span><select class="dp-input" [value]="entry[0]" (change)="mapChange(n, 0, val($event))"><option value="" [disabled]="mappedElsewhere('',n)">{{ i18n.t('dataops.choose') }}</option>@for (col of columns(); track col) { <option [value]="col" [disabled]="mappedElsewhere(col,n)">{{ col }}</option> }</select></label>
        <label class="dp-field"><span>{{ i18n.t('dataops.param.name') }}</span><input class="dp-input" maxlength="256" [value]="entry[1]" (input)="mapChange(n, 1, val($event))" /></label><button type="button" class="dp-button" (click)="removeMapping(n)">{{i18n.t('dataops.remove')}}</button></div>
      }
      <button type="button" class="dp-button" [disabled]="mapping().some(emptyMapping)" (click)="addMapping()">{{ i18n.t('dataops.add_rename') }}</button>
    }
  `,
})
export class PrepParamsComponent {
  readonly i18n = inject(I18nService);
  private readonly secretApi = inject(SecretsApi); readonly workspace = inject(WorkspaceService);
  readonly secrets = signal<Array<{name:string; ref:string; version:number}>>([]); readonly secretError = signal(false);
  constructor() { effect(() => { this.workspace.currentSlug(); this.workspace.contextEpoch(); if (this.kind() === 'hash') void this.loadSecrets(); }); }
  private async loadSecrets(): Promise<void> {
    const scope = this.workspace.captureRequestScope(); this.secrets.set([]); this.secretError.set(false);
    try { const response = await firstValueFrom(this.secretApi.list({scope:'workspace'}));
      if (!this.workspace.isRequestScopeCurrent(scope)) return;
      this.secrets.set(hashSaltOptions(response.secrets));
    } catch { if (this.workspace.isRequestScopeCurrent(scope)) this.secretError.set(true); }
  }
  readonly saltName = signal(''); readonly saltSaving = signal(false); readonly saltError = signal('');
  canCreateSalt(): boolean { return this.workspace.isAdmin() && isValidSecretName(this.saltName()) && !this.saltSaving(); }
  async createSalt(): Promise<void> {
    if (!this.canCreateSalt()) return;
    this.saltSaving.set(true); this.saltError.set('');
    try { const secret = await this.api.createHashSalt(this.saltName()); const options = hashSaltOptions([secret]); const current = options.find(option => option.version === secret.current_version);
      if (!current) throw new Error('invalid salt metadata'); this.secrets.update(values => [...values,...options]); this.set('salt_secret_ref',current.ref); this.saltName.set('');
    } catch (error) { const code = secretErrorCode(error); const key = code ? 'resources.secrets.error.'+code.toLowerCase() : 'resources.secrets.error.unknown'; this.saltError.set(this.i18n.t(key) === key ? 'resources.secrets.error.unknown' : key); }
    finally { this.saltSaving.set(false); }
  }
  private readonly api = inject(DataOpsApi); readonly validating = signal(false); readonly validation = signal<{expression: string; message: string} | null>(null);
  readonly literalTypes = ['string', 'number', 'boolean', 'null'];
  readonly kind = input.required<string>(); readonly params = input.required<Record<string, unknown>>();
  readonly columns = input<string[]>([]); readonly rightColumns = input<string[]>([]);
  readonly paramsChange = output<Record<string, unknown>>(); readonly functions = functions;
  readonly fields = computed(() => prepFields(this.kind()));
  readonly expressionResult = computed(() => this.validation()?.expression === this.string('expression') ? this.validation()?.message : null);
  async validate(): Promise<void> { const expression = this.string('expression'); this.validating.set(true); try { const result = await this.api.validateExpression(expression, this.columns()); this.validation.set({expression, message: result.valid ? 'dataops.expression_valid' : 'dataops.error.expression'}); } catch { this.validation.set({expression, message: 'dataops.error.expression'}); } finally { this.validating.set(false); } }
  literalType(key: string): string { return this.params()[key] === null ? 'null' : typeof this.params()[key] === 'undefined' ? 'string' : typeof this.params()[key]; }
  literalKind(key: string, type: string): void { this.set(key, type === 'number' ? 0 : type === 'boolean' ? false : type === 'null' ? null : ''); }
  val(event: Event): string { return (event.target as HTMLInputElement).value; }
  checked(event: Event): boolean { return (event.target as HTMLInputElement).checked; }
  number(event: Event): number | undefined { return prepNumber(this.val(event)); }
  selected(event: Event): string[] { return Array.from((event.target as HTMLSelectElement).selectedOptions, option => option.value); }
  typeofValue(value:unknown):string { return typeof value==='undefined' ? 'string' : typeof value; }
  emptyLiteral(type:string):unknown { return type==='number' ? 0 : type==='boolean' ? false : type==='null' ? null : ''; }
  setNumbers(key: string, text: string): void { const values = text.split('\n').filter(this.nonempty).map(prepNumber); this.set(key, values.some(v => v === undefined) ? undefined : values); }
  valueType(value: unknown): string { return value === null ? 'null' : this.typeofValue(value); }
  literals(key: string): unknown[] { return Array.isArray(this.params()[key]) ? this.params()[key] as unknown[] : []; }
  literalListSet(key: string, index: number, value: unknown): void { this.set(key, this.literals(key).map((item,n) => n === index ? value : item)); }
  removeLiteral(key: string, index: number): void { this.set(key, this.literals(key).filter((_,n) => n !== index)); }
  nonempty(value: string): boolean { return !!value.trim(); }
  value(key: string): unknown { return this.params()[key] ?? prepFieldDefault(this.kind(), key); }
  string(key: string): string { return String(this.value(key) ?? ''); }
  list(key: string): string { return Array.isArray(this.value(key)) ? (this.value(key) as unknown[]).join('\n') : ''; }
  includes(key: string, value: string): boolean { return Array.isArray(this.params()[key]) && (this.params()[key] as string[]).includes(value); }
  set(key: string, value: unknown): void { this.paramsChange.emit(prepStepParamChange(this.kind(), this.params(), key, value)); }
  rows(key: string): Record<string, unknown>[] { return (this.params()[key] as Record<string, unknown>[] | undefined) ?? []; }
  rowSet(key: string, index: number, field: string, value: unknown): void { this.set(key, this.rows(key).map((row, n) => n === index ? prepParamChange(row, field, value) : row)); }
  addRow(key: string, row: Record<string, unknown>): void { this.set(key, [...this.rows(key), row]); }
  removeRow(key: string, index: number): void { this.set(key, this.rows(key).filter((_, n) => n !== index)); }
  mapping(): [string, string][] { const rows = Object.entries((this.params()['mapping'] ?? {}) as Record<string, string>); return rows.length ? rows : [['', '']]; }
  mappedElsewhere(value: string, index: number): boolean { return this.mapping().some((row,n) => n !== index && row[0] === value); }
  mapChange(index: number, field: 0 | 1, value: string): void { if (field === 0 && this.mappedElsewhere(value,index)) return; const rows = this.mapping(); rows[index][field] = value; this.set('mapping', Object.fromEntries(rows)); }
  removeMapping(index: number): void { this.set('mapping',Object.fromEntries(this.mapping().filter((_,n) => n !== index))); }
  emptyMapping(entry: [string, string]): boolean { return !entry[0] || !entry[1]; }
  addMapping(): void { this.set('mapping', {...Object.fromEntries(this.mapping()), '': ''}); }
}
