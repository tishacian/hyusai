import { WorkAppElsewhereComponent } from './work-app-elsewhere.component';
import { ThemeService } from '@app/core/theme.service';
import { workTheme, workThemeMode } from './work-catalog';
import { DecisionRightComponent, mayDecide } from '@app/shared/ui/decision-right.component';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { checkMessage, decisionMessage, type DecisionMessage } from '@app/shared/ui/run-decision';
import { decisionNoticeKey, noticeForRun, type DecisionNoticeMap, type DecisionNoticeTarget } from '@app/shared/ui/run-decision-notice';
import { writeFailure } from '@app/shared/ui/load-state';
import { DatePipe, NgTemplateOutlet } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom, lastValueFrom, Subscription, timer } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run, type SkillInvocation } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { PG_ERROR_CODES, pgFailure, type PgFailure } from '@app/features/connectors/postgresql/postgresql.types';
import { WorkActionReceiptComponent, type WorkActionReceipt } from '@app/shared/work-records/work-action-receipt.component';
import { AgentDecisionTrailComponent } from '@app/shared/work-records/agent-decision-trail.component';
import { RunQualityReviewComponent } from '@app/shared/work-records/run-quality-review.component';
import { typedJudgeOutcome, typedResult } from '@app/features/data/dataops.models';
import { WorkSourcePanelComponent } from '@app/shared/work-sources/work-source-panel.component';
import { WorkRecordQueueComponent, type WorkRecordItem } from '@app/shared/work-records/work-record-queue.component';
import { workSourceRef } from '@app/shared/work-sources/work-source';
import { WorkBarComponent } from './work-bar.component';
import { WorkAppHeaderComponent } from './work-app-header.component';
import { WorkReleasePagesNavComponent } from './work-release-pages-nav.component';
import { ClaimsBenchmarkComponent } from './claims-benchmark.component';
import { ClaimsResolutionPolicyComponent } from './claims-resolution-policy.component';
import { WorkApiService } from './work-api.service';
import { runtimeFailureKind } from '../runtime/runtime-failure';
import { CLAIM_ACTION_LABELS, CLAIM_REASON_LABELS, CLAIM_TOOL_LABELS, claimActionGroups, claimRunProjection, recordedClaimActions, type ClaimProposal, type ClaimRow, type ClaimSnapshot } from './claim-run';
import { caseDatasets, freshTriage, queueByPriority, selectedAdvice, type ClaimTriage } from './claim-triage';
import { RunSituationComponent } from '@app/shared/work-records/run-situation.component';
import { WorkRecordAttemptsComponent } from '@app/shared/work-records/work-record-attempts.component';
import { pollRun } from '@app/core/run-polling';

type InvestigationRequest = { key: string; state: 'sending' | 'unknown' | 'rejected' }
  | { key: string; state: 'confirmed'; runId: string };

export function claimInvestigationFailureMessage(run: Run | null): string | null {
  if (!run || !['failed', 'cancelled'].includes(run.status)) return null;
  const checkpoints = run.checkpoints ?? [];
  const resume = [...checkpoints].reverse().find(checkpoint => checkpoint['kind'] === 'hitl_resume');
  if (resume?.['decision_status'] === 'rejected') {
    const pause = checkpoints.slice(0, checkpoints.indexOf(resume)).reverse().find(checkpoint => checkpoint['kind'] === 'hitl_pause'
      && typeof resume['passage_id'] === 'string' && typeof resume['node_id'] === 'string'
      && checkpoint['passage_id'] === resume['passage_id'] && checkpoint['node_id'] === resume['node_id']);
    const decisionId = resume['decision_id'] ?? pause?.['decision_id'];
    const expired = typeof decisionId === 'string' && checkpoints.some(checkpoint => checkpoint['kind'] === 'gate_ttl_expired'
      && checkpoint['decision_id'] === decisionId && checkpoint['expiry_action'] === 'reject');
    return expired ? 'experience.claims.approval_expired' : 'experience.claims.approval_rejected';
  }
  if (run.status === 'cancelled') return 'experience.claims.run_cancelled';
  const kind = runtimeFailureKind(run.error);
  return ['failed', 'status_unknown'].includes(kind) ? 'experience.claims.run_failed' : `experience.runtime.failure.${kind}`;
}

