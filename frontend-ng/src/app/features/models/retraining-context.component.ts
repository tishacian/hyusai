import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { DriftEvidenceComponent } from './drift-evidence.component';
import { retrainingReviewReady, type RetrainingBinding } from './retraining-evidence.vm';

@Component({
  selector: 'ck-retraining-context', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective, DriftEvidenceComponent],
  template: `
    <section data-testid="retraining-context">
      <h4>{{ t('review_title') }}</h4><p>{{ t('review_hint') }}</p>
      @if (context(); as b) {
        <dl>
          <dt>{{ t('source') }}</dt><dd><a [navLink]="{leaf:'model-doc',ref:b.model_id}">{{ b.model_name || b.model_id }} · v{{ b.model_version }}</a></dd>
          <dt>{{ t('dataset') }}</dt><dd><a [navLink]="{leaf:'data-doc',ref:b.dataset_id}">{{ b.dataset_id }} · v{{ b.dataset_version }}</a></dd>
          <dt>{{ t('fingerprint') }}</dt><dd><code>{{ b.dataset_sha256 }}</code></dd>
          <dt>{{ t('labeled_rows') }}</dt><dd>{{ b.labeled_rows }}</dd>
          <dt>{{ t('algorithm') }}</dt><dd>{{ b.training.algo }}</dd>
          <dt>{{ t('target') }}</dt><dd>{{ b.training.target }}</dd>
          <dt>{{ t('features') }}</dt><dd>{{ b.training.features.join(', ') }}</dd>
          <dt>{{ t('test_size') }}</dt><dd>{{ b.training.test_size * 100 }} %</dd>
          <dt>{{ t('cross_validation') }}</dt><dd>{{ b.training.cross_validation }}</dd>
          <dt>{{ t('knobs') }}</dt><dd><code>{{ json(b.training.knobs) }}</code></dd>
          <dt>{{ t('spec') }}</dt><dd><code>{{ json(b.training.spec) }}</code></dd>
          <dt>{{ t('proposal') }}</dt><dd><code>{{ b.proposal_id }}</code></dd>
        </dl>
        <h4>{{ t('frozen_evidence') }}</h4>
        <p>{{ t('badge') }}: {{ badge(b.evidence.badge) }} · {{ t('prediction_count') }}: {{ b.evidence.window.predictions }} · {{ t('labeled_count') }}: {{ b.evidence.window.labeled }}</p>
        <dl>
          <dt>{{ t('data_drift') }}</dt><dd>{{ badge(b.evidence.data_drift.status) }}</dd>
          <dt>{{ t('score_drift') }}</dt><dd>{{ badge(b.evidence.score_drift.status) }} · {{ b.evidence.score_drift.value ?? '—' }}</dd>
          <dt>{{ t('concept_drift') }}</dt><dd>{{ badge(b.evidence.concept_drift.status) }} · {{ b.evidence.concept_drift.delta ?? '—' }}</dd>
        </dl>
        <ck-drift-evidence [features]="b.evidence.data_drift.features" />
      } @else { <p role="alert">{{ t('context_missing') }}</p> }
    </section>
  `,
  styles: [`section{padding:12px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin:12px 0;font-size:12px}h4{margin:0 0 8px;font-size:13px}p,dt{color:var(--ck-fg-3);line-height:1.5}dl{display:grid;grid-template-columns:minmax(110px,1fr) minmax(0,3fr);gap:8px 16px}dd{margin:0;overflow-wrap:anywhere}code{white-space:pre-wrap}a{color:var(--ck-signal-cool)}[role=alert]{color:var(--ck-signal-neg)}`],
})
export class RetrainingContextComponent {
  readonly i18n = inject(I18nService);
  readonly binding = input<RetrainingBinding | null>();
  readonly context = computed(() => retrainingReviewReady(this.binding()) ? this.binding() : null);
  t(key: string): string { return this.i18n.t('models.retraining.' + key); }
  badge(value: string | null | undefined): string { return this.i18n.t('models.monitor.tests.status.' + (['ok','watch','alert'].includes(value ?? '') ? value : 'unknown')); }
  json(value: unknown): string { return JSON.stringify(value, null, 2) ?? '—'; }
}
