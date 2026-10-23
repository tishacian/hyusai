import { formatInstant } from '@app/core/format-instant';
import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import { AgentDecisionTrailComponent } from '@app/shared/work-records/agent-decision-trail.component';
import { TypedJudgeResultComponent } from '../../data/typed-judge-result.component';
import { typedResult } from '../../data/dataops.models';
import { ForecastChartComponent } from '../../data/viz/forecast-chart.component';
import {
  flowNodeDecisionRun, flowResultSupports, projectFlowResult,
  type FlowResultDatasetPreview, type FlowResultPresentation,
} from './flow-result.vm';

/** The same charts, tables and recorded choices used in Work, projected from
 * an already authorized retained output. Opening this component never executes
 * a Skill, fetches a dataset, or substitutes current configuration for evidence. */
@Component({
  selector: 'app-flow-result-viewer', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ForecastChartComponent, DataTableComponent, AgentDecisionTrailComponent, TypedJudgeResultComponent],
  styleUrl: './flow-result-viewer.component.scss',
  template: `
    <section class="flow-result" data-testid="flow-result-viewer" [attr.aria-label]="title() || i18n.t('flow.results.viewer.title')">
      @if (loading()) {
        <p class="flow-result__empty" role="status">{{ i18n.t('flow.results.viewer.loading') }}</p>
      } @else if (error()) {
        <p class="flow-result__error" role="alert">{{ error() }}</p>
      } @else if (judge()) {
        <app-typed-judge-result [value]="judge()" [compact]="true" [runId]="run()?.id || null" [invocationId]="invocationId()" />
      } @else if (!supported()) {
        <p class="flow-result__empty" role="status">{{ i18n.t(presentation() === 'auto' ? 'flow.results.viewer.empty' : 'flow.results.viewer.incompatible') }}</p>
        @if (view().structured && !view().empty) {
          <details class="flow-result__details"><summary>{{ i18n.t('flow.results.viewer.raw') }}</summary>
            <pre>{{ view().structured }}</pre>
            @if (view().structuredTruncated) { <p class="flow-result__note">{{ i18n.t('flow.results.viewer.raw_partial') }}</p> }
          </details>
        }
      } @else {
        @if (showDecisions()) {
          <app-agent-decision-trail [run]="decisionRun()" [showLinks]="true" [compact]="false" />
        }
        @if (showChart()) {
          @if (view().chart; as chart) {
            <div class="flow-result__chart-head">
              <h4>{{ i18n.t('flow.results.viewer.forecast') }}</h4>
              @if (chart.groups.length > 1) {
                <label>{{ i18n.t('experience.timeseries.series') }}
                  <select [value]="selected()?.name ?? ''" (change)="selectSeries($event)">
                    @for (group of chart.groups; track group.name) { <option [value]="group.name" [selected]="group.name===selected()?.name">{{ group.name }}</option> }
                  </select>
                </label>
              }
            </div>
            @if (selected(); as group) {
              <ck-forecast-chart [series]="group.series" [aspect]="2.7" [maxTicks]="5" [frequency]="view().frequency"
                [label]="chartLabel()" [locale]="i18n.locale()" [format]="numberFormat()"
                [names]="{actual:i18n.t('experience.timeseries.actual'),pred:i18n.t('experience.timeseries.forecast'),interval:i18n.t('experience.timeseries.interval')}" />
            }
            @if (chartPartial()) { <p class="flow-result__note" role="status">{{ i18n.t('flow.results.viewer.chart_partial') }}</p> }
          }
        }
        @if (showPrediction()) {
          @if (view().prediction; as prediction) {
            <div class="flow-result__prediction">
              <span>{{ prediction.target || i18n.t('flow.results.viewer.prediction') }}</span>
              <strong>{{ predictionValue() }}</strong>
              @if (prediction.positiveLabel) { <span>{{ prediction.positiveLabel }}</span> }
              @if (prediction.capturedAt) { <small>{{ i18n.t('flow.results.viewer.captured') }} · {{ formatDate(prediction.capturedAt) }}</small> }
            </div>
          }
        }
        @if (showTable()) {
          @if (view().table; as table) {
            <ck-data-table [columns]="table.columns" [rows]="table.rows" [rowCount]="table.total" [showProfile]="false"
              [caption]="i18n.t('flow.results.viewer.rows')" maxHeight="360px" />
            @if (table.truncated) { <p class="flow-result__note" role="status">{{ i18n.t('flow.results.viewer.table_partial', { count: table.rows.length }) }}</p> }
          }
        }
        @if (showDocuments()) {
          <div class="flow-result__documents">
            @for (document of view().documents; track $index) {
              <article>
                @if (document.title) { <h4>{{ documentTitle(document.title) }}</h4> }
                <p>{{ document.text }}</p>
                @if (document.source) { <small>{{ i18n.t('flow.results.viewer.source') }} · {{ document.source }}</small> }
              </article>
            }
          </div>
          @if (view().documentTruncated) { <p class="flow-result__note">{{ i18n.t('flow.results.viewer.document_partial') }}</p> }
        }
        @if (showFacts()) {
          <dl class="flow-result__facts">
            @for (fact of view().facts; track fact.key) { <div><dt>{{ factLabel(fact.key) }}</dt><dd>{{ factValue(fact.value) }}</dd></div> }
          </dl>
        }
        @if (showChart() && view().table?.columns?.length) {
          <details class="flow-result__details"><summary>{{ i18n.t('experience.timeseries.values') }}</summary>
            @if (view().table; as table) {
              <ck-data-table [columns]="table.columns" [rows]="table.rows" [rowCount]="table.total" [showProfile]="false"
                [caption]="i18n.t('flow.results.viewer.rows')" maxHeight="300px" />
              @if (table.truncated) { <p class="flow-result__note">{{ i18n.t('flow.results.viewer.table_partial', { count: table.rows.length }) }}</p> }
            }
          </details>
        }
        @if (view().structured && !view().empty) {
          <details class="flow-result__details" [open]="rawOnly()"><summary>{{ i18n.t('flow.results.viewer.raw') }}</summary>
            <pre>{{ view().structured }}</pre>
            @if (view().structuredTruncated) { <p class="flow-result__note">{{ i18n.t('flow.results.viewer.raw_partial') }}</p> }
          </details>
        }
      }
    </section>
  `,
})
export class FlowResultViewerComponent {
  readonly i18n = inject(I18nService);
  readonly value = input<unknown>(null);
  readonly run = input<Run | null>(null);
  readonly nodeId = input<string | null>(null);
  readonly invocationId = input<string | null>(null);
  readonly title = input('');
  readonly presentation = input<FlowResultPresentation>('auto');
  readonly datasetPreview = input<FlowResultDatasetPreview | null>(null);
  readonly mapping = input<unknown>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  /** A view preference, so a pin/expanded window can preserve the visible series. */
  readonly selectedSeriesName = model<string | null>(null);
  readonly view = computed(() => projectFlowResult(this.value(), this.datasetPreview(), this.mapping()));
  readonly judge = computed(() => ['auto', 'quality'].includes(this.presentation()) ? typedResult(this.value()) : null);
  readonly decisionRun = computed(() => flowNodeDecisionRun(this.run(), this.nodeId(), this.invocationId()));
  readonly supported = computed(() => flowResultSupports(this.view(), this.presentation(), !!this.decisionRun()));
  readonly showDecisions = computed(() => !!this.decisionRun() && ['auto', 'decisions'].includes(this.presentation()));
  readonly showChart = computed(() => !!this.view().chart && (this.presentation() === 'chart' || this.presentation() === 'auto' && !this.showDecisions()));
  readonly showPrediction = computed(() => !!this.view().prediction && (this.presentation() === 'metric' || this.presentation() === 'auto' && !this.showDecisions() && !this.showChart()));
  readonly showTable = computed(() => !!this.view().table?.columns.length && (this.presentation() === 'table' || this.presentation() === 'auto' && !this.showDecisions() && !this.showChart() && !this.showPrediction()));
  readonly showDocuments = computed(() => this.view().documents.length > 0 && (this.presentation() === 'document' || this.presentation() === 'auto' && !this.showDecisions() && !this.showChart() && !this.showPrediction() && !this.showTable()));
  readonly showFacts = computed(() => this.view().facts.length > 0 && (this.presentation() === 'metric' && !this.showPrediction() || this.presentation() === 'auto' && !this.showDecisions() && !this.showChart() && !this.showPrediction() && !this.showTable() && !this.showDocuments()));
  readonly rawOnly = computed(() => !this.showDecisions() && !this.showChart() && !this.showPrediction() && !this.showTable() && !this.showDocuments() && !this.showFacts());
  readonly selected = computed(() => this.view().chart?.groups.find(group => group.name === this.selectedSeriesName()) ?? this.view().chart?.groups[0] ?? null);
  readonly chartPartial = computed(() => {
    const chart = this.view().chart;
    return !!this.datasetPreview()?.truncated || !!chart && chart.omitted + chart.invalid + chart.duplicate + chart.invalidIntervals > 0;
  });
  readonly chartLabel = computed(() => [this.title() || this.i18n.t('flow.results.viewer.forecast'), this.selected()?.name].filter(Boolean).join(' · '));
  readonly numberFormat = computed(() => {
    const format = new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 2 });
    return (value: number) => format.format(value);
  });
  readonly predictionValue = computed(() => {
    const prediction = this.view().prediction;
    if (!prediction) return '';
    if (prediction.task === 'classification') return new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 }).format(Number(prediction.value));
    const value = typeof prediction.value === 'number' ? this.numberFormat()(prediction.value) : prediction.value;
    return `${value}${prediction.unit && prediction.unit !== 'segment' ? ' ' + prediction.unit : ''}`;
  });
  selectSeries(event: Event): void {
    const name = (event.target as HTMLSelectElement).value;
    if (this.view().chart?.groups.some(group => group.name === name)) this.selectedSeriesName.set(name);
  }
  factLabel(key: string): string {
    const known = ['value', 'rows_in', 'rows_out', 'scored_rows', 'excluded_rows', 'case_count', 'horizon', 'duration_ms', 'confidence', 'count'];
    if (key.startsWith('metrics.')) {
      const name = key.slice('metrics.'.length), translation = this.i18n.t('models.metric.' + name);
      return translation === 'models.metric.' + name ? name.replace(/_/g, ' ') : translation;
    }
    return known.includes(key) ? this.i18n.t('flow.results.viewer.fact.' + key) : key.replace(/_/g, ' ');
  }
  factValue(value: string | number | boolean): string {
    if (typeof value === 'boolean') return this.i18n.t(value ? 'flow.results.viewer.true' : 'flow.results.viewer.false');
    return typeof value === 'number' ? this.numberFormat()(value) : value;
  }
  documentTitle(title: string): string {
    return ['answer', 'summary', 'text', 'content'].includes(title) ? this.i18n.t('flow.results.viewer.document.' + title) : title;
  }
  formatDate(value: string): string {
    return formatInstant(value, this.i18n.locale()) ?? this.i18n.t('flow.results.viewer.unknown');
  }
}
