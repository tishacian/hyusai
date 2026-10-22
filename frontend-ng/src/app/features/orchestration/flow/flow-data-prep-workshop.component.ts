import { prepSplitConditionOutputs } from '@app/features/data/prep-fields';
import type { PrepStepDefinition } from '@app/features/data/prep-fields';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, Injector, afterNextRender, computed, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { CdkDragDrop, DragDropModule } from '@angular/cdk/drag-drop';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { DataService, type DatasetDto } from '@app/features/data/data.service';
import { DataOpsApi } from '@app/features/data/dataops.api';
import { prepDraftFromNode, prepDraftPorts, prepNodePatch, prepColumnsBefore, type DatasetRef, type PrepAction, type PrepCompilation, type PrepDraft, type PrepPreview } from '@app/features/data/dataops.models';
import { PrepParamsComponent } from '@app/features/data/prep-params.component';
import { PrepOperationComponent } from '@app/features/data/prep-operation.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { CodeEditorComponent } from '@app/shared/ui/code-editor.component';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import { FlowStore } from './flow.store';
import { FlowRunService } from './flow-run.service';
import { FlowWorkbenchService } from './flow-workbench.service';
import { editablePrepDraft, newPrepStep, PREP_STEP_GROUPS, PREP_WRITE_DEBOUNCE, PrepHistory, prepError, prepInputStates, prepPinnedEdges, prepPreviewInputs, prepPreviewOutputRows, saltedPrep, type PrepInputState } from './flow-data-prep.vm';

