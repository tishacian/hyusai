import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { timer, switchMap, takeWhile } from 'rxjs';
import { JsonPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { observabilityText } from '../observability/observability-labels';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { CorrectionReviewComponent } from './correction-review.component';
import type { Run } from '@app/core/canonical-api.service';

export interface ExaminedClaim { claim?: string; text?: string; verdict?: string; excerpt_ids?: string[]; response_span?: {start: number; end: number} | null; }
export interface ExaminedExcerpt { id: string; text: string | null; availability?: string; truncated?: boolean; document_ref?: string; page?: number; invocation_id?: string; }
export interface RunEvaluation { evaluation_id?: string; status: string; reason?: string; composite_score?: number | null; claim_audit?: { claims?: ExaminedClaim[] }; metadata?: { response_examined?: string; response_truncated?: boolean; excerpts?: ExaminedExcerpt[]; context_examined?: string; method?: string; [key: string]: unknown }; }

@Component({
 selector: 'app-run-investigation', standalone: true, imports: [JsonPipe, CorrectionReviewComponent, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
 template: `
 <section class="investigation" aria-labelledby="investigation-title">
  <header><h2 id="investigation-title">{{ i18n.t('runs.investigation.title') }}</h2>
   <button type="button" (click)="evaluate()" [disabled]="busy() || run().status !== 'completed'">{{ i18n.t('runs.investigation.evaluate') }}</button>
  </header>
  <div class="states"><span>{{ i18n.t('runs.investigation.execution') }}: {{code('status',run().status)}}</span>
   <span>{{ i18n.t('runs.investigation.evaluation') }}: {{code('status',evaluation()?.status || 'unavailable')}}</span>
   <span>{{ i18n.t('runs.investigation.human_separate') }}</span></div>
  @if (run().test_result; as test) {
   <details open>
    <summary>{{i18n.t('runs.investigation.test_criteria')}} · {{test.case_id}} · {{code('verdict',test.verdict)}}</summary>
    @for(check of test.assertions;track check.id){
     <p>{{check.id}} · {{code('verdict',check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'unevaluated')}}</p>
     @for(invocationId of check.invocation_ids;track invocationId){
      <p><a [navLink]="{type:'skill_invocation',runId:run().id,ref:invocationId}">{{i18n.t('runs.investigation.invocation')}} · {{invocationId}}</a></p>
     }
    }
   </details>
  }
  @if (error()) { <p role="alert">{{ error() }}</p> }
  @if (evaluation()?.reason) { <p class="reserve">{{code('reason',evaluation()?.reason)}}</p><details><summary>{{i18n.t('observability.quality.technical')}}</summary><code>{{evaluation()?.reason}}</code></details> }
  <div class="evidence-columns">
   <div><h3>{{ i18n.t('runs.investigation.answer') }}</h3>
    <p class="answer">@if(responseParts();as parts){ {{parts.before}}<mark>{{parts.selected}}</mark>{{parts.after}} } @else { {{ response() || i18n.t('runs.investigation.no_answer') }} }</p>
    @if (evaluation()?.metadata?.response_truncated) { <p>{{ i18n.t('runs.investigation.truncated') }}</p> }
    <h3>{{ i18n.t('runs.investigation.claims') }}</h3>
    @for (claim of claims(); track $index) {
     <button type="button" class="claim" [class.selected]="selected() === $index" [attr.aria-pressed]="selected() === $index" (click)="selectClaim($index)">
      <span>{{ claim.text || claim.claim }}</span><strong>{{code('verdict',claim.verdict)}}</strong>
     </button>
    } @empty { <p>{{ i18n.t('runs.investigation.no_claims') }}</p> }
   </div>
   <aside><h3>{{ i18n.t('runs.investigation.evidence') }}</h3>
    @for (excerpt of selectedExcerpts(); track excerpt.id) {
     <article class="excerpt"><strong>{{ excerpt.document_ref || i18n.t('runs.investigation.excerpt') }} @if (excerpt.page) { · {{i18n.t('observability.quality.page',{page:excerpt.page})}} }</strong><blockquote>{{ excerpt.availability === 'source_unavailable' ? i18n.t('observability.charts.source_unavailable') : excerpt.text }}</blockquote>@if(excerpt.truncated){<p>{{i18n.t('runs.investigation.truncated')}}</p>}
      @if (excerpt.invocation_id) { <p>{{ i18n.t('runs.investigation.invocation') }}: <a [navLink]="{type: 'skill_invocation', ref: excerpt.invocation_id}">{{ excerpt.invocation_id }}</a></p> }
     </article>
    } @empty { <p>{{ i18n.t('runs.investigation.no_evidence') }}</p> }
    <details><summary>{{ i18n.t('runs.investigation.method') }}</summary><p>{{code('method',evaluation()?.metadata?.method)}}</p><pre>{{ evaluation()?.metadata | json }}</pre></details>
   </aside>
  </div>
 @if (evaluation()?.evaluation_id; as evaluationId) {
  <app-correction-review [run]="run()" [evaluationId]="evaluationId" />
 }
 </section>`,
 styles: [`:host{display:block;margin:24px 0}.investigation{padding:24px;background:var(--ck-bg-panel);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:6px}header,.states{display:flex;gap:20px;align-items:center;flex-wrap:wrap}header{justify-content:space-between}h2{font-size:24px;font-weight:600}h3{font-size:16px;font-weight:600;margin:20px 0 12px}.states{font-size:13px;padding:16px 0;border-bottom:1px solid var(--ck-stroke-2)}.evidence-columns{display:grid;grid-template-columns:1fr 1fr;gap:32px}.answer,blockquote{white-space:pre-wrap;line-height:1.7;overflow-wrap:anywhere}.claim{display:flex;flex-direction:column;gap:10px;width:100%;text-align:left;margin:12px 0}.claim.selected{border-color:var(--ck-signal-cool);background:var(--ck-status-info-bg)}button{border:1px solid var(--ck-stroke-3);padding:12px 16px;border-radius:6px;color:inherit;background:transparent}button:disabled{opacity:.5}button:focus-visible,summary:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}.excerpt{padding:20px;background:var(--ck-bg-panel-hi);border-left:3px solid var(--ck-signal-cool)}mark{background:var(--ck-status-warn-bg);color:inherit}a{overflow-wrap:anywhere;color:var(--ck-signal-cool)}.reserve{color:var(--ck-signal-warn)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}details{margin-top:24px}@media(max-width:800px){.evidence-columns{grid-template-columns:1fr}.investigation{padding:16px}}`]
})
export class RunInvestigationComponent {
 code(category:string,value:unknown):string{return observabilityText(this.i18n,category,value);}
 readonly run = input.required<Run>();
 readonly i18n = inject(I18nService);
 private readonly api = inject(ApiService);
 private readonly workspace = inject(WorkspaceService);
 private readonly router = inject(Router);
 private readonly route = inject(ActivatedRoute);
 private readonly reload = signal(0);
 readonly evaluation = signal<RunEvaluation | null>(null);
 readonly error = signal('');
 readonly busy = signal(false);
 readonly selected = signal(0);
 readonly claims = computed(() => this.evaluation()?.claim_audit?.claims || []);
 readonly response = computed(() => this.evaluation()?.metadata?.response_examined || '');
 readonly responseParts = computed(() => {
  const claim=this.claims()[this.selected()];const span=claim?.response_span;const response=this.response();
  if(!span || span.start<0 || span.end<=span.start || span.end>response.length || response.slice(span.start,span.end)!==(claim.text || claim.claim))return null;
  return {before:response.slice(0,span.start),selected:response.slice(span.start,span.end),after:response.slice(span.end)};
 });
 readonly selectedExcerpts = computed(() => {
  const ids = this.claims()[this.selected()]?.excerpt_ids || [];
  return (this.evaluation()?.metadata?.excerpts || []).filter(e => ids.includes(String(e.id)));
 });
 constructor() {
  effect(onCleanup => {
   this.reload();
   const id = this.run().id; const workspaceId = this.workspace.current()?.id;
   this.evaluation.set(null); this.error.set('');
   this.selected.set(Math.max(0, Number(this.route.snapshot.queryParamMap.get('claim')) || 0));
   const subscription = timer(0, 2500).pipe(
    switchMap(() => this.api.get<RunEvaluation>(`/evaluation/by-run/${encodeURIComponent(id)}`)),
    takeWhile(value => ['queued', 'running', 'pending'].includes(value.status), true),
   ).subscribe({
    next: value => { if (this.run().id === id && this.workspace.current()?.id === workspaceId) this.evaluation.set(value); },
    error: () => this.error.set(this.i18n.t('runs.investigation.load_failed')),
   });
   onCleanup(() => subscription.unsubscribe());
  });
 }
 selectClaim(index: number): void {
  this.selected.set(index);
  void this.router.navigate([], {relativeTo:this.route,queryParams:{claim:index},queryParamsHandling:'merge',replaceUrl:true});
 }
 evaluate(): void {
  if(this.busy()) return;
  this.busy.set(true); this.error.set('');
  const id=this.run().id; const workspaceId=this.workspace.current()?.id;
  this.api.post<RunEvaluation>(`/evaluation/by-run/${encodeURIComponent(id)}/score`, {idempotency_key:crypto.randomUUID()}).subscribe({
   next: value => {if(this.run().id===id && this.workspace.current()?.id===workspaceId) {this.evaluation.set(value);this.reload.update(n=>n+1);}this.busy.set(false);},
   error: () => {this.busy.set(false);this.error.set(this.i18n.t('runs.investigation.load_failed'));}
  });
 }
}
