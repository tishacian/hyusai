import { formatInstant } from '@app/core/format-instant';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { AuthStore } from '@app/store/auth.store';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { TypedJudgeResultComponent } from '../data/typed-judge-result.component';
import { qualityMessage, qualityState, type QualityMessage } from './quality-messages';
import { orderedEvaluationRecords, type EvaluationRecord, type EvaluationSummary } from './evaluation-records.models';

@Component({selector:'app-evaluation-records',standalone:true,changeDetection:ChangeDetectionStrategy.OnPush,
 imports:[JsonPipe,NavLinkDirective,TypedJudgeResultComponent],
 template:`<section class="quality-records" data-testid="evaluation-records" [attr.aria-label]="t('title')">
  <header><div><h2>{{t('title')}}</h2><p>{{t('recorded')}}</p></div><button type="button" (click)="reload.update(increment)" [disabled]="loading()">{{t('refresh')}}</button></header>
  @if(loading()){<p role="status">{{t('loading')}}</p>}
  @if(error()){<p role="alert">{{t('unavailable')}}</p>}
  @if(summary();as summary){
   <dl class="quality-stats"><div><dt>{{t('evaluations')}}</dt><dd>{{summary.totals.evaluations}}</dd></div><div><dt>{{t('assessed')}}</dt><dd>{{summary.totals.assessed}} / {{summary.totals.evaluations}}</dd></div><div><dt>{{t('technical')}}</dt><dd>{{summary.totals.technical_failures}}</dd></div><div><dt>{{t('unassessed')}}</dt><dd>{{summary.totals.unassessed}}</dd></div></dl>
   <p class="quality-note">{{t('denominator')}}</p>
   @for(control of summary.unrecorded_controls || [];track control.id){<p role="status">{{control.node_id || t('title')}} · {{t('execution')}}: {{state(control.execution_status,true)}} · {{t('verdict')}}: {{state(control.quality_status)}} @if(runId()){<a [navLink]="{type:'skill_invocation',runId:runId() || undefined,ref:control.producer_invocation_id}">{{t('invocation')}}</a>}</p>}
   <div class="quality-list">@for(record of records();track record.id){
    <article class="quality-record" [class.is-selected]="selectedId()===record.id">
     <button class="quality-select" type="button" (click)="open(record)" [attr.aria-expanded]="selectedId()===record.id" [attr.aria-label]="t('open')+' · '+label(record)">
      <span><strong>{{label(record)}}</strong><small>{{date(record.created_at)}} · {{record.source}}</small></span>
      <span class="quality-statuses"><span>{{t('execution')}}: {{state(record.execution_status,true)}}</span><span>{{t('verdict')}}: {{state(record.quality_status)}}</span></span>
     </button>
     @if(selectedId()===record.id){<div class="quality-detail">
      <div class="quality-links">@if(record.run_id){<a [navLink]="{type:'run',ref:record.run_id,params:{facet:'quality',evaluationId:record.id}}">{{t('run')}}</a>}
       @if(record.run_id && record.producer_invocation_id){<a [navLink]="{type:'skill_invocation',runId:record.run_id,ref:record.producer_invocation_id}">{{t('invocation')}}</a>}</div>
      @if(detailLoading()){<p role="status">{{t('loading')}}</p>}
      @if(detailError()){<p role="alert">{{t('unavailable')}}</p>}
      @if(selectedDetail();as detail){
       @if(detail.evidence_availability==='unavailable'){<p role="status">{{t('evidence_unavailable')}}</p>}
       @if(detail.typed_evaluation){<app-typed-judge-result [value]="detail.typed_evaluation" [compact]="true" [runId]="detail.run_id" [invocationId]="detail.producer_invocation_id || null" [evidenceSources]="detail.evidence_sources || []" />}
       @else {<p>{{t('verdict')}}: {{state(detail.quality_status)}}</p>@if(detail.metrics?.composite_score!=null){<p>{{detail.metrics?.composite_score}} / 100</p>}}
       <p class="quality-note">{{t('human')}} @if(detail.review?.count){ · {{t('review_count')}}: {{detail.review?.count}} }</p>
       <details><summary>{{t('details')}}</summary><pre>{{technical(detail) | json}}</pre></details>
      }
     </div>}
    </article>
   }@empty{<p>{{t('empty')}}</p>}</div>
   @if(summary.has_more){<p class="quality-note">{{i18n.t('observability.assurance.recent_records',{count:records().length,total:summary.totals.evaluations})}}</p>}
  }
 </section>`,
 styles:`:host{display:block}.quality-records{border:1px solid var(--ck-stroke-2);border-radius:6px;background:var(--ck-bg-panel);padding:18px;color:var(--ck-fg-1)}header{display:flex;justify-content:space-between;align-items:start;gap:16px}h2{font-size:16px;margin:0 0 5px}p{margin:8px 0;line-height:1.5}header p,.quality-note,small{font-size:12px;color:var(--ck-fg-3)}button{font:inherit;font-size:12px;border:1px solid var(--ck-stroke-2);background:transparent;color:inherit;border-radius:4px;padding:6px 10px;cursor:pointer}button:disabled{opacity:.5;cursor:default}.quality-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:18px 0}.quality-stats dt{font-size:12px;color:var(--ck-fg-3)}.quality-stats dd{font-size:24px;font-variant-numeric:tabular-nums;margin:6px 0}.quality-list{border-top:1px solid var(--ck-stroke-2)}.quality-record{border-bottom:1px solid var(--ck-stroke-2)}.quality-select{border:0;display:flex;justify-content:space-between;gap:16px;width:100%;text-align:start;padding:12px 0;min-height:44px}.quality-select small{display:block;margin-top:5px}.quality-statuses{display:flex;flex-direction:column;gap:5px;font-size:12px;text-align:end}.is-selected .quality-select{color:var(--ck-signal-cool)}.quality-detail{padding:0 0 14px}.quality-links{display:flex;gap:16px;margin:8px 0}.quality-links a{font-size:12px;color:var(--ck-signal-cool)}details{margin-top:12px;font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto}button:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}@media(max-width:640px){.quality-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.quality-select{flex-direction:column}.quality-statuses{text-align:start}.quality-records{padding:12px}}`})
