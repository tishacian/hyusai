import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { typedResult } from './dataops.models';
@Component({
  selector: 'app-typed-judge-result', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush, styleUrl: './dataops-editor.scss',
  template: `@if (result(); as evaluation) {
    <section class="dp-section" data-testid="typed-judge-result"><h2>{{ i18n.t('dataops.judge.result') }}</h2>
      <div class="dp-row"><span>{{ i18n.t('dataops.judge.technical') }}: {{ i18n.t('dataops.status.' + evaluation.status) }}</span><span>{{ i18n.t('dataops.judge.quality') }}: {{ i18n.t('dataops.status.' + evaluation.quality_status) }}</span></div>
      <p class="dp-note">{{ i18n.t('dataops.judge.review_required') }}</p>
      <p class="dp-note">{{ i18n.t('dataops.judge.confidence') }}: {{ evaluation.confidence == null ? i18n.t('dataops.unknown') : evaluation.confidence }}</p>
      @if (evaluation.confidence != null && evaluation.calibration; as calibration) { <p class="dp-note">{{calibration.scope}}</p> }
      <p class="dp-note">{{ i18n.t('dataops.judge.coverage', {answered: coverage('questions_answered'), total: coverage('questions_total'), images: coverage('images_examined'), imagesTotal: coverage('images_total')}) }}</p>
      <p class="dp-note">{{ i18n.t('dataops.judge.evidence_coverage', {examined: coverage('evidence_examined'), total: coverage('evidence_total')}) }} · {{ i18n.t('dataops.judge.unit_scope') }}</p>
      @if (evaluation.cost; as cost) { <p class="dp-note">{{ i18n.t('dataops.judge.cost') }}: {{ cost.amount == null ? i18n.t('dataops.unknown') : cost.amount }} {{ cost.currency }}</p> }
      @for (entry of answers(); track entry.key) { <details class="dp-section"><summary>{{ entry.key }} · {{ i18n.t('dataops.status.' + entry.answer.status) }} · {{ display(entry.answer.value) }}</summary>
        <p class="dp-note">{{ entry.answer.explanation }}</p>@if (entry.answer.reason) { <p class="dp-note">{{ entry.answer.reason }}</p> }
        @for (proof of entry.answer.evidence; track $index) { <blockquote><p>{{ proof.kind === 'image' ? proof.description : proof.quote }}</p><small>{{ proof.evidence_id }} @if (proof.kind === 'image') { · {{ proof.image_sha256 }} · {{ display(proof.region) }} } @else { · {{ proof.start }}–{{ proof.end }} }</small></blockquote> }
      </details> }
    </section>
  }`,
})
export class TypedJudgeResultComponent {
  readonly i18n = inject(I18nService); readonly value = input<unknown>(null); readonly result = computed(() => typedResult(this.value()));
  readonly answers = computed(() => Object.entries(this.result()?.answers ?? {}).map(([key, answer]) => ({ key, answer })));
  coverage(key: string): number | string { return this.result()?.coverage[key] ?? this.i18n.t('dataops.unknown'); }
  display(value: unknown): string { return value == null ? this.i18n.t('dataops.unknown') : typeof value === 'boolean' ? this.i18n.t(value ? 'dataops.yes' : 'dataops.no') : Array.isArray(value) ? value.join(', ') : String(value); }
}
