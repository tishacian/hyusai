import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { RouterLink } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { ModelsService } from './models.service';
import { diagnosticDoc, diagnosticRows, partitionRecorded, type EvaluationReview } from './evaluation-evidence.vm';
import type { MetricsBlock } from './models.vm';

@Component({
  selector: 'ck-evaluation-evidence', standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ck-evaluation" data-testid="evaluation-evidence">
      <h3>{{ i18n.t('models.evaluation.title') }}</h3>
      <p class="ck-hint" data-testid="evaluation-partition">{{ i18n.t(recorded() ? 'models.evaluation.recorded' : 'models.evaluation.unverified') }}</p>
      @if (recorded() && metrics()?.evaluation?.rows; as rows) {
        <p class="ck-hint">{{ i18n.t('models.evaluation.rows', { train: rows.train, test: rows.test }) }}</p>
      }
      @if (recorded() && metrics()?.evaluation?.fingerprint; as hash) {
        <details><summary>{{ i18n.t('models.evaluation.fingerprint') }}</summary><code>{{ hash }}</code></details>
      }
      @if (metrics()?.evaluation?.duplicate_overlap) { <p class="ck-warning">{{ i18n.t('models.evaluation.duplicates') }}</p> }
      @if (metrics()?.metric_semantics?.positive_class; as positive) {
        <p class="ck-hint">{{ i18n.t('models.evaluation.positive', { label: positive }) }}</p>
      }
      <p class="ck-hint">{{ i18n.t('models.evaluation.scope') }}</p>
      <p class="ck-hint" data-testid="diagnostic-status">{{ i18n.t(statusKey()) }}</p>
      @for (row of rows(); track row.code) {
        <details tabindex="-1" [id]="'evaluation-check-' + row.code" [attr.data-check-code]="row.code" [attr.data-check-section]="row.section" [open]="row.section === 'issue' || row.section === 'error'">
          <summary>{{ row.code }} · {{ row.title }} · {{ i18n.t('models.evaluation.section.' + row.section) }}</summary>
          @if (row.explanation) { <p class="ck-explanation">{{ row.explanation }}</p> }
          @if (doc(row.documentation_url); as url) { <a [href]="url" target="_blank" rel="noopener noreferrer">{{ i18n.t('models.evaluation.documentation') }}</a> }
        </details>
      }
      @if (metrics()?.diagnostics?.status === 'completed' && recorded()) {
        <button class="ck-btn-primary" type="button" [disabled]="busy()" (click)="review()">{{ i18n.t('models.evaluation.review') }}</button>
      }
      @if (failed()) { <p class="ck-warning" role="alert">{{ i18n.t('models.evaluation.review_error') }}</p> }
      @if (reviewed(); as value) {
        <p class="ck-hint">{{ i18n.t('models.evaluation.review_scope') }}</p>
        @if (!value.proposals.length) { <p class="ck-hint">{{ i18n.t('models.evaluation.no_proposals') }}</p> }
        @for (proposal of value.proposals; track proposal.code) {
          <p><a [routerLink]="[]" [fragment]="proposal.evidence_anchor" queryParamsHandling="preserve" (click)="focusCheck(proposal.code)">{{ proposal.code }} · {{ i18n.t('models.evaluation.hypothesis.' + proposal.hypothesis) }}</a></p>
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .ck-evaluation { padding: 16px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; }
    h3 { font-size: 13px; color: var(--ck-fg-2); }
    .ck-hint, details, a { font-size: 12px; line-height: 1.5; color: var(--ck-fg-3); }
    details { margin: 8px 0; }
    summary { cursor: pointer; }
    .ck-explanation { white-space: pre-wrap; overflow-wrap: anywhere; }
    .ck-warning { font-size: 12px; color: var(--ck-signal-warn); }
    code { overflow-wrap: anywhere; }
    a { text-decoration: underline; color: var(--ck-signal-cool); }
    button, a, summary { outline-offset: 3px; }
  `],
})
export class EvaluationEvidenceComponent {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly document = inject(DOCUMENT);
  readonly metrics = input<MetricsBlock | null>();
  readonly modelId = input.required<string>();
  protected readonly recorded = computed(() => partitionRecorded(this.metrics()?.evaluation));
  protected readonly rows = computed(() => diagnosticRows(this.metrics()?.diagnostics));
  protected readonly busy = signal(false);
  protected readonly failed = signal(false);
  private readonly result = signal<EvaluationReview | null>(null);
  protected readonly reviewed = computed(() => this.result()?.model_id === this.modelId() ? this.result() : null);
  protected readonly doc = diagnosticDoc;
  protected focusCheck(code: string): void {
    const element = this.document.getElementById('evaluation-check-' + code) as HTMLDetailsElement | null;
    if (!element) return;
    element.open = true;
    element.scrollIntoView({ block: 'center' });
    element.focus({ preventScroll: true });
  }
  protected statusKey(): string {
    const status = this.metrics()?.diagnostics?.status;
    return 'models.evaluation.status.' + (['disabled', 'completed', 'error', 'timed_out'].includes(status ?? '') ? status : 'unavailable');
  }
  protected async review(): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true); this.failed.set(false);
    try { this.result.set(await this.models.evaluationReview(this.modelId())); }
    catch { this.failed.set(true); }
    finally { this.busy.set(false); }
  }
}
