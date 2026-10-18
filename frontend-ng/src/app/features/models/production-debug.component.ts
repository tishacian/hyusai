/**
 * "In production" (Evidence tab) and the fairness watch (Monitor tab).
 *
 * One component in two modes, reading one endpoint: the latest production
 * report of this exact version and the fairness series of its analyses.
 *
 * - `evidence`: where the served answers were wrong on labelled production
 *   samples, drawn with the training pack's own error-tree chart and group
 *   table, plus what the numbers stand on — samples used, samples left out and
 *   why, the window and the date — and the "Analyse production" button, gated
 *   by `serving.permissions.score` exactly as the server gates it.
 * - `monitor`: the fairness badge and the per-column gap over successive
 *   analyses, with the alert threshold drawn as a level.
 *
 * Neutral by default; amber and red only carry the fairness badge.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { CurveChartComponent, type CurveReference } from '../data/viz/curve-chart.component';
import { ExplanationEvidenceComponent } from './explanation-evidence.component';
import { ModelsService } from './models.service';
import type { CurvePoint, ModelTask } from './models.vm';
import {
  badgeTone,
  canRun,
  dateText,
  exclusionRows,
  fairnessReasonKey,
  fairnessSeries,
  gapDomain,
  gapMetricKey,
  isActive,
  productionEvidence,
  readView,
  statusKey,
  windowText,
  type ProductionDebugView,
} from './production-debug.vm';

/** How often a queued or running analysis is re-read, and for how long. */
const POLL_MS = 3000;
const POLL_LIMIT = 100;

