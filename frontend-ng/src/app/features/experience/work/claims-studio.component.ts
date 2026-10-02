import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { firstValueFrom, Subscription, timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { WorkSourcePanelComponent } from '@app/shared/work-sources/work-source-panel.component';
import { workSourceRef } from '@app/shared/work-sources/work-source';
import { WorkBarComponent } from './work-bar.component';
import { WorkAppHeaderComponent } from './work-app-header.component';
import { ClaimsBenchmarkComponent } from './claims-benchmark.component';
import { WorkApiService } from './work-api.service';
import { CLAIM_ACTION_LABELS, CLAIM_REASON_LABELS, CLAIM_TOOL_LABELS, claimRunProjection, type ClaimRow, type ClaimSnapshot } from './claim-run';

@Component({
  selector: 'app-claims-studio', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, WorkBarComponent, WorkAppHeaderComponent, WorkSourcePanelComponent, NavLinkDirective, ClaimsBenchmarkComponent, IconComponent],
  styleUrls: ['./work.scss', './claims-studio.scss'],
  template: `
    <div class="xp-work claims-app">
      <app-work-bar [appContext]="i18n.t('experience.claims.title')" />
      <app-work-app-header [title]="i18n.t('experience.claims.title')" [eyebrow]="i18n.t('experience.claims.brand')"
        [description]="i18n.t('experience.claims.promise')" [status]="i18n.t('experience.claims.demo')" emblem="◈">
        @if (run(); as current) { <a class="xp-work-btn" [navLink]="{ type: 'run', lens: 'operate', ref: current.id }">{{ i18n.t('experience.claims.trace') }}</a> }
      </app-work-app-header>
      @if (!loading() && !error()) { <app-claims-benchmark [sources]="detail()?.sources ?? []" (caseSelected)="select($event)" (manualActive)="manualMode.set($event)" /> }
      <main class="claims-main" aria-labelledby="work-app-title">
        @if (loading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
        @if (error()) { <div class="claims-error" role="alert"><p>{{ i18n.t('experience.claims.unavailable') }}</p><button class="xp-work-btn" (click)="load()">{{ i18n.t('experience.claims.retry') }}</button></div> }
        @if (!loading() && !error()) {
          <aside class="claims-queue" [attr.aria-label]="i18n.t('experience.claims.queue')">
            <div class="claims-section-title"><h2>{{ i18n.t('experience.claims.queue') }}</h2><span>{{ rows().length }}</span></div>
            @for (row of rows(); track row.claim_id) {
              <button class="claims-case" [class.is-selected]="selected() === row.claim_id" [attr.aria-pressed]="selected() === row.claim_id"
                [disabled]="busy() || manualMode()" (click)="select(row.claim_id)">
                <span class="claims-case-top"><strong>{{ row.order_id }}</strong><b>{{ money(row.paid_amount, row.currency) }}</b></span>
                <span>{{ row.display_name }}</span><span class="claims-case-reason">{{ i18n.t(reasonLabel(row.reason)) }}</span>
                <span class="claims-case-foot">{{ row.claim_id }} · {{ row.opened_at | date:'dd/MM' }}</span>
              </button>
            } @empty { <p>{{ i18n.t('experience.claims.empty') }}</p> }
            <p class="claims-quiet">{{ i18n.t('experience.claims.synthetic') }}</p>
          </aside>
          @if (!detail() && !detailLoading() && actionError()) { <div class="claims-error" role="alert"><p>{{ i18n.t('experience.claims.unavailable') }}</p><button class="xp-work-btn" (click)="select(selected()!)">{{ i18n.t('experience.claims.retry') }}</button></div> }
          @if (detail(); as dossier) {
            <section class="claims-dossier" [attr.aria-label]="i18n.t('experience.claims.dossier')">
              <div class="claims-section-title"><h2>{{ dossier.data.context[0].order_id }}</h2><span>{{ i18n.t('experience.claims.dossier') }}</span></div>
              <div class="claims-facts">
                <article><span>{{ i18n.t('experience.claims.paid') }}</span><strong>{{ money(dossier.data.context[0].paid_amount, dossier.data.context[0].currency) }}</strong></article>
                <article><span>{{ i18n.t('experience.claims.postcode') }}</span><strong>{{ dossier.data.context[0].shipping_postcode }}</strong></article>
                <article><span>{{ i18n.t('experience.claims.shipping') }}</span><strong>{{ shipping(dossier.data.shipments[0]?.status) }}</strong></article>
              </div>
              <p class="claims-provenance">{{ i18n.t('experience.claims.database') }} · {{ dossier.provenance.captured_at | date:'dd/MM HH:mm:ss' }}</p>
              <article class="claims-panel"><h3>{{ i18n.t('experience.claims.order') }}</h3>
                @for (item of dossier.data.items; track $index) { <p>{{ item.product_name }} · {{ item.quantity }} × {{ money(item.unit_price, 'EUR') }}</p> }
                @for (shipment of dossier.data.shipments; track shipment.tracking_id) { <p class="claims-quiet">{{ shipment.carrier }} · {{ shipment.tracking_id }}</p> }
                <h3>{{ i18n.t('experience.claims.refunds') }}</h3>
                @for (refund of dossier.data.refunds; track refund.refund_id) { <p>{{ refund.refund_id }} · {{ money(refund.amount, refund.currency) }} · {{ refundState(refund.status) }}</p> }
                @empty { <p class="claims-quiet">{{ i18n.t('experience.claims.no_refund') }}</p> }
              </article>
              <article class="claims-panel"><h3>{{ i18n.t('experience.claims.documents') }}</h3>
                <div class="claims-source-list">@for (source of sources(); track source.documentId) {
                  <button class="claims-source" (click)="selectSource(source.n)"><app-icon name="external-link" [size]="14" /><span>{{ source.title }}</span></button>
                } @empty { <p>{{ i18n.t('experience.claims.no_sources') }}</p> }</div>
                @if (sourceIndex(); as n) { <app-work-source-panel [sources]="sources()" [selected]="n" (selectedChange)="selectSource($event)" (closed)="sourceDocumentId.set(null)" /> }
              </article>
              <article class="claims-panel"><h3>{{ i18n.t('experience.claims.inquiry') }}</h3>
                <ol class="claims-steps" aria-live="polite">@for (step of projection().steps; track step.id) {
                  <li [attr.data-state]="step.status"><span class="claims-step-dot" aria-hidden="true"></span><span>{{ i18n.t(toolLabel(step.skill_slug)) }}</span><span class="claims-quiet">{{ stepState(step.status) }}</span></li>
                } @empty { <li class="claims-quiet claims-step-empty">{{ i18n.t('experience.claims.not_started') }}</li> }</ol>
              </article>
            </section>
            <aside class="claims-decision" [attr.aria-label]="i18n.t('experience.claims.decision')">
              <h2>{{ i18n.t('experience.claims.decision') }}</h2>
              @if (projection().proposal; as proposal) {
                <div class="claims-recommendation" [class.is-warning]="proposal.action !== 'refund'"><span class="claims-eyebrow">{{ i18n.t('experience.claims.proposal') }}</span><h3>{{ i18n.t(actionLabel(proposal.action)) }}</h3><p>{{ i18n.t(reasonLabel(proposal.reason)) }}</p>
                  @if (proposal.action === 'refund') { <strong class="claims-amount">{{ money(proposal.amount, proposal.currency) }}</strong> }
                  @if (proposal.missing_references.length) { <p>{{ i18n.t('experience.claims.missing') }}</p> }
                </div>
                @if (proposal.receipt_id) { <div class="claims-receipt" role="status"><h3>{{ i18n.t('experience.claims.receipt') }}</h3><p>{{ i18n.t('experience.claims.simulated') }}</p><code>{{ proposal.receipt_id }}</code></div> }
              } @else { <p class="claims-quiet">{{ i18n.t('experience.claims.start_hint') }}</p> }
              @if (run()?.status === 'hitl_pending') {
                <div class="claims-approval"><p>{{ i18n.t('experience.claims.approval_hint') }}</p>
                  <button class="xp-work-btn xp-work-btn-primary" [disabled]="busy()" (click)="decide('accept')">{{ i18n.t('experience.claims.approve') }}</button>
                  <button class="xp-work-btn" [disabled]="busy()" (click)="decide('reject')">{{ i18n.t('experience.claims.reject') }}</button>
                </div>
              } @else if (run()?.status === 'running' || run()?.status === 'pending') { <p role="status">{{ i18n.t('experience.claims.running') }}</p> }
              @else { <button class="xp-work-btn xp-work-btn-primary claims-primary" [disabled]="busy() || manualMode()" (click)="investigate()">{{ i18n.t('experience.claims.investigate') }}</button> }
              @if (actionError()) { <p class="claims-error" role="alert">{{ i18n.t('experience.claims.action_error') }}</p> }
              <p class="claims-quiet">{{ i18n.t('experience.claims.action_notice') }}</p>
              @if (dossier.receipts.length) { <h3>{{ i18n.t('experience.claims.history') }}</h3>@for (receipt of dossier.receipts; track receipt.receipt_id) { <p class="claims-history">{{ i18n.t(actionLabel(receipt.action)) }}<br><small>{{ i18n.t('experience.claims.simulated') }}</small></p> } }
            </aside>
          } @else if (detailLoading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
        }
      </main>
    </div>
  `,
})
export class ClaimsStudioComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly work = inject(WorkApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  readonly rows = signal<ClaimRow[]>([]); readonly selected = signal<string | null>(null);
  readonly detail = signal<ClaimSnapshot | null>(null); readonly run = signal<Run | null>(null);
  readonly loading = signal(true); readonly detailLoading = signal(false); readonly error = signal(false);
  readonly manualMode = signal(false);
  readonly busy = signal(false); readonly actionError = signal(false); readonly sourceDocumentId = signal<string | null>(null);
  readonly projection = computed(() => claimRunProjection(this.manualMode() ? null : this.run()));
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
  private poll?: Subscription; private detailRequest?: Subscription; private generation = 0;
  constructor() {
    effect(() => { this.workspace.current()?.id; void this.load(); });
    this.destroy.onDestroy(() => { this.generation++; this.poll?.unsubscribe(); this.detailRequest?.unsubscribe(); });
  }
  async load(): Promise<void> {
    const generation = ++this.generation;
    this.poll?.unsubscribe(); this.detailRequest?.unsubscribe();
    this.rows.set([]); this.detail.set(null); this.run.set(null); this.selected.set(null); this.sourceDocumentId.set(null);
    this.error.set(false); this.loading.set(true); this.busy.set(false);
    try {
      const release = await firstValueFrom(this.work.resolve('reclamations'));
      if (generation !== this.generation) return;
      if (release.kind !== 'ok') throw Error('Release unavailable');
      const response = await firstValueFrom(this.api.get<{ data: { queue: ClaimRow[] } }>('/ecommerce-claims'));
      if (generation !== this.generation) return;
      this.rows.set(response.data.queue); this.loading.set(false);
      if (response.data.queue[0]) this.select(response.data.queue[0].claim_id);
    } catch { if (generation === this.generation) { this.error.set(true); this.loading.set(false); } }
  }
  select(id: string): void {
    this.poll?.unsubscribe(); this.detailRequest?.unsubscribe(); this.run.set(null); this.detail.set(null);
    this.selected.set(id); this.sourceDocumentId.set(null); this.actionError.set(false); this.detailLoading.set(true);
    this.refreshDetail(id);
  }
  private refreshDetail(id: string): void {
    this.detailRequest = this.api.get<ClaimSnapshot>(`/ecommerce-claims/${encodeURIComponent(id)}`).pipe(takeUntilDestroyed(this.destroy)).subscribe({
      next: detail => { if (this.selected() === id) { this.detail.set(detail); this.detailLoading.set(false); if (detail.latest_run_id && !this.run()) this.watchRun(detail.latest_run_id, id); } },
      error: () => { this.detailLoading.set(false); this.actionError.set(true); },
    });
  }
  async investigate(): Promise<void> {
    const id = this.selected(); if (!id || this.busy() || this.manualMode()) return;
    const generation = this.generation;
    this.busy.set(true); this.actionError.set(false);
    try {
      const result = await firstValueFrom(this.api.post<{ id: string }>('/work/reclamations/bindings/showcase.claims.investigate/runs',
        { payload: { claim_id: id }, confirmed: true, page_id: 'dossier', component_id: 'investigation' },
        { headers: { 'Idempotency-Key': crypto.randomUUID() } }));
      if (generation !== this.generation || this.selected() !== id) return;
      this.run.set({ id: result.id, system_id: '', status: 'pending' });
      this.watchRun(result.id, id);
    } catch { if (generation === this.generation) this.actionError.set(true); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
  private watchRun(runId: string, claimId: string): void {
    this.poll?.unsubscribe(); const g = this.generation;
    this.poll = timer(0, 2000).pipe(switchMap(() => this.canonical.getRun(runId)), takeUntilDestroyed(this.destroy)).subscribe({
      next: run => { if (g !== this.generation || this.selected() !== claimId) return;
        if (!run) { this.actionError.set(true); this.poll?.unsubscribe(); return; }
        this.run.set(run);
        if (['completed', 'failed', 'cancelled'].includes(run.status)) { this.poll?.unsubscribe(); this.refreshDetail(claimId); }
        if (run.status === 'failed') this.actionError.set(true);
      }, error: () => { if (g === this.generation) this.actionError.set(true); },
    });
  }
  async decide(action: 'accept' | 'reject'): Promise<void> {
    const run = this.run(); if (!run || this.busy()) return;
    this.busy.set(true); this.actionError.set(false);
    const generation = this.generation;
    try { const updated = await firstValueFrom(this.work.decide(run, action, this.i18n.t('experience.claims.decision_note'))); if (updated && generation === this.generation && this.run()?.id === run.id) this.run.set({ ...run, ...updated, skill_invocations: updated.skill_invocations ?? run.skill_invocations }); }
    catch { if (generation === this.generation) this.actionError.set(true); } finally { if (generation === this.generation) this.busy.set(false); }
  }
  money(value: string | null | undefined, currency: string): string {
    if (value == null || !value.trim() || !/^[A-Z]{3}$/.test(currency) || !Number.isFinite(Number(value))) return this.i18n.t('experience.claims.unknown');
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(Number(value));
  }
  refundState(value: string): string { return this.i18n.t(['executed', 'failed', 'prepared', 'approved'].includes(value) ? 'experience.claims.refund.' + value : 'experience.claims.unknown'); }
  shipping(value?: string): string { return this.i18n.t(value === 'in_transit' ? 'experience.claims.shipping.in_transit' : value === 'lost' ? 'experience.claims.shipping.lost' : value === 'delivered' ? 'experience.claims.shipping.delivered' : 'experience.claims.unknown'); }
  toolLabel(value?: string): string { return CLAIM_TOOL_LABELS[value ?? ''] ?? 'experience.claims.inquiry'; }
  actionLabel(value: string): string { return CLAIM_ACTION_LABELS[value] ?? 'experience.claims.unknown'; }
  reasonLabel(value: string): string { return CLAIM_REASON_LABELS[value] ?? 'experience.claims.unknown'; }
  stepState(value?: string): string { return this.i18n.t(value === 'completed' ? 'experience.claims.step.done' : value === 'failed' ? 'experience.claims.step.failed' : 'experience.claims.step.pending'); }
}
