import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import type { ClusteringEvidence } from './clustering.vm';

@Component({
  selector: 'ck-clustering-evidence',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (evidence(); as result) {
      <section class="space-y-4" data-testid="clustering-evidence">
        <p class="ck-hint">{{ i18n.t('models.clustering.evidence_hint') }}</p>
        <div class="grid gap-3 md:grid-cols-2">
          <section class="ck-surface rounded p-3">
            <h3>{{ i18n.t('models.metric.silhouette') }} · {{ number(result.silhouette.value) }}</h3>
            <p class="ck-hint">{{ i18n.t('models.clustering.silhouette_hint', { rows: result.silhouette.sample_rows }) }}</p>
            @if (result.silhouette.value === null) { <p class="ck-hint">{{ i18n.t('models.clustering.unavailable') }}</p> }
          </section>
          <section class="ck-surface rounded p-3">
            <h3>{{ i18n.t('models.metric.stability_ari') }} · {{ number(result.stability.mean) }}</h3>
            <p class="ck-hint">{{ i18n.t('models.clustering.stability_hint', { runs: result.stability.runs, rows: result.stability.sample_rows, subset: result.stability.subsample_rows }) }}</p>
            <p class="ck-mono text-xs">{{ i18n.t('models.clustering.stability_spread', { min: number(result.stability.min), std: number(result.stability.std) }) }}</p>
            @if (result.stability.mean === null) { <p class="ck-hint">{{ i18n.t('models.clustering.unavailable') }}</p> }
          </section>
        </div>
        <p class="ck-hint">{{ i18n.t('models.clustering.profiles_hint') }}</p>
        @for (group of result.clusters; track group.cluster) {
          <section class="ck-surface rounded p-3" data-testid="cluster-profile">
            <h3 class="mb-2">{{ i18n.t('models.clustering.group', { cluster: group.cluster }) }} · {{ i18n.t('models.clustering.size', { count: group.count, share: number(group.share * 100) }) }}</h3>
            <div class="overflow-auto">
              <table class="w-full text-xs text-left">
                <thead><tr>
                  <th class="p-2">{{ i18n.t('models.clustering.feature') }}</th>
                  <th class="p-2">{{ i18n.t('models.clustering.mean') }}</th>
                  <th class="p-2">{{ i18n.t('models.clustering.median') }}</th>
                  <th class="p-2">{{ i18n.t('models.clustering.std') }}</th>
                  <th class="p-2">{{ i18n.t('models.clustering.overall') }}</th>
                  <th class="p-2">{{ i18n.t('models.clustering.missing') }}</th>
                </tr></thead>
                <tbody>
                  @for (feature of group.features; track feature.feature) {
                    <tr><th class="p-2 ck-mono">{{ feature.feature }}</th><td class="p-2">{{ number(feature.mean) }}</td><td class="p-2">{{ number(feature.median) }}</td><td class="p-2">{{ number(feature.std) }}</td><td class="p-2">{{ number(feature.overall_mean) }}</td><td class="p-2">{{ feature.missing }}</td></tr>
                  }
                </tbody>
              </table>
            </div>
          </section>
        }
        @for (warning of result.warnings ?? []; track $index) {
          <p class="ck-hint">{{ warningText(warning.code) }}</p>
        }
      </section>
    }
  `,
})
export class ClusteringEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly evidence = input<ClusteringEvidence | null | undefined>(null);
  protected number(value: number | null | undefined): string {
    return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 }) : '—';
  }
  protected warningText(code: string): string {
    const key = `models.clustering.warning.${code.toLowerCase()}`;
    const translated = this.i18n.t(key);
    return translated === key ? this.i18n.t('models.clustering.warning.generic') : translated;
  }
}
