import { PrepFormulaComponent } from './prep-formula.component';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { firstValueFrom } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { SecretsApi, isValidSecretName, secretErrorCode } from '@app/shared/secrets/secrets.api';
import { DataOpsApi } from './dataops.api';

import { catalogPrepFields, type PrepStepDefinition, functions, prepFields, prepFieldDefault, prepNumber, prepParamChange, prepStepParamChange, prepRenameRows, PREP_SELECTOR_KINDS, hashSaltOptions } from './prep-fields';

@Component({
  selector: 'app-prep-params', standalone: true, imports: [PrepFormulaComponent], changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './dataops-editor.scss',
  template: `
    <div class="dp-grid">
      @for (field of fields(); track field.key) {
        <label class="dp-field"><span>{{ i18n.t(field.labelKey ?? 'dataops.param.' + field.key) }}</span>
          @switch (field.kind) {
            @case ('selector') {
              <select class="dp-input" [value]="selector(field.key)['mode']" (change)="selectorMode(field.key,val($event))">@for(mode of selectorModes;track mode){<option [value]="mode">{{i18n.t('dataops.selector.'+mode)}}</option>}</select>
              @if(selector(field.key)['mode']==='names'){<select multiple class="dp-input" (change)="selectorSet(field.key,'names',selected($event))">@for(col of columns();track col){<option [value]="col" [selected]="selectorIncludes(field.key,'names',col)">{{col}}</option>}</select>}
              @if(selector(field.key)['mode']==='pattern'){<input class="dp-input" [value]="selector(field.key)['regex']??''" (input)="selectorSet(field.key,'regex',val($event))" /><select class="dp-input" [value]="selector(field.key)['match']??'full'" (change)="selectorSet(field.key,'match',val($event))"><option value="full">{{i18n.t('dataops.match.full')}}</option><option value="contains">{{i18n.t('dataops.match.contains')}}</option></select>}
              @if(selector(field.key)['mode']==='kinds'){<select multiple class="dp-input" (change)="selectorSet(field.key,'kinds',selected($event))">@for(kind of columnKinds;track kind){<option [value]="kind" [selected]="selectorIncludes(field.key,'kinds',kind)">{{kind}}</option>}</select>}
              <small>{{i18n.t('dataops.exclude_columns')}}</small><select multiple class="dp-input" (change)="selectorSet(field.key,'exclude',selected($event))">@for(col of columns();track col){<option [value]="col" [selected]="selectorIncludes(field.key,'exclude',col)">{{col}}</option>}</select>
            }
            @case ('order') {
              @for(order of ordering(field.key);track $index;let n=$index){<div class="dp-row"><select class="dp-input" [value]="order['column']" (change)="orderSet(field.key,n,'column',val($event))"><option value=""></option>@for(col of columns();track col){<option [value]="col">{{col}}</option>}</select><select class="dp-input" [value]="order['direction']??'asc'" (change)="orderSet(field.key,n,'direction',val($event))"><option value="asc">{{i18n.t('dataops.order.asc')}}</option><option value="desc">{{i18n.t('dataops.order.desc')}}</option></select><select class="dp-input" [value]="order['nulls']??'last'" (change)="orderSet(field.key,n,'nulls',val($event))"><option value="first">{{i18n.t('dataops.order.nulls_first')}}</option><option value="last">{{i18n.t('dataops.order.nulls_last')}}</option></select><button class="dp-button" (click)="set(field.key,ordering(field.key).filter(notIndex(n)))">{{i18n.t('dataops.remove')}}</button></div>}
              <button class="dp-button" (click)="set(field.key,ordering(field.key).concat([{column:'',direction:'asc',nulls:'last'}]))">{{i18n.t('dataops.add_key')}}</button>
            }
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
                } @else if (child.kind === 'boolean') { <input type="checkbox" [checked]="row[child.key]===true" (change)="rowSet(field.key,n,child.key,checked($event))" />
                } @else if (child.kind === 'columns' || child.kind === 'order') {<select class="dp-input" multiple (change)="rowSet(field.key,n,child.key,selected($event))">@for(col of columns();track col){<option [value]="col" [selected]="arrayIncludes(row[child.key],col)">{{col}}</option>}</select>
                } @else if (child.kind === 'literals') { @for(item of literalValues(row[child.key]);track $index;let index=$index){<div class="dp-row"><select class="dp-input" [value]="valueType(item)" (change)="rowLiteralSet(field.key,n,child.key,index,emptyLiteral(val($event)))">@for(type of literalTypes;track type){<option [value]="type">{{i18n.t('dataops.literal.'+type)}}</option>}</select>@if(valueType(item)==='boolean'){<input type="checkbox" [checked]="item===true" (change)="rowLiteralSet(field.key,n,child.key,index,checked($event))" />}@else if(item!==null){<input class="dp-input" [type]="valueType(item)==='number'?'number':'text'" [value]="item??''" (input)="rowLiteralSet(field.key,n,child.key,index,valueType(item)==='number'?number($event):val($event))" />}<button class="dp-button" (click)="rowLiteralRemove(field.key,n,child.key,index)">{{i18n.t('dataops.remove')}}</button></div>}<button class="dp-button" [disabled]="literalValues(row[child.key]).length>=(child.maxItems??100)" (click)="rowSet(field.key,n,child.key,literalValues(row[child.key]).concat(['']))">{{i18n.t('dataops.add_item')}}</button>
                } @else if (child.key === 'when') { <app-prep-formula [value]="textValue(row[child.key])" [columns]="columns()" (valueChange)="rowSet(field.key,n,child.key,$event)" /> } @else { <input class="dp-input" [type]="child.kind === 'number' ? 'number':'text'" [value]="row[child.key] ?? ''" (input)="rowSet(field.key,n,child.key,child.kind === 'number' ? number($event) : val($event))" /> }
                </label>
              }<button type="button" class="dp-button" (click)="removeRow(field.key,n)">{{i18n.t('dataops.remove')}}</button></div>
            }<button type="button" class="dp-button" [disabled]="rows(field.key).length >= (field.maxItems ?? 1000)" (click)="addRow(field.key,{})">{{i18n.t('dataops.add_item')}}</button></div> }
            @case ('literals') { <div>@for (item of literals(field.key); track $index; let n=$index) {
              <div class="dp-row"><select class="dp-input" [value]="valueType(item)" (change)="literalListSet(field.key,n,emptyLiteral(val($event)))">@for (type of literalTypes;track type) { <option [value]="type">{{i18n.t('dataops.literal.'+type)}}</option> }</select>
              @if (valueType(item) === 'boolean') { <input type="checkbox" [checked]="item === true" (change)="literalListSet(field.key,n,checked($event))" /> }
              @else if (item !== null) { <input class="dp-input" [type]="valueType(item) === 'number' ? 'number' : 'text'" [value]="item ?? ''" (input)="literalListSet(field.key,n,valueType(item) === 'number' ? number($event) : val($event))" /> }
              <button type="button" class="dp-button" (click)="removeLiteral(field.key,n)">{{i18n.t('dataops.remove')}}</button></div>
            }<button type="button" class="dp-button" [disabled]="literals(field.key).length >= (field.maxItems ?? 100)" (click)="set(field.key, literals(field.key).concat(['']))">{{i18n.t('dataops.add_item')}}</button></div> }
            @case ('options') { <select class="dp-input" multiple (change)="set(field.key,selected($event))">@for (option of field.options; track option) { <option [value]="option" [selected]="includes(field.key,option)">{{option}}</option> }</select> }
            @case ('numbers') { <textarea class="dp-input" [value]="list(field.key)" (change)="setNumbers(field.key,val($event))"></textarea> }
            @case ('list') { <textarea class="dp-input" rows="3" [value]="list(field.key)" (change)="set(field.key, val($event).split('\n').filter(nonempty))"></textarea><small class="dp-note">{{ i18n.t('dataops.one_per_line') }}</small> }
            @case ('literal') { <select class="dp-input" [value]="literalType(field.key)" (change)="literalKind(field.key, val($event))">@for (type of literalTypes; track type) { <option [value]="type">{{ i18n.t('dataops.literal.' + type) }}</option> }</select>@if (literalType(field.key) === 'boolean') { <input type="checkbox" [checked]="value(field.key) === true" [disabled]="kind() === 'replace_values' && field.key === 'normalize_accents' && string('match') !== 'exact'" (change)="set(field.key, checked($event))" /> } @else if (literalType(field.key) !== 'null') { <input class="dp-input" [type]="literalType(field.key) === 'number' ? 'number' : 'text'" [value]="string(field.key)" (input)="set(field.key, literalType(field.key) === 'number' ? number($event) : val($event))" /> } }
            @default { @if (field.key === 'expression') { <app-prep-formula [value]="string(field.key)" [columns]="columns()" [schema]="schema()" [functions]="expressionFunctions()" (valueChange)="set(field.key,$event)" /> } @else { <input class="dp-input" [value]="string(field.key)" [attr.maxlength]="field.maxLength??4000" (input)="set(field.key, val($event))" /> } }
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
  readonly schema = input<Array<{name:string; dtype?:string}>>([]);
  textValue(value: unknown): string { return String(value ?? ''); }
  readonly columns = input<string[]>([]); readonly rightColumns = input<string[]>([]);
  readonly paramsChange = output<Record<string, unknown>>(); readonly functions = functions;
  readonly definition = input<PrepStepDefinition|null>(null); readonly expressionFunctions=input<string[]>([]);
  readonly fields = computed(() => this.definition()?catalogPrepFields(this.definition()!):prepFields(this.kind()));
  readonly selectorModes=['names','pattern','kinds','all'];readonly columnKinds=PREP_SELECTOR_KINDS;
  selector(key:string):Record<string,unknown>{const value=this.params()[key];return Array.isArray(value)?{mode:'names',names:value}:value&&typeof value==='object'?value as Record<string,unknown>:{mode:'names',names:[]};}
  selectorMode(key:string,mode:string):void{this.set(key,{mode,...(mode==='names'?{names:[]}:mode==='pattern'?{regex:'',match:'full'}:mode==='kinds'?{kinds:[]}:{}),...(this.selector(key)['exclude']?{exclude:this.selector(key)['exclude']}:{})});}
  selectorSet(key:string,field:string,value:unknown):void{this.set(key,{...this.selector(key),[field]:value});}
  selectorIncludes(key:string,field:string,value:string):boolean{return this.arrayIncludes(this.selector(key)[field],value);}
  arrayIncludes(value:unknown,item:string):boolean{return Array.isArray(value)&&value.includes(item);}arrayText(value:unknown):string{return Array.isArray(value)?value.join('\n'):'';}
  ordering(key:string):Record<string,unknown>[]{const rows=this.params()[key];return Array.isArray(rows)?rows.map(row=>typeof row==='string'?{column:row,direction:'asc',nulls:'last'}:row):[];}
  orderSet(key:string,index:number,field:string,value:unknown):void{this.set(key,this.ordering(key).map((row,n)=>n===index?{...row,[field]:value}:row));}
  notIndex(index:number):(row:unknown,n:number)=>boolean{return(_row,n)=>n!==index;}

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
  literalValues(value:unknown):unknown[]{return Array.isArray(value)?value:[];}
  rowLiteralSet(key:string,n:number,child:string,index:number,value:unknown):void{this.rowSet(key,n,child,this.literalValues(this.rows(key)[n][child]).map((item,i)=>i===index?value:item));}
  rowLiteralRemove(key:string,n:number,child:string,index:number):void{this.rowSet(key,n,child,this.literalValues(this.rows(key)[n][child]).filter((_,i)=>i!==index));}
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
  mapping(): [string, string][] { const rows = prepRenameRows(this.params()['mapping']); return rows.length ? rows : [['', '']]; }
  mappedElsewhere(value: string, index: number): boolean { return this.mapping().some((row,n) => n !== index && row[0] === value); }
  mapChange(index: number, field: 0 | 1, value: string): void { if (field === 0 && this.mappedElsewhere(value,index)) return; const rows = this.mapping(); rows[index][field] = value; this.set('mapping', Object.fromEntries(rows)); }
  removeMapping(index: number): void { this.set('mapping',Object.fromEntries(this.mapping().filter((_,n) => n !== index))); }
  emptyMapping(entry: [string, string]): boolean { return !entry[0] || !entry[1]; }
  addMapping(): void { this.set('mapping', {...Object.fromEntries(this.mapping()), '': ''}); }
}
