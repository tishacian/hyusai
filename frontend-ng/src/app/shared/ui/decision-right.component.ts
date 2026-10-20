import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { RunHitlPayload } from '@app/core/canonical-api.service';
import { IconComponent } from './icon.component';

const REASONS = new Set(['not_authorized', 'admin_required', 'decided', 'expired', 'missing']);

/** False only when the server said so; an older server that says nothing keeps the buttons. */
export function mayDecide(hitl: Pick<RunHitlPayload, 'can_decide'> | null | undefined): boolean {
  return hitl?.can_decide !== false;
}

/**
 * "Read only" and why, shown before any decision button when the server says
 * this reader may not decide a pause (`hitl.can_decide === false`). Access to
 * the application is never taken for the right to approve.
 */
@Component({
  selector: 'app-decision-right',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (readOnly()) {
      <div class="flex items-start gap-2 text-xs ck-tone-warn" style="padding:var(--ck-space-2) var(--ck-space-3); border-radius:var(--ck-radius-sm);"
        role="status" data-testid="decision-read-only" [attr.data-reason]="reason()">
        <app-icon name="lock" [size]="14" aria-hidden="true" />
        <p><strong>{{ i18n.t('state.decision.read_only') }}</strong> · {{ i18n.t('state.decision.read_only.' + reason()) }}</p>
      </div>
    }
  `,
})
export class DecisionRightComponent {
  readonly i18n = inject(I18nService);
  readonly hitl = input<Pick<RunHitlPayload, 'can_decide' | 'decide_reason'> | null | undefined>(null);

  readonly readOnly = computed(() => !mayDecide(this.hitl()));
  readonly reason = computed(() => {
    const reason = this.hitl()?.decide_reason ?? '';
    return REASONS.has(reason) ? reason : 'not_authorized';
  });
}
