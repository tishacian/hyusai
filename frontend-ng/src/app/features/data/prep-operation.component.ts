import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { PrepParamsComponent } from './prep-params.component';
import { PrepFormulaComponent } from './prep-formula.component';
import { prepNumber, prepBindingSources, prepSplitConditionOutputs } from './prep-fields';
import type { PrepDraft } from './dataops.models';

@Component({selector: 'app-prep-operation', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PrepParamsComponent, PrepFormulaComponent], styleUrl: './dataops-editor.scss', template: `
  @switch (draft().spec.operation) {
    @case ('join') {
      <label class="dp-field"><span>{{i18n.t('dataops.param.how')}}</span><select class="dp-input" [value]="text('how','left')" (change)="set('how',val($event))">@for (how of joins; track how) { <option [value]="how">{{i18n.t('dataops.join.'+how)}}</option> }</select></label>
      <button type="button" class="dp-button" data-testid="prep-match-keys" (click)="matchKeys()">{{i18n.t('dataops.match_keys')}}</button>
      @for (pair of rows('on'); track $index; let n=$index) {
        <div class="dp-row"><label class="dp-field"><span>{{i18n.t('dataops.left_key')}}</span><select class="dp-input" [value]="pair['left'] ?? ''" (change)="rowSet('on',n,'left',val($event))"><option value=""></option>@for (col of columns();track col) {<option [value]="col">{{col}}</option>}</select></label>
        <label class="dp-field"><span>{{i18n.t('dataops.condition')}}</span><select class="dp-input" [value]="pair['op'] ?? 'eq'" (change)="rowSet('on',n,'op',val($event))">@for (op of operators;track op) {<option [value]="op">{{op}}</option>}</select></label>
        <label class="dp-field"><span>{{i18n.t('dataops.right_key')}}</span><select class="dp-input" [value]="pair['right'] ?? ''" (change)="rowSet('on',n,'right',val($event))"><option value=""></option>@for (col of rightColumns();track col) {<option [value]="col">{{col}}</option>}</select></label><button class="dp-button" (click)="removeRow('on',n)">{{i18n.t('dataops.remove')}}</button></div>
      }
      <button class="dp-button" (click)="addRow('on',{left:'',op:'eq',right:''})">{{i18n.t('dataops.add_key')}}</button>
      @if (!hasEquality()) {<p class="dp-error" role="status">{{i18n.t('dataops.join_no_equality')}}</p>}
      <label class="dp-check"><input type="checkbox" [checked]="params()['null_equal'] === true" (change)="set('null_equal',checked($event))" />{{i18n.t('dataops.null_equal')}}</label>
      <label class="dp-check"><input type="checkbox" [checked]="params()['merge_keys'] === true" (change)="set('merge_keys',checked($event))" />{{i18n.t('dataops.merge_keys')}}</label>
      @for (side of sides;track side) {<label class="dp-field"><span>{{i18n.t('dataops.select_side.'+side)}}</span><select multiple class="dp-input" (change)="nested('select',side,selected($event))">@for (col of side === 'left' ? columns() : rightColumns();track col) {<option [value]="col" [selected]="sideSelected(side,col)">{{col}}</option>}</select></label>}
      <label class="dp-field"><span>{{i18n.t('dataops.right_suffix')}}</span><input class="dp-input" [value]="nestedText('suffix','right','_right')" (input)="nested('suffix','right',val($event))" /></label>
    }
    @case ('union') {
      <label class="dp-field"><span>{{i18n.t('dataops.union_mode')}}</span><select class="dp-input" [value]="text('mode','by_name')" (change)="set('mode',val($event))">@for (mode of unionModes;track mode) {<option [value]="mode">{{i18n.t('dataops.union.'+mode)}}</option>}</select></label>
      <label class="dp-check"><input type="checkbox" [checked]="params()['allow_missing'] !== false" (change)="set('allow_missing',checked($event))" />{{i18n.t('dataops.allow_missing')}}</label>
      <label class="dp-check"><input type="checkbox" [checked]="params()['distinct'] === true" (change)="set('distinct',checked($event))" />{{i18n.t('dataops.param.distinct')}}</label>
      @if (text('mode','by_name') === 'bindings') {
        @for (binding of rows('bindings');track $index;let n=$index) {
          <label class="dp-field"><span>{{i18n.t('dataops.output_name')}}</span><input class="dp-input" [value]="binding['output']" (input)="rowSet('bindings',n,'output',val($event))" /></label>
          @for (port of ports();track port;let p=$index) {<label class="dp-field"><span>{{port}}</span><select class="dp-input" [value]="bindingSource(n,p)" (change)="setBinding(n,p,val($event))"><option value="">NULL</option>@for (col of portColumns()[port] ?? [];track col) {<option [value]="col">{{col}}</option>}</select></label>}
          <button class="dp-button" (click)="removeRow('bindings',n)">{{i18n.t('dataops.remove')}}</button>
        }
        <button class="dp-button" (click)="addRow('bindings',{output:'',sources:{}})">{{i18n.t('dataops.add_mapping')}}</button>
      }
      <table class="dp-mapping"><caption>{{i18n.t('dataops.column_mapping')}}</caption><thead><tr><th>{{i18n.t('dataops.param.column')}}</th>@for(port of ports();track port){<th>{{port}}</th>}</tr></thead><tbody>@for (column of unionColumns();track column) {<tr><th>{{column}}</th>@for(port of ports();track port){<td>{{unionSource(column,port)}}</td>}</tr>}</tbody></table>
      <p class="dp-note">{{i18n.t('dataops.union_types')}}</p>
    }
    @case ('aggregate') {
      <app-prep-params kind="aggregate_groups" [params]="params()" [columns]="columns()" (paramsChange)="paramsChange.emit($event)" />
      @for (aggregation of rows('aggregations');track $index;let n=$index) {
        <div class="dp-section"><label class="dp-field"><span>{{i18n.t('dataops.param.function')}}</span><select class="dp-input" [value]="aggregation['op']" (change)="rowSet('aggregations',n,'op',val($event))">@for(op of aggregates;track op){<option [value]="op">{{op}}</option>}</select></label>
        <label class="dp-field"><span>{{i18n.t('dataops.param.column')}}</span><select class="dp-input" [value]="aggregation['column'] ?? ''" (change)="rowSet('aggregations',n,'column',val($event) || undefined)"><option value="">{{i18n.t('dataops.all_rows')}}</option>@for(col of columns();track col){<option [value]="col">{{col}}</option>}</select></label>
        <label class="dp-field"><span>{{i18n.t('dataops.output_name')}}</span><input class="dp-input" [value]="aggregation['output']" (input)="rowSet('aggregations',n,'output',val($event))" /></label>
        @if (aggregation['op'] === 'quantile') {<label class="dp-field"><span>{{i18n.t('dataops.quantile')}}</span><input class="dp-input" type="number" min="0" max="1" step="0.01" [value]="aggregation['p'] ?? 0.5" (input)="rowSet('aggregations',n,'p',number($event))" /></label>}
        @if (aggregation['op'] === 'string_agg') {<label class="dp-field"><span>{{i18n.t('dataops.param.separator')}}</span><input class="dp-input" [value]="aggregation['sep'] ?? ','" (input)="rowSet('aggregations',n,'sep',val($event))" /></label>}
        @if (['first','last','string_agg'].includes(''+aggregation['op'])) {<label class="dp-field"><span>{{i18n.t('dataops.param.order_by')}}</span><select multiple class="dp-input" (change)="rowSet('aggregations',n,'order_by',selected($event))">@for(col of columns();track col){<option [value]="col" [selected]="includes(aggregation['order_by'],col)">{{col}}</option>}</select></label>}
        <button class="dp-button" (click)="removeRow('aggregations',n)">{{i18n.t('dataops.remove')}}</button></div>
      }
      <button class="dp-button" (click)="addRow('aggregations',{op:'count_rows',output:'count'})">{{i18n.t('dataops.add_aggregate')}}</button>
      <label class="dp-check"><input type="checkbox" [checked]="!!params()['pivot']" (change)="togglePivot(checked($event))" />{{i18n.t('dataops.operation.pivot')}}</label>
      @if (pivot();as pivot) {
        <app-prep-params kind="pivot_options" [params]="pivot" [columns]="columns()" (paramsChange)="set('pivot',$event)" />
        <button class="dp-button" [disabled]="!pivot['column']" (click)="suggestPivot.emit(''+pivot['column'])">{{i18n.t('dataops.suggest_pivot')}}</button><p class="dp-note">{{i18n.t('dataops.pivot_limit')}}</p>
      }
    }
    @case ('unpivot') { <app-prep-params kind="unpivot_v1" [params]="params()" [columns]="columns()" (paramsChange)="paramsChange.emit($event)" /> <p class="dp-note">{{i18n.t('dataops.unpivot_types')}}</p> }
    @case ('split') {
      <label class="dp-field"><span>{{i18n.t('dataops.param.method')}}</span><select class="dp-input" [value]="text('method','random')" (change)="set('method',val($event))">@for(method of splitMethods;track method){<option [value]="method">{{i18n.t('dataops.method.'+method)}}</option>}</select></label>
      @if (text('method','random') === 'condition') {<label class="dp-field"><span>{{i18n.t('dataops.else_port')}}</span><select class="dp-input" [value]="text('else_port')" (change)="set('else_port',val($event))"><option value=""></option>@for(out of draft().spec.outputs;track out.port){<option [value]="out.port">{{out.port}}</option>}</select></label>}
      @for(out of draft().spec.outputs;track $index;let n=$index){<section class="dp-section"><strong>{{out.port}}</strong>
        @if(text('method','random') === 'condition'){ @if(text('else_port') !== out.port){<app-prep-formula [value]="outputText(n,'filter')" [columns]="columns()" (valueChange)="splitOutput(n,'filter',$event)" />}}
        @else {<label class="dp-field"><span>{{i18n.t('dataops.ratio')}}</span><input class="dp-input" type="number" min="0" max="1" step="0.01" [value]="outputText(n,'ratio')" (input)="splitOutput(n,'ratio',number($event))" /></label>}
      </section>}
      @if (text('method','random') !== 'condition') {<app-prep-params kind="split_order" [params]="params()" [columns]="columns()" (paramsChange)="paramsChange.emit($event)" />}
    }
    @case ('sample') {
      <label class="dp-field"><span>{{i18n.t('dataops.param.method')}}</span><select class="dp-input" [value]="text('method','random')" (change)="set('method',val($event))">@for(method of sampleMethods;track method){<option [value]="method">{{i18n.t('dataops.method.'+method)}}</option>}</select></label>
      <label class="dp-field"><span>{{i18n.t('dataops.sample_size')}}</span><select class="dp-input" [value]="params()['fraction'] !== undefined ? 'fraction':'n'" (change)="sampleSize(val($event))"><option value="n">{{i18n.t('dataops.param.rows')}}</option><option value="fraction">{{i18n.t('dataops.fraction')}}</option></select></label>
      <label class="dp-field"><span>{{i18n.t(params()['fraction'] !== undefined ? 'dataops.fraction':'dataops.param.rows')}}</span><input class="dp-input" type="number" [attr.min]="params()['fraction'] !== undefined ? 0 : 1" [attr.max]="params()['fraction'] !== undefined ? 1 : null" [attr.step]="params()['fraction'] !== undefined ? 0.01 : 1" [value]="params()['fraction'] ?? params()['n'] ?? 100" (input)="set(params()['fraction'] !== undefined ? 'fraction':'n',number($event))" /></label>
      <app-prep-params kind="sample_order" [params]="params()" [columns]="columns()" (paramsChange)="paramsChange.emit($event)" />
    }
  }
  `})