export class EvaluationRecordsComponent {
 readonly runId=input<string|null>(null);readonly systemId=input('');readonly since=input('7d');readonly asOf=input('');readonly traffic=input<'business'|'evaluation'|'all'>('business');
 readonly i18n=inject(I18nService);private readonly api=inject(ApiService);private readonly workspace=inject(WorkspaceService);private readonly auth=inject(AuthStore);private readonly route=inject(ActivatedRoute);private readonly router=inject(Router);
 readonly summary=signal<EvaluationSummary|null>(null);readonly records=computed(()=>orderedEvaluationRecords(this.summary()?.records ?? []));readonly loading=signal(false);readonly error=signal(false);readonly reload=signal(0);readonly increment=(n:number)=>n+1;
 readonly selectedId=signal<string|null>(this.route.snapshot.queryParamMap.get('evaluationId'));readonly selectedDetail=signal<EvaluationRecord|null>(null);readonly detailLoading=signal(false);readonly detailError=signal(false);
 private readonly queryParams=toSignal(this.route.queryParamMap,{initialValue:this.route.snapshot.queryParamMap});
 t(key:QualityMessage){return qualityMessage(this.i18n,key);}state(value:unknown,execution=false){return qualityState(this.i18n,value,execution);}date(value:string|null){return formatInstant(value,this.i18n.locale(),{seconds:true})??this.t('unknown');}label(record:EvaluationRecord){return record.rubric?.id ? record.rubric.id+(record.rubric.version != null?' · '+record.rubric.version:'') : record.source;}
 technical(record:EvaluationRecord){return {evaluation_id:record.evaluation_id,source:record.source,run_id:record.run_id,producer_invocation_id:record.producer_invocation_id,execution_status:record.execution_status,quality_status:record.quality_status,rubric:record.rubric,coverage:record.coverage,metrics:record.metrics,evidence_availability:record.evidence_availability};}
 private principal(){return JSON.stringify([this.workspace.current()?.id,this.auth.authEpoch()]);}
 constructor(){
  effect(()=>{this.selectedId.set(this.queryParams().get('evaluationId'));});
  effect(cleanup=>{this.reload();const run=this.runId(),system=this.systemId(),since=this.since(),asOf=this.asOf(),traffic=this.traffic(),wid=this.principal();this.summary.set(null);this.error.set(false);this.loading.set(true);
   const endpoint=run?`/evaluation/by-run/${encodeURIComponent(run)}/summary`:'/evaluation/summary';const params=run?{}:{since,traffic,...(system?{system_id:system}:{}),...(asOf?{as_of:asOf}:{})};
   const sub=this.api.get<EvaluationSummary>(endpoint,params).subscribe({next:value=>{if(wid!==this.principal())return;if(value?.schema_version===1 && Array.isArray(value.records) && value.totals){this.summary.set(value);}else{this.error.set(true);}this.loading.set(false);},error:()=>{if(wid!==this.principal())return;this.loading.set(false);this.error.set(true);}});cleanup(()=>sub.unsubscribe());
  });
  effect(cleanup=>{const id=this.selectedId(),rows=this.records(),wid=this.principal();this.selectedDetail.set(null);this.detailError.set(false);this.detailLoading.set(false);if(!id||!rows.some(row=>row.id===id))return;this.detailLoading.set(true);const sub=this.api.get<EvaluationRecord>(`/evaluation/records/${encodeURIComponent(id)}`).subscribe({next:record=>{if(wid!==this.principal()||this.selectedId()!==id)return;this.selectedDetail.set(record);this.detailLoading.set(false);},error:()=>{if(wid!==this.principal()||this.selectedId()!==id)return;this.detailError.set(true);this.detailLoading.set(false);}});cleanup(()=>sub.unsubscribe());});
 }
 open(record:EvaluationRecord){this.selectedId.update(id=>id===record.id?null:record.id);void this.router.navigate([],{relativeTo:this.route,queryParams:{evaluationId:this.selectedId()},queryParamsHandling:'merge',replaceUrl:true});}
}
