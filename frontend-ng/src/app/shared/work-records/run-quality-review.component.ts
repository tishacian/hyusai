import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { TypedJudgeResultComponent } from '@app/features/data/typed-judge-result.component';
import { runQualityReviews } from './run-quality-review';
import { NavLinkDirective } from '@app/shared/cockpit';

@Component({
  selector: 'app-run-quality-review', standalone: true,
  imports: [TypedJudgeResultComponent, NgTemplateOutlet, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../../features/data/dataops-editor.scss',
  template: `@for (review of reviews(); track review.invocationId) {
    <ng-template #identity>
      <div class="quality-review-identity" data-testid="quality-review-identity">
        @if (review.nodeLabel) { <span class="dp-note">{{ i18n.t('dataops.judge.recorded_step') }} : {{ review.nodeLabel }}</span> }
        @if (run()?.id; as runId) { <a [navLink]="{type:'skill_invocation',runId,ref:review.invocationId}">{{ i18n.t('dataops.judge.open_review') }}</a> }
      </div>
    </ng-template>
    @if (review.result) { <app-typed-judge-result [value]="review.result" [heading]="review.model" [compact]="true" [runId]="run()?.id || null" [invocationId]="review.invocationId">
      <div judgeReviewContext><ng-container [ngTemplateOutlet]="identity" /></div>
    </app-typed-judge-result> }
    @else { <section class="dp-section" data-testid="run-quality-review-state">
      <h3>{{ review.model || i18n.t('dataops.judge.result') }}</h3>
      <ng-container [ngTemplateOutlet]="identity" />
      <p class="dp-note" role="status">{{ i18n.t(review.state === 'pending' ? 'dataops.judge.pending' : 'dataops.judge.unavailable') }}</p>
    </section> }
  }`,
  styles: [`.quality-review-identity{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px;margin:4px 0 10px;font-size:12px;line-height:1.5;overflow-wrap:anywhere}.quality-review-identity a{color:var(--ck-signal-cool);text-decoration:underline;text-underline-offset:3px}.quality-review-identity a:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}`],
})
export class RunQualityReviewComponent {
  readonly i18n = inject(I18nService);
  readonly run = input<Run | null>(null);
  readonly reviews = computed(() => runQualityReviews(this.run()));
}