export class PrepOperationComponent {
  readonly i18n=inject(I18nService); readonly draft=input.required<PrepDraft>(); readonly columns=input<string[]>([]); readonly rightColumns=input<string[]>([]);
  readonly portColumns=input<Record<string,string[]>>({}); readonly ports=input<string[]>([]); readonly paramsChange=output<Record<string,unknown>>(); readonly suggestPivot=output<string>();
  readonly params=computed(()=>this.draft().spec.params); readonly unionColumns=computed(()=>this.text('mode','by_name')==='bindings'?this.rows('bindings').map(row=>String(row['output'])):this.text('mode')==='by_position'?(this.portColumns()[this.ports()[0]]??[]):[...new Set(Object.values(this.portColumns()).flat())]);
  readonly joins=['inner','left','right','full','cross','semi','anti']; readonly operators=['eq','ne','lt','le','gt','ge','contains','starts_with']; readonly sides=['left','right']; readonly unionModes=['by_name','by_position','bindings'];
  readonly aggregates=['count_rows','count','count_distinct','sum','mean','min','max','std','std_pop','var','median','quantile','mode','string_agg','first','last']; readonly splitMethods=['random','stratified','order','condition']; readonly sampleMethods=['first','random','stratified'];
  val(e:Event):string{return(e.target as HTMLInputElement).value;} checked(e:Event):boolean{return(e.target as HTMLInputElement).checked;} number(e:Event):number|undefined{return prepNumber(this.val(e));}
  selected(e:Event):string[]{return Array.from((e.target as HTMLSelectElement).selectedOptions,o=>o.value);} includes(v:unknown,s:string):boolean{return Array.isArray(v)&&v.includes(s);}
  text(key:string,fallback=''):string{return String(this.params()[key]??fallback);} rows(key:string):Record<string,unknown>[]{return (this.params()[key] as Record<string,unknown>[])??[];}
  set(key:string,value:unknown):void{const next={...this.params()};if(value===undefined)delete next[key];else next[key]=value;if(this.draft().spec.operation==='split'&&(key==='method'||key==='else_port')){const ports=this.draft().spec.outputs.map(out=>out.port);if(next['method']==='condition'){next['else_port']??=ports.at(-1);next['outputs']=prepSplitConditionOutputs(ports,this.rows('outputs'),String(next['else_port']));}else{delete next['else_port'];next['outputs']=ports.map(port=>({port,ratio:1/ports.length}));}}if(key==='aggregations'&&next['pivot'])next['pivot']={...next['pivot'] as object,aggregations:value};this.paramsChange.emit(next);}
  rowSet(key:string,n:number,field:string,value:unknown):void{this.set(key,this.rows(key).map((r,i)=>{if(i!==n)return r;const next={...r};if(value===undefined)delete next[field];else next[field]=value;return next;}));}
  addRow(key:string,row:Record<string,unknown>):void{this.set(key,[...this.rows(key),row]);} removeRow(key:string,n:number):void{this.set(key,this.rows(key).filter((_,i)=>i!==n));}
  nested(key:string,field:string,value:unknown):void{this.set(key,{...this.params()[key] as object,[field]:value});}
  nestedText(key:string,field:string,fallback=''):string{return String((this.params()[key] as Record<string,unknown>)?.[field]??fallback);}
  sideSelected(side:string,col:string):boolean{const select=this.params()['select'] as Record<string,string[]>|undefined;return !select?.[side]||select[side].includes(col);}
  hasEquality():boolean{return this.rows('on').some(pair=>pair['op']==='eq');}
  matchKeys():void{this.set('on',this.columns().filter(col=>this.rightColumns().includes(col)).map(col=>({left:col,op:'eq',right:col})));}
  bindingSource(n:number,index:number):string{return prepBindingSources(this.rows('bindings')[n]?.['sources'])[this.ports()[index]]??'';}
  setBinding(n:number,index:number,value:string):void{const sources=prepBindingSources(this.rows('bindings')[n]?.['sources']);if(value)sources[this.ports()[index]]=value;else delete sources[this.ports()[index]];this.rowSet('bindings',n,'sources',sources);}
  unionSource(column:string,port:string):string{if(this.text('mode')==='bindings')return prepBindingSources(this.rows('bindings').find(row=>row['output']===column)?.['sources'])[port]??'NULL';if(this.text('mode')==='by_position')return this.portColumns()[port]?.[this.unionColumns().indexOf(column)]??'NULL';return this.portColumns()[port]?.includes(column)?column:'NULL';}
  pivot():Record<string,unknown>|null{return this.params()['pivot'] as Record<string,unknown>|null??null;}
  togglePivot(enabled:boolean):void{this.set('pivot',enabled?{column:'',values:[],aggregations:structuredClone(this.rows('aggregations')),naming:'{value}',null_label:'(null)',others:'drop'}:undefined);}
  outputText(n:number,key:string):string{return String(this.rows('outputs').find(row=>row['port']===this.draft().spec.outputs[n].port)?.[key]??'');}
  splitOutput(n:number,key:string,value:unknown):void{const rows=this.draft().spec.outputs.filter(out=>this.text('method')!=='condition'||out.port!==this.text('else_port')).map(out=>({...this.rows('outputs').find(row=>row['port']===out.port),port:out.port,...(out.port===this.draft().spec.outputs[n].port?{[key]:value}:{})}));this.set('outputs',rows);}
  sampleSize(key:string):void{const next={...this.params()};delete next['n'];delete next['fraction'];next[key]=key==='n'?100:0.1;this.paramsChange.emit(next);}
}
