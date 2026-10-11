import { ChangeDetectionStrategy, Component, Input, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { NavLinkDirective } from '@app/shared/cockpit';
import { FormsModule } from '@angular/forms';
import { JsonPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, timer, exhaustMap, takeWhile, forkJoin, switchMap, of } from 'rxjs';
import { CanonicalApiService, BrdGenerationJob, BrdImport, BrdProposal, Skill, Run, SystemFlowWorkbenchGoldenRunRequest } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { backendMessage } from './new-skill-dialog.component';

@Component({
  selector: 'app-brd-system-proposal', standalone: true,
  imports: [FormsModule, JsonPipe, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [`
    :host { display:block; margin-top:24px; color:var(--ck-fg-1); font-size:14px; }
    section { border-top:1px solid var(--ck-stroke-soft); padding-top:20px; }
    h3 { font-size:18px; font-weight:500; margin:0 0 8px; }
    p { line-height:1.5; margin:8px 0; }
    .fields { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:16px 0; }
    label { display:block; line-height:1.5; }
    input:not([type=checkbox]), select { display:block; width:100%; min-height:40px; margin-top:4px; padding:8px; border:1px solid var(--ck-stroke-strong); border-radius:4px; background:var(--ck-bg-inset); color:var(--ck-fg-1); }
    button, .action { display:inline-block; min-height:40px; padding:9px 14px; border:1px solid var(--ck-stroke-strong); border-radius:4px; color:var(--ck-fg-1); background:var(--ck-bg-inset); }
    button:disabled { opacity:.5; cursor:not-allowed; }
    :is(button,input,select,summary,a):focus-visible { outline:2px solid var(--ck-accent); outline-offset:3px; }
    .primary { background:var(--ck-fg-1); color:var(--ck-bg-base); }
    .tools { max-height:180px; overflow:auto; margin:12px 0; }
    .tools label { padding:6px 0; }
    .muted { color:var(--ck-fg-3); }
    .warning { color:var(--ck-fg-1); border-left:3px solid var(--ck-warn); padding-left:8px; }
    .error { color:var(--ck-neg); }
    .operations { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; padding:0; list-style:none; }
    .operations li { border:1px solid var(--ck-stroke-soft); border-radius:4px; padding:8px 12px; }
    .coverage { padding:12px 0; border-top:1px solid var(--ck-stroke-soft); overflow-wrap:anywhere; }
    .coverage-head { display:flex; justify-content:space-between; gap:12px; }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:320px; overflow:auto; font-size:12px; padding:12px; background:var(--ck-bg-inset); }
    details { margin:16px 0; } summary { cursor:pointer; }
    .review { margin:16px 0; }
    @media(max-width:600px) { .fields { grid-template-columns:1fr; } }
  `],
  template: `
    <section aria-labelledby="brd-system-heading">
      <h3 id="brd-system-heading">{{ i18n.t('skills.brdSystem.title') }}</h3>
      <p class="muted">{{ i18n.t('skills.brdSystem.description') }}</p>
      <button type="button" (click)="download()">{{ i18n.t('skills.brdSystem.original') }}</button>
      @if (!proposal()) {
        <div class="fields">
          <label>{{ i18n.t('skills.brdSystem.name') }}
            <input [(ngModel)]="name" maxlength="200" [disabled]="busy()" />
          </label>
          <label>{{ i18n.t('skills.brdSystem.family') }}
            <select [(ngModel)]="family" [disabled]="busy()">
              <option value="document_summary">{{ i18n.t('skills.brdSystem.summary') }}</option>
              <option value="intervention_preparation">{{ i18n.t('skills.brdSystem.intervention') }}</option>
            </select>
          </label>
        </div>
        <details [open]="family === 'intervention_preparation'">
          <summary>{{ i18n.t('skills.brdSystem.tools') }}</summary>
          <p class="muted">{{ i18n.t('skills.brdSystem.toolsHelp') }}</p>
          <div class="tools">
            @for (skill of skills(); track skill.id) {
              <label><input type="checkbox" [checked]="selected.includes(skill.slug)" [disabled]="busy()"
                (change)="toggleSkill(skill.slug, $any($event.target).checked)" /> {{ skill.name }}</label>
            }
          </div>
        </details>
        <button class="primary" type="button" [disabled]="busy() || !name.trim()" (click)="generate()">
          {{ i18n.t('skills.brdSystem.generate') }}
        </button>
      }
      @if (busy()) { <p role="status">{{ i18n.t(applying() ? 'skills.brdSystem.applying' : 'skills.brdSystem.generating') }}</p> }
      @if (failure()) { <p role="alert" class="error">{{ failure() }}</p> }
      @if (proposal(); as current) {
        <h3 style="margin-top:20px">{{ current.proposal.name }}</h3>
        <p>{{ current.proposal.objective }}</p>
        <ul class="operations" [attr.aria-label]="i18n.t('skills.brdSystem.operations')">
          @for (node of current.proposal.flow_definition.nodes; track node.id) {
            <li>{{ node.label || node.id }}</li>
          }
        </ul>
        @if (!testRuns().length) { <p class="muted">{{ i18n.t('skills.brdSystem.notTested') }}</p> }
        @for (issue of current.proposal.problems; track $index) { <p class="warning">{{ issue }}</p> }
        @for (row of current.proposal.coverage; track row.table + ':' + row.row) {
          <div class="coverage">
            <div class="coverage-head"><strong>{{ row.reference }}</strong>
              <span [class.warning]="row.status === 'uncovered'">{{ i18n.t(row.status === 'uncovered' ? 'skills.brdSystem.uncovered' : 'skills.brdSystem.proposed') }}</span>
            </div>
            <p>{{ requirementText(row.table, row.row) }}</p>
            @if (row.node_ids.length || row.case_ids.length) {
              <span class="muted">{{ row.node_ids.join(' → ') }} @if (row.node_ids.length && row.case_ids.length) { · } {{ row.case_ids.join(', ') }}</span>
            }
            @if (row.reason) { <p>{{ row.reason }}</p> }
            @for (run of requirementRuns(row.case_ids); track run.id) {
              <p><a [navLink]="{type:'run',ref:run.id}">{{ run.test_result?.case_id }} · {{ i18n.t('skills.brdSystem.verdict.' + (run.status === 'hitl_pending' ? 'human' : run.test_result?.verdict)) }}</a></p>
            }
          </div>
        }
        <details><summary>{{ i18n.t('skills.brdSystem.details') }}</summary><pre>{{ current.proposal | json }}</pre></details>
        @if (current.system_id) {
          <p role="status">{{ i18n.t('skills.brdSystem.created') }}</p>
          <a class="action primary" [navLink]="{type:'system',ref:current.system_id,lens:'build',facet:'design'}">{{ i18n.t('skills.brdSystem.open') }}</a>
          <p class="muted">{{ i18n.t('skills.brdSystem.testsHelp') }}</p>
          <button type="button" [disabled]="testing()" (click)="testCases()">{{ i18n.t('skills.brdSystem.testCases') }}</button>
          @if (testRuns().length) {
            <button type="button" [disabled]="testing()" (click)="newTestAttempt()">{{ i18n.t('skills.brdSystem.newTest') }}</button>
            <button type="button" [disabled]="testing()" (click)="refreshTests()">{{ i18n.t('skills.brdSystem.refreshTests') }}</button>
          }
          @for (run of testRuns(); track run.id) {
            <div class="coverage">
              <strong>{{ run.test_result?.case_id || run.id }}</strong>
              <p>{{ i18n.t('skills.brdSystem.verdict.' + (run.status === 'hitl_pending' ? 'human' : (run.test_result?.verdict || 'pending'))) }}</p>
              <a class="action" [navLink]="{type:'run',ref:run.id}">{{ i18n.t('skills.brdSystem.inspectRun') }}</a>
            </div>
          }
        } @else {
          <label class="review"><input type="checkbox" [(ngModel)]="reviewed" [disabled]="busy()" /> {{ i18n.t('skills.brdSystem.review') }}</label>
          <button class="primary" type="button" [disabled]="busy() || !reviewed" (click)="apply()">{{ i18n.t('skills.brdSystem.apply') }}</button>
          <button type="button" style="margin-left:8px" [disabled]="busy()" (click)="revise()">{{ i18n.t('skills.brdSystem.revise') }}</button>
        }
      }
    </section>
  `,
})
export class BrdSystemProposalComponent implements OnInit, OnDestroy {
  @Input({ required: true }) document!: BrdImport;
  private readonly api = inject(CanonicalApiService);
  readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);
  private readonly scope = this.workspace.captureRequestScope();
  private readonly subscriptions = new Subscription();
  private polling?: Subscription;
  readonly proposal = signal<BrdProposal | null>(null);
  readonly skills = signal<Skill[]>([]);
  readonly busy = signal(false);
  readonly applying = signal(false);
  readonly failure = signal<string | null>(null);
  readonly testing = signal(false);
  readonly testRuns = signal<Run[]>([]);
  private testRequest?: { system: string; body: SystemFlowWorkbenchGoldenRunRequest };
  name = '';
  family: 'document_summary' | 'intervention_preparation' = 'document_summary';
  selected: string[] = [];
  reviewed = false;
  private generationRequest?: { fingerprint: string; key: string };

  ngOnInit(): void {
    this.name = this.document.document?.filename?.replace(/\.docx$/i, '') ?? '';
    this.subscriptions.add(this.api.listSkills({ propagateErrors: true }).subscribe({
      next: rows => { if (this.current()) this.skills.set(rows); },
      error: error => this.fail(error),
    }));
    const job = this.route.snapshot.queryParamMap.get('brd_job');
    if (job) { this.busy.set(true); this.poll(job); }
  }
  ngOnDestroy(): void { this.subscriptions.unsubscribe(); this.polling?.unsubscribe(); }
  private current(): boolean { return this.workspace.isRequestScopeCurrent(this.scope); }
  private fail(error: unknown): void {
    if (!this.current()) return;
    this.failure.set(backendMessage(error, this.i18n.t('skills.brdSystem.failed')));
    this.busy.set(false); this.applying.set(false);
  }
  toggleSkill(slug: string, checked: boolean): void {
    this.selected = checked ? [...new Set([...this.selected, slug])] : this.selected.filter(s => s !== slug);
  }
  generate(): void {
    const id = this.document.document?.id;
    if (!id || this.busy() || !this.current() || !this.name.trim()) return;
    this.busy.set(true); this.failure.set(null); this.reviewed = false;
    const fingerprint = JSON.stringify([id, this.name.trim(), this.family, [...this.selected].sort()]);
    if (this.generationRequest?.fingerprint !== fingerprint) this.generationRequest = { fingerprint, key: crypto.randomUUID() };
    this.subscriptions.add(this.api.generateBrdSystem(id, { request_key: this.generationRequest.key, name: this.name.trim(), family: this.family, skill_slugs: this.selected }).subscribe({
      next: job => { if (!this.current()) return;
        void this.router.navigate([], { relativeTo: this.route, queryParams: { brd_document: id, brd_job: job.id }, queryParamsHandling: 'merge', replaceUrl: true });
        this.receive(job); if (this.busy()) this.poll(job.id);
      }, error: error => this.fail(error),
    }));
  }
  private poll(jobId: string): void {
    const id = this.document.document?.id;
    if (!id) return;
    this.polling?.unsubscribe();
    this.polling = timer(0, 1500).pipe(
      takeWhile(() => this.current()),
      exhaustMap(() => this.api.getBrdGeneration(id, jobId)),
      takeWhile(job => ['created', 'queued', 'running'].includes(job.status), true),
    ).subscribe({ next: job => this.receive(job), error: error => this.fail(error) });
  }
  private receive(job: BrdGenerationJob): void {
    if (!this.current()) return;
    if (job.status === 'completed' && job.result?.id) {
      this.subscriptions.add(this.api.getBrdProposal(this.document.document!.id!, job.result.id).subscribe({
        next: proposal => { if (!this.current()) return; this.proposal.set(proposal); this.busy.set(false); this.restoreTests(proposal.system_id); },
        error: error => this.fail(error),
      }));
    }
    else if (['failed', 'cancelled', 'completed'].includes(job.status)) { this.generationRequest = undefined; this.fail({ error: { detail: job.error || this.i18n.t('skills.brdSystem.failed') } }); }
  }
  apply(): void {
    const id = this.document.document?.id, proposal = this.proposal();
    if (!id || !proposal || !this.reviewed || this.busy() || !this.current()) return;
    this.busy.set(true); this.applying.set(true); this.failure.set(null);
    this.subscriptions.add(this.api.applyBrdProposal(id, proposal).subscribe({
      next: result => { if (!this.current()) return; this.proposal.set(result); this.busy.set(false); this.applying.set(false); },
      error: error => this.fail(error),
    }));
  }
  testCases(): void {
    const system = this.proposal()?.system_id;
    if (!system || this.testing() || !this.current()) return;
    this.testing.set(true); this.failure.set(null);
    const request = this.testRequest?.system === system ? of(this.testRequest.body) : forkJoin({
      system: this.api.getSystem(system), state: this.api.getSystemFlowState(system),
    }).pipe(switchMap(({system: record, state}) => {
      if (!this.current()) return of(null);
      const provenance = record?.settings?.['brd_provenance'] as {suite_id?: string} | undefined;
      if (!provenance?.suite_id) throw new Error(this.i18n.t('skills.brdSystem.noSuite'));
      const body: SystemFlowWorkbenchGoldenRunRequest = {acknowledge_real_side_effects: true,
        suite_id: provenance.suite_id, request_key: crypto.randomUUID(),
        flow_definition: state.draft.flow_definition, expected_flow_sha256: state.draft.flow_sha256};
      this.testRequest = {system, body};
      return of(body);
    }));
    this.subscriptions.add(request.pipe(switchMap(body => body && this.current()
      ? this.api.triggerSystemFlowWorkbenchGoldenRuns(system, body) : of(null))).subscribe({
        next: result => { if (!this.current()) return; this.testing.set(false);
          if (result) {
            void this.router.navigate([], {relativeTo: this.route, queryParams: {brd_batch: result.batch_id}, queryParamsHandling: 'merge', replaceUrl: true});
            this.testRuns.set(result.runs); this.refreshTests();
          } },
        error: error => { this.testing.set(false); this.fail(error); },
      }));
  }
  private restoreTests(system: string | null): void {
    const batch = this.route.snapshot.queryParamMap.get('brd_batch');
    if (!system || !batch || !this.current()) return;
    this.testing.set(true);
    this.subscriptions.add(this.api.listRuns({system_id: system, golden_batch_id: batch}).subscribe({
      next: runs => { if (!this.current()) return; this.testRuns.set(runs); this.testing.set(false); },
      error: error => { this.testing.set(false); this.fail(error); },
    }));
  }
  newTestAttempt(): void {
    if (this.testing() || !this.current()) return;
    this.testRequest = undefined; this.testRuns.set([]); this.testCases();
  }
  refreshTests(): void {
    if (!this.current() || this.testing() || !this.testRuns().length) return;
    this.testing.set(true);
    this.subscriptions.add(forkJoin(this.testRuns().map(run => this.api.getRun(run.id))).subscribe({
      next: rows => { if (!this.current()) return; this.testRuns.set(rows.filter((row): row is Run => row !== null)); this.testing.set(false); },
      error: error => { this.testing.set(false); this.fail(error); },
    }));
  }
  revise(): void { this.generationRequest = undefined; this.proposal.set(null); this.reviewed = false; this.failure.set(null); }
  download(): void {
    const id = this.document.document?.id;
    if (!id || !this.current()) return;
    this.subscriptions.add(this.api.downloadBrdDocument(id).subscribe({ next: blob => {
      if (!this.current()) return;
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = this.document.document?.filename || 'business-requirements.docx'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, error: error => this.fail(error) }));
  }
  requirementRuns(caseIds: string[]): Run[] {
    const proposal = this.proposal();
    return this.testRuns().filter(run => run.test_result?.brd_proposal_id === proposal?.id
      && run.test_result?.brd_proposal_sha256 === proposal?.sha256
      && caseIds.includes(run.test_result?.case_id ?? ''));
  }
  requirementText(table: number, row: number): string {
    const source = this.document.provenance?.find(p => p.table === table && p.row === row);
    if (!source) return '';
    const siblings = this.document.provenance?.filter(p => p.section === source.section) ?? [];
    const index = siblings.indexOf(source);
    if (source.section === 'business outcomes') return this.document.outcomes[index]?.outcome ?? '';
    if (source.section === 'functional requirements') return this.document.requirements[index]?.requirement ?? '';
    if (source.section === 'decisions') return this.document.decisions[index]?.decision ?? '';
    const kind = source.section === 'prohibitions' ? 'prohibition' : 'rule';
    return this.document.guardrails.filter(g => g.kind === kind)[index]?.text ?? '';
  }
}
