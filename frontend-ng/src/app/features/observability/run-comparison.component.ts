import { formatInstant } from '@app/core/format-instant';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { formatSkillCost } from '../skills/skill-cost';
import { observabilityText, observabilityNumber } from './observability-labels';
import { FormsModule } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import { JsonPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { timer, switchMap, exhaustMap, takeWhile } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { AuthStore } from '@app/store/auth.store';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { qualityMessage, qualityState, type QualityMessage } from './quality-messages';
import { editTestCase, newTestCase, serializeTestCases, readableOutput, type TestCaseDraft } from './test-suite-editor.models';
import { settleWrite } from '@app/shared/ui/load-state';
import { campaignPollingActive, campaignResponseCurrent, CampaignRetryRequests, retryTarget, type Campaign, type CaseResult, type CampaignResult, type CampaignSide } from './campaign-retry.models';
interface Suite {id:string;name:string;revision:number;cases:unknown[];}
interface Generation {id:string;status:string;stage:string;progress:number;error?:string;result?:{cases?:Array<{id?:string;question?:string;reference_answer?:string;reference_context?:string}>;method?:string;version?:string;usage?:unknown;models?:unknown;coverage?:unknown;sides?:unknown};}
interface Preflight {eligible:boolean;preflight_sha256:string;planned_runs:number;comparability:string;limitations:string[];issues:Array<{code:string;node_id?:string;message:string}>;}
interface CollectionOption {id:string;name:string;status:string;}
@Component({selector:'app-run-comparison',standalone:true,imports:[FormsModule,JsonPipe,NavLinkDirective],changeDetection:ChangeDetectionStrategy.OnPush,
 template:`<section class="comparison">
 <h2>{{t('campaign')}}</h2>
 <div class="controls">
  <label>{{t('baseline')}}<select [(ngModel)]="selectedBaseline" [disabled]="!!baselineRunId()"><option value="">{{t('choose')}}</option>@for(run of baselineRuns();track run.id){<option [value]="run.id">{{run.started_at ? date(run.started_at) : run.id}} · {{run.id.slice(0,8)}}</option>}</select></label>
  <span>{{t('candidate')}} · {{t('draft')}} {{effectiveRevision() || '—'}}</span>
 </div>
 @if(!baselineRunId() && !baselineRuns().length){<p>{{t('no_baseline')}}</p>}
 <details><summary>{{t('campaigns')}} · {{campaigns().length}}</summary>@for(row of campaigns();track row.id){<button type="button" (click)="selectCampaign(row.id)">{{row.created_at ? date(row.created_at) : row.id}} · {{state(row.status)}}</button>}@empty{<p>{{t('no_campaign')}}</p>}</details>
 <p>{{i18n.t('runs.comparison.scope')}}</p>
 <div class="controls"><label>{{i18n.t('runs.comparison.suite')}}<select [(ngModel)]="suiteId">@for(suite of suites();track suite.id){<option [value]="suite.id">{{suite.name}} · {{suite.revision}}</option>}</select></label>
 </div>
 <div class="controls"><label>{{t('mode')}}<select [(ngModel)]="executionMode"><option value="qualified_prefix">{{t('qualified_prefix')}}</option><option value="legacy_readonly">{{t('read_only')}}</option></select></label>
 <label>{{t('repetitions')}}<select [(ngModel)]="repeatCount"><option [ngValue]="1">1</option><option [ngValue]="2">2</option></select></label>
 <button type="button" (click)="checkPath()" [disabled]="busy() || !suiteId || !effectiveBaseline() || !effectiveRevision()">{{t('preflight')}}</button>
 <button type="button" (click)="compare()" [disabled]="busy() || !preflightCurrent() || !preflight()?.eligible">{{t('start')}}</button></div>
 <p class="scope-note">{{t('preflight_required')}}</p>
 @if(preflightCurrent() && preflight();as check){<section class="preflight" role="status"><strong>{{t(check.eligible?'eligible':'ineligible')}}</strong><p>{{t('planned')}}: {{check.planned_runs}} · {{state(check.comparability)}}</p>@for(issue of check.issues;track $index){<p>{{issue.node_id}} · {{issue.message}}</p>}@for(limitation of check.limitations;track $index){<p>{{limitation}}</p>}</section>}
 @if(error()){<p role="alert">{{error()}}</p>}
 @if(!suites().length){<p>{{i18n.t('runs.comparison.no_suite')}}</p>}
 <details><summary>{{i18n.t('runs.generation.title')}}</summary>
  <p>{{i18n.t('runs.generation.scope')}}</p>
  <label>{{i18n.t('runs.generation.collection')}}<select [(ngModel)]="collectionId" [disabled]="generationBusy()"> <option value="">{{i18n.t('runs.generation.choose')}}</option>@for(collection of collections();track collection.id){<option [value]="collection.id" [disabled]="collection.status !== 'ready'">{{collection.name}} · {{code('status',collection.status)}}</option>}</select></label>
  @if(!collections().length){<p>{{i18n.t('runs.generation.no_collection')}}</p>}
  <button type="button" (click)="generate()" [disabled]="generationBusy() || !collectionId">{{i18n.t('runs.generation.generate')}}</button>
  @if(generation();as job){<p aria-live="polite">{{code('status',job.status)}} · {{code('stage',job.stage)}}</p><progress [value]="job.progress" max="100" [attr.aria-label]="code('stage',job.stage)"></progress>
   @if(job.error){<p role="alert">{{code('reason',job.error)}}</p><details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{job.error}}</pre></details>}
   @if(job.result?.cases?.length){<h3>{{i18n.t('runs.generation.proposed')}}</h3>@for(test of job.result?.cases;track $index){<article><strong>{{test.question}}</strong><p>{{test.reference_answer}}</p><details><summary>{{i18n.t('runs.generation.reference')}}</summary><p>{{test.reference_context}}</p></details></article>}
    <button type="button" (click)="reviewGenerated()">{{i18n.t('runs.generation.review')}}</button>
   }
   @if(job.result){<details><summary>{{i18n.t('runs.generation.method')}}</summary><p>{{code('method',job.result.method)}} {{job.result.version}}</p><pre>{{job.result.models | json}}</pre><pre>{{job.result.coverage | json}}</pre><pre>{{job.result.usage | json}}</pre></details>}
  }
 </details>
 <details class="suite-editor"><summary>{{t('create_suite')}}</summary>
  <label>{{t('suite_name')}}<input [(ngModel)]="suiteName" maxlength="160" /></label>
  @if(referenceSeeded()){<p>{{t('source_run')}}</p>}
 @for(test of caseDrafts;track $index;let caseIndex=$index){<fieldset>
   <legend>{{t('case_id')}} {{caseIndex+1}}</legend>
   <div class="controls"><label>{{t('case_id')}}<input [(ngModel)]="test.id" maxlength="100" (ngModelChange)="test.reviewed=false" /></label><label>{{t('family')}}<input [(ngModel)]="test.family" (ngModelChange)="test.reviewed=false" /></label><label class="check"><input type="checkbox" [(ngModel)]="test.critical" (ngModelChange)="test.reviewed=false" />{{t('critical')}}</label><button type="button" (click)="removeCase(caseIndex)">{{t('remove')}}</button></div>
   <label>{{t('question')}}<textarea rows="2" [(ngModel)]="test.question" (ngModelChange)="test.reviewed=false"></textarea></label>
   <h4>{{t('input_fields')}}</h4>
   @for(field of test.fields;track $index;let fieldIndex=$index){<div class="controls field-row"><label>{{t('field')}}<input [(ngModel)]="field.key" (ngModelChange)="test.reviewed=false" /></label><label>{{t('field_type')}}<select [(ngModel)]="field.type" (ngModelChange)="test.reviewed=false">@for(kind of ['string','number','boolean','null'];track kind){<option [value]="kind">{{state(kind)}}</option>}@if(field.type==='json'){<option value="json">JSON</option>}</select></label><label>{{t('value')}}@if(field.type==='boolean'){<select [(ngModel)]="field.value" (ngModelChange)="test.reviewed=false"><option value="">{{t('choose')}}</option><option value="true">{{i18n.t('dataops.yes')}}</option><option value="false">{{i18n.t('dataops.no')}}</option></select>}@else{<input [(ngModel)]="field.value" [disabled]="field.type==='null'" (ngModelChange)="test.reviewed=false" />}</label><button type="button" (click)="test.fields.splice(fieldIndex,1);test.reviewed=false">{{t('remove')}}</button></div>}
   <button type="button" (click)="test.fields.push({key:'',type:'string',value:''});test.reviewed=false">{{t('add_field')}}</button>
   <div class="columns"><label>{{t('reference')}}<textarea rows="3" [(ngModel)]="test.reference_answer" (ngModelChange)="test.reviewed=false"></textarea></label><label>{{t('context')}}<textarea rows="3" [(ngModel)]="test.reference_context" (ngModelChange)="test.reviewed=false"></textarea></label></div>
   <div class="controls"><label>{{t('answer_path')}}<input [(ngModel)]="test.answer_path" (ngModelChange)="test.reviewed=false" /></label><label>{{i18n.t('observability.assurance.answer_format')}}<select [(ngModel)]="test.answer_format" (ngModelChange)="test.reviewed=false"><option value="text">{{i18n.t('observability.assurance.answer_text')}}</option><option value="json">{{i18n.t('observability.assurance.answer_json')}}</option></select></label><label>{{t('output_skill')}}<input [(ngModel)]="test.output_skill" (ngModelChange)="test.reviewed=false" /></label><label>{{i18n.t('observability.assurance.selected_output_path')}}<input [(ngModel)]="test.output_path" (ngModelChange)="test.reviewed=false" /></label><label>{{t('termination')}}<select [(ngModel)]="test.expected_termination" (ngModelChange)="test.reviewed=false"><option value="completed">{{t('completed')}}</option><option value="human_gate">{{t('human_gate')}}</option><option value="either">{{t('either')}}</option></select></label></div>
   <h4>{{t('assertions')}}</h4>
   @for(check of test.assertions;track $index;let checkIndex=$index){<div class="controls field-row"><label>{{t('output_path')}}<input [(ngModel)]="check.path" [disabled]="check.operator==='invocation_succeeded'" (ngModelChange)="test.reviewed=false" /></label><label>{{t('operator')}}<select [(ngModel)]="check.operator" (ngModelChange)="test.reviewed=false">@for(operator of ['equals','contains','not_contains','exists','invocation_succeeded'];track operator){<option [value]="operator">{{state(operator)}}</option>}</select></label>@if(check.operator!=='exists'){<label>{{t('expected')}}<input [(ngModel)]="check.value" (ngModelChange)="test.reviewed=false" /></label><label>{{t('field_type')}}<select [(ngModel)]="check.type" (ngModelChange)="test.reviewed=false">@for(kind of ['string','number','boolean','null'];track kind){<option [value]="kind">{{state(kind)}}</option>}</select></label>}<button type="button" (click)="test.assertions.splice(checkIndex,1);test.reviewed=false">{{t('remove')}}</button></div>}
   <button type="button" (click)="test.assertions.push({id:'check-'+(test.assertions.length+1),path:'',operator:'contains',type:'string',value:''});test.reviewed=false">{{t('add_assertion')}}</button>
   <h4>{{t('trajectory')}}</h4>
   @for(check of test.trajectory_assertions;track $index;let trajectoryIndex=$index){<div class="controls field-row"><label>{{t('operator')}}<select [(ngModel)]="check.operator" (ngModelChange)="test.reviewed=false">@for(operator of ['tool_required','tool_forbidden','before','max_calls','human_gate','no_business_effects'];track operator){<option [value]="operator">{{state(operator)}}</option>}</select></label>
    @if(check.operator==='tool_required'||check.operator==='tool_forbidden'||check.operator==='max_calls'){<label>{{t('skill')}}<input [(ngModel)]="check.skill_slug" (ngModelChange)="test.reviewed=false" /></label>}
    @if(check.operator==='before'){<label>{{t('before_skill')}}<input [(ngModel)]="check.before_skill" (ngModelChange)="test.reviewed=false" /></label><label>{{t('after_skill')}}<input [(ngModel)]="check.after_skill" (ngModelChange)="test.reviewed=false" /></label>}
    @if(check.operator==='max_calls'){<label>{{t('limit')}}<input type="number" min="0" step="1" [(ngModel)]="check.limit" (ngModelChange)="test.reviewed=false" /></label>}
    <label>{{t('severity')}}<select [(ngModel)]="check.severity" (ngModelChange)="test.reviewed=false"><option value="normal">{{t('normal')}}</option><option value="critical">{{t('critical')}}</option></select></label><button type="button" (click)="test.trajectory_assertions.splice(trajectoryIndex,1);test.reviewed=false">{{t('remove')}}</button>
   </div>}
   <button type="button" (click)="test.trajectory_assertions.push({id:'path-'+(test.trajectory_assertions.length+1),operator:'human_gate',severity:'critical'});test.reviewed=false">{{t('add_trajectory')}}</button>
   <label class="check"><input type="checkbox" [(ngModel)]="test.reviewed" />{{t('reviewed')}}</label>
  </fieldset>}
  <div class="controls"><button type="button" (click)="addCase()" [disabled]="caseDrafts.length>=20">{{t('add_case')}}</button><button type="button" (click)="saveSuite()" [disabled]="busy() || !suiteReady()">{{t('save')}}</button></div>
  <details><summary>{{t('advanced')}}</summary><textarea rows="6" [(ngModel)]="casesText" [attr.aria-label]="t('advanced')"></textarea><button type="button" (click)="importCases()">{{t('import_json')}}</button><button type="button" (click)="exportCases()">{{t('export_json')}}</button></details>
 </details>
 @if(campaign();as comparison){
  <h3>{{i18n.t('runs.comparison.status')}}: {{code('status',comparison.status)}}</h3>
  @if(comparison.retry_pending){<p role="status" class="scope-note">{{i18n.t('observability.assurance.retry_pending')}}</p>}
  <p>{{code('method',comparison.method)}} · {{code('comparability',comparison.snapshot.comparability)}}</p>
  @for(limitation of comparison.snapshot.limitations;track $index){<p>{{code('limitation',limitation)}}</p><details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{limitation | json}}</pre></details>}
  @for(test of comparison.results;track test.result_key || test.case_id+'-'+$index){
   <article><h3>{{test.case_id}} · {{t('assertions')}}: {{code('change',test.change)}} @if(test.repetition_index!=null){ · {{t('repeat')}} {{test.repetition_index!+1}} }</h3>
    <div class="columns">
     @for(side of [test.baseline,test.candidate];track $index;let sideIndex=$index){
      <div><strong>{{i18n.t($index === 0 ? 'runs.comparison.baseline' : 'runs.comparison.candidate')}}</strong>
       <p>{{side.termination==='human_gate'?t('human_gate'):code('status',side.status)}} · {{t('assertions')}}: {{code('verdict',side.verdict)}}</p><p>{{t('verdict')}}: {{state(side.quality_status || 'unassessed')}}</p>@if(side.termination==='human_gate'){<p class="scope-note">{{i18n.t('observability.assurance.qa_human_boundary')}}</p>}<p class="answer">{{output(side.output_ref) || t('no_output')}}</p>
       @if(side.run_id){<a [navLink]="{type:'run',ref:side.run_id}">{{i18n.t('runs.comparison.proof')}}</a>}
       <details><summary>{{i18n.t('runs.comparison.assertions')}}</summary>
        @for(control of side.controls || [];track control.invocation_id){<p>{{t('execution')}}: {{qualityStatus(control.execution_status,true)}} · {{t('verdict')}}: {{state(control.quality_status)}} <a [navLink]="{type:'run',ref:side.run_id,params:{facet:'quality',evaluationId:control.evaluation_id}}">{{t('open')}}</a></p>}
        @for(check of checks(side);track check.id){
         <p>{{check.id}} · {{code('verdict',check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'unevaluated')}}</p>
         @for(invocationId of check.invocation_ids;track invocationId){
          <p><a [navLink]="{type:'skill_invocation',runId:side.run_id,ref:invocationId}">{{i18n.t('runs.investigation.invocation')}} · {{invocationId}}</a></p>
         }
        }
        <details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{side.assertions | json}}</pre></details><p>{{i18n.t('runs.comparison.cost')}}: {{cost(side.execution_cost)}} · {{i18n.t('observability.quality.milliseconds',{value:number(side.duration_ms)})}}</p></details>
       @if(side.attempts?.length){
        <section class="retry-history" [attr.aria-label]="i18n.t('observability.assurance.retry_history')">
         <h4>{{i18n.t('observability.assurance.retry_history')}}</h4>
         <p class="scope-note">{{i18n.t('observability.assurance.retry_initial_preserved')}}</p>
         @for(attempt of side.attempts;track attempt.id){
          <div class="retry-attempt" [attr.data-attempt-id]="attempt.id">
           <strong>{{i18n.t('observability.assurance.retry_attempt',{number:attempt.attempt_index})}}</strong> <span class="scope-note"> · {{date(attempt.created_at)}}</span>
           <p>{{i18n.t('runs.sections.execution')}}: {{attempt.termination==='human_gate'?t('human_gate'):code('status',attempt.status)}} · {{t('assertions')}}: {{code('verdict',attempt.verdict)}}<br />{{t('verdict')}}: {{state(attempt.quality_status || 'unassessed')}}</p>
           @if(attempt.termination==='human_gate'){<p class="scope-note">{{i18n.t('observability.assurance.qa_human_boundary')}}</p>}
           @if(output(attempt.output_ref)){<p class="answer">{{output(attempt.output_ref)}}</p>}
           @if(attempt.run_id){<a [navLink]="{type:'run',ref:attempt.run_id}">{{i18n.t('runs.comparison.proof')}}</a>}
           @for(control of attempt.controls || [];track control.invocation_id){<p>{{t('execution')}}: {{qualityStatus(control.execution_status,true)}} · {{t('verdict')}}: {{state(control.quality_status)}} <a [navLink]="{type:'run',ref:attempt.run_id,params:{facet:'quality',evaluationId:control.evaluation_id}}">{{t('open')}}</a></p>}
           <details><summary>{{i18n.t('observability.assurance.retry_provenance')}}</summary>
            <p>{{i18n.t('observability.assurance.retry_source')}}: <a [navLink]="{type:'run',ref:attempt.source_run_id}">{{attempt.source_run_id}}</a></p>
            <p>{{i18n.t('observability.assurance.retry_initial')}}: <a [navLink]="{type:'run',ref:attempt.initial_run_id}">{{attempt.initial_run_id}}</a></p>
            <p>{{i18n.t('observability.assurance.retry_actor')}}: {{attempt.actor_user_id}}</p>
            @if(attempt.reason){<p>{{attempt.reason}}</p>}
            @for(check of checks(attempt);track check.id){<p>{{check.id}} · {{code('verdict',check.passed===true?'passed':check.passed===false?'failed':'unevaluated')}}</p>}
            <p>{{i18n.t('runs.comparison.cost')}}: {{cost(attempt.execution_cost)}} · {{i18n.t('observability.quality.milliseconds',{value:number(attempt.duration_ms)})}}</p>
           </details>
          </div>
         }
        </section>
       }
       @if(retryNotice(test,sideIndex);as notice){<p class="scope-note" [attr.role]="notice.kind==='failed'?'alert':'status'">{{retryMessage(notice)}}</p>}
       @if(test.result_key && (side.can_retry===true || retryNotice(test,sideIndex)?.kind==='unknown')){
        <div class="retry-actions"><button type="button" (click)="retry(test,sideIndex,side)" [disabled]="retryNotice(test,sideIndex)?.kind==='sent'">{{i18n.t(retryNotice(test,sideIndex)?.kind==='unknown'?'observability.assurance.retry_check':'observability.assurance.retry_action')}}</button><span class="scope-note">{{i18n.t('observability.assurance.retry_hint')}}</span></div>
       }
      </div>
     }
    </div>
   </article>
  }
  <a [navLink]="{leaf:'system-flow',ref:systemId()}">{{i18n.t('runs.comparison.publication')}}</a>
  @if(comparison.status === 'completed'){<h3>{{t('raget_title')}}</h3><p>{{t('raget_hint')}}</p><button type="button" (click)="evaluateRaget()" [disabled]="ragetBusy()">{{t('raget_run')}}</button>}
  @if(raget();as report){<p aria-live="polite">{{code('status',report.status)}} · {{code('stage',report.stage)}}</p>@if(report.error){<p role="alert">{{code('reason',report.error)}}</p><details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{report.error}}</pre></details>}@if(report.result?.sides){<section><h4>{{t('report')}}</h4>@for(side of reportSides(report.result?.sides);track side.name){<article><h4>{{state(side.name)}}</h4>@for(row of side.rows;track $index){<p class="answer">{{row}}</p>}@empty{<p>{{t('report_empty')}}</p>}</article>}<details><summary>{{t('details')}}</summary><pre>{{report.result?.sides | json}}</pre></details></section>}}
 }
 </section>`,
 styles:[`.retry-history{border-top:1px solid var(--ck-stroke-2);margin-top:18px;padding-top:4px}.retry-attempt{border-left:2px solid var(--ck-stroke-3);padding:4px 0 4px 12px;margin:12px 0}.retry-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px}.retry-actions button{font-size:12px;white-space:nowrap}.retry-attempt>p{margin:8px 0}fieldset{border:1px solid var(--ck-stroke-2);border-radius:4px;margin:16px 0;padding:16px;min-width:0}legend{padding:0 6px;font-size:13px}h4{font-size:13px;margin:12px 0}.check{display:flex;align-items:center;gap:8px}.check input{width:auto}.field-row{gap:10px}.field-row label{flex:1;min-width:130px}.field-row select{min-width:0}.field-row input{width:100%}.answer{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}.preflight{border-left:2px solid var(--ck-signal-cool);padding:8px 14px;background:var(--ck-bg-inset);font-size:12px}.scope-note{color:var(--ck-fg-3);font-size:12px}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}.comparison{padding:18px;border-top:1px solid var(--ck-stroke-2);color:var(--ck-fg-1)}h2{font-size:18px;font-weight:600}h3{font-size:15px;margin:20px 0}p{margin:12px 0;line-height:1.6}.controls{display:flex;align-items:end;gap:16px;flex-wrap:wrap}label{display:block;margin:12px 0}select,input,textarea,button{background:var(--ck-bg-panel);color:inherit;border:1px solid var(--ck-stroke-3);padding:7px 10px;border-radius:6px}textarea{display:block;width:100%;font-family:monospace}select{display:block;min-width:min(240px,100%);max-width:100%}input,textarea{max-width:100%}textarea{font-family:inherit}details>textarea{font-family:monospace}button:disabled{opacity:.5}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}.columns>div{min-width:0;padding:20px;background:var(--ck-bg-panel-hi)}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere;color:var(--ck-signal-cool);text-decoration:underline}details{margin:16px 0}article{border-top:1px solid var(--ck-stroke-2);margin-top:24px}@media(max-width:800px){.columns{grid-template-columns:1fr}}`]
})
export class RunComparisonComponent {
 code(category:string,value:unknown):string{return observabilityText(this.i18n,category,value);}
 number(value:number|null|undefined,digits=0):string{return observabilityNumber(value,this.i18n.locale(),digits);}
 cost(value:number|null|undefined):string{return formatSkillCost(value,'USD',this.i18n.locale());}
 date(value:string|null|undefined):string {return formatInstant(value,this.i18n.locale())??'—';}
 readonly systemId=input.required<string>();readonly baselineRunId=input<string>('');readonly draftRevision=input<number|null>(null);
 readonly i18n=inject(I18nService);private readonly canonical=inject(CanonicalApiService);
 t(key:QualityMessage){return qualityMessage(this.i18n,key);}state(value:unknown){return qualityState(this.i18n,value);}qualityStatus(value:unknown,execution=false){return qualityState(this.i18n,value,execution);}readonly output=readableOutput;
 readonly baselineRuns=signal<Array<{id:string;started_at?:string}>>([]);readonly loadedRevision=signal<number|null>(null);readonly campaigns=signal<Campaign[]>([]);readonly preflight=signal<Preflight|null>(null);private checkedBody='';selectedBaseline='';executionMode:'legacy_readonly'|'qualified_prefix'='qualified_prefix';repeatCount:1|2=1;caseDrafts:TestCaseDraft[]=[newTestCase(1)];
 effectiveBaseline(){return this.baselineRunId()||this.selectedBaseline;}effectiveRevision(){return this.draftRevision()||this.loadedRevision();}
private readonly api=inject(ApiService);private readonly workspace=inject(WorkspaceService);private readonly auth=inject(AuthStore);private readonly router=inject(Router);private readonly route=inject(ActivatedRoute);
 private readonly query=toSignal(this.route.queryParamMap,{initialValue:this.route.snapshot.queryParamMap});private readonly referenceId=computed(()=>this.query().get('referenceRunId'));readonly referenceSeeded=signal(false);
 readonly retryNotices=signal<Partial<Record<string,{kind:'sent'|'unknown'|'failed';code?:string|null;status?:number|null}>>>({});private readonly retryRequests=new CampaignRetryRequests();private readonly campaignRefresh=signal(0);
 readonly suites=signal<Suite[]>([]);readonly campaign=signal<Campaign|null>(null);readonly campaignId=signal('');readonly error=signal('');readonly busy=signal(false);
 readonly collections=signal<CollectionOption[]>([]);readonly generation=signal<Generation|null>(null);readonly generationId=signal('');readonly generationBusy=signal(false);readonly raget=signal<Generation|null>(null);readonly ragetId=signal('');readonly ragetBusy=signal(false);
 collectionId='';reviewCollectionId='';reviewGenerationId='';private ragetRequest:{campaignId:string;key:string}|null=null;
 private comparisonRequest:{body:string;key:string}|null=null;private generationRequest:{body:string;key:string}|null=null;
 private scope():string{return JSON.stringify([this.workspace.current()?.id,this.auth.authEpoch(),this.systemId()]);}
 suiteId='';suiteName='';reviewed=false;casesText='[\n  {"id":"case-1","input_ref":{},"assertions":[]}\n]';
 constructor(){
  effect(cleanup=>{const context=this.scope(),reference=this.referenceId();this.referenceSeeded.set(false);if(!reference)return;const sub=this.canonical.getRun(reference).subscribe({next:run=>{if(!run||context!==this.scope()||run.system_id!==this.systemId())return;const draft=editTestCase({id:'case-'+run.id.slice(0,8),input_ref:run.input_ref || {},reference_answer:readableOutput(run.output_ref),reference_run_id:run.id},1);this.caseDrafts=[draft];this.referenceSeeded.set(true);if(run.status==='completed')this.selectedBaseline=run.id;},error:()=>{if(context===this.scope())this.error.set(this.t('load_failed'));}});cleanup(()=>sub.unsubscribe());});
  effect(cleanup=>{const context=this.scope(),system=this.systemId();this.selectedBaseline=this.baselineRunId();this.loadedRevision.set(null);this.baselineRuns.set([]);this.campaigns.set([]);this.preflight.set(null);this.checkedBody='';this.caseDrafts=[newTestCase(1)];
   const runs=this.canonical.listRuns({system_id:system,status:'completed'}).subscribe({next:rows=>{if(context===this.scope())this.baselineRuns.set(rows.map(row=>({id:row.id,started_at:row.started_at || undefined})));},error:()=>{if(context===this.scope())this.error.set(this.t('load_failed'));}});
   const flow=this.api.get<{draft?:{revision?:number}}>(`/systems/${encodeURIComponent(system)}/flow-state`).subscribe({next:value=>{if(context===this.scope())this.loadedRevision.set(value.draft?.revision || null);},error:()=>{if(context===this.scope())this.error.set(this.t('load_failed'));}});
   const history=this.api.get<Campaign[]>('/evaluation/campaigns',{system_id:system}).subscribe({next:rows=>{if(context===this.scope())this.campaigns.set(rows);},error:()=>{if(context===this.scope())this.error.set(this.t('load_failed'));}});cleanup(()=>{runs.unsubscribe();flow.unsubscribe();history.unsubscribe();});
  });
  effect(onCleanup=>{const context=this.scope();const system=this.systemId();this.suites.set([]);this.campaign.set(null);this.campaignId.set(this.route.snapshot.queryParamMap.get('campaign') || '');const subscription=this.api.get<Suite[]>('/evaluation/suites',{system_id:system}).subscribe({next:rows=>{if(context===this.scope())this.suites.set(rows);},error:()=>{if(context===this.scope())this.error.set(this.i18n.t('runs.comparison.unavailable'));}});onCleanup(()=>subscription.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();const id=this.campaignId();this.campaignRefresh();if(!id)return;const subscription=timer(0,2500).pipe(exhaustMap(()=>this.api.get<Campaign>(`/evaluation/campaigns/${encodeURIComponent(id)}`)),takeWhile(campaignPollingActive,true)).subscribe({next:value=>{if(campaignResponseCurrent(context,this.scope(),id,this.campaignId(),value.id))this.campaign.set(value);},error:()=>{if(campaignResponseCurrent(context,this.scope(),id,this.campaignId()))this.error.set(this.i18n.t('runs.comparison.unavailable'));}});onCleanup(()=>subscription.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();this.retryRequests.clear();this.retryNotices.set({});this.comparisonRequest=null;this.generationRequest=null;this.ragetRequest=null;this.collections.set([]);this.generation.set(null);this.generationId.set('');this.raget.set(null);this.ragetId.set('');this.reviewGenerationId='';this.reviewCollectionId='';this.collectionId='';this.reviewed=false;this.suiteId='';this.suiteName='';this.casesText='[]';this.generationBusy.set(false);this.ragetBusy.set(false);this.busy.set(false);const sub=this.api.get<{items?:CollectionOption[]}>('/documents/collections').subscribe({next:value=>{if(context===this.scope())this.collections.set(value.items || []);},error:()=>{if(context===this.scope())this.error.set(this.i18n.t('runs.generation.unavailable'));}});onCleanup(()=>sub.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();const id=this.generationId();if(!id)return;const sub=timer(0,2000).pipe(switchMap(()=>this.api.get<Generation>(`/evaluation/generations/${encodeURIComponent(id)}`)),takeWhile(job=>['created','queued','running'].includes(job.status),true)).subscribe({next:job=>{if(context!==this.scope())return;this.generation.set(job);this.generationBusy.set(['created','queued','running'].includes(job.status));},error:()=>{if(context!==this.scope())return;this.generationBusy.set(false);this.error.set(this.i18n.t('runs.generation.unavailable'));}});onCleanup(()=>sub.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();const id=this.ragetId();if(!id)return;const sub=timer(0,2500).pipe(switchMap(()=>this.api.get<Generation>(`/evaluation/generations/${encodeURIComponent(id)}`)),takeWhile(job=>['created','queued','running'].includes(job.status),true)).subscribe({next:job=>{if(context!==this.scope())return;this.raget.set(job);this.ragetBusy.set(['created','queued','running'].includes(job.status));},error:()=>{if(context!==this.scope())return;this.ragetBusy.set(false);this.error.set(this.i18n.t('runs.generation.unavailable'));}});onCleanup(()=>sub.unsubscribe());});
 }
 addCase(){let next=this.caseDrafts.length+1;while(this.caseDrafts.some(row=>row.id===`case-${next}`))next++;this.caseDrafts=[...this.caseDrafts,newTestCase(next)];}removeCase(index:number){this.caseDrafts=this.caseDrafts.filter((_,i)=>i!==index);}suiteReady(){try{return !!this.suiteName.trim()&&serializeTestCases(this.caseDrafts).length>0;}catch{return false;}}
 importCases(){try{const raw=JSON.parse(this.casesText);if(!Array.isArray(raw)||raw.length>20)throw new Error();this.caseDrafts=raw.map((row,index)=>editTestCase(row,index+1));this.error.set('');}catch{this.error.set(this.t('invalid'));}}
 exportCases(){try{this.casesText=JSON.stringify(serializeTestCases(this.caseDrafts),null,2);}catch{this.error.set(this.t('invalid'));}}
 saveSuite():void{
  if(this.busy())return;const context=this.scope();let cases:Record<string,unknown>[];try{cases=serializeTestCases(this.caseDrafts);}catch{this.error.set(this.t('invalid'));return;}
  this.busy.set(true);this.error.set('');this.api.post<Suite>('/evaluation/suites',{schema_version:2,system_id:this.systemId(),name:this.suiteName.trim(),cases,reviewed:true,collection_ids:this.reviewCollectionId?[this.reviewCollectionId]:[],generation_job_id:this.reviewGenerationId || undefined}).subscribe({next:suite=>{if(context!==this.scope())return;this.suites.update(rows=>[suite,...rows]);this.suiteId=suite.id;this.busy.set(false);this.preflight.set(null);},error:()=>{if(context!==this.scope())return;this.busy.set(false);this.error.set(this.t('invalid'));}});
 }
 private comparisonBody(){return {suite_id:this.suiteId,baseline_run_id:this.effectiveBaseline(),expected_draft_revision:this.effectiveRevision(),execution_mode:this.executionMode,repeat_count:this.repeatCount};}
 preflightCurrent(){return this.checkedBody===JSON.stringify(this.comparisonBody());}
 checkPath(){if(this.busy())return;const context=this.scope(),body=this.comparisonBody(),fingerprint=JSON.stringify(body);this.busy.set(true);this.error.set('');this.preflight.set(null);this.api.post<Preflight>('/evaluation/campaigns/preflight',{...body,request_key:crypto.randomUUID()}).subscribe({next:check=>{if(context!==this.scope())return;this.preflight.set(check);this.checkedBody=fingerprint;this.busy.set(false);},error:()=>{if(context!==this.scope())return;this.busy.set(false);this.error.set(this.t('load_failed'));}});}
 compare():void{
  if(this.busy()||!this.preflightCurrent()||!this.preflight()?.eligible)return;const context=this.scope();const body={...this.comparisonBody(),preflight_sha256:this.preflight()?.preflight_sha256};const fingerprint=JSON.stringify(body);if(this.comparisonRequest?.body!==fingerprint)this.comparisonRequest={body:fingerprint,key:crypto.randomUUID()};this.busy.set(true);this.error.set('');
  this.api.post<Campaign>('/evaluation/campaigns',{...body,request_key:this.comparisonRequest.key}).subscribe({next:campaign=>{if(context!==this.scope())return;this.comparisonRequest=null;this.campaign.set(campaign);this.campaignId.set(campaign.id);this.campaigns.update(rows=>[campaign,...rows.filter(row=>row.id!==campaign.id)]);this.busy.set(false);void this.router.navigate([],{relativeTo:this.route,queryParams:{campaign:campaign.id},queryParamsHandling:'merge'});},error:()=>{if(context!==this.scope())return;this.busy.set(false);this.preflight.set(null);this.error.set(this.t('load_failed'));}});
 }
 selectCampaign(id:string):void {this.campaign.set(null);this.error.set('');this.campaignId.set(id);this.campaignRefresh.update(value=>value+1);}
 private retryKey(test:CampaignResult,index:number):string {return retryTarget(this.campaignId(),test.result_key || '',index===0?'baseline':'candidate');}
 retryNotice(test:CampaignResult,index:number){return this.retryNotices()[this.retryKey(test,index)];}
 retryMessage(notice:{kind:'sent'|'unknown'|'failed';code?:string|null;status?:number|null}):string {
  if(notice.kind!=='failed')return this.i18n.t(notice.kind==='sent'?'observability.assurance.retry_sent':'observability.assurance.retry_unknown');
  if(notice.status===401||notice.status===403)return this.i18n.t('observability.assurance.retry_denied');
  if(notice.status===409)return this.i18n.t('observability.assurance.retry_conflict');
  return this.i18n.t('observability.assurance.retry_failed');
 }
 retry(test:CampaignResult,index:number,side:CaseResult):void {
  const id=this.campaignId(),context=this.scope(),target=this.retryKey(test,index),notice=this.retryNotices()[target];
  if(!test.result_key || this.campaign()?.id!==id || (side.can_retry!==true&&notice?.kind!=='unknown'))return;
  const sideName:CampaignSide=index===0?'baseline':'candidate';
  if(!side.retry_source_run_id&&notice?.kind!=='unknown')return;
  const body=this.retryRequests.begin(target,{result_key:test.result_key,side:sideName,source_run_id:side.retry_source_run_id || side.run_id},()=>crypto.randomUUID());
  if(!body)return;
  this.retryNotices.update(rows=>({...rows,[target]:{kind:'sent'}}));
  settleWrite(this.api.post<Campaign>(`/evaluation/campaigns/${encodeURIComponent(id)}/retries`,body)).subscribe(outcome=>{
   if(context!==this.scope()||outcome.s==='sent')return;
   const current=campaignResponseCurrent(context,this.scope(),id,this.campaignId());
   if(outcome.s==='confirmed'||outcome.s==='accepted'){
    if(outcome.value.id!==id){this.retryRequests.settle(target,true);this.retryNotices.update(rows=>({...rows,[target]:{kind:'unknown'}}));return;}
    this.retryRequests.settle(target,false);this.retryNotices.update(rows=>{const next={...rows};delete next[target];return next;});if(current){this.campaign.set(outcome.value);this.campaignRefresh.update(value=>value+1);}
   }else{
    this.retryRequests.settle(target,outcome.s==='unknown');this.retryNotices.update(rows=>({...rows,[target]:{kind:outcome.s,code:outcome.code,status:outcome.status}}));if(current)this.campaignRefresh.update(value=>value+1);
   }
  });
 }
 checks(side:CaseResult){return [...(side.assertions || []),...(side.trajectory_assertions || [])];}
 reportSides(value:unknown):Array<{name:string;rows:string[]}>{if(!value||typeof value!=='object')return [];return Object.entries(value).map(([name,raw])=>{const side=raw as {cases?:unknown[]};return {name,rows:Array.isArray(side?.cases)?side.cases.map(readableOutput):[]};});}
 generate():void{if(this.generationBusy() || !this.collectionId)return;const context=this.scope();const body={system_id:this.systemId(),collection_ids:[this.collectionId],num_questions:3,language:this.i18n.locale()};const fingerprint=JSON.stringify(body);if(this.generationRequest?.body!==fingerprint)this.generationRequest={body:fingerprint,key:crypto.randomUUID()};this.error.set('');this.generationBusy.set(true);this.reviewCollectionId=this.collectionId;this.api.post<Generation>('/evaluation/generations',{...body,request_key:this.generationRequest.key}).subscribe({next:job=>{if(context!==this.scope())return;this.generationRequest=null;this.generation.set(job);this.generationId.set(job.id);},error:()=>{if(context!==this.scope())return;this.generationBusy.set(false);this.error.set(this.i18n.t('runs.generation.unavailable'));}});}
 reviewGenerated():void{const job=this.generation();if(job?.status !== 'completed' || !job.result?.cases?.length)return;this.reviewed=false;this.reviewGenerationId=job.id;this.suiteName=this.i18n.t('runs.generation.suite_name');this.caseDrafts=job.result.cases.map((test,index)=>editTestCase({id:test.id || `case-${index+1}`,input_ref:{question:test.question || ''},question:test.question,reference_answer:test.reference_answer,reference_context:test.reference_context,answer_path:[],assertions:[]},index+1));}
 evaluateRaget():void{const context=this.scope();const comparison=this.campaign();if(!comparison || this.ragetBusy())return;if(this.ragetRequest?.campaignId!==comparison.id)this.ragetRequest={campaignId:comparison.id,key:crypto.randomUUID()};const requestKey=this.ragetRequest.key;this.ragetBusy.set(true);this.api.post<Generation>(`/evaluation/campaigns/${encodeURIComponent(comparison.id)}/raget`,{request_key:requestKey}).subscribe({next:job=>{if(context!==this.scope())return;this.raget.set(job);this.ragetId.set(job.id);this.ragetRequest=null;},error:()=>{if(context!==this.scope())return;this.ragetBusy.set(false);this.error.set(this.i18n.t('runs.generation.raget_unavailable'));}});}
}