@Component({
  selector: 'ck-production-debug',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ExplanationEvidenceComponent, CurveChartComponent],
  template: `
    @if (view(); as debug) {
      @if (mode() === 'evidence') {
        <section class="ck-prod" data-testid="production-debug">
          <div class="ck-prod__head">
            <div>
              <div class="ck-section-label">{{ i18n.t('models.production.title') }}</div>
              <p class="ck-hint">{{ i18n.t('models.production.hint', { min: debug.limits.min_rows, max: debug.limits.max_rows }) }}</p>
            </div>
            @if (permissions()?.['score']) {
              <button type="button" class="ck-btn-soft" data-testid="production-debug-run"
                [disabled]="!runnable() || busy()" (click)="run()">
                {{ i18n.t(busy() || active() ? 'models.production.running' : 'models.production.run') }}
              </button>
            }
          </div>
          @if (!debug.supported) {
            <p class="ck-hint">{{ i18n.t('models.production.unsupported') }}</p>
          } @else if (!debug.latest) {
            <p class="ck-hint" data-testid="production-none">{{ i18n.t('models.production.none') }}</p>
          }
          @if (debug.supported && debug.latest) {
            @let report = debug.latest;
            <p class="ck-hint" data-testid="production-status">
              {{ i18n.t(statusKey(report)) }}
              · {{ i18n.t(report.trigger === 'scheduled' ? 'models.production.trigger.scheduled' : 'models.production.trigger.manual') }}
              @if (report.completed_at || report.created_at) { · {{ date(report.completed_at ?? report.created_at) }} }
              · {{ window(report) }}
            </p>
            <p class="ck-measure" data-testid="production-counts">
              {{ i18n.t('models.production.counts', { used: report.counts.used, labeled: report.counts.labeled }) }}
              @if (report.metrics.accuracy != null) { · {{ i18n.t('models.production.accuracy', { value: percent(report.metrics.accuracy) }) }} }
              @if (report.metrics.mae != null) { · {{ i18n.t('models.production.mae', { value: number(report.metrics.mae) }) }} }
            </p>
            @for (item of exclusions(); track item.reason) {
              <p class="ck-hint" data-testid="production-excluded">{{ i18n.t(item.key, { count: item.count }) }}</p>
            }
            @if (report.status === 'insufficient_data') {
              <p class="ck-hint" data-testid="production-insufficient">{{ i18n.t('models.production.insufficient', { min: report.report.minimum ?? debug.limits.min_rows }) }}</p>
            }
            @if (report.status === 'failed') {
              <p class="ck-hint">{{ i18n.t('models.production.failed', { code: report.error_code ?? '' }) }}</p>
            }
            @if (report.status === 'completed') {
              <p class="ck-hint">{{ i18n.t('models.production.measure') }}</p>
              @if (report.report.fairness; as fairness) {
                @if (fairness.reason) {
                  <p class="ck-hint" data-testid="production-fairness-reason">{{ i18n.t(fairnessReason(fairness.reason)) }}</p>
                }
                @for (gap of fairness.gaps ?? []; track gap.column) {
                  <p class="ck-measure" data-testid="production-gap">
                    <span class="ck-prod__badge" [attr.data-tone]="tone(gap.badge)">{{ i18n.t('models.production.badge.' + (gap.badge ?? 'none')) }}</span>
                    {{ gap.column }} · {{ i18n.t(gapKey(gap.metric)) }}
                    @if (gap.gap != null) { {{ number(gap.gap) }} } @else { — {{ i18n.t(fairnessReason(gap.reason)) }} }
                    @if (gap.small_groups) { · {{ i18n.t('models.production.small_groups', { count: gap.small_groups, min: debug.limits.min_group_rows }) }} }
                  </p>
                }
              }
              @if (evidence(); as pack) {
                <div class="ck-prod__charts">
                  <ck-explanation-evidence [evidence]="pack" [regression]="task() === 'regression'" />
                </div>
              }
            }
          }
          @if (error()) { <p class="ck-hint" data-testid="production-error">{{ i18n.t(error()) }}</p> }
        </section>
      } @else if (debug.supported && debug.fairness_columns.length) {
        <section class="ck-prod" data-testid="fairness-monitor">
          <div class="ck-section-label">{{ i18n.t('models.production.fairness.monitor') }}</div>
          <p class="ck-measure">
            <span class="ck-prod__badge" [attr.data-tone]="tone(debug.latest?.fairness_badge)">{{ i18n.t('models.production.badge.' + (debug.latest?.fairness_badge ?? 'none')) }}</span>
            {{ i18n.t('models.production.thresholds', { watch: number(debug.limits.watch_gap), alert: number(debug.limits.alert_gap) }) }}
          </p>
          @if (series().length) {
            @if (series().length > 1) {
              <label class="ck-prod__pick">{{ i18n.t('models.production.fairness.column') }}
                <select [value]="selected()?.key" (change)="column.set($any($event.target).value)">
                  @for (option of series(); track option.key) { <option [value]="option.key">{{ option.column }}</option> }
                </select>
              </label>
            }
            @if (selected(); as line) {
              <ck-curve-chart
                [points]="line.points"
                [domain]="domain()"
                [reference]="alertLine()"
                [tone]="'neutral'"
                [label]="i18n.t('models.production.fairness.chart', { column: line.column })"
                [xLabel]="i18n.t('models.production.fairness.x')"
                [yLabel]="i18n.t(gapKey(line.metric))"
                [pointLabel]="pointLabel"
              />
            }
          } @else {
            <p class="ck-hint">{{ i18n.t('models.production.fairness.empty') }}</p>
          }
        </section>
      }
    }
  `,
  styles: [`
    :host { display: block; }
    .ck-prod { margin-top: 16px; padding: 16px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; }
    .ck-prod__head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
    .ck-section-label { color: var(--ck-fg-2); font-size: 12px; }
    .ck-hint { color: var(--ck-fg-4); font-size: 11px; line-height: 1.5; margin: 6px 0; }
    .ck-measure { color: var(--ck-fg-3); font-size: 11.5px; margin: 6px 0; font-variant-numeric: tabular-nums; }
    .ck-prod__charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 12px; }
    .ck-prod__badge { display: inline-block; padding: 1px 6px; margin-right: 6px; border: 1px solid var(--ck-stroke-2); border-radius: 4px; color: var(--ck-fg-2); font-size: 11px; }
    .ck-prod__badge[data-tone='warn'] { color: var(--ck-signal-warn); border-color: var(--ck-signal-warn); }
    .ck-prod__badge[data-tone='alert'] { color: var(--ck-signal-neg); border-color: var(--ck-signal-neg); }
    .ck-prod__pick { display: flex; align-items: center; gap: 12px; font-size: 12px; margin: 8px 0; }
    select { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); border: 1px solid var(--ck-stroke-2); padding: 6px; border-radius: 4px; }
  `],
})
export class ProductionDebugComponent {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);

  readonly modelId = input.required<string>();
  readonly task = input<ModelTask>('classification');
  /** `serving.permissions` from the card: no role is inferred here. */
  readonly permissions = input<Record<string, boolean> | null | undefined>(null);
  readonly mode = input<'evidence' | 'monitor'>('evidence');

  readonly view = signal<ProductionDebugView | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly column = signal('');
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private polls = 0;

  protected readonly active = computed(() => isActive(this.view()?.latest));
  protected readonly runnable = computed(() => canRun(this.view(), this.permissions()));
  protected readonly evidence = computed(() => productionEvidence(this.view()?.latest ?? null));
  protected readonly exclusions = computed(() => exclusionRows(this.view()?.latest ?? null));
  protected readonly series = computed(() => fairnessSeries(this.view()?.series));
  protected readonly selected = computed(
    () => this.series().find((item) => item.key === this.column()) ?? this.series()[0] ?? null,
  );
  protected readonly domain = computed(() =>
    gapDomain(this.selected()?.points ?? [], this.view()?.limits.alert_gap ?? 0.1),
  );
  protected readonly alertLine = computed<CurveReference>(() => ({
    kind: 'level',
    value: this.view()?.limits.alert_gap ?? null,
  }));
  protected readonly statusKey = statusKey;
  protected readonly gapKey = gapMetricKey;
  protected readonly fairnessReason = fairnessReasonKey;
  protected readonly tone = badgeTone;
  protected readonly pointLabel = (point: CurvePoint) =>
    `${this.date(this.selected()?.dates[point.x - 1] ?? '')} · ${this.number(point.y)}`;

  constructor() {
    effect(() => {
      this.modelId();
      this.workspace.current()?.id;
      untracked(() => void this.load());
    });
    this.destroy.onDestroy(() => {
      this.generation++;
      this.stop();
    });
  }

  /** Re-read the view; keeps polling while an analysis is queued or running. */
  async load(): Promise<void> {
    this.stop();
    const id = this.modelId(), generation = ++this.generation;
    const scope = this.workspace.captureRequestScope();
    const current = () =>
      generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
    try {
      const view = readView(await this.models.productionDebug(id));
      if (!current()) return;
      this.view.set(view);
      this.error.set('');
      if (view) this.schedule(view);
    } catch {
      if (current()) this.view.set(null);
    }
  }

  async run(): Promise<void> {
    if (this.busy() || !this.runnable()) return;
    this.stop();
    const id = this.modelId(), generation = ++this.generation;
    const scope = this.workspace.captureRequestScope();
    const current = () =>
      generation === this.generation && id === this.modelId() && this.workspace.isRequestScopeCurrent(scope);
    this.busy.set(true);
    this.error.set('');
    try {
      const view = readView(await this.models.runProductionDebug(id));
      if (!current()) return;
      this.view.set(view);
      this.polls = 0;
      if (view) this.schedule(view);
    } catch (failure) {
      if (current()) this.error.set(runErrorKey(failure));
    } finally {
      if (current()) this.busy.set(false);
    }
  }

  private schedule(view: ProductionDebugView): void {
    if (!isActive(view.latest) || this.polls >= POLL_LIMIT) return;
    this.polls++;
    this.timer = setTimeout(() => void this.load(), POLL_MS);
  }

  private stop(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  protected window(report: NonNullable<ProductionDebugView['latest']>): string {
    return windowText(report.window, this.i18n.locale(), {
      all: this.i18n.t('models.production.window.all'),
      since: this.i18n.t('models.production.window.since'),
      until: this.i18n.t('models.production.window.until'),
    });
  }

  protected date(value: string | null | undefined): string {
    return dateText(value, this.i18n.locale()) || '—';
  }

  protected percent(value: number | null | undefined): string {
    return typeof value === 'number' && Number.isFinite(value)
      ? value.toLocaleString(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 })
      : '—';
  }

  protected number(value: number | null | undefined): string {
    return typeof value === 'number' && Number.isFinite(value)
      ? value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 })
      : '—';
  }
}

export function runErrorKey(failure: unknown): string {
  const code = failure instanceof HttpErrorResponse ? String(failure.error?.detail?.code ?? '') : '';
  const known: Record<string, string> = {
    ML_PRODUCTION_DEBUG_RUNNING: 'models.production.error.running',
    ML_PRODUCTION_DEBUG_UNSUPPORTED: 'models.production.unsupported',
    ML_FORBIDDEN_ACTION: 'models.production.error.forbidden',
    ML_AUDIT_UNAVAILABLE: 'models.production.error.audit',
  };
  return known[code] ?? 'models.production.error.failed';
}
