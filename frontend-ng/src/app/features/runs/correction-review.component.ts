import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { RunComparisonComponent } from '@app/features/observability/run-comparison.component';
import type { Run } from '@app/core/canonical-api.service';

interface CorrectionContext { run_id: string; system_id: string; node_id: string; evaluation_id: string; expected_draft_revision: number; template: string; }
interface CorrectionProposal { id: string; status: string; proposal_sha256: string; applied_revision: number | null; proposal: { run_id: string; system_id: string; node_id: string; evaluation_id: string; expected_draft_revision: number; original_template: string; replacement_template: string; rationale: string; diff: string; }; }
interface AssistantProposalResponse { answer: string; tool_calls?: Array<{ name: string; ok: boolean; result?: CorrectionProposal & { ok?: boolean } }>; }

@Component({
 selector: 'app-correction-review', standalone: true, imports: [FormsModule, RunComparisonComponent], changeDetection: ChangeDetectionStrategy.OnPush,
 template: `
 <section class="correction" aria-labelledby="correction-title">
  <header><h3 id="correction-title">{{ i18n.t('runs.correction.title') }}</h3><p>{{ i18n.t('runs.correction.scope') }}</p></header>
  @if (previousProposals().length) {
   <details><summary>{{ i18n.t('runs.correction.title') }} · {{ previousProposals().length }}</summary>
    <div class="actions">@for (saved of previousProposals(); track saved.id) {
     <button type="button" [disabled]="busy()" (click)="selectSavedProposal(saved)">{{ saved.proposal.node_id }} · {{ saved.proposal.rationale }} · {{ i18n.t('runs.correction.revision') }} {{ saved.applied_revision || saved.proposal.expected_draft_revision }}</button>
    }</div>
   </details>
  }
  @if (!proposal()) {
   <label for="correction-node">{{ i18n.t('runs.correction.node') }}</label>
   <div class="actions"><select id="correction-node" [ngModel]="nodeId()" (ngModelChange)="chooseNode($event)" [disabled]="busy()">
    <option value="">{{ i18n.t('runs.correction.choose') }}</option>
    @for (node of nodes(); track node.id) { <option [value]="node.id">{{ node.label }}</option> }
   </select><button type="button" (click)="inspect()" [disabled]="busy() || !nodeId() || !evaluationId()">{{ i18n.t('runs.correction.inspect') }}</button></div>
   @if (!nodes().length) { <p>{{ i18n.t('runs.correction.no_nodes') }}</p> }
  }
  @if (error()) { <p role="alert" class="error">{{ error() }}</p> }
  @if (context(); as ctx) {
   @if (!proposal()) {
    <p>{{ i18n.t('runs.correction.revision') }} {{ ctx.expected_draft_revision }} · {{ ctx.node_id }}</p>
    <button type="button" (click)="suggest()" [disabled]="busy()">{{ i18n.t('runs.correction.suggest') }}</button>
    @if (assistantAnswer()) { <p class="answer">{{ assistantAnswer() }}</p> }
    <details><summary>{{ i18n.t('runs.correction.manual') }}</summary>
     <label for="correction-template">{{ i18n.t('runs.correction.template') }}</label>
     <textarea id="correction-template" rows="8" maxlength="8000" [ngModel]="template()" (ngModelChange)="template.set($event)" [disabled]="busy()"></textarea>
     <label for="correction-rationale">{{ i18n.t('runs.correction.rationale') }}</label>
     <textarea id="correction-rationale" rows="3" maxlength="2000" [ngModel]="rationale()" (ngModelChange)="rationale.set($event)" [disabled]="busy()"></textarea>
     <button type="button" (click)="prepare()" [disabled]="busy() || !rationale().trim() || template() === ctx.template">{{ i18n.t('runs.correction.prepare') }}</button>
    </details>
   }
  }
  @if (proposal(); as p) {
   <p>{{ p.proposal.rationale }}</p>
   <div class="versions"><article><h4>{{ i18n.t('runs.correction.reference') }}</h4><pre>{{ p.proposal.original_template }}</pre></article><article><h4>{{ i18n.t('runs.correction.candidate') }}</h4><pre>{{ p.proposal.replacement_template }}</pre></article></div>
   <details><summary>{{ i18n.t('runs.correction.diff') }}</summary><pre>{{ p.proposal.diff }}</pre></details>
   @if (p.status === 'applied') {
    <p role="status">{{ i18n.t('runs.correction.applied') }} {{ p.applied_revision }}</p>
    <button type="button" (click)="openDraft()">{{ i18n.t('runs.correction.open_draft') }}</button>
    <app-run-comparison [systemId]="p.proposal.system_id" [baselineRunId]="run().id" [draftRevision]="p.applied_revision" />
   } @else {
    @if (!applicationAllowed()) { <p role="status">{{ i18n.t('runs.correction.unsaved') }}</p> }
    <label class="review"><input type="checkbox" [ngModel]="reviewed()" (ngModelChange)="reviewed.set($event)" [disabled]="busy()">{{ i18n.t('runs.correction.reviewed') }}</label>
    <div class="actions"><button type="button" (click)="apply()" [disabled]="busy() || !reviewed() || !applicationAllowed()">{{ i18n.t('runs.correction.apply') }}</button><button type="button" (click)="resetProposal()" [disabled]="busy()">{{ i18n.t('runs.correction.revise') }}</button></div>
   }
  }
  @if (busy()) { <p role="status">{{ i18n.t('runs.correction.working') }}</p> }
 </section>`,
 styles: [`:host{display:block}.correction{padding:24px;border:1px solid var(--ck-stroke-2);border-radius:6px;background:var(--ck-bg-panel);color:var(--ck-fg-1)}h3{font-size:20px;margin:0 0 12px}label{display:block;margin:16px 0 8px}select,textarea,button{font:inherit;color:inherit;background:var(--ck-bg-panel);border:1px solid var(--ck-stroke-3);border-radius:6px;padding:10px 12px}textarea{display:block;width:100%;box-sizing:border-box;margin-bottom:12px}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}.actions{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.versions{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{min-width:0;background:var(--ck-bg-panel-hi);padding:16px}pre,.answer{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}pre{font-size:13px}details{margin:20px 0}.review{display:flex;gap:12px;align-items:flex-start}.error{color:var(--ck-signal-warn)}a{color:var(--ck-signal-cool)}button:focus-visible,textarea:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}@media(max-width:800px){.versions{grid-template-columns:1fr}.correction{padding:16px}}`]
})
export class CorrectionReviewComponent {
 readonly run = input.required<Run>();
 readonly evaluationId = input.required<string>();
 readonly proposalId = input<string | null>(null);
 readonly applicationAllowed = input(true);
 readonly applied = output<{ proposalId: string; revision: number }>();
 readonly i18n = inject(I18nService);
 private readonly api = inject(ApiService);
 private readonly destroyRef = inject(DestroyRef);
 private readonly workspace = inject(WorkspaceService);
 private readonly route = inject(ActivatedRoute);
 private readonly router = inject(Router);
 private readonly navigation = inject(ZoomContextService);
 readonly nodeId = signal(''); readonly context = signal<CorrectionContext | null>(null);
 readonly previousProposals = signal<CorrectionProposal[]>([]);
 readonly proposal = signal<CorrectionProposal | null>(null); readonly reviewed = signal(false);
 readonly busy = signal(false); readonly error = signal(''); readonly assistantAnswer = signal('');
 readonly template = signal(''); readonly rationale = signal('');
 readonly nodes = computed(() => {
  const nodes = new Map<string, string>();
  for (const cp of this.run().checkpoints || []) { const id = cp['node_id']; if (typeof id === 'string' && !id.startsWith('__')) nodes.set(id, typeof cp['node_label'] === 'string' ? cp['node_label'] : id); }
  for (const invocation of this.run().skill_invocations || []) { const id = invocation.trace?.['node_id']; if (typeof id === 'string') nodes.set(id, `${id} · ${invocation.skill_slug || ''}`); }
  return [...nodes].map(([id, label]) => ({id, label}));
 });
 constructor() {
  effect(onCleanup => {
   const runId = this.run().id; this.workspace.current(); const workspaceId = this.workspace.captureRequestScope();
   const proposalId = this.proposalId() || this.route.snapshot.queryParamMap.get('correction');
   this.context.set(null); this.proposal.set(null); this.error.set(''); this.reviewed.set(false); this.busy.set(false); this.nodeId.set(''); this.previousProposals.set([]);
   if (!proposalId) {
    const sub = this.api.get<{corrections:CorrectionProposal[]}>('/evaluation/corrections', {run_id:runId}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
     next: result => { if (this.isCurrent(runId, workspaceId)) this.previousProposals.set(result.corrections.filter(p => p.proposal.run_id === runId && p.proposal.system_id === this.run().system_id)); },
     error: e => { if (this.isCurrent(runId, workspaceId)) this.fail(e); },
    });
    onCleanup(() => sub.unsubscribe());
    return;
   }
   const sub = this.api.get<CorrectionProposal>(`/evaluation/corrections/${encodeURIComponent(proposalId)}`).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({ next: p => { if (this.isCurrent(runId, workspaceId) && p.proposal.run_id === runId) { this.proposal.set(p); this.nodeId.set(p.proposal.node_id); } }, error: e => { if (this.isCurrent(runId, workspaceId)) this.fail(e); } });
   onCleanup(() => sub.unsubscribe());
  });
 }
 selectSavedProposal(p: CorrectionProposal): void {
  if (this.busy() || p.proposal.run_id !== this.run().id || p.proposal.system_id !== this.run().system_id) return;
  this.nodeId.set(p.proposal.node_id); this.context.set(null); this.error.set(''); this.showProposal(p);
 }
 private isCurrent(runId: string, workspaceId: WorkspaceRequestScope): boolean { return this.run().id === runId && this.workspace.isRequestScopeCurrent(workspaceId); }
 private fail(e: {error?: {detail?: string | {message?: string}}}): void { const detail = e?.error?.detail; this.error.set(typeof detail === 'string' ? detail : detail?.message || this.i18n.t('runs.correction.failed')); this.busy.set(false); }
 chooseNode(id: string): void { this.nodeId.set(id); this.context.set(null); this.error.set(''); this.assistantAnswer.set(''); }
 inspect(): void {
  if (this.busy()) return;
  const runId = this.run().id, workspaceId = this.workspace.captureRequestScope(), node = this.nodeId(); this.busy.set(true); this.error.set('');
  this.api.get<CorrectionContext>('/evaluation/corrections/context', {run_id:runId,node_id:node,evaluation_id:this.evaluationId()}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({next: c => { if (!this.isCurrent(runId, workspaceId)) return; this.context.set(c); this.template.set(c.template); this.rationale.set(''); this.busy.set(false); }, error:e => {if(this.isCurrent(runId, workspaceId)) this.fail(e);}});
 }
 suggest(): void {
  const ctx = this.context(); if (!ctx || this.busy()) return;
  const runId = this.run().id, workspaceId = this.workspace.captureRequestScope(); this.busy.set(true); this.error.set('');
  this.api.post<AssistantProposalResponse>('/assistant/turns', {surface:'pilot',system_ids:[ctx.system_id],request_id:crypto.randomUUID(),
   text:`Inspect correction context for Run ${ctx.run_id}, node ${ctx.node_id}, evaluation ${ctx.evaluation_id}. Propose a template correction based on its evidence with propose_correction, preserving placeholders and not inserting the reference answer. Store a proposal only; never apply it. Reply in ${this.i18n.locale()}.`,
   session_context:{correction:{run_id:ctx.run_id,node_id:ctx.node_id,evaluation_id:ctx.evaluation_id}}}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({next: result => {
    if (!this.isCurrent(runId, workspaceId)) return; this.busy.set(false); this.assistantAnswer.set(result.answer);
    const p = result.tool_calls?.find(call => call.name === 'propose_correction' && call.ok && call.result?.id)?.result;
    if (p?.proposal?.run_id === runId) this.showProposal(p); else this.error.set(this.i18n.t('runs.correction.no_proposal'));
   },error:e=>{if(this.isCurrent(runId, workspaceId)) this.fail(e);}});
 }
 prepare(): void {
  const ctx = this.context(); if (!ctx || this.busy()) return; const workspaceId = this.workspace.captureRequestScope(); this.busy.set(true); this.error.set('');
  this.api.post<CorrectionProposal>('/evaluation/corrections', {run_id:ctx.run_id,node_id:ctx.node_id,evaluation_id:ctx.evaluation_id,expected_draft_revision:ctx.expected_draft_revision,replacement_template:this.template(),rationale:this.rationale(),idempotency_key:crypto.randomUUID()}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({next:p=>{if(this.isCurrent(ctx.run_id, workspaceId)) this.showProposal(p);},error:e=>{if(this.isCurrent(ctx.run_id,workspaceId))this.fail(e);}});
 }
 private showProposal(p: CorrectionProposal): void { this.proposal.set(p); this.reviewed.set(false); this.busy.set(false); void this.router.navigate([], {relativeTo:this.route,queryParams:{correction:p.id},queryParamsHandling:'merge',replaceUrl:true}); }
 apply(): void {
  const p = this.proposal(); if (!p || !this.reviewed() || this.busy() || !this.applicationAllowed() || p.status === 'applied') return; const runId=this.run().id,workspaceId=this.workspace.captureRequestScope();this.busy.set(true);this.error.set('');
  this.api.post<CorrectionProposal>(`/evaluation/corrections/${encodeURIComponent(p.id)}/apply`,{expected_draft_revision:p.proposal.expected_draft_revision,reviewed_proposal_sha256:p.proposal_sha256}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({next:r=>{if(!this.isCurrent(runId,workspaceId))return;this.proposal.set(r);this.busy.set(false);if(r.applied_revision)this.applied.emit({proposalId:r.id,revision:r.applied_revision});},error:e=>{if(this.isCurrent(runId,workspaceId))this.fail(e);}});
 }
 openDraft(): void {
  const p = this.proposal(); if (!p) return;
  const resolved = this.navigation.resolveLink({leaf:'system-flow',ref:p.proposal.system_id});
  const url = this.router.parseUrl(resolved.url);
  url.queryParams = {...url.queryParams,correction:p.id,reference_run:this.run().id,node:p.proposal.node_id};
  void this.router.navigateByUrl(url);
 }
 resetProposal(): void { this.proposal.set(null);this.reviewed.set(false);this.error.set('');void this.router.navigate([],{relativeTo:this.route,queryParams:{correction:null},queryParamsHandling:'merge',replaceUrl:true});if(this.nodeId())this.inspect(); }
}