@Component({
  selector: 'app-claims-studio', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, NgTemplateOutlet, WorkBarComponent, WorkAppHeaderComponent, WorkReleasePagesNavComponent, WorkSourcePanelComponent, WorkRecordQueueComponent, WorkActionReceiptComponent, RunQualityReviewComponent, AgentDecisionTrailComponent, NavLinkDirective, ClaimsBenchmarkComponent, ClaimsResolutionPolicyComponent, IconComponent, DecisionRightComponent, RunSituationComponent, WorkRecordAttemptsComponent, WorkAppElsewhereComponent],
  styleUrls: ['./work.scss', './claims-studio.scss'],
  template: `
    <div class="xp-work claims-app" data-brand-scope [attr.data-theme]="themeMode()">
      <app-work-bar [appContext]="i18n.t('experience.claims.title')" />
      <app-work-app-header [title]="i18n.t('experience.claims.title')" [eyebrow]="i18n.t('experience.claims.brand')"
        [description]="i18n.t('experience.claims.promise')" [status]="i18n.t('experience.claims.demo')" emblem="◈">
        <app-work-release-pages-nav [document]="releasePages()" slug="reclamations" activePage="dossier"
          [hostedPage]="{ pageId: 'dossier', routeSegment: 'studio' }" />
        @if (machineAidsAllowed() && run(); as current) { <a class="xp-work-btn" [navLink]="{ type: 'run', lens: 'operate', ref: current.id }">{{ i18n.t('experience.claims.trace') }}</a> }
      </app-work-app-header>
      @if (!loading() && !error()) { <app-claims-benchmark [compact]="true" [sources]="detail()?.sources ?? []" (caseSelected)="select($event)" (manualActive)="manualMode.set($event)" (modeReady)="benchmarkReady.set($event)" /> }
      <main class="claims-main" aria-labelledby="work-app-title">
        @if (loading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
        @if (error()) { <div class="claims-data-error claims-data-error-queue" role="alert"><ng-container [ngTemplateOutlet]="dataUnavailable" /></div> }
        @if (!loading() && !error()) {
          @if (machineAidsAllowed()) {
            <section class="claims-triage" aria-labelledby="claims-triage-title">
              <div class="claims-section-title"><h2 id="claims-triage-title">{{ i18n.t(triage()?.composition ? 'experience.claims.triage.composed_title' : 'experience.claims.triage.title') }}</h2>
                @if (triage()?.scoring; as scoring) {
                  <div class="claims-triage-actions">
                    <a class="claims-triage-flow" [navLink]="{ leaf: 'system-flow', lens: 'build', ref: scoring.system_id }">{{ i18n.t(triage()?.composition ? 'experience.claims.triage.composed_flow' : 'experience.claims.triage.flow') }} <app-icon name="arrow-right" [size]="12" /></a>
                    <button class="xp-work-btn claims-compact" [disabled]="triageBusy() || busy()" (click)="recalculatePriority()">{{ i18n.t(triageBusy() ? 'experience.claims.triage.running' : 'experience.claims.triage.recalculate') }}</button>
                  </div>
                }
              </div>
              @if (triageLoading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
              @else if (triage()?.model; as model) {
                <p class="claims-provenance" [attr.data-state]="triage()?.status" aria-live="polite">{{ i18n.t('experience.claims.triage.' + triage()!.status) }}
                  @if (triage()?.captured_at; as captured) { · {{ captured | date:'dd/MM HH:mm:ss' }} }
                  @if (triage()?.run_id; as runId) { · <a [navLink]="{ type: 'run', lens: 'operate', ref: runId }">{{ i18n.t('experience.claims.triage.trace') }}</a> }
                </p>
                <details class="claims-triage-details">
                  <summary>{{ i18n.t('experience.claims.triage.details') }}</summary>
                <div class="claims-triage-path">
                  @if (triage()?.composition) {
                    @if (canConfigureData()) { <a [navLink]="{ leaf: 'connector-postgresql' }">PostgreSQL</a> }
                    @else { <span>PostgreSQL</span> }
                    <span aria-hidden="true">→</span>
                    @if (triage()?.prepared_dataset; as dataset) { <a [navLink]="{ leaf: 'data-doc', ref: dataset.id }">{{ i18n.t('experience.claims.triage.prepared') }} <span>{{ dataset.rows }} {{ i18n.t('experience.claims.triage.cases') }}</span></a><span aria-hidden="true">→</span> }
                  } @else if (triage()?.training_dataset; as dataset) { <a [navLink]="{ leaf: 'data-doc', ref: dataset.id }">{{ i18n.t('experience.claims.triage.history') }} <span>{{ dataset.rows }} {{ i18n.t('experience.claims.triage.cases') }}</span></a><span aria-hidden="true">→</span> }
                  <a [navLink]="{ leaf: 'model-doc', ref: model.id }">{{ i18n.t('experience.claims.triage.model') }} <span>v{{ model.version }}</span></a>
                  @if (triage()?.scored_dataset; as dataset) { <span aria-hidden="true">→</span><a [navLink]="{ leaf: 'data-doc', ref: dataset.id }">{{ i18n.t('experience.claims.triage.scored') }} <span>{{ dataset.rows }} {{ i18n.t('experience.claims.triage.cases') }}</span></a> }
                </div>
                @if (triage()?.composition) { <p class="claims-quiet">{{ i18n.t('experience.claims.triage.composed_path') }}</p> }
                <p class="claims-quiet">{{ i18n.t('experience.claims.triage.notice') }}</p>
                </details>
              } @else { <p class="claims-quiet">{{ i18n.t('experience.claims.triage.unavailable') }}</p> }
              @if (triageError()) { <p class="claims-error" role="alert">{{ i18n.t('experience.claims.triage.error') }}</p> }
            </section>
          }
          <aside class="claims-queue" [attr.aria-label]="i18n.t('experience.claims.queue')">
            <app-work-record-queue [title]="i18n.t('experience.claims.queue')" [items]="queueItems()"
              [selected]="selected()" [disabled]="busy() || manualMode()" [emptyText]="i18n.t('experience.claims.empty')"
              (selectedChange)="select($event)" />
            <p class="claims-quiet">{{ i18n.t('experience.claims.synthetic') }}</p>
          </aside>
          @if (!detail() && !detailLoading() && detailReadFailed()) { <div class="claims-data-error" role="alert"><ng-container [ngTemplateOutlet]="dataUnavailable" /></div> }
          @if (detail(); as dossier) {
            <section class="claims-dossier" [attr.aria-label]="i18n.t('experience.claims.dossier')">
              <header class="claims-dossier-heading">
                <div><p class="claims-dossier-reference">{{ i18n.t('experience.claims.dossier') }} · {{ dossier.data.context[0].claim_id }}</p><h2>{{ dossier.data.context[0].order_id }}</h2></div>
                <p class="claims-dossier-customer">{{ dossier.data.context[0].display_name }}<span>{{ i18n.t(reasonLabel(dossier.data.context[0].reason)) }}</span></p>
              </header>
              <div class="claims-facts">
                <article class="claims-fact-amount"><span>{{ i18n.t('experience.claims.paid') }}</span><strong>{{ money(dossier.data.context[0].paid_amount, dossier.data.context[0].currency) }}</strong></article>
                <article><span>{{ i18n.t('experience.claims.postcode') }}</span><strong>{{ dossier.data.context[0].shipping_postcode }}</strong></article>
                <article><span>{{ i18n.t('experience.claims.shipping') }}</span><strong>{{ shipping(dossier.data.shipments[0]?.status) }}</strong></article>
              </div>
              <p class="claims-provenance">{{ i18n.t('experience.claims.database') }} · {{ dossier.provenance.captured_at | date:'dd/MM HH:mm:ss' }}</p>
              <article class="claims-panel claims-panel-order"><h3>{{ i18n.t('experience.claims.order') }}</h3>
                @for (item of dossier.data.items; track $index) { <p>{{ item.product_name }} · {{ item.quantity }} × {{ money(item.unit_price, 'EUR') }}</p> }
                @for (shipment of dossier.data.shipments; track shipment.tracking_id) { <p class="claims-quiet">{{ shipment.carrier }} · {{ shipment.tracking_id }}</p> }
                <h3>{{ i18n.t('experience.claims.refunds') }}</h3>
                @for (refund of dossier.data.refunds; track refund.refund_id) { <p>{{ refund.refund_id }} · {{ money(refund.amount, refund.currency) }} · {{ refundState(refund.status) }}</p> }
                @empty { <p class="claims-quiet">{{ i18n.t('experience.claims.no_refund') }}</p> }
              </article>
              <article class="claims-panel claims-panel-evidence"><h3>{{ i18n.t('experience.claims.documents') }}</h3>
                <div class="claims-source-list">@for (source of sources(); track source.documentId) {
                  <button class="claims-source" [class.is-selected]="source.documentId === sourceDocumentId()" [attr.aria-expanded]="source.documentId === sourceDocumentId()" (click)="selectSource(source.n)"><span class="claims-source-index" aria-hidden="true">{{ source.n }}</span><span class="claims-source-title">{{ source.title }}</span><app-icon name="external-link" [size]="14" /></button>
                } @empty { <p>{{ i18n.t('experience.claims.no_sources') }}</p> }</div>
                @if (sourceIndex(); as n) { <app-work-source-panel [sources]="sources()" [selected]="n" (selectedChange)="selectSource($event)" (closed)="sourceDocumentId.set(null)" /> }
              </article>
              <app-claims-resolution-policy [applied]="projection().proposal?.resolution_policy ?? null" />
              @if (machineAidsAllowed()) { <app-agent-decision-trail [run]="run()" [toolLabels]="agentToolLabels" [compact]="true" /> }
              <article class="claims-panel claims-panel-progress"><h3>{{ i18n.t('experience.claims.inquiry') }}</h3>
                <ol class="claims-steps" aria-live="polite">@for (step of projection().steps; track step.id) {
                  @let outcome = stepOutcome(step);
                  <li [attr.data-state]="outcome?.state ?? step.status"><span class="claims-step-dot" aria-hidden="true"></span><span>{{ i18n.t(toolLabel(step.skill_slug)) }}</span><span class="claims-quiet">{{ outcome ? i18n.t(outcome.label) : stepState(step.status) }}</span></li>
                } @empty { <li class="claims-quiet claims-step-empty">{{ i18n.t('experience.claims.not_started') }}</li> }</ol>
              </article>
            </section>
            <aside class="claims-decision" [attr.aria-label]="i18n.t('experience.claims.decision')">
              <h2>{{ i18n.t('experience.claims.decision') }}</h2>
              @if (run(); as current) { <app-run-situation [runId]="current.id" [refreshKey]="current.status" [compact]="true" [showRunLink]="true" /> }
              @if (selected(); as recordId) {
                <app-work-record-attempts slug="reclamations" bindingKey="showcase.claims.investigate" [recordRef]="recordId"
                  [selectedRunId]="run()?.id ?? null" [currentRunId]="run()?.id ?? null" [refreshKey]="attemptsRefresh()" (selectRun)="openAttempt($event)" />
              }
              @if (advice(); as advice) { <div class="claims-risk" [attr.data-priority]="advice.priority">
                <span>{{ triage()?.prediction_contract?.label || i18n.t('experience.claims.triage.risk') }}</span><strong>{{ percent(advice.risk) }}</strong>
                <p>{{ priorityLabel(advice.priority) }} · {{ i18n.t('experience.claims.triage.basis.' + advice.basis) }}</p>
                @if (caseData(); as data) { <div class="claims-case-data">
                  <a [navLink]="{ leaf: 'data-doc', ref: data.prepared.id }">{{ i18n.t('experience.claims.triage.case_prepared') }}</a>
                  <a [navLink]="{ leaf: 'data-doc', ref: data.scored.id }">{{ i18n.t('experience.claims.triage.case_scored') }}</a>
                </div> }
              </div> }
              @if (projection().proposal; as proposal) {
                @if (!proposal.receipt_id) {
                @if (actionGroups().previous.length) { <p class="claims-inquiry-context">{{ i18n.t('experience.claims.new_inquiry_notice') }}</p> }
                <div class="claims-recommendation" [class.is-warning]="proposal.action !== 'refund'"><span class="claims-eyebrow">{{ i18n.t('experience.claims.proposal') }}</span><h3>{{ i18n.t(actionLabel(proposal.action)) }}</h3><p>{{ i18n.t(reasonLabel(proposal.reason)) }}</p>
                  @if (proposal.action === 'refund') { <strong class="claims-amount">{{ money(proposal.amount, proposal.currency) }}</strong> }
                  @if (proposal.missing_references.length) { <p>{{ i18n.t('experience.claims.missing') }}</p> }
                </div>
                }
              } @else if (!recordedActions().length) { <p class="claims-quiet">{{ i18n.t('experience.claims.start_hint') }}</p> }
              @if (actionGroups().current; as receipt) { <app-work-action-receipt [receipt]="receiptView(receipt)" /> }
              @if (machineAidsAllowed()) { <app-run-quality-review [run]="run()" /> }
              @if (machineAidsAllowed() && decisionNotice(); as notice) {
                <div class="claims-decision-notice" [attr.data-tone]="notice.tone" [attr.role]="notice.role">
                  <p data-testid="claims-decision-notice">{{ i18n.t(notice.key, notice.params) }}</p>
                  @if (notice.verifiable) { <button type="button" class="xp-work-btn claims-compact" data-testid="claims-decision-verify" [disabled]="busy()" (click)="checkDecision()">{{ i18n.t('state.decision.verify') }}</button> }
                </div>
              }
              @if (machineAidsAllowed() && run()?.status === 'hitl_pending') {
                <div class="claims-approval"><p>{{ i18n.t('experience.claims.approval_hint') }}</p>
                  <app-decision-right [hitl]="run()?.hitl" />
                  @if (mayDecide(run()?.hitl)) {
                  <div class="claims-decision-actions">
                  <button class="xp-work-btn xp-work-btn-primary" [disabled]="busy() || !!decisionNotice()?.unknown" (click)="decide('accept')">{{ i18n.t('experience.claims.approve') }}</button>
                  <button class="xp-work-btn" [disabled]="busy() || !!decisionNotice()?.unknown" (click)="decide('reject')">{{ i18n.t('experience.claims.reject') }}</button>
                  </div>
                  }
                </div>
              } @else if (!runReadFailed() && (run()?.status === 'running' || run()?.status === 'pending')) { <p role="status">{{ i18n.t('experience.claims.running') }}</p> }
              @else if (recordedActions().length) {
                <details class="claims-reexamine">
                  <summary>{{ i18n.t('experience.claims.reexamine') }}</summary>
                  <p class="claims-quiet">{{ i18n.t('experience.claims.reexamine_hint') }}</p>
                  <button class="xp-work-btn" [disabled]="busy() || !machineAidsAllowed() || !!investigationUnconfirmed() || !!runReadFailed() || detailReadFailed()" (click)="investigate(true)">{{ i18n.t('experience.claims.reinvestigate') }}</button>
                </details>
              } @else { <button class="xp-work-btn xp-work-btn-primary claims-primary" [disabled]="busy() || !machineAidsAllowed() || !!investigationUnconfirmed() || !!runReadFailed() || detailReadFailed()" (click)="investigate()">{{ i18n.t('experience.claims.investigate') }}</button> }
              @if (machineAidsAllowed()) {
                @if (investigationRequest()?.state === 'unknown') {
                  <div class="claims-decision-notice" data-tone="warn" role="alert" data-testid="claims-start-unconfirmed">
                    <p>{{ i18n.t('experience.claims.start_unconfirmed') }}</p>
                    <button class="xp-work-btn claims-compact" [disabled]="busy()" (click)="investigate(true, true)">{{ i18n.t('experience.claims.resume_request') }}</button>
                  </div>
                } @else if (investigationRequest()?.state === 'rejected') {
                  <p class="claims-error" role="alert">{{ i18n.t('experience.claims.start_rejected') }}</p>
                } @else if (investigationRequest()?.state === 'confirmed' && !runReadFailed()) {
                  <div class="claims-decision-notice" data-tone="neutral" role="status" data-testid="claims-start-confirmed">
                    <p>{{ i18n.t('experience.claims.start_confirmed') }}</p>
                    <button class="xp-work-btn claims-compact" [disabled]="busy() || runRefreshing()" (click)="refreshInvestigation()">{{ i18n.t('experience.claims.refresh') }}</button>
                  </div>
                }
                @if (runReadFailed(); as runId) {
                  <div class="claims-decision-notice" data-tone="warn" role="alert" data-testid="claims-run-read-error">
                    <p>{{ i18n.t('experience.claims.run_read_error') }}</p>
                    <button class="xp-work-btn claims-compact" [disabled]="busy() || runRefreshing()" (click)="refreshInvestigation()">{{ i18n.t('experience.claims.refresh') }}</button>
                  </div>
                } @else if (runFailureMessage(); as message) {
                  <div class="claims-decision-notice" [attr.data-tone]="message === 'experience.claims.approval_expired' || message === 'experience.claims.approval_rejected' || message === 'experience.claims.run_cancelled' ? 'warn' : 'neg'" role="alert" data-testid="claims-run-failure">
                    <p>{{ i18n.t(message) }}</p>
                    <a class="claims-triage-flow" [navLink]="{ type: 'run', lens: 'operate', ref: run()!.id }">{{ i18n.t('experience.claims.trace') }} <app-icon name="arrow-right" [size]="12" /></a>
                  </div>
                }
              }
              @if (detailReadFailed()) { <div class="claims-data-error" role="alert" data-testid="claims-detail-read-error"><ng-container [ngTemplateOutlet]="dataUnavailable" /></div> }
              <p class="claims-quiet">{{ i18n.t('experience.claims.action_notice') }}</p>
              @if (actionGroups().previous.length) { <details class="claims-reexamine claims-history" data-testid="claims-previous-actions"><summary>{{ i18n.t('experience.claims.previous_actions') }} · {{ actionGroups().previous.length }}</summary>@for (receipt of actionGroups().previous; track receipt.receipt_id) { <app-work-action-receipt [receipt]="receiptView(receipt)" /> }</details> }
            </aside>
          } @else if (detailLoading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
        }
      </main>
      <ng-template #dataUnavailable>
        @if (appMissing()) { <app-work-app-elsewhere appSlug="reclamations" />
        } @else if (dataError(); as failure) {
          <p class="claims-data-error-title">{{ i18n.t('experience.claims.data_unavailable') }}</p>
          <p>{{ i18n.t('connectors.pg.error.' + failure.code) }}</p>
          @if (!canConfigureData()) { <p class="claims-quiet">{{ i18n.t('connectors.pg.contact_admin') }}</p> }
        } @else { <p>{{ i18n.t('experience.claims.unavailable') }}</p> }
        <div class="claims-data-error-actions">
          <button class="xp-work-btn claims-compact" (click)="retryData()">{{ i18n.t('experience.claims.retry') }}</button>
          @if (dataError() && canConfigureData()) { <a class="xp-work-btn claims-compact" [navLink]="{ leaf: 'connector-postgresql' }">{{ i18n.t('connectors.pg.open') }}</a> }
        </div>
      </ng-template>
    </div>
  `,
})
export class ClaimsStudioComponent {
  readonly i18n = inject(I18nService);
  readonly agentToolLabels = CLAIM_TOOL_LABELS;
  private readonly api = inject(ApiService);
  private readonly work = inject(WorkApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroy = inject(DestroyRef);
  readonly releasePages = signal<unknown>(null);
  /** The app is not published in this workspace (404), not a data outage. */
  readonly appMissing = signal(false);
  /** Same theme rule as every Work page: release mode, else the reader's. */
  private readonly readerTheme = inject(ThemeService);
  readonly releaseTheme = signal<ReturnType<typeof workTheme> | null>(null);
  readonly themeMode = computed(() => workThemeMode(this.releaseTheme(), this.readerTheme.resolved()));
  readonly rows = signal<ClaimRow[]>([]); readonly selected = signal<string | null>(null);
  readonly detail = signal<ClaimSnapshot | null>(null); readonly run = signal<Run | null>(null);
  readonly loading = signal(true); readonly detailLoading = signal(false); readonly error = signal(false);
  readonly dataError = signal<PgFailure | null>(null);
  readonly canConfigureData = signal(false);
  readonly manualMode = signal(false);
  readonly benchmarkReady = signal(false);
  readonly machineAidsAllowed = computed(() => this.benchmarkReady() && !this.manualMode());
  readonly triageData = signal<ClaimTriage | null>(null);
  readonly triageLoading = signal(false); readonly triageBusy = signal(false); readonly triageError = signal(false);
  private readonly clock = signal(Date.now());
  readonly triage = computed(() => freshTriage(this.triageData(), this.clock()));
  readonly orderedRows = computed(() => queueByPriority(this.rows(), this.triage(), !this.machineAidsAllowed()));
  readonly queueItems = computed<WorkRecordItem[]>(() => this.orderedRows().map(row => {
    const priority = this.machineAidsAllowed() ? this.priorityFor(row.claim_id) : null;
    const knownState = ['to_investigate', 'waiting_information', 'awaiting_decision', 'resolved'].includes(row.state);
    const opened = Date.parse(row.opened_at);
    return {
      id: row.claim_id, title: row.order_id, subtitle: row.display_name,
      value: this.money(row.paid_amount, row.currency), description: this.i18n.t(this.reasonLabel(row.reason)),
      meta: row.claim_id + (Number.isFinite(opened) ? ' · ' + new Intl.DateTimeFormat(this.i18n.locale(), { day: '2-digit', month: '2-digit' }).format(opened) : ''),
      status: { value: row.state, label: knownState ? this.i18n.t('experience.claims.state.' + row.state) : this.i18n.t('experience.claims.unknown') },
      ...(priority ? { badge: { label: `${this.priorityLabel(priority.priority)} · ${this.percent(priority.risk)}`, ...(priority.priority === 'high' ? { tone: 'warning' as const } : {}) } } : {}),
    };
  }));
  readonly advice = computed(() => selectedAdvice(this.triage(), this.run(), this.selected(), !this.machineAidsAllowed(), this.clock()));
  readonly caseData = computed(() => caseDatasets(this.triage(), this.run(), this.selected(), !this.machineAidsAllowed(), this.clock()));
  protected readonly mayDecide = mayDecide;
  readonly busy = signal(false);
  readonly detailReadFailed = signal(false);
  readonly runReadFailed = signal<string | null>(null);
  readonly runRefreshing = signal(false);
  /** Keep an uncertain submission and its idempotency key attached to its case.
   * A latest-run lookup cannot prove whether this exact request was received. */
  private readonly investigationRequests = signal<Record<string, InvestigationRequest>>({});
  readonly investigationRequest = computed(() => this.investigationRequests()[this.investigationKey()] ?? null);
  readonly investigationUnconfirmed = computed(() => ['sending', 'unknown', 'confirmed'].includes(this.investigationRequest()?.state ?? ''));
  readonly runFailureMessage = computed(() => claimInvestigationFailureMessage(this.run()));
  /** Unresolved answers survive record/workspace changes, without leaking into
   * another record. The target pause is retained independently of live polling. */
  private readonly decisionNotices = signal<DecisionNoticeMap>({});
  readonly decisionNotice = computed(() => noticeForRun(this.decisionNotices(), this.workspace.current()?.id ?? null, this.run()));
  readonly sourceDocumentId = signal<string | null>(null);
  readonly projection = computed(() => claimRunProjection(this.machineAidsAllowed() ? this.run() : null));
  readonly recordedActions = computed(() => this.machineAidsAllowed() ? recordedClaimActions(this.detail(), this.projection().proposal) : []);
  readonly actionGroups = computed(() => claimActionGroups(this.recordedActions(), this.projection().proposal, this.run()?.id ?? null));
  readonly sources = computed(() => {
    const cited = this.projection().proposal?.citations ?? [];
    const originals: Record<string, unknown>[] = this.detail()?.sources ?? [];
    const seen = new Set<string>();
    const citedIds = new Set(cited.map(s => String(s['document_id'])));
    return [...cited, ...originals].filter(source => {
      const key = String(source['document_id']);
      if (seen.has(key)) return false; seen.add(key); return true;
    }).map((source, index) => workSourceRef(source, index + 1, { cited: citedIds.has(String(source['document_id'])) }));
  });
  readonly sourceIndex = computed(() => this.sources().find(source => source.documentId === this.sourceDocumentId())?.n ?? null);
  selectSource(index: number): void {
    this.sourceDocumentId.set(this.sources().find(source => source.n === index)?.documentId ?? null);
  }
  private poll?: Subscription; private priorityPoll?: Subscription; private detailRequest?: Subscription; private generation = 0;
  constructor() {
    effect(() => { this.workspace.current()?.id; void this.load(); });
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroy)).subscribe(params => {
      const id = params.get('record');
      if (this.loading() || !id || id === this.selected()) return;
      // A manual trial or an in-flight action owns its selection until settled.
      if (this.busy() || this.manualMode()) {
        if (this.selected()) void this.writeRecordUrl(this.selected()!, true);
        return;
      }
      if (this.rows().some(row => row.claim_id === id)) this.select(id, false);
    });
    timer(0, 60000).pipe(takeUntilDestroyed(this.destroy)).subscribe(() => this.clock.set(Date.now()));
    this.destroy.onDestroy(() => { this.generation++; this.poll?.unsubscribe(); this.priorityPoll?.unsubscribe(); this.detailRequest?.unsubscribe(); });
  }
  async load(): Promise<void> {
    const generation = ++this.generation;
    this.poll?.unsubscribe(); this.priorityPoll?.unsubscribe(); this.detailRequest?.unsubscribe();
    this.releasePages.set(null);
    this.triageData.set(null); this.triageBusy.set(false); this.triageError.set(false); this.triageLoading.set(false);
    this.benchmarkReady.set(false);
    this.rows.set([]); this.detail.set(null); this.run.set(null); this.selected.set(null); this.sourceDocumentId.set(null);
    this.error.set(false); this.dataError.set(null); this.canConfigureData.set(false);
    this.detailReadFailed.set(false); this.runReadFailed.set(null); this.runRefreshing.set(false);
    this.loading.set(true); this.busy.set(false);
    try {
      const release = await firstValueFrom(this.work.resolve('reclamations'));
      if (generation !== this.generation) return;
      this.appMissing.set(release.kind === 'missing');
      if (release.kind !== 'ok') throw Error('Release unavailable');
      this.releasePages.set(release.body.release.pages ?? null);
      this.releaseTheme.set(workTheme(release.body.release.theme as Record<string, unknown> | null | undefined));
      void this.loadDataAccess(generation);
      const response = await firstValueFrom(this.api.get<{ data: { queue: ClaimRow[] } }>('/ecommerce-claims'));
      if (generation !== this.generation) return;
      this.rows.set(response.data.queue); this.loading.set(false);
      const requested = this.route.snapshot.queryParamMap.get('record');
      const initial = response.data.queue.find(row => row.claim_id === requested) ?? response.data.queue[0];
      if (initial) { this.select(initial.claim_id, false); void this.writeRecordUrl(initial.claim_id, true); }
      void this.loadTriage(generation);
    } catch (error) { if (generation === this.generation) { this.dataError.set(this.readFailure(error)); this.error.set(true); this.loading.set(false); } }
  }
  private async loadDataAccess(generation: number): Promise<void> {
    // Work consumers may read cases without administering their source. Use the
    // server's capability, and never retain it across a workspace or release reload.
    try {
      const response = await firstValueFrom(this.api.get<{ can_configure: boolean }>('/connectors'));
      if (generation === this.generation) this.canConfigureData.set(response.can_configure === true);
    } catch { if (generation === this.generation) this.canConfigureData.set(false); }
  }
  private readFailure(error: unknown): PgFailure | null {
    const code = (error as { error?: { detail?: { code?: unknown } } } | null)?.error?.detail?.code;
    return typeof code === 'string' && PG_ERROR_CODES.has(code) ? pgFailure(error) : null;
  }
  retryData(): void {
    if (this.error()) void this.load();
    else if (this.selected()) this.refreshDetail(this.selected()!);
  }
  private async loadTriage(generation = this.generation): Promise<void> {
    this.triageLoading.set(true);
    try {
      const response = await firstValueFrom(this.api.get<ClaimTriage>('/ecommerce-claims/triage'));
      if (generation === this.generation) { this.clock.set(Date.now()); this.triageData.set(response); }
    } catch { if (generation === this.generation) this.triageData.set({ status: 'unavailable', rows: [] }); }
    finally { if (generation === this.generation) this.triageLoading.set(false); }
  }
  priorityFor(claimId: string) { return this.triage()?.status === 'ready' ? this.triage()?.rows.find(row => row.claim_id === claimId) : null; }
  priorityLabel(key: string): string { return this.triage()?.prediction_contract?.bands?.find(band => band.key === key)?.label ?? this.i18n.t('experience.claims.triage.priority.' + key); }
  percent(value: number): string { return new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 0 }).format(value); }
  async recalculatePriority(): Promise<void> {
    const scoring = this.triage()?.scoring;
    if (!scoring || this.triageBusy() || this.busy() || !this.machineAidsAllowed()) return;
    const generation = this.generation; this.triageBusy.set(true); this.triageError.set(false);
    try {
      const result = await firstValueFrom(this.triage()?.composition
        ? this.api.post<{ id: string }>('/work/reclamations/bindings/showcase.claims.refresh_queue/runs', {
            payload: {}, confirmed: true, page_id: 'dossier', component_id: 'queue_refresh',
          }, { headers: { 'Idempotency-Key': crypto.randomUUID() } })
        : this.api.post<{ id: string }>(`/systems/${scoring.system_id}/ingresses/${scoring.ingress_id}/runs`, {
            kind: 'manual', payload: {}, expected_published_version_id: scoring.version_id, expected_flow_sha256: scoring.flow_sha256,
          }));
      if (generation !== this.generation) return;
      this.priorityPoll?.unsubscribe();
      this.priorityPoll = pollRun(() => this.canonical.getRun(result.id)).pipe(takeUntilDestroyed(this.destroy)).subscribe({
        next: run => {
          if (generation !== this.generation) return;
          if (!run || ['completed', 'failed', 'cancelled'].includes(run.status)) {
            this.priorityPoll?.unsubscribe(); this.triageBusy.set(false);
            if (run?.status === 'completed') void this.loadTriage(generation); else this.triageError.set(true);
          }
        }, error: () => { if (generation === this.generation) { this.priorityPoll?.unsubscribe(); this.triageBusy.set(false); this.triageError.set(true); } },
      });
    } catch { if (generation === this.generation) { this.triageBusy.set(false); this.triageError.set(true); } }
  }
  /** Attempt chosen by the reader; a refresh never swaps it for the latest. */
  readonly pinnedRun = signal<string | null>(null);
  readonly attemptsRefresh = signal(0);
  openAttempt(runId: string): void {
    const id = this.selected();
    if (!id || this.run()?.id === runId) return;
    this.poll?.unsubscribe();
    this.pinnedRun.set(runId);
    this.run.set(null); this.runReadFailed.set(null);
    void this.writeRecordUrl(id, true);
    this.watchRun(runId, id);
  }
  select(id: string, updateUrl = true): void {
    // A record opened from the URL keeps the attempt the URL names.
    const requested = updateUrl ? null : this.route?.snapshot?.queryParamMap?.get('attempt') ?? null;
    this.pinnedRun.set(requested && requested.trim() ? requested : null);
    this.poll?.unsubscribe(); this.detailRequest?.unsubscribe(); this.run.set(null); this.detail.set(null);
    this.selected.set(id); this.sourceDocumentId.set(null); this.detailReadFailed.set(false); this.runReadFailed.set(null); this.runRefreshing.set(false); this.dataError.set(null); this.detailLoading.set(true);
    if (updateUrl) void this.writeRecordUrl(id);
    this.refreshDetail(id);
  }
  private writeRecordUrl(id: string, replaceUrl = false): Promise<boolean> {
    return this.router.navigate([], { relativeTo: this.route, queryParams: { record: id, attempt: this.pinnedRun() }, queryParamsHandling: 'merge', replaceUrl });
  }
  private refreshDetail(id: string): void {
    const generation = this.generation;
    this.detailRequest?.unsubscribe();
    this.detailLoading.set(true);
    this.detailRequest = this.api.get<ClaimSnapshot>(`/ecommerce-claims/${encodeURIComponent(id)}`).pipe(takeUntilDestroyed(this.destroy)).subscribe({
      next: detail => { if (generation === this.generation && this.selected() === id) { this.dataError.set(null); this.detailReadFailed.set(false); this.detail.set(detail); this.detailLoading.set(false); const shown = this.pinnedRun() ?? detail.latest_run_id; if (shown && !this.run()) this.watchRun(shown, id); } },
      error: error => { if (generation === this.generation && this.selected() === id) { this.dataError.set(this.readFailure(error)); this.detailLoading.set(false); this.detailReadFailed.set(true); } },
    });
  }
  private investigationKey(): string { return JSON.stringify([this.workspace.current()?.id ?? null, this.selected()]); }
  async investigate(reexamine = false, resume = false): Promise<void> {
    const id = this.selected();
    const requestKey = this.investigationKey();
    const prior = this.investigationRequests()[requestKey];
    if (!id || this.busy() || !this.machineAidsAllowed() || prior?.state === 'sending'
      || resume && prior?.state !== 'unknown' || !resume && (this.investigationUnconfirmed() || this.runReadFailed() || this.detailReadFailed()
        || this.recordedActions().length && !reexamine || ['running', 'pending', 'hitl_pending'].includes(this.run()?.status ?? ''))) return;
    const generation = this.generation;
    const key = prior?.key ?? crypto.randomUUID();
    this.investigationRequests.update(current => ({ ...current, [requestKey]: { key, state: 'sending' } }));
    this.busy.set(true);
    try {
      const result = await firstValueFrom(this.api.post<{ id: string }>('/work/reclamations/bindings/showcase.claims.investigate/runs',
        { payload: { claim_id: id }, confirmed: true, page_id: 'dossier', component_id: 'investigation' },
        { headers: { 'Idempotency-Key': key } }));
      if (!result?.id) throw new Error('Unconfirmed investigation');
      if (generation !== this.generation || this.selected() !== id) {
        // A late success still owns this case's request. Preserve its exact Run
        // for read-only recovery; clearing the lock here could permit a duplicate.
        this.investigationRequests.update(current => ({ ...current, [requestKey]: { key, state: 'confirmed', runId: result.id } }));
        return;
      }
      // A new analysis becomes the shown attempt; earlier ones stay listed.
      this.pinnedRun.set(null); this.attemptsRefresh.update(n => n + 1);
      void this.writeRecordUrl(id, true);
      this.run.set({ id: result.id, system_id: '', status: 'pending' });
      this.investigationRequests.update(current => { const next = { ...current }; delete next[requestKey]; return next; });
      this.watchRun(result.id, id);
    } catch (error) {
      const problem = writeFailure(error);
      // Keep an earlier uncertain result uncertain, even if a later replay is
      // refused: that refusal does not prove the original request was absent.
      const state = prior?.state === 'unknown' || problem.s === 'unknown' ? 'unknown' : 'rejected';
      this.investigationRequests.update(current => ({ ...current, [requestKey]: { key, state } }));
    }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  refreshInvestigation(): void {
    const id = this.selected(); const request = this.investigationRequest();
    const runId = request?.state === 'confirmed' ? request.runId : this.runReadFailed();
    if (id && runId && !this.runRefreshing()) this.watchRun(runId, id);
  }
  private watchRun(runId: string, claimId: string): void {
    this.poll?.unsubscribe(); const g = this.generation;
    this.runRefreshing.set(true);
    this.poll = pollRun(() => this.canonical.getRun(runId)).pipe(takeUntilDestroyed(this.destroy)).subscribe({
      next: run => { if (g !== this.generation || this.selected() !== claimId) return;
        this.runRefreshing.set(false);
        if (!run || run.id !== runId) { this.runReadFailed.set(runId); this.poll?.unsubscribe(); return; }
        if (this.pinnedRun() === run.id && run.input_ref?.['claim_id'] !== undefined && run.input_ref['claim_id'] !== claimId) {
          // An attempt named in the URL must belong to this case.
          this.pinnedRun.set(null); this.poll?.unsubscribe(); this.run.set(null); void this.writeRecordUrl(claimId, true); this.refreshDetail(claimId); return;
        }
        this.runReadFailed.set(null);
        this.clock.set(Date.now());
        this.run.set(run);
        const request = this.investigationRequest();
        if (request?.state === 'confirmed' && request.runId === run.id) {
          const key = this.investigationKey();
          this.investigationRequests.update(current => { const next = { ...current }; delete next[key]; return next; });
        }
        if (['completed', 'failed', 'cancelled'].includes(run.status)) { this.poll?.unsubscribe(); this.refreshDetail(claimId); }
      }, error: () => { if (g === this.generation && this.selected() === claimId) { this.runRefreshing.set(false); this.runReadFailed.set(runId); } },
    });
  }
  async decide(action: 'accept' | 'reject'): Promise<void> {
    const run = this.run(); if (!run || this.busy() || !this.machineAidsAllowed() || this.decisionNotice()?.unknown || !mayDecide(run.hitl)) return;
    const workspaceId = this.workspace.current()?.id;
    if (!workspaceId) return;
    const target: DecisionNoticeTarget = { workspaceId, runId: run.id, decisionId: run.hitl?.decision_id ?? null };
    this.busy.set(true);
    const generation = this.generation;
    // If the workspace changes while the request is in flight, its original
    // pause remains locked until the response arrives or that pause is checked.
    this.setDecisionNotice(target, decisionMessage({ s: 'sent' }, action), true, false);
    try {
      const outcome = await lastValueFrom(this.work.decide(run, action, this.i18n.t('experience.claims.decision_note')));
      if (outcome.s === 'confirmed' || outcome.s === 'accepted') this.setDecisionNotice(target, null);
      else this.setDecisionNotice(target, decisionMessage(outcome, action), outcome.s === 'unknown', outcome.s === 'unknown' || (outcome.s === 'failed' && outcome.status === 409));
      if (generation !== this.generation || this.run()?.id !== run.id) return;
      if (outcome.s === 'confirmed' || outcome.s === 'accepted') {
        const updated = outcome.value;
        this.run.set({ ...run, ...updated, skill_invocations: updated.skill_invocations ?? run.skill_invocations });
      }
    }
    catch { this.setDecisionNotice(target, decisionMessage({ s: 'unknown', status: null, code: null }, action), true, true); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  /** Reads the Run back after a lost answer; deciding again is allowed only if it still waits. */
  async checkDecision(): Promise<void> {
    const run = this.run(); if (!run || this.busy()) return;
    const notice = this.decisionNotice();
    if (!notice?.verifiable) return;
    const generation = this.generation;
    this.busy.set(true);
    try {
      const check = await lastValueFrom(this.work.checkDecision({ ...run, hitl: { ...run.hitl, decision_id: notice.decisionId ?? undefined } }));
      if (check.s === 'pending') this.setDecisionNotice(notice, null);
      else this.setDecisionNotice(notice, checkMessage(check), check.s !== 'recorded', check.s !== 'recorded');
      if (generation !== this.generation || this.run()?.id !== run.id) return;
      if (check.s === 'recorded' || check.s === 'pending') {
        this.run.set({ ...run, ...check.run, skill_invocations: check.run.skill_invocations ?? run.skill_invocations });
      }
    } catch { this.setDecisionNotice(notice, checkMessage({ s: 'unknown' }), true, true); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private setDecisionNotice(target: DecisionNoticeTarget, message: DecisionMessage | null, unknown = false, verifiable = false): void {
    this.decisionNotices.update(current => {
      const next = { ...current };
      const key = decisionNoticeKey(target);
      if (message) next[key] = { ...target, ...message, unknown, verifiable };
      else delete next[key];
      return next;
    });
  }
  money(value: string | null | undefined, currency: string): string {
    if (value == null || !value.trim() || !/^[A-Z]{3}$/.test(currency) || !Number.isFinite(Number(value))) return this.i18n.t('experience.claims.unknown');
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(Number(value));
  }
  receiptView(receipt: ClaimProposal): WorkActionReceipt {
    return { reference: receipt.receipt_id!, label: this.i18n.t('experience.claims.recorded.' + receipt.action),
      ...(receipt.action === 'refund' ? { value: this.money(receipt.amount, receipt.currency) } : {}),
      notice: [this.i18n.t('experience.claims.simulated'),
        ...(receipt.idempotent_replay && receipt.reused_for_run_id === this.run()?.id ? [this.i18n.t('experience.claims.receipt_reused')] : []),
      ].join('. '),
      ...(receipt.executed_at && Number.isFinite(Date.parse(receipt.executed_at)) ? { recordedAt: receipt.executed_at } : {}),
    };
  }
  refundState(value: string): string { return this.i18n.t(['executed', 'failed', 'prepared', 'approved'].includes(value) ? 'experience.claims.refund.' + value : 'experience.claims.unknown'); }
  shipping(value?: string): string { return this.i18n.t(value === 'in_transit' ? 'experience.claims.shipping.in_transit' : value === 'lost' ? 'experience.claims.shipping.lost' : value === 'delivered' ? 'experience.claims.shipping.delivered' : 'experience.claims.unknown'); }
  toolLabel(value?: string): string { return CLAIM_TOOL_LABELS[value ?? ''] ?? 'experience.claims.inquiry'; }
  actionLabel(value: string): string { return CLAIM_ACTION_LABELS[value] ?? 'experience.claims.unknown'; }
  reasonLabel(value: string): string { return CLAIM_REASON_LABELS[value] ?? 'experience.claims.unknown'; }
  stepState(value?: string): string { return this.i18n.t(value === 'completed' ? 'experience.claims.step.done' : value === 'failed' ? 'experience.claims.step.failed' : 'experience.claims.step.pending'); }
  stepOutcome(step: SkillInvocation) { return typedJudgeOutcome(typedResult(step.output_ref)); }
}
