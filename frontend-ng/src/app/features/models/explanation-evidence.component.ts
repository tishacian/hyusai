import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { PartialEffectChartComponent } from './partial-effect-chart.component';
import { fairnessMetrics, readableRule, surrogateRules, type ExplanationEvidence, type ExplainRule, type FairnessEvidence, type FairnessGroup } from './explanation-evidence.vm';

@Component({
  selector: 'ck-explanation-evidence', standalone: true, imports: [PartialEffectChartComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (evidence(); as explanation) {
      @if (explanation.error) {
        <p class="ck-hint" data-testid="explain-unavailable">{{ failure(explanation.error) }}</p>
      } @else {
        @if (explanation.error_tree; as tree) {
          <section class="ck-chart" data-testid="error-tree-evidence">
            <div class="ck-section-label">{{ i18n.t('models.explain.errors.title') }}</div>
            <p class="ck-hint">{{ i18n.t('models.explain.rows', { rows: explanation.rows ?? 0 }) }}</p>
            @if (tree.error) { <p class="ck-hint">{{ failure(tree.error) }}</p> }
            @else {
              <p class="ck-hint">{{ i18n.t('models.explain.errors.global', { value: measure(tree.global_error, regression()) }) }}</p>
              <ol>@for (leaf of tree.rules ?? []; track $index) {
                <li><span>{{ rule(leaf.rule) }}</span><span class="ck-measure">{{ i18n.t('models.explain.errors.rule', { rows: leaf.rows, value: measure(leaf.error, regression()) }) }}</span></li>
              }</ol>
            }
          </section>
        }
        @if (explanation.surrogate; as simple) {
          <section class="ck-chart" data-testid="surrogate-evidence">
            <div class="ck-section-label">{{ i18n.t('models.explain.surrogate.title') }}</div>
            @if (simple.error) { <p class="ck-hint">{{ failure(simple.error) }}</p> }
            @else {
              <span class="ck-badge">{{ i18n.t('models.explain.surrogate.fidelity', { value: measure(simple.fidelity) }) }}</span>
              <p class="ck-hint">{{ i18n.t('models.explain.surrogate.hint') }}</p>
              @if (surrogate().length) {
                <ol>@for (leaf of surrogate(); track $index) {
                  <li><span>{{ rule(leaf.rule) }} → {{ leaf.prediction }}</span><span class="ck-measure">{{ i18n.t('models.explain.support', { rows: leaf.rows }) }}</span></li>
                }</ol>
              } @else { <p class="ck-hint" data-testid="surrogate-too-complex">{{ i18n.t('models.explain.surrogate.complex') }}</p> }
            }
          </section>
        }
        @for (effect of explanation.pdp ?? []; track effect.feature) {
          <section class="ck-chart" data-testid="pdp-evidence">
            <div class="ck-section-label">{{ i18n.t('models.explain.pdp.title', { feature: effect.feature }) }}</div>
            @if (effect.error) { <p class="ck-hint">{{ failure(effect.error) }}</p> }
            @else {
              @if (effect.class !== undefined) { <p class="ck-hint">{{ i18n.t('models.explain.pdp.class', { label: effect.class }) }}</p> }
              <ck-partial-effect-chart [effect]="effect" />
              <p class="ck-hint">{{ i18n.t('models.explain.pdp.hint') }}</p>
            }
          </section>
        }
        @if (fairnessError(); as error) { <p class="ck-hint">{{ failure(error) }}</p> }
        @for (comparison of fairness(); track comparison.column) {
          <section class="ck-chart ck-fairness" data-testid="fairness-evidence" [class.ck-signal]="comparison.signal">
            <div class="ck-section-label">{{ i18n.t('models.explain.fairness.title', { column: comparison.column }) }}</div>
            @if (comparison.error) { <p class="ck-hint">{{ failure(comparison.error) }}</p> }
            @else {
              <p class="ck-hint">{{ i18n.t('models.explain.fairness.hint') }}</p>
              @if (comparison.selection_ratio !== undefined) {
                <p class="ck-measure">{{ i18n.t('models.explain.fairness.selection_ratio', { value: measure(comparison.selection_ratio) }) }}</p>
              }
              @if (comparison.equalized_odds_diff !== undefined) {
                <p class="ck-measure">{{ i18n.t('models.explain.fairness.odds', { value: measure(comparison.equalized_odds_diff) }) }}</p>
              }
              @if (comparison.mae_gap_ratio !== undefined) {
                <p class="ck-measure">{{ i18n.t('models.explain.fairness.mae_gap', { value: measure(comparison.mae_gap_ratio) }) }}</p>
              }
              @if (comparison.signal) { <p class="ck-alert">{{ i18n.t('models.explain.fairness.signal') }}</p> }
              <div class="ck-table"><table>
                <thead><tr><th>{{ i18n.t('models.explain.fairness.group') }}</th><th>{{ i18n.t('models.explain.fairness.rows') }}</th>@for (key of columns(comparison); track key) { <th>{{ i18n.t('models.explain.metric.' + key) }}</th> }</tr></thead>
                <tbody>@for (group of comparison.groups ?? []; track $index) {
                  <tr [class.ck-low]="group.low_support"><th>{{ group.group ?? '—' }} @if (group.low_support) { <small>{{ i18n.t('models.explain.fairness.low_support') }}</small> }</th><td>{{ group.n }}</td>@for (key of columns(comparison); track key) { <td>{{ groupMeasure(group, key) }}</td> }</tr>
                }</tbody>
              </table></div>
            }
          </section>
        }
      }
    }
  `,
  styles: [`
    :host { display: contents; }
    .ck-chart { min-width: 0; padding: 16px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; }
    .ck-section-label { color: var(--ck-fg-2); font-size: 12px; margin-bottom: 10px; }
    .ck-hint { color: var(--ck-fg-4); font-size: 11px; line-height: 1.5; margin: 8px 0; }
    .ck-badge { color: var(--ck-fg-2); font-size: 12px; border: 1px solid var(--ck-stroke-2); padding: 3px 6px; border-radius: 4px; }
    ol { padding-left: 20px; font-size: 12px; color: var(--ck-fg-2); }
    li { margin: 12px 0; overflow-wrap: anywhere; }
    li span { display: block; }
    .ck-measure { color: var(--ck-fg-3); font-size: 11px; margin-top: 4px; font-variant-numeric: tabular-nums; }
    .ck-fairness { grid-column: 1 / -1; }
    .ck-signal { border-color: var(--ck-signal-warn); }
    .ck-alert { color: var(--ck-signal-warn); font-size: 12px; }
    .ck-table { overflow-x: auto; }
    table { width: 100%; font-size: 11px; color: var(--ck-fg-2); border-collapse: collapse; }
    th, td { text-align: right; padding: 8px 4px; border-bottom: 1px solid var(--ck-stroke-2); font-variant-numeric: tabular-nums; }
    th:first-child { text-align: left; font-weight: 400; }
    .ck-low { color: var(--ck-fg-4); }
    small { display: block; font-weight: 400; }
  `],
})
export class ExplanationEvidenceComponent {
  readonly i18n = inject(I18nService);
  readonly evidence = input<ExplanationEvidence | null | undefined>();
  readonly regression = input(false);
  protected readonly surrogate = computed(() => surrogateRules(this.evidence()?.surrogate));
  protected readonly fairness = computed(() => { const value = this.evidence()?.fairness; return Array.isArray(value) ? value : []; });
  protected readonly fairnessError = computed(() => { const value = this.evidence()?.fairness; return value && !Array.isArray(value) ? value.error : null; });
  protected columns = fairnessMetrics;
  protected rule(terms: ExplainRule[]): string { return readableRule(terms, this.i18n.locale(), this.i18n.t('models.explain.all'), this.i18n.t('models.explain.and')); }
  protected failure(error: string): string { return this.i18n.t(error === 'budget' ? 'models.explain.budget' : 'models.explain.section_unavailable'); }
  protected measure(value: number | null | undefined, numeric = false): string {
    return typeof value !== 'number' || !Number.isFinite(value) ? '—' : value.toLocaleString(this.i18n.locale(), numeric ? { maximumFractionDigits: 3 } : { style: 'percent', maximumFractionDigits: 1 });
  }
  protected groupMeasure(group: FairnessGroup, key: string): string { return this.measure(typeof group[key] === 'number' ? group[key] : null, ['mae', 'bias'].includes(key)); }
}
