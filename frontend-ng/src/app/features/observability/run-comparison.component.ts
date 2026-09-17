import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { formatSkillCost } from '../skills/skill-cost';
import { observabilityText, observabilityNumber } from './observability-labels';
import { FormsModule } from '@angular/forms';
import { JsonPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { timer, switchMap, takeWhile } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import type { RunAssertionResult } from '@app/core/canonical-api.service';
interface Suite {id:string;name:string;revision:number;cases:unknown[];}
interface CaseResult {run_id:string;status:string;verdict:string;output_ref:unknown;duration_ms:number|null;execution_cost:number|null;assertions:RunAssertionResult[];}
interface Campaign {id:string;status:string;method:string;snapshot:{comparability:string;limitations:unknown[]};results:Array<{case_id:string;change:string;baseline:CaseResult;candidate:CaseResult}>;}
interface Generation {id:string;status:string;stage:string;progress:number;error?:string;result?:{cases?:Array<{id?:string;question?:string;reference_answer?:string;reference_context?:string}>;method?:string;version?:string;usage?:unknown;models?:unknown;coverage?:unknown;sides?:unknown};}
interface CollectionOption {id:string;name:string;status:string;}
@Component({selector:'app-run-comparison',standalone:true,imports:[FormsModule,JsonPipe,NavLinkDirective],changeDetection:ChangeDetectionStrategy.OnPush,
 template:`<section class="comparison">
 <h2>{{i18n.t('runs.comparison.title')}}</h2>
 <p>{{i18n.t('runs.comparison.scope')}}</p>
 <div class="controls"><label>{{i18n.t('runs.comparison.suite')}}<select [(ngModel)]="suiteId">@for(suite of suites();track suite.id){<option [value]="suite.id">{{suite.name}} · {{suite.revision}}</option>}</select></label>
 <button type="button" (click)="compare()" [disabled]="busy() || !suiteId || !draftRevision()">{{i18n.t('runs.comparison.start')}}</button></div>
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
 <details><summary>{{i18n.t('runs.comparison.create_suite')}}</summary>
  <label>{{i18n.t('runs.comparison.name')}}<input [(ngModel)]="suiteName" /></label>
  <label>{{i18n.t('runs.comparison.cases')}}<textarea rows="8" [(ngModel)]="casesText"></textarea></label>
  <p>{{i18n.t('runs.comparison.oracle')}}</p>
  @if(reviewGenerationId){<p>{{i18n.t('runs.generation.mapping')}}</p>}
  <label><input type="checkbox" [(ngModel)]="reviewed" />{{i18n.t('runs.comparison.reviewed')}}</label>
  <button type="button" (click)="saveSuite()" [disabled]="busy() || !reviewed || !suiteName">{{i18n.t('runs.comparison.save')}}</button>
 </details>
 @if(campaign();as comparison){
  <h3>{{i18n.t('runs.comparison.status')}}: {{code('status',comparison.status)}}</h3>
  <p>{{code('method',comparison.method)}} · {{code('comparability',comparison.snapshot.comparability)}}</p>
  @for(limitation of comparison.snapshot.limitations;track $index){<p>{{code('limitation',limitation)}}</p><details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{limitation | json}}</pre></details>}
  @for(test of comparison.results;track test.case_id){
   <article><h3>{{test.case_id}} · {{code('change',test.change)}}</h3>
    <div class="columns">
     @for(side of [test.baseline,test.candidate];track $index){
      <div><strong>{{i18n.t($index === 0 ? 'runs.comparison.baseline' : 'runs.comparison.candidate')}}</strong>
       <p>{{code('status',side.status)}} · {{code('verdict',side.verdict)}}</p><pre>{{side.output_ref | json}}</pre>
       @if(side.run_id){<a [navLink]="{type:'run',ref:side.run_id}">{{i18n.t('runs.comparison.proof')}}</a>}
       <details><summary>{{i18n.t('runs.comparison.assertions')}}</summary>
        @for(check of side.assertions;track check.id){
         <p>{{check.id}} · {{code('verdict',check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'unevaluated')}}</p>
         @for(invocationId of check.invocation_ids;track invocationId){
          <p><a [navLink]="{type:'skill_invocation',runId:side.run_id,ref:invocationId}">{{i18n.t('runs.investigation.invocation')}} · {{invocationId}}</a></p>
         }
        }
        <details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{side.assertions | json}}</pre></details><p>{{i18n.t('runs.comparison.cost')}}: {{cost(side.execution_cost)}} · {{i18n.t('observability.quality.milliseconds',{value:number(side.duration_ms)})}}</p></details>
      </div>
     }
    </div>
   </article>
  }
  <a [navLink]="{leaf:'system-flow',ref:systemId()}">{{i18n.t('runs.comparison.publication')}}</a>
  @if(comparison.status === 'completed'){<button type="button" (click)="evaluateRaget()" [disabled]="ragetBusy()">{{i18n.t('runs.generation.evaluate')}}</button>}
  @if(raget();as report){<p aria-live="polite">{{code('status',report.status)}} · {{code('stage',report.stage)}}</p>@if(report.error){<p role="alert">{{code('reason',report.error)}}</p><details><summary>{{i18n.t('observability.quality.technical')}}</summary><pre>{{report.error}}</pre></details>}@if(report.result?.sides){<details open><summary>{{i18n.t('runs.generation.report')}}</summary><pre>{{report.result?.sides | json}}</pre></details>}}
 }
 </section>`,
 styles:[`.comparison{padding:24px;border-top:1px solid var(--ck-stroke-2);color:var(--ck-fg-1)}h2{font-size:24px;font-weight:600}h3{font-size:18px;margin:20px 0}p{margin:12px 0;line-height:1.6}.controls{display:flex;align-items:end;gap:16px;flex-wrap:wrap}label{display:block;margin:12px 0}select,input,textarea,button{background:var(--ck-bg-panel);color:inherit;border:1px solid var(--ck-stroke-3);padding:10px;border-radius:6px}textarea{display:block;width:100%;font-family:monospace}select{display:block;min-width:240px}button:disabled{opacity:.5}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}.columns>div{min-width:0;padding:20px;background:var(--ck-bg-panel-hi)}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere;color:var(--ck-signal-cool);text-decoration:underline}details{margin:16px 0}article{border-top:1px solid var(--ck-stroke-2);margin-top:24px}@media(max-width:800px){.columns{grid-template-columns:1fr}}`]
})
export class RunComparisonComponent {
 code(category:string,value:unknown):string{return observabilityText(this.i18n,category,value);}
 number(value:number|null|undefined,digits=0):string{return observabilityNumber(value,this.i18n.locale(),digits);}
 cost(value:number|null|undefined):string{return formatSkillCost(value,'USD',this.i18n.locale());}
 readonly systemId=input.required<string>();readonly baselineRunId=input.required<string>();readonly draftRevision=input<number|null>(null);
 readonly i18n=inject(I18nService);private readonly api=inject(ApiService);private readonly workspace=inject(WorkspaceService);private readonly router=inject(Router);private readonly route=inject(ActivatedRoute);
 readonly suites=signal<Suite[]>([]);readonly campaign=signal<Campaign|null>(null);readonly campaignId=signal('');readonly error=signal('');readonly busy=signal(false);
 readonly collections=signal<CollectionOption[]>([]);readonly generation=signal<Generation|null>(null);readonly generationId=signal('');readonly generationBusy=signal(false);readonly raget=signal<Generation|null>(null);readonly ragetId=signal('');readonly ragetBusy=signal(false);
 collectionId='';reviewCollectionId='';reviewGenerationId='';private ragetRequest:{campaignId:string;key:string}|null=null;
 private comparisonRequest:{body:string;key:string}|null=null;private generationRequest:{body:string;key:string}|null=null;
 private scope():string{return JSON.stringify([this.workspace.current()?.id,this.systemId()]);}
 suiteId='';suiteName='';reviewed=false;casesText='[\n  {"id":"case-1","input_ref":{},"assertions":[]}\n]';
 constructor(){
  effect(onCleanup=>{const context=this.scope();const system=this.systemId();this.suites.set([]);this.campaign.set(null);this.campaignId.set(this.route.snapshot.queryParamMap.get('campaign') || '');const subscription=this.api.get<Suite[]>('/evaluation/suites',{system_id:system}).subscribe({next:rows=>{if(context===this.scope())this.suites.set(rows);},error:()=>{if(context===this.scope())this.error.set(this.i18n.t('runs.comparison.unavailable'));}});onCleanup(()=>subscription.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();const id=this.campaignId();if(!id)return;const subscription=timer(0,2500).pipe(switchMap(()=>this.api.get<Campaign>(`/evaluation/campaigns/${encodeURIComponent(id)}`)),takeWhile(value=>['queued','running'].includes(value.status),true)).subscribe({next:value=>{if(context===this.scope())this.campaign.set(value);},error:()=>{if(context===this.scope())this.error.set(this.i18n.t('runs.comparison.unavailable'));}});onCleanup(()=>subscription.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();this.comparisonRequest=null;this.generationRequest=null;this.ragetRequest=null;this.collections.set([]);this.generation.set(null);this.generationId.set('');this.raget.set(null);this.ragetId.set('');this.reviewGenerationId='';this.reviewCollectionId='';this.collectionId='';this.reviewed=false;this.suiteId='';this.suiteName='';this.casesText='[]';this.generationBusy.set(false);this.ragetBusy.set(false);this.busy.set(false);const sub=this.api.get<{items?:CollectionOption[]}>('/documents/collections').subscribe({next:value=>{if(context===this.scope())this.collections.set(value.items || []);},error:()=>{if(context===this.scope())this.error.set(this.i18n.t('runs.generation.unavailable'));}});onCleanup(()=>sub.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();const id=this.generationId();if(!id)return;const sub=timer(0,2000).pipe(switchMap(()=>this.api.get<Generation>(`/evaluation/generations/${encodeURIComponent(id)}`)),takeWhile(job=>['created','queued','running'].includes(job.status),true)).subscribe({next:job=>{if(context!==this.scope())return;this.generation.set(job);this.generationBusy.set(['created','queued','running'].includes(job.status));},error:()=>{if(context!==this.scope())return;this.generationBusy.set(false);this.error.set(this.i18n.t('runs.generation.unavailable'));}});onCleanup(()=>sub.unsubscribe());});
  effect(onCleanup=>{const context=this.scope();const id=this.ragetId();if(!id)return;const sub=timer(0,2500).pipe(switchMap(()=>this.api.get<Generation>(`/evaluation/generations/${encodeURIComponent(id)}`)),takeWhile(job=>['created','queued','running'].includes(job.status),true)).subscribe({next:job=>{if(context!==this.scope())return;this.raget.set(job);this.ragetBusy.set(['created','queued','running'].includes(job.status));},error:()=>{if(context!==this.scope())return;this.ragetBusy.set(false);this.error.set(this.i18n.t('runs.generation.unavailable'));}});onCleanup(()=>sub.unsubscribe());});
 }
 saveSuite():void{
  if(this.busy())return;const context=this.scope();let cases:unknown;try{cases=JSON.parse(this.casesText);}catch{this.error.set(this.i18n.t('runs.comparison.invalid'));return;}
  this.busy.set(true);this.api.post<Suite>('/evaluation/suites',{system_id:this.systemId(),name:this.suiteName,cases,reviewed:this.reviewed,collection_ids:this.reviewCollectionId?[this.reviewCollectionId]:[],generation_job_id:this.reviewGenerationId || undefined}).subscribe({next:suite=>{if(context!==this.scope())return;this.suites.update(rows=>[suite,...rows]);this.suiteId=suite.id;this.busy.set(false);},error:()=>{if(context!==this.scope())return;this.busy.set(false);this.error.set(this.i18n.t('runs.comparison.invalid'));}});
 }
 compare():void{
  if(this.busy() || !this.draftRevision())return;const context=this.scope();const body={suite_id:this.suiteId,baseline_run_id:this.baselineRunId(),expected_draft_revision:this.draftRevision()};const fingerprint=JSON.stringify(body);if(this.comparisonRequest?.body!==fingerprint)this.comparisonRequest={body:fingerprint,key:crypto.randomUUID()};this.busy.set(true);this.error.set('');
  this.api.post<Campaign>('/evaluation/campaigns',{...body,request_key:this.comparisonRequest.key}).subscribe({next:campaign=>{if(context!==this.scope())return;this.comparisonRequest=null;this.campaign.set(campaign);this.campaignId.set(campaign.id);this.busy.set(false);void this.router.navigate([],{relativeTo:this.route,queryParams:{campaign:campaign.id},queryParamsHandling:'merge'});},error:()=>{if(context!==this.scope())return;this.busy.set(false);this.error.set(this.i18n.t('runs.comparison.unavailable'));}});
 }
 generate():void{if(this.generationBusy() || !this.collectionId)return;const context=this.scope();const body={system_id:this.systemId(),collection_ids:[this.collectionId],num_questions:3,language:this.i18n.locale()};const fingerprint=JSON.stringify(body);if(this.generationRequest?.body!==fingerprint)this.generationRequest={body:fingerprint,key:crypto.randomUUID()};this.error.set('');this.generationBusy.set(true);this.reviewCollectionId=this.collectionId;this.api.post<Generation>('/evaluation/generations',{...body,request_key:this.generationRequest.key}).subscribe({next:job=>{if(context!==this.scope())return;this.generationRequest=null;this.generation.set(job);this.generationId.set(job.id);},error:()=>{if(context!==this.scope())return;this.generationBusy.set(false);this.error.set(this.i18n.t('runs.generation.unavailable'));}});}
 reviewGenerated():void{const job=this.generation();if(job?.status !== 'completed' || !job.result?.cases?.length)return;this.reviewed=false;this.reviewGenerationId=job.id;this.suiteName=this.i18n.t('runs.generation.suite_name');this.casesText=JSON.stringify(job.result.cases.map((test,index)=>({id:test.id || `case-${index+1}`,input_ref:{question:test.question},question:test.question,reference_answer:test.reference_answer,reference_context:test.reference_context,answer_path:[],assertions:[]})),null,2);}
 evaluateRaget():void{const context=this.scope();const comparison=this.campaign();if(!comparison || this.ragetBusy())return;if(this.ragetRequest?.campaignId!==comparison.id)this.ragetRequest={campaignId:comparison.id,key:crypto.randomUUID()};const requestKey=this.ragetRequest.key;this.ragetBusy.set(true);this.api.post<Generation>(`/evaluation/campaigns/${encodeURIComponent(comparison.id)}/raget`,{request_key:requestKey}).subscribe({next:job=>{if(context!==this.scope())return;this.raget.set(job);this.ragetId.set(job.id);this.ragetRequest=null;},error:()=>{if(context!==this.scope())return;this.ragetBusy.set(false);this.error.set(this.i18n.t('runs.generation.raget_unavailable'));}});}
}
