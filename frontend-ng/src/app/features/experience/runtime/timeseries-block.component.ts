import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { NavLinkDirective } from '@app/shared/cockpit';
import { WorkspaceService } from '@app/core/workspace.service';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { ForecastChartComponent } from '../../data/viz/forecast-chart.component';
import { ExperienceRuntimeService } from './experience-runtime.service';
import { type ExperienceNode, type RuntimeNodeContext } from './model';
import { projectTimeseries } from './timeseries';
interface DatasetResponse {
  rows: Record<string, unknown>[]; total_rows: number; returned_rows: number; truncated: boolean;
  provenance: { dataset_id: string; dataset_version?: number; dataset_name?: string; run_id: string; run_completed_at?: string; model_id?: string; model?: {model_id: string; name?: string; version?: number} };
  freshness: { dataset_created_at?: string; run_completed_at?: string };
}
@Component({
  selector: 'xp-timeseries', standalone: true, imports: [ForecastChartComponent, NavLinkDirective],
  changeDetection: ChangeDetectionStrategy.OnPush, styleUrl: './runtime.scss',
  template: `
    @if (loading() || working()) { <p class="xp-rt-hint" role="status">{{ i18n.t('experience.timeseries.loading') }}</p> }
    @else if (error() || runError()) {
      <p class="xp-rt-err" role="alert">{{ i18n.t('experience.timeseries.error') }}</p>
      @if (!runError()) { <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="retry()">{{ i18n.t('experience.wizard.retry') }}</button> }
    } @else if (!projection().groups.length) { <p class="xp-rt-hint">{{ i18n.t('experience.timeseries.empty') }}</p> }
    @else {
      @if (projection().groups.length > 1) {
        <label class="xp-rt-timeseries-select">{{ i18n.t('experience.timeseries.series') }}
          <select [value]="selectedName()" (change)="selectSeries($event)">
            @for (group of projection().groups; track group.name) { <option [value]="group.name">{{ group.name }}</option> }
          </select>
        </label>
      }
      @if (selected(); as group) {
        <ck-forecast-chart [maxTicks]="4" [series]="group.series" [label]="chartLabel()" [locale]="i18n.locale()" [format]="formatter()"
          [names]="{actual:i18n.t('experience.timeseries.actual'),pred:i18n.t('experience.timeseries.forecast'),interval:i18n.t('experience.timeseries.interval')}" />
      }
      @if (partial()) { <p class="xp-rt-hint" role="status">{{ i18n.t('experience.timeseries.partial') }}</p> }
      @if (response(); as result) {
        <p class="xp-rt-hint">{{ i18n.t('experience.timeseries.source') }}: <a [navLink]="{leaf:'data-doc',ref:result.provenance.dataset_id}">{{ result.provenance.dataset_name || result.provenance.dataset_id }}</a> · v{{ result.provenance.dataset_version ?? '—' }}
          · {{ result.returned_rows }} / {{ result.total_rows }} {{ i18n.t('experience.timeseries.rows') }}</p>
        @if (result.provenance.model; as model) { <p class="xp-rt-hint"><a [navLink]="{leaf:'model-doc',ref:model.model_id}">{{ model.name || i18n.t('experience.prediction.model') }} · v{{ model.version }}</a></p> }
        <p class="xp-rt-hint">{{ i18n.t('experience.timeseries.updated') }}: {{ updated() || i18n.t('experience.timeseries.unknown') }}</p>
      }
      <details class="xp-rt-timeseries-table"><summary>{{ i18n.t('experience.timeseries.values') }}</summary>
        @if (selected(); as group) {
          <div class="xp-rt-table-scroll"><table class="xp-rt-table"><thead><tr>
            <th>{{ i18n.t('experience.timeseries.time') }}</th><th>{{ i18n.t('experience.timeseries.actual') }}</th><th>{{ i18n.t('experience.timeseries.forecast') }}</th><th>{{ i18n.t('experience.timeseries.interval') }}</th>
          </tr></thead><tbody>
            @for (stamp of group.series.labels; track stamp; let i = $index) {
              <tr><td>{{ stamp }}</td><td>{{ formatValue(group.series.actual[i]) }}</td><td>{{ formatValue(group.series.pred[i]) }}</td><td>{{ formatInterval(group.series.lower[i], group.series.upper[i]) }}</td></tr>
            }
          </tbody></table></div>
        }
      </details>
    }
  `,
})
export class TimeseriesBlockComponent {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly value = input<unknown>(null);
  readonly response = signal<DatasetResponse | null>(null);
  readonly loading = signal(false); readonly error = signal(false);
  readonly working = computed(() => ['loading', 'running'].includes(this.runtime.phase(this.context().sourceStateKey)));
  readonly runError = computed(() => this.runtime.phase(this.context().sourceStateKey) === 'error');
  readonly selectedName = signal(''); private readonly refresh = signal(0);
  readonly projection = computed(() => projectTimeseries(this.working() ? null : this.datasetMode() ? this.response()?.rows : this.value(), this.node().props?.['mapping']));
  readonly selected = computed(() => this.projection().groups.find(g => g.name === this.selectedName()) ?? this.projection().groups[0] ?? null);
  readonly partial = computed(() => this.response()?.truncated || this.projection().omitted + this.projection().invalid + this.projection().duplicate + this.projection().invalidIntervals > 0);
  readonly chartLabel = computed(() => `${this.node().props?.['title'] ?? this.i18n.t('experience.timeseries.forecast')} ${this.selected()?.name ?? ''}`);
  readonly formatter = computed(() => { const unit = String(this.node().props?.['unit'] ?? '').slice(0, 40), locale = this.i18n.locale(); return (v: number) => `${v.toLocaleString(locale, {maximumFractionDigits: 2})}${unit ? ' ' + unit : ''}`; });
  readonly updated = computed(() => { const raw = this.response()?.freshness.dataset_created_at; return raw && Number.isFinite(Date.parse(raw)) ? new Date(raw).toLocaleString(this.i18n.locale()) : ''; });
  readonly datasetMode = computed(() => !!this.node().props?.['datasetSource']);
  // RuntimeHost creates context objects during change detection; stable identity
  // prevents those renders from issuing the same authorized read repeatedly.
  private readonly request = computed(() => {
    const context = this.context(), run = this.runtime.run(context.sourceStateKey);
    const workspace = this.workspace.currentSlug();
    const ready = workspace && this.datasetMode() && context.mode === 'live' && !this.working() && !this.runError() && run?.id && run.status === 'completed';
    const route = [context.experienceSlug, 'datasets', context.pageId, context.componentId].map(encodeURIComponent).join('/');
    const url = ready ? `/work/${route}?run_id=${encodeURIComponent(run!.id)}` : null;
    return {url, key: JSON.stringify([workspace, context.sourceStateKey, url, this.refresh()])};
  }, {equal: (previous, next) => previous.key === next.key});
  constructor() {
    effect((onCleanup) => {
      const request = this.request();
      this.response.set(null); this.error.set(false); this.loading.set(false);
      if (!request.url) return;
      this.loading.set(true);
      const subscription = this.api.get<DatasetResponse>(request.url).subscribe({
        next: data => { this.response.set(data); this.loading.set(false); },
        error: () => { this.error.set(true); this.loading.set(false); },
      });
      onCleanup(() => subscription.unsubscribe());
    });
  }
  retry(): void { this.refresh.update(v => v + 1); }
  selectSeries(event: Event): void { this.selectedName.set((event.target as HTMLSelectElement).value); }
  formatValue(value: number | null | undefined): string { return value === null || value === undefined ? '—' : this.formatter()(value); }
  formatInterval(lower: number | null | undefined, upper: number | null | undefined): string { return lower == null || upper == null ? '—' : `${this.formatter()(lower)} – ${this.formatter()(upper)}`; }
}