@Component({selector:'app-flow-data-prep-workshop',standalone:true,changeDetection:ChangeDetectionStrategy.OnPush,
  imports:[A11yModule,DragDropModule,PrepParamsComponent,PrepOperationComponent,DataTableComponent,CodeEditorComponent,NavLinkDirective],
  styleUrls:['../../data/dataops-editor.scss','./flow-data-prep-workshop.component.scss'],template:`
  <div class="dp-workshop" role="dialog" aria-modal="true" [attr.aria-label]="i18n.t('dataops.workshop')" cdkTrapFocus [cdkTrapFocusAutoCapture]="true" (keydown.escape)="finish()">
    <header class="dp-workshop-head"><div><h2>{{i18n.t('dataops.operation.'+draft().spec.operation)}}</h2><span>{{node().label}}</span></div><div class="dp-row">
      <button class="dp-button" data-testid="prep-undo" [disabled]="readOnly()||!canUndo()" (click)="undo()">{{i18n.t('dataops.undo')}}</button><button class="dp-button" data-testid="prep-redo" [disabled]="readOnly()||!canRedo()" (click)="redo()">{{i18n.t('dataops.redo')}}</button>
      <button class="dp-button" data-testid="close-prep-workshop" (click)="finish()">{{i18n.t('common.close')}}</button></div></header>
    @if(readOnly()){<p class="dp-note dp-readonly-note" role="status" data-testid="prep-readonly">{{i18n.t('dataops.workshop_readonly')}}</p>}
    <section class="dp-workshop-inputs"><fieldset class="dp-fence" [disabled]="readOnly()">@for(port of ports();track port){<label class="dp-field"><span>{{i18n.t('dataops.input')}} · {{port}}</span><select class="dp-input" [attr.data-testid]="'prep-input-'+port" [value]="draft().inputs[port]?.dataset_id ?? ''" (change)="pin(port,val($event))"><option value="">{{i18n.t('dataops.use_upstream')}}</option>@for(ds of datasets();track ds.id){<option [value]="ds.id" [disabled]="ds.status !== 'ready'">{{ds.name}} · v{{ds.version}}</option>}</select><small class="dp-note">{{i18n.t('dataops.origin.'+origin(port))}}</small></label>
      @if(draft().spec.operation === 'union' && ports().length > 2){<button class="dp-button" (click)="removeInput(port)" [disabled]="connectedInput(port)||port!==ports()[ports().length-1]">{{i18n.t('dataops.remove')}}</button>}}
      @if(draft().spec.operation === 'union'){<button class="dp-button" data-testid="prep-add-input" [disabled]="ports().length>=16" (click)="addInput()">{{i18n.t('dataops.add_input')}}</button>}
    </fieldset></section>
    <details class="dp-preview-inputs" [open]="!flowInputsReady()||hasPreviewChoices()" data-testid="prep-preview-sources">
      <summary>{{i18n.t('dataops.preview_sources')}}</summary>
      <p class="dp-note">{{i18n.t('dataops.preview_sources_hint')}}</p>
      <div class="dp-preview-inputs-row">@for(port of ports();track port){
        <div class="dp-preview-source">
          <label class="dp-field"><span>{{i18n.t('dataops.preview_source',{port})}}</span>
            <select class="dp-input" [attr.data-testid]="'prep-preview-input-'+port" [value]="previewChoices()[port]??''" (change)="choosePreviewInput(port,val($event))">
              <option value="">{{i18n.t('dataops.preview_source_flow')}}</option>
              @for(ds of datasets();track ds.id){@if(ds.status==='ready'){<option [value]="ds.id">{{ds.name}} · v{{ds.version}}</option>}}
            </select>
          </label>
          @if(previewDataset(port);as dataset){
            <p class="dp-note" data-testid="prep-preview-provenance">{{i18n.t('dataops.preview_source_selected',{name:dataset.name,version:dataset.version})}}
              @if(dataset.run_id){ · <a [navLink]="{type:'run',ref:dataset.run_id}">{{i18n.t('dataops.preview_source_run',{run:dataset.run_id.slice(0,8)})}}</a>}
              @if(dataset.node_id){ · {{dataset.node_id}}}
            </p>
          }
          <small class="dp-note" [class.dp-error]="!inputReady(port)">{{i18n.t(inputReady(port)?'dataops.preview_source_ready':'dataops.preview_source_missing')}}</small>
        </div>
      }</div>
    </details>
    @if(error();as failure){<p class="dp-error dp-workshop-error" role="alert" data-testid="prep-error">{{errorText(failure.code)}}</p>}
    <div class="dp-workshop-body">
      <aside class="dp-workshop-left">
        @if(draft().spec.operation === 'prepare'){
          <h3>{{i18n.t('dataops.steps')}}</h3><div cdkDropList [cdkDropListDisabled]="readOnly()" (cdkDropListDropped)="drop($event)">
          @for(step of draft().spec.steps;track step.id;let n=$index){<div cdkDrag class="dp-step" [class.is-selected]="step.id === selectedStep()" [attr.data-step-id]="step.id">
            <button cdkDragHandle class="dp-button" [disabled]="readOnly()" [attr.aria-label]="i18n.t('dataops.drag_step')">⠿</button><button class="dp-step-name" (click)="selectStep(step.id!)">{{n+1}}. {{stepLabel(step.action)}}@if(step.enabled===false){ · {{i18n.t('dataops.disabled')}} } @if(error()?.stepId===step.id){<span class="dp-error"> ! </span>}</button>
            <button class="dp-button" [disabled]="readOnly()||n===0" (click)="move(n,-1)" [attr.aria-label]="i18n.t('dataops.up')">↑</button><button class="dp-button" [disabled]="readOnly()||n===draft().spec.steps.length-1" (click)="move(n,1)" [attr.aria-label]="i18n.t('dataops.down')">↓</button>
          </div>}</div>
          <fieldset class="dp-fence" [disabled]="readOnly()"><label class="dp-field"><span>{{i18n.t('dataops.search_steps')}}</span><input class="dp-input" type="search" data-testid="prep-step-search" [value]="search()" (input)="search.set(val($event))" /></label>
          @for(group of groups;track group){@if(groupActions(group).length){<section class="dp-catalog-group"><h4>{{i18n.t('dataops.group.'+group)}}</h4>@for(action of groupActions(group);track action){<button class="dp-button" [attr.data-testid]="'prep-add-'+action" [disabled]="draft().spec.steps.length>=200" (click)="addStep(action)">{{stepLabel(action)}}</button>}</section>}}</fieldset>
        } @else {<h3>{{i18n.t('dataops.outputs')}}</h3><fieldset class="dp-fence" [disabled]="readOnly()">@for(out of draft().spec.outputs;track $index;let n=$index){<div class="dp-section"><label class="dp-field"><span>{{i18n.t('dataops.port')}}</span><input class="dp-input" maxlength="31" [disabled]="draft().spec.operation!=='split'" [value]="out.port" (change)="outputField(n,'port',val($event))" /></label><label class="dp-field"><span>{{i18n.t('dataops.output_name')}}</span><input class="dp-input" [attr.data-testid]="'prep-output-name-'+n" [value]="out.name" (input)="outputField(n,'name',val($event))" /></label>@if(draft().spec.operation==='split'){<button class="dp-button" [disabled]="draft().spec.outputs.length<=2||connectedOutput(out.port)" (click)="removeOutput(n)">{{i18n.t('dataops.remove')}}</button>}</div>}
          @if(draft().spec.operation==='split'){<button class="dp-button" [disabled]="draft().spec.outputs.length>=8" (click)="addOutput()">{{i18n.t('dataops.add_output')}}</button>}</fieldset>
        }
      </aside>
      <main class="dp-workshop-center">
        <div class="dp-row"><button class="dp-button" data-testid="prep-preview" [disabled]="busy()||!inputsReady()" (click)="preview()">{{i18n.t('dataops.preview')}}</button><button class="dp-button" [disabled]="busy()||!inputsReady()" (click)="preview(true)">{{i18n.t('dataops.preview_all')}}</button>@if(selectedStep()){<span class="dp-note">{{i18n.t('dataops.preview_step',{step:selectedIndex()+1})}}</span>}</div>
        @if(sample();as result){
          <p class="dp-note" data-testid="prep-sample-notice">{{i18n.t('dataops.sample_rows',{rows:sampleRows(result)})}}</p>
          @if(result.sample_info?.of_rows!=null){<p class="dp-note">{{i18n.t('dataops.sample_of',{rows:result.sample_info!.of_rows})}}</p>}
          <ck-data-table [columns]="result.output_schema??result.schema" [rows]="result.rows" [stats]="result.stats ?? null" [rowCount]="previewOutputRows(result)" [durationMs]="result.duration_ms ?? null" [caption]="i18n.t('dataops.preview')" maxHeight="55vh" selectMode="single" [selected]="selectedColumns()" (selectedChange)="selectedColumns.set($event)" />
          @if(!readOnly() && selectedColumns().length && draft().spec.operation==='prepare'){<div class="dp-row">@for(action of columnActions;track action){<button class="dp-button" (click)="addStep(action,selectedColumns()[0])">{{stepLabel(action)}} · {{selectedColumns()[0]}}</button>}</div>}
          @for(diff of schemaDiff();track diff){<span class="dp-schema-chip">{{diff}}</span>}
          @for(warning of result.warnings??[];track $index){<p class="dp-error">{{errorText(warningCode(warning))}}</p>}
          @if(joinExpanded()){<p class="dp-error" role="status">{{i18n.t('dataops.join_expansion')}}</p>}
          @if(draft().spec.operation==='union'||draft().spec.operation==='unpivot'){@for(column of result.output_schema??result.schema;track column.name){<span class="dp-schema-chip">{{column.name}} · {{column.dtype}}</span>}}
          @for(count of counters();track count.key){<p class="dp-note">{{count.key}} · {{count.value}}</p>}
        } @else {<p class="dp-note">{{i18n.t('dataops.preview_hint')}}</p>}
      </main>
      <aside class="dp-workshop-right"><fieldset class="dp-fence" [disabled]="readOnly()">
        @if(draft().spec.operation==='prepare'){@if(selected();as step){<h3>{{stepLabel(step.action)}}</h3><label class="dp-check"><input type="checkbox" data-testid="prep-step-enabled" [checked]="step.enabled!==false" (change)="stepMeta('enabled',checked($event))" />{{i18n.t('dataops.enabled')}}</label>
          <app-prep-params [kind]="step.action" [definition]="stepDefinition(step.action)" [expressionFunctions]="functions()" [params]="step.params" [columns]="stepColumns()" [schema]="stepSchema()" (paramsChange)="stepParams($event)" />
          <label class="dp-field"><span>{{i18n.t('dataops.comment')}}</span><textarea class="dp-input" maxlength="500" data-testid="prep-step-comment" [value]="step.comment??''" (input)="stepMeta('comment',val($event))"></textarea></label><div class="dp-row"><button class="dp-button" (click)="duplicate()">{{i18n.t('dataops.duplicate')}}</button><button class="dp-button" (click)="removeStep()">{{i18n.t('dataops.remove')}}</button></div>
        }@else{<p class="dp-note">{{i18n.t('dataops.choose_step')}}</p>}}
        @else{<app-prep-operation [draft]="draft()" [columns]="columns()" [rightColumns]="portColumns()['right']" [portColumns]="portColumns()" [ports]="ports()" (paramsChange)="params($event)" (suggestPivot)="suggestPivot($event)" />}
        @if(draft().spec.operation==='sample'||draft().spec.operation==='split'){<label class="dp-field"><span>{{i18n.t('dataops.seed')}}</span><input class="dp-input" type="number" min="0" max="2147483647" [value]="draft().spec.seed" (input)="seed(val($event))" /></label>}
      </fieldset></aside>
    </div>
    <footer class="dp-workshop-foot">@if(draft().spec.operation==='split'){<label class="dp-field"><span>{{i18n.t('dataops.port')}}</span><select class="dp-input" [value]="sqlPort()||draft().spec.outputs[0].port" (change)="selectOutputPort(val($event))">@for(out of draft().spec.outputs;track out.port){<option [value]="out.port">{{out.port}}</option>}</select></label>}<span class="dp-note">{{i18n.t('dataops.sample_notice')}} {{i18n.t(hasPreviewChoices()?'dataops.preview_source_no_conversion':'dataops.sql_conversion_notice')}}</span><button #sqlTrigger class="dp-button" data-testid="prep-sql" [disabled]="busy()||!inputsReady()" (click)="compile()">{{i18n.t('dataops.sql')}}</button><button class="dp-button" data-testid="prep-convert-sql" [disabled]="readOnly()||busy()||salted()||hasPreviewChoices()||!inputsReady()" [title]="salted()?i18n.t('dataops.salted_no_sql'):hasPreviewChoices()?i18n.t('dataops.preview_source_no_conversion'):''" (click)="convertSql()">{{i18n.t('dataops.convert_sql')}}</button></footer>
    @if(compilation();as compiled){
      <div class="dp-sql-backdrop">
        <section class="dp-sql" data-testid="prep-sql-result" role="dialog" aria-modal="true" aria-labelledby="prep-sql-title" cdkTrapFocus [cdkTrapFocusAutoCapture]="true" (keydown.escape)="closeSql($event)">
          <header class="dp-sql-head">
            <div><h2 id="prep-sql-title">{{i18n.t('dataops.sql')}}</h2><span class="dp-note">{{i18n.t('dataops.sql_readonly')}}</span></div>
            <button class="dp-button" cdkFocusInitial (click)="closeSql()">{{i18n.t('common.close')}}</button>
          </header>
          <div class="dp-sql-body"><ck-code-editor language="sql" [readOnly]="true" [value]="compiled.sql" [ariaLabel]="i18n.t('dataops.sql')" /></div>
        </section>
      </div>
    }
  </div>`})
