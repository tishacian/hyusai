import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { TypedJudgeResultComponent } from '@app/features/data/typed-judge-result.component';
import { runQualityReviews } from './run-quality-review';

@Component({
  selector: 'app-run-quality-review', standalone: true,
  imports: [TypedJudgeResultComponent], changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../../features/data/dataops-editor.scss',
  template: `@for (review of reviews(); track review.invocationId) {
    @if (review.result) { <app-typed-judge-result [value]="review.result" [compact]="true" [runId]="run()?.id || null" [invocationId]="review.invocationId" /> }
    @else { <section class="dp-section" data-testid="run-quality-review-state">
      <h3>{{ i18n.t('dataops.judge.result') }}</h3>
      <p class="dp-note" role="status">{{ i18n.t(review.state === 'pending' ? 'dataops.judge.pending' : 'dataops.judge.unavailable') }}</p>
    </section> }
  }`,
})
export class RunQualityReviewComponent {
  readonly i18n = inject(I18nService);
  readonly run = input<Run | null>(null);
  readonly reviews = computed(() => runQualityReviews(this.run()));
}
