import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { distillationValue, type DistillationEvidence } from './distillation-evidence.vm';

@Component({
  selector: 'ck-distillation-evidence', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective],
  template: `
    @if (evidence(); as result) {
      <section data-testid="distillation-evidence">
        <h3>{{ i18n.t('models.distillation.title') }}</h3>
        <p>{{ i18n.t('models.distillation.held_out', { count: result.test_rows }) }}</p>
        <dl>
          <dt>{{ i18n.t('models.distillation.agreement') }}</dt><dd data-testid="distillation-agreement">{{ score(result.agreement) }}</dd>
          <dt>{{ i18n.t('models.distillation.reviewed_accuracy') }}</dt><dd>{{ score(result.reviewed_accuracy) }}</dd>
          <dt>{{ i18n.t('models.distillation.teacher_accuracy') }}</dt><dd>{{ score(result.teacher_accuracy_on_reviewed) }}</dd>
          <dt>{{ i18n.t('models.distillation.llm_cost') }}</dt><dd>{{ cost(result.llm_estimated_cost_per_1000) }}</dd>
          <dt>{{ i18n.t('models.distillation.model_cost') }}</dt><dd data-testid="distillation-model-cost">{{ cost(result.inference_cost_basis === 'declared' ? result.inference_cost_per_1000 : null) }}</dd>
        </dl>
        <p>{{ i18n.t('models.distillation.cost_hint') }}</p>
        @if (result.unknown_attempts > 0) { <p>{{ i18n.t('models.distillation.unknown_attempts', { count: result.unknown_attempts }) }}</p> }
        <p>{{ i18n.t('models.distillation.reviewed', { total: result.rows_reviewed, corrected: result.corrected_rows }) }}</p>
        <p>{{ i18n.t('models.distillation.teacher') }} : {{ result.teacher_model.model || '—' }}</p>
        <a [navLink]="{leaf:'data-doc',ref:result.reviewed_dataset_id}">{{ i18n.t('models.distillation.dataset') }}</a>
      </section>
    }
  `,
  styles: [`section{padding:16px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin:12px 0;color:var(--ck-fg-1)}h3{font-size:13px;margin:0 0 10px}p{font-size:12px;line-height:1.5;color:var(--ck-fg-3)}dl{display:grid;grid-template-columns:minmax(150px,1fr) auto;gap:8px 16px;font-size:12px}dt{color:var(--ck-fg-3)}dd{margin:0;font-variant-numeric:tabular-nums}a{font-size:12px;color:var(--ck-signal-cool)}`],
})
export class DistillationEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly evidence = input<DistillationEvidence>();
  score(raw: unknown): string { const value = distillationValue(raw, 1); return value === null ? '—' : new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 }).format(value); }
  cost(raw: unknown): string { const value = distillationValue(raw); return value === null ? this.i18n.t('models.distillation.unavailable') : new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value); }
}