export class FlowDataPrepWorkshopComponent {
  readonly node=input.required<CanonicalFlowNode>(); readonly close=output<void>();
  /** Consultation of a published version: preview and inspect, never write. */
  readonly readOnly=input(false); readonly i18n=inject(I18nService);
  private readonly injector=inject(Injector); private readonly sqlTrigger=viewChild<ElementRef<HTMLButtonElement>>('sqlTrigger');
  private readonly api=inject(DataOpsApi); private readonly data=inject(DataService); private readonly store=inject(FlowStore); private readonly run=inject(FlowRunService); private readonly workbench=inject(FlowWorkbenchService); private readonly workspace=inject(WorkspaceService); private readonly scope=this.workspace.captureRequestScope();
  readonly draft=signal<PrepDraft>(editablePrepDraft(prepDraftFromNode(this.store.selectedNode()!))); readonly datasets=signal<DatasetDto[]>([]); readonly sqlPort=signal(''); readonly search=signal(''); readonly selectedStep=signal<string|null>(null); readonly selectedColumns=signal<string[]>([]);
  readonly sample=signal<PrepPreview|null>(null); readonly compilation=signal<PrepCompilation|null>(null); readonly error=signal<{code:string;stepId?:string}|null>(null); readonly busy=signal(false);
  private readonly previewSystemId=this.workbench.systemId(); private readonly previewNodeId=this.store.selectedNode()?.id;
  readonly previewChoices=signal<Partial<Record<string,string>>>({});
  readonly hasPreviewChoices=computed(()=>this.ports().some(port=>!!this.previewChoices()[port]));
  readonly definitions=signal<PrepStepDefinition[]>([]);readonly functions=signal<string[]>([]);readonly available=signal<PrepAction[]>([]); readonly groups=Object.keys(PREP_STEP_GROUPS); readonly columnActions:PrepAction[]=['drop_columns','rename_columns','cast','filter_rows','text_transform'];
  private readonly history=new PrepHistory(); readonly historyRevision=signal(0); private pending:ReturnType<typeof setTimeout>|undefined; private saved=structuredClone(this.draft()); private revision=0; private destroyed=false;
  readonly canUndo=computed(()=>{this.historyRevision();return this.history.canUndo||JSON.stringify(this.saved)!==JSON.stringify(this.draft());}); readonly canRedo=computed(()=>{this.historyRevision();return this.history.canRedo;});
  readonly ports=computed(()=>prepDraftPorts(this.draft())); readonly selectedIndex=computed(()=>this.draft().spec.steps.findIndex(step=>step.id===this.selectedStep())); readonly selected=computed(()=>this.draft().spec.steps[this.selectedIndex()]??null);
  readonly portColumns=computed(()=>Object.fromEntries(this.ports().map(port=>{const ref=this.inputStates().find(state=>state.port===port)?.ref;const dataset=this.datasets().find(ds=>ds.id===ref?.dataset_id);return [port,dataset?.schema.map(col=>col.name)??[]];})));
  readonly columns=computed(()=>this.portColumns()[this.draft().spec.operation==='join'?'left':this.ports()[0]]??[]);
  readonly stepSchema=computed(()=>{const index=this.selectedIndex();return this.sample()?.step_schemas?.find(s=>s.index===index-1)?.schema??(index===0?this.datasets().find(ds=>ds.id===this.inputStates().find(input=>input.port==='in')?.ref?.dataset_id)?.schema??[]:[]);});
  readonly stepColumns=computed(()=>this.stepSchema().length?this.stepSchema().map(c=>c.name):prepColumnsBefore(this.draft(),this.columns(),[],this.selectedIndex())); readonly salted=computed(()=>saltedPrep(this.draft()));
  // Preview results are as ephemeral as their input test. A graph, workspace
  // or test change must hide old rows/SQL, including a late HTTP response.
  private readonly previewContext=computed(()=>JSON.stringify({systemId:this.workbench.systemId(),revision:this.store.revision(),scope:this.workspace.captureRequestScope(),inputs:this.inputStates(),draft:this.draft()}));
  private sampleContext:string|null=null; private compilationContext:string|null=null;
  constructor(){effect(()=>{const context=this.previewContext();if(!this.previewScopeCurrent()){if(Object.keys(this.previewChoices()).length)this.previewChoices.set({});if(this.datasets().length)this.datasets.set([]);}if(this.sampleContext&&this.sampleContext!==context)this.sample.set(null);if(this.compilationContext&&this.compilationContext!==context)this.compilation.set(null);});inject(DestroyRef).onDestroy(()=>{this.flush();this.destroyed=true;clearTimeout(this.pending);});void this.load();}
  private async load():Promise<void>{try{const [datasets,catalog]=await Promise.all([this.data.refresh(),this.api.catalog()]);if(!this.destroyed&&this.previewScopeCurrent()){this.datasets.set(datasets);this.available.set(catalog.steps);this.definitions.set(catalog.step_definitions??[]);this.functions.set((catalog.functions??[]).map(row=>row.name));}}catch(error){if(!this.destroyed)this.error.set(prepError(error));}}
  val(e:Event):string{return(e.target as HTMLInputElement).value;} checked(e:Event):boolean{return(e.target as HTMLInputElement).checked;}
  flowInputStates():PrepInputState[]{try{const node={...this.node(),...prepNodePatch(this.node(),this.draft())};return prepInputStates(node,{nodes:this.store.nodes(),edges:this.store.edges()},{...this.run.nodeRuns(),...this.workbench.nodePreviewRuns()});}catch{return this.ports().map(port=>({port,origin:'unavailable'}));}}
  private previewScopeCurrent():boolean{return this.workspace.isRequestScopeCurrent(this.scope)&&this.workbench.systemId()===this.previewSystemId&&this.node().id===this.previewNodeId;}
  inputStates():PrepInputState[]{if(!this.previewScopeCurrent())return this.ports().map(port=>({port,origin:'unavailable'}));return prepPreviewInputs(this.flowInputStates(),this.previewChoices(),this.datasets());}
  origin(port:string):string{return this.flowInputStates().find(s=>s.port===port)?.origin??'unavailable';}
  flowInputsReady():boolean{return this.flowInputStates().every(input=>!!input.ref);}
  inputsReady():boolean{return this.inputStates().every(input=>!!input.ref);}
  inputReady(port:string):boolean{return !!this.inputStates().find(input=>input.port===port)?.ref;}
  previewDataset(port:string):DatasetDto|undefined{return this.previewScopeCurrent()?this.datasets().find(dataset=>dataset.id===this.previewChoices()[port]&&dataset.status==='ready'):undefined;}
  choosePreviewInput(port:string,id:string):void{if(!this.previewScopeCurrent()||!this.ports().includes(port)||id&&!this.datasets().some(dataset=>dataset.id===id&&dataset.status==='ready'))return;this.previewChoices.update(current=>({...current,[port]:id}));this.revision++;this.sample.set(null);this.compilation.set(null);this.error.set(null);}
  stepLabel(kind:string):string{return this.i18n.t(this.stepDefinition(kind)?.label_key??'dataops.step.'+kind);}
  stepDefinition(kind:string):PrepStepDefinition|null{return this.definitions().find(definition=>definition.kind===kind)??null;}
  groupActions(group:string):PrepAction[]{const query=this.search().trim().toLocaleLowerCase();return PREP_STEP_GROUPS[group].filter(action=>this.available().includes(action)&&(!query||this.stepLabel(action).toLocaleLowerCase().includes(query)));}
  private change(fn:(draft:PrepDraft)=>void,structural=false):void{if(this.readOnly())return;if(structural)this.flush();const draft=structuredClone(this.draft());fn(draft);this.draft.set(draft);this.revision++;this.error.set(null);this.sample.set(null);this.compilation.set(null);clearTimeout(this.pending);this.pending=setTimeout(()=>this.flush(),PREP_WRITE_DEBOUNCE);this.historyRevision.update(n=>n+1);if(structural)this.flush();}
  flush():void{clearTimeout(this.pending);if(this.readOnly())return;if(JSON.stringify(this.saved)===JSON.stringify(this.draft()))return;this.history.record(this.saved,this.draft());this.persist();this.saved=structuredClone(this.draft());this.historyRevision.update(n=>n+1);}
  private persist():void{if(this.readOnly())return;if(!this.workspace.isRequestScopeCurrent(this.scope))return;const node=this.store.nodes().find(n=>n.id===this.node().id);if(!node)return;const patch=prepNodePatch(node,this.draft());const old=prepDraftFromNode(node);const renames=new Map<string,string>();if(old.spec.outputs.length===this.draft().spec.outputs.length)old.spec.outputs.forEach((out,i)=>{if(out.port!==this.draft().spec.outputs[i].port)renames.set(out.port,this.draft().spec.outputs[i].port);});
    const keptEdges=prepPinnedEdges(this.store.edges(),node.id,this.draft());if(renames.size||keptEdges.length!==this.store.edges().length){const graph=this.store.snapshot();graph.edges=keptEdges;graph.nodes=graph.nodes.map(row=>row.id===node.id?{...row,...patch}:row);graph.edges=graph.edges.map(edge=>edge.from===node.id&&renames.has(edge.from_port??'')?{...edge,from_port:renames.get(edge.from_port!)!}:edge);this.store.replaceAsEdit(graph);this.store.setSelection(node.id);}else this.store.patchNode(node.id,patch);}
  undo():void{if(this.readOnly())return;this.flush();this.draft.set(this.history.undo(this.draft()));this.persist();this.saved=structuredClone(this.draft());this.historyRevision.update(n=>n+1);this.revision++;this.sample.set(null);this.compilation.set(null);}
  redo():void{if(this.readOnly())return;this.flush();this.draft.set(this.history.redo(this.draft()));this.persist();this.saved=structuredClone(this.draft());this.historyRevision.update(n=>n+1);this.revision++;this.sample.set(null);this.compilation.set(null);}
  finish():void{this.flush();this.close.emit();}
  closeSql(event?:Event):void{
    event?.stopPropagation();this.compilation.set(null);
    // Compilation temporarily disables its trigger, which can move browser
    // focus to the body before the dialog captures it. Restore explicitly
    // after the nested focus trap has been removed.
    afterNextRender(()=>{if(!this.destroyed&&this.previewScopeCurrent()&&!this.compilation())this.sqlTrigger()?.nativeElement.focus();},{injector:this.injector});
  }
  addStep(action:PrepAction,column?:string):void{if(this.draft().spec.steps.length>=200)return;const step=newPrepStep(action,column);if(action==='select_columns')step.params['columns']=this.columns();this.change(d=>d.spec.steps.push(step),true);this.selectedStep.set(step.id!);}
  selectStep(id:string):void{this.selectedStep.set(id);}
  stepParams(params:Record<string,unknown>):void{this.change(d=>{d.spec.steps[this.selectedIndex()].params=params;});}
  stepMeta(key:'enabled'|'comment',value:boolean|string):void{this.change(d=>{const step=d.spec.steps[this.selectedIndex()];if(key==='enabled')step.enabled=value===true;else step.comment=String(value).slice(0,500);});}
  duplicate():void{const step=this.selected();if(!step||this.draft().spec.steps.length>=200)return;const copy={...structuredClone(step),id:crypto.randomUUID()};this.change(d=>d.spec.steps.splice(this.selectedIndex()+1,0,copy),true);this.selectedStep.set(copy.id);}
  removeStep():void{this.change(d=>d.spec.steps.splice(this.selectedIndex(),1),true);this.selectedStep.set(null);}
  move(index:number,delta:number):void{if(index+delta<0||index+delta>=this.draft().spec.steps.length)return;this.change(d=>{const [step]=d.spec.steps.splice(index,1);d.spec.steps.splice(index+delta,0,step);},true);}
  drop(event:CdkDragDrop<unknown>):void{this.move(event.previousIndex,event.currentIndex-event.previousIndex);}
  pin(port:string,id:string):void{this.change(d=>{d.inputs[port]={dataset_id:id};});}
  connectedInput(port:string):boolean{return this.store.edges().some(e=>e.to===this.node().id&&(e.to_port??'in')===port);}
  connectedOutput(port:string):boolean{return this.store.edges().some(e=>e.from===this.node().id&&(e.from_port??'out')===port);}
  addInput():void{if(this.ports().length>=16)return;this.change(d=>{let n=1;while(this.ports().includes('in_'+n))n++;d.inputs['in_'+n]={dataset_id:''};});}
  removeInput(port:string):void{if(this.ports().length<=2||this.connectedInput(port)||port!==this.ports()[this.ports().length-1])return;this.change(d=>{delete d.inputs[port];});}
  params(params:Record<string,unknown>):void{this.change(d=>{d.spec.params=params;});} seed(value:string):void{this.change(d=>{d.spec.seed=Number(value);});}
  outputField(n:number,key:'port'|'name',value:string):void{this.change(d=>{const before=d.spec.outputs[n].port;d.spec.outputs[n][key]=value;if(key==='port'){const rows=d.spec.params['outputs'] as Array<Record<string,unknown>>|undefined;const row=rows?.find(row=>row['port']===before);if(row)row['port']=value;if(d.spec.params['else_port']===before)d.spec.params['else_port']=value;}});}
  addOutput():void{if(this.draft().spec.outputs.length>=8)return;this.change(d=>{let n=1;while(d.spec.outputs.some(out=>out.port==='out_'+n))n++;d.spec.outputs.push({port:'out_'+n,name:''});const old=(d.spec.params['outputs']??[]) as Array<Record<string,unknown>>;d.spec.params['outputs']=d.spec.params['method']==='condition'?prepSplitConditionOutputs(d.spec.outputs.map(out=>out.port),old,String(d.spec.params['else_port'])):d.spec.outputs.map(out=>({port:out.port,ratio:1/d.spec.outputs.length}));});}
  removeOutput(n:number):void{if(this.draft().spec.outputs.length<=2||this.connectedOutput(this.draft().spec.outputs[n].port))return;this.change(d=>{const removed=d.spec.outputs[n].port;d.spec.outputs.splice(n,1);const rows=d.spec.params['outputs'] as Array<Record<string,unknown>>;if(d.spec.params['method']==='condition'){if(d.spec.params['else_port']===removed)d.spec.params['else_port']=d.spec.outputs.at(-1)!.port;d.spec.params['outputs']=prepSplitConditionOutputs(d.spec.outputs.map(out=>out.port),rows,String(d.spec.params['else_port']));}else d.spec.params['outputs']=d.spec.outputs.map(out=>({port:out.port,ratio:1/d.spec.outputs.length}));});}
  private resolved():Record<string,DatasetRef>{if(!this.workspace.isRequestScopeCurrent(this.scope))throw new Error('DATAPREP_INPUT_UNAVAILABLE');const inputs=this.inputStates();if(inputs.some(input=>!input.ref))throw new Error('DATAPREP_INPUT_UNAVAILABLE');return Object.fromEntries(inputs.map(input=>[input.port,input.ref!]));}
  selectedOutputPort():string{return this.draft().spec.outputs.some(out=>out.port===this.sqlPort())?this.sqlPort():this.draft().spec.outputs[0].port;}
  selectOutputPort(port:string):void{this.sqlPort.set(port);this.sample.set(null);this.revision++;}
  async preview(all=false):Promise<void>{this.flush();const revision=this.revision;await this.action(async()=>{const context=this.previewContext();const result=await this.api.previewFlow(this.draft(),this.resolved(),all?undefined:this.selectedStep()??undefined,this.draft().spec.operation==='split'?(this.selectedOutputPort()):undefined);if(!this.destroyed&&revision===this.revision&&context===this.previewContext()){this.sampleContext=context;this.sample.set(result);}});}
  async compile():Promise<void>{this.flush();await this.action(async()=>{const revision=this.revision,context=this.previewContext();const result=await this.api.compileFlow(this.draft(),this.resolved());if(!this.destroyed&&revision===this.revision&&context===this.previewContext()){this.compilationContext=context;this.compilation.set(result);}});}
  async suggestPivot(column:string):Promise<void>{if(this.readOnly())return;await this.action(async()=>{const context=this.previewContext();const result=await this.api.pivotValues(this.draft(),this.resolved(),column);if(this.destroyed||context!==this.previewContext())return;this.change(d=>{d.spec.params['pivot']={...d.spec.params['pivot'] as object,values:result.values.slice(0,200)};});});}
  async convertSql():Promise<void>{if(this.readOnly())return;if(this.salted()||this.hasPreviewChoices()||!this.inputsReady())return;this.flush();const revision=this.revision;await this.action(async()=>{const selected=this.selectedOutputPort();if(this.draft().spec.outputs.some(out=>out.port!==selected&&this.connectedOutput(out.port)))throw new Error('DATAPREP_SQL_MULTIPLE_OUTPUTS');const context=this.previewContext();const inputs=this.resolved();const compiled=await this.api.compileFlow(this.draft(),inputs);const sources=compiled.sources??Object.entries(inputs).flatMap(([port,ref])=>ref.dataset_id?[{port,dataset_id:ref.dataset_id}]:[]);if(!sources.length)throw new Error('DATAPREP_INPUT_UNAVAILABLE');if(this.destroyed||revision!==this.revision||context!==this.previewContext())return;const sql=this.draft().spec.operation==='split'?compiled.sql_export_by_port?.[selected]:compiled.sql_export;if(compiled.sql_export_allowed!==true||!sql)throw new Error('DATAPREP_SALTED_SQL');const graph=this.store.snapshot();graph.nodes=graph.nodes.map(node=>node.id===this.node().id?{...node,config:{skill_slug:'sql_transform_v1',params:{sql,sources:sources.map(ref=>({view:ref.port==='in'?'input':ref.port,dataset_id:ref.dataset_id})),output_name:this.draft().spec.outputs.find(out=>out.port===selected)!.name}},outputs:[{name:'out',schema:'object'}]}:node);graph.edges=graph.edges.map(edge=>edge.from===this.node().id?{...edge,from_port:'out'}:edge);this.store.replaceAsEdit(graph);this.store.setSelection(this.node().id);this.close.emit();});}
  private async action(work:()=>Promise<void>):Promise<void>{if(this.busy()||!this.workspace.surfaceFeatureEnabled('data-preparation'))return;this.busy.set(true);this.error.set(null);const revision=this.revision;try{await work();}catch(error){if(!this.destroyed&&revision===this.revision)this.error.set(prepError(error));}finally{if(!this.destroyed)this.busy.set(false);}}
  warningCode(value:string|{code:string}):string{return typeof value==='string'?value:value.code;}
  errorText(code:string):string{const key='dataops.error.'+code;const text=this.i18n.t(key);return text===key?this.i18n.t('dataops.error.request')+' · '+code:text;}
  schemaDiff():string[]{const diff=this.sample()?.step_schemas?.find(step=>step.id===this.selectedStep())?.schema_diff;return diff?[...(diff.added??[]).map(name=>'+ '+name),...(diff.removed??[]).map(name=>'− '+name),...(diff.changed??[]).map(name=>'~ '+name)]:[];}
  previewOutputRows(result:PrepPreview):number|null{return prepPreviewOutputRows(result,this.draft().spec.operation==='split'?this.selectedOutputPort():'out');}
  sampleRows(result:PrepPreview):number{return result.sample_info?.rows??(typeof result.sample_metadata?.['sample_rows']==='number'?result.sample_metadata['sample_rows']:result.rows.length);}
  joinExpanded():boolean{if(this.draft().spec.operation!=='join')return false;const counts=this.sample()?.counters;const inputs=Object.values(counts?.['inputs'] as Record<string,number>??{}).filter(n=>typeof n==='number');const outputs=Object.values(counts?.['outputs'] as Record<string,number>??{}).filter(n=>typeof n==='number');return inputs.length===2&&outputs.some(n=>n>Math.max(...inputs));}
  counters():Array<{key:string;value:number}>{const result=this.sample();return Object.entries({...result?.counts,...result?.counters}).flatMap(([key,value])=>{
    if(typeof value==='number')return [{key,value}];if(!value||typeof value!=='object')return [];
    if(key==='steps')return Object.entries(value).flatMap(([id,counts])=>counts&&typeof counts==='object'?Object.entries(counts).flatMap(([metric,n])=>{const label=this.i18n.t('dataops.preview_step',{step:this.draft().spec.steps.findIndex(step=>step.id===id)+1})+' · '+this.i18n.t('dataops.counter.'+metric);return typeof n==='number'?[{key:label,value:n}]:n&&typeof n==='object'?Object.entries(n).flatMap(([column,value])=>typeof value==='number'?[{key:label+' · '+column,value}]:[]):[];}):[]);
    const label=this.i18n.t('dataops.counter.'+key);return Object.entries(value).flatMap(([port,count])=>typeof count==='number'?[{key:label+' · '+port,value:count}]:[]);
  });}
}
