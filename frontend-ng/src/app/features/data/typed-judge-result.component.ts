import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import { typedJudgeFailure, typedResult } from './dataops.models';
@Component({
  selector: 'app-typed-judge-result', standalone: true, imports: [NgTemplateOutlet], changeDetection: ChangeDetectionStrategy.OnPush, styleUrl: './dataops-editor.scss',
  template: `@if (result(); as evaluation) {
    <section class="dp-section" data-testid="typed-judge-result"><h2>{{ i18n.t('dataops.judge.result') }}</h2>
      @if (compact()) { <p class="dp-note">{{ i18n.t('dataops.judge.quality') }}: {{ i18n.t(qualityLabel()) }}</p> }
      @else { <div class="dp-row"><span>{{ i18n.t('dataops.judge.evaluation') }}: {{ i18n.t('dataops.status.' + evaluation.status) }}</span><span>{{ i18n.t('dataops.judge.quality') }}: {{ i18n.t(qualityLabel()) }}</span></div> }
      @if (failure(); as failure) {
        <div class="judge-failure" role="status" data-testid="judge-failure">
          <h3>{{ i18n.t('dataops.judge.failure.title') }}</h3>
          <p>{{ i18n.t(failure.message) }}</p>
          @if (failure.question) { <p class="dp-note">{{ i18n.t('dataops.judge.failure.question') }}: {{ failure.question }}</p> }
          <p class="dp-note">{{ i18n.t(failure.action) }} {{ i18n.t('dataops.judge.failure.no_approval') }}</p>
        </div>
      }
      <p class="dp-note">{{ i18n.t('dataops.judge.review_required') }}</p>
      @if (failedQuestions().length) {
        <details class="judge-questions" data-testid="judge-failed-questions"><summary>{{ i18n.t('dataops.judge.failure.questions') }} · {{ failedQuestions().length }}</summary>
          <ol>@for (question of failedQuestions(); track $index) { <li class="dp-note">{{ question }}</li> }</ol>
        </details>
      }
      <ng-template #technical>
      @if (compact()) { <p class="dp-note">{{ i18n.t('dataops.judge.evaluation') }}: {{ i18n.t('dataops.status.' + evaluation.status) }}</p> }
      <p class="dp-note">{{ i18n.t('dataops.judge.confidence') }}: {{ evaluation.confidence == null ? i18n.t('dataops.unknown') : evaluation.confidence }}</p>
      @if (evaluation.confidence != null && evaluation.calibration; as calibration) { <p class="dp-note">{{calibration.scope}}</p> }
      <p class="dp-note">{{ i18n.t('dataops.judge.coverage', {answered: coverage('questions_answered'), total: coverage('questions_total'), images: coverage('images_examined'), imagesTotal: coverage('images_total')}) }}</p>
      <p class="dp-note">{{ i18n.t('dataops.judge.evidence_coverage', {examined: coverage('evidence_examined'), total: coverage('evidence_total')}) }} · {{ i18n.t('dataops.judge.unit_scope') }}</p>
      @if (evaluation.cost; as cost) { <p class="dp-note">{{ i18n.t('dataops.judge.cost') }}: {{ cost.amount == null ? i18n.t('dataops.unknown') : cost.amount }} {{ cost.currency }}</p> }
      </ng-template>
      @if (!compact()) { <ng-container [ngTemplateOutlet]="technical" /> }
      @for (entry of answers(); track entry.key) {
        @if (compact()) { <div class="dp-answer">
          <h3>{{ entry.question }}</h3><p class="dp-note">{{ i18n.t('dataops.status.' + entry.answer.status) }}@if (entry.answer.value != null) { · {{ display(entry.answer.value) }} }@if (entry.answer.reason) { · {{ reason(entry.answer.reason) }} }</p>
          <p class="dp-note">{{ entry.answer.explanation }}</p>
          @if (entry.answer.evidence.length) { <details><summary>{{ i18n.t('dataops.judge.proofs') }} · {{ entry.answer.evidence.length }}</summary>
            @for (proof of entry.answer.evidence; track $index) { <blockquote><p>{{ proof.kind === 'image' ? proof.description : proof.quote }}</p><small>{{ proof.evidence_id }} · {{ proof.kind === 'image' ? proof.image_sha256 : i18n.t('dataops.judge.source_version_unknown') }}</small></blockquote> }
          </details> }
        </div> }
        @else { <details class="dp-section"><summary>{{ entry.question }} · {{ i18n.t('dataops.status.' + entry.answer.status) }} · {{ display(entry.answer.value) }}</summary>
        <p class="dp-note">{{ entry.answer.explanation }}</p>@if (entry.answer.reason) { <p class="dp-note">{{ reason(entry.answer.reason) }}</p> }
        @for (proof of entry.answer.evidence; track $index) { <blockquote><p>{{ proof.kind === 'image' ? proof.description : proof.quote }}</p><small>{{ proof.evidence_id }} @if (proof.kind === 'image') { · {{ proof.image_sha256 }} · {{ display(proof.region) }} } @else { · {{ proof.start }}–{{ proof.end }} · {{ i18n.t('dataops.judge.source_version_unknown') }} }</small></blockquote> }
      </details> }
      }
      @if (compact()) { <details data-testid="judge-technical-details"><summary>{{ i18n.t('dataops.judge.technical_details') }}</summary><ng-container [ngTemplateOutlet]="technical" /></details> }
    </section>
  }`,
  styles: [`.judge-failure{margin:12px 0;padding:12px 14px;border-inline-start:2px solid var(--ck-signal-warn);background:var(--ck-bg-inset);border-radius:4px;overflow-wrap:anywhere}.judge-failure h3{margin:0 0 6px}.judge-failure p{margin:4px 0;font-size:12px;line-height:1.5}.judge-questions{margin:8px 0}.judge-questions ol{padding-inline-start:20px;list-style:decimal}.judge-questions li{margin:4px 0;overflow-wrap:anywhere}`],
})
export class TypedJudgeResultComponent {
  readonly i18n = inject(I18nService); readonly value = input<unknown>(null); readonly result = computed(() => typedResult(this.value()));
  readonly failure = computed(() => typedJudgeFailure(this.result()));
  readonly qualityLabel = computed(() => this.result()?.quality_status === 'failed' ? 'dataops.judge.criteria_failed' : 'dataops.status.' + this.result()?.quality_status);
  readonly failedQuestions = computed(() => {
    const questions = this.result()?.questions;
    return this.failure() && Array.isArray(questions) ? questions.flatMap(question => typeof question?.question === 'string' && question.question.trim() ? [question.question.slice(0, 2000)] : []) : [];
  });
  readonly compact = input(false);
  readonly answers = computed(() => Object.entries(this.result()?.answers ?? {}).filter(([,answer]) => !this.failure() || answer.status !== 'invalid').map(([key, answer]) => {
    const questions = this.result()?.questions;
    const label = Array.isArray(questions) ? questions.find(q => q && q.key === key)?.question : null;
    return { key, answer, question: typeof label === 'string' && label.trim() ? label.slice(0, 2000) : key };
  }));
  reason(value: string): string {
    return this.i18n.t(['insufficient_evidence', 'ambiguous', 'out_of_scope', 'unsupported_modality'].includes(value) ? 'dataops.judge.reason.' + value : 'dataops.judge.unavailable');
  }
  coverage(key: string): number | string { return this.result()?.coverage[key] ?? this.i18n.t('dataops.unknown'); }
  display(value: unknown): string { return value == null ? this.i18n.t('dataops.unknown') : typeof value === 'boolean' ? this.i18n.t(value ? 'dataops.yes' : 'dataops.no') : Array.isArray(value) ? value.join(', ') : String(value); }
}
