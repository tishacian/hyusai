/**
 * Models (Build > Models) — the registry, and the door into the training studio.
 *
 * The list is a cockpit table (mo1): one row per model, served version as a
 * column, versions living on the sheet. A fit in flight keeps its checklist
 * under the row so the seconds between "start training" and a score read as
 * work; the score keeps the metric that scored it.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { DataService } from '@app/features/data/data.service';
import { ModelTrainComponent } from './model-train.component';
import { ModelsService, isModelActive } from './models.service';
import {
  bestScore,
  formatMetric,
  groupModelsBySlug,
  metricTone,
  primaryScore,
  trainChecklist,
  type ModelDto,
  type ModelTask,
  type TrainStep,
} from './models.vm';

const POLL_INTERVAL_MS = 1500;

type ModelFilter = 'all' | ModelTask | 'serving';

@Component({
  selector: 'app-models-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NavLinkDirective,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
    ModelTrainComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="i18n.t('models.eyebrow')"
      [title]="i18n.t('models.title')"
      [subtitle]="i18n.t('models.subtitle')"
      [kpis]="kpis()"
    >
      <div actions class="flex items-center gap-1.5">
        <a
          [navLink]="{ surface: 'data' }"
          class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
        >
          <app-icon name="table" [size]="14" /> {{ i18n.t('models.list.go_data') }}
        </a>
        <button
          type="button"
          class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
          (click)="reload()"
          [disabled]="models.loading()"
        >
          <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="models.loading()" />
          {{ i18n.t('models.list.refresh') }}
        </button>
        @if (canTrain()) {
          <button
            type="button"
            class="ck-cta inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
            (click)="openStudio()"
          >
            <app-icon name="brain" [size]="14" /> {{ i18n.t('models.list.train') }}
          </button>
        }
      </div>
    </ck-object-header>

    @if (!models.catalog().enabled) {
      <app-empty-state
        icon="brain"
        [title]="i18n.t('models.disabled.title')"
        [description]="i18n.t('models.disabled.description')"
      />
    } @else {
      <div class="flex items-center gap-1.5 mb-3 flex-wrap">
        @for (option of filters(); track option.key) {
          <button
            type="button"
            class="ck-chip"
            [class.ck-chip--on]="filter() === option.key"
            (click)="filter.set(option.key)"
          >
            {{ i18n.t(option.label) }}
          </button>
        }
      </div>

      @if (models.loading() && !models.models().length) {
        <div class="space-y-2">
          @for (_ of [0, 1, 2]; track $index) {
            <div class="ck-surface rounded-md p-5 animate-pulse">
              <div class="h-3 w-56 rounded" style="background: rgba(255,255,255,0.05)"></div>
            </div>
          }
        </div>
      } @else if (!visible().length) {
        <app-empty-state
          icon="brain"
          [title]="i18n.t('models.list.empty.title')"
          [description]="
            hasDataset()
              ? i18n.t('models.list.empty.description')
              : i18n.t('models.list.empty.no_dataset')
          "
        >
          @if (hasDataset()) {
            <button
              type="button"
              class="ck-cta inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
              (click)="openStudio()"
            >
              <app-icon name="brain" [size]="14" /> {{ i18n.t('models.list.train') }}
            </button>
          } @else {
            <a
              [navLink]="{ surface: 'data' }"
              class="ck-cta inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
            >
              <app-icon name="table" [size]="14" /> {{ i18n.t('models.list.import_data') }}
            </a>
          }
        </app-empty-state>
      } @else {
        <div class="ck-h-scroll" data-testid="models-list">
          <table class="ck-models-table">
            <thead>
              <tr>
                <th scope="col">{{ i18n.t('models.list.col.model') }}</th>
                <th scope="col">{{ i18n.t('models.list.col.target') }}</th>
                <th scope="col">{{ i18n.t('models.list.col.dataset') }}</th>
                <th scope="col">{{ i18n.t('models.list.col.served') }}</th>
                <th scope="col" class="ck-num">{{ i18n.t('models.list.col.score') }}</th>
                <th scope="col">{{ i18n.t('models.list.col.monitor') }}</th>
              </tr>
            </thead>
            <tbody>
              @for (entry of visible(); track entry.slug) {
                <tr class="ck-models-row" [class.is-busy]="isActive(entry.row)">
                  <td>
                    <a
                      [navLink]="{ leaf: 'model-doc', ref: entry.id }"
                      class="ck-models-primary"
                    >
                      <span class="ck-models-name">{{ entry.name }}</span>
                      @if (entry.row.status !== 'ready') {
                        <span
                          class="ck-models-tag"
                          data-testid="model-status"
                          [attr.data-tone]="entry.row.status === 'failed' ? 'neg' : 'cool'"
                        >
                          {{ i18n.t('models.status.' + entry.row.status) }}
                        </span>
                      }
                      <span class="ck-models-sub">
                        {{ i18n.t('models.task.' + entry.task) }}
                        · {{ i18n.t('models.algo.' + entry.algo) }}
                      </span>
                    </a>
                    @if (isActive(entry.row)) {
                      <ol class="ck-steps" data-testid="train-checklist">
                        @for (step of checklist(entry.row); track step.step) {
                          <li class="ck-steps__item" [attr.data-state]="step.state">
                            @if (step.state === 'done') {
                              <app-icon name="check" [size]="11" class="shrink-0" />
                            } @else if (step.state === 'active') {
                              <span class="ck-pulse shrink-0"></span>
                            } @else {
                              <span class="ck-steps__dot shrink-0"></span>
                            }
                            <span class="truncate">{{ i18n.t(step.key, step.params) }}</span>
                          </li>
                        }
                      </ol>
                    } @else if (entry.row.status === 'failed' && entry.row.error) {
                      <div class="ck-models-error ck-mono">{{ entry.row.error }}</div>
                    }
                  </td>
                  <td class="ck-mono ck-models-target">{{ entry.target }}</td>
                  <td class="ck-models-dataset">
                    @if (entry.row.dataset_slug) {
                      <span [class.is-neg]="entry.row.status === 'failed'">{{
                        entry.row.dataset_slug
                      }}</span>
                    } @else {
                      <span class="ck-muted">{{ i18n.t('models.list.dataset.none') }}</span>
                    }
                  </td>
                  <td data-testid="served-version">
                    @if (isActive(entry.row)) {
                      <span class="ck-models-served is-progress">{{
                        i18n.t('models.list.served.progress', { version: entry.row.version })
                      }}</span>
                    } @else if (entry.served_version !== null) {
                      <span class="ck-models-served is-live">
                        <span class="ck-models-live-mark" aria-hidden="true"></span>
                        {{ i18n.t('models.list.served', { version: entry.served_version }) }}
                      </span>
                    } @else {
                      <span class="ck-muted">{{ i18n.t('models.list.served.none') }}</span>
                    }
                  </td>
                  <td class="ck-num">
                    @if (scoreOf(entry.row); as score) {
                      <div class="ck-score">{{ score.value }}</div>
                      <div class="ck-models-metric ck-mono">{{ score.label }}</div>
                    } @else {
                      <span class="ck-muted">—</span>
                    }
                  </td>
                  <td>
                    @if (entry.row.monitor_status; as tone) {
                      <span
                        class="ck-models-monitor"
                        data-testid="monitor-badge"
                        [attr.data-tone]="tone"
                      >
                        @if (tone === 'watch' || tone === 'alert') {
                          <app-icon name="alert-triangle" [size]="12" class="shrink-0" />
                        }
                        {{ i18n.t('models.list.monitor.' + tone) }}
                      </span>
                    } @else {
                      <span class="ck-muted">{{ i18n.t('models.list.monitor.none') }}</span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    }

    @if (studioOpen()) {
      <app-model-train
        [datasets]="data.datasets()"
        (close)="studioOpen.set(false)"
        (trained)="onTrained()"
      />
    }
  `,
  styles: [
    `
      .ck-models-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      .ck-models-table thead th {
        text-align: left;
        padding: 6px 12px 10px 0;
        border-bottom: 1px solid var(--ck-stroke-2);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        font-weight: 500;
        color: var(--ck-fg-3);
        white-space: nowrap;
      }
      .ck-models-table thead th.ck-num,
      .ck-models-table td.ck-num {
        text-align: right;
      }
      .ck-models-table tbody td {
        padding: 14px 12px 14px 0;
        border-bottom: 1px solid var(--ck-stroke-2);
        vertical-align: top;
        color: var(--ck-fg-2);
      }
      .ck-models-row {
        position: relative;
      }
      .ck-models-row:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
      }
      .ck-models-primary {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        min-width: 0;
        text-decoration: none;
        color: inherit;
      }
      /* Whole row is the hit target; nested interactive bits stay above. */
      .ck-models-primary::after {
        content: '';
        position: absolute;
        inset: -14px 0 -14px -4px;
        right: -9999px;
      }
      .ck-models-name {
        font-size: 14px;
        font-weight: 600;
        color: var(--ck-fg-1);
      }
      .ck-models-sub {
        font-size: 11px;
        color: var(--ck-fg-4);
      }
      .ck-models-tag {
        display: inline-flex;
        align-items: center;
        margin-top: 2px;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .ck-models-tag[data-tone='cool'] {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      .ck-models-tag[data-tone='neg'] {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.1);
      }
      .ck-models-target {
        font-size: 12px;
        color: var(--ck-fg-2);
      }
      .ck-models-dataset {
        font-size: 12px;
        color: var(--ck-fg-2);
      }
      .ck-models-dataset .is-neg {
        color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-models-served {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--ck-fg-1);
      }
      .ck-models-served.is-progress {
        color: var(--ck-fg-3);
      }
      .ck-models-live-mark {
        width: 7px;
        height: 7px;
        flex: 0 0 auto;
        border-radius: 1px;
        background: var(--ck-signal-pos, #34d399);
      }
      .ck-models-metric {
        margin-top: 2px;
        font-size: 10px;
        color: var(--ck-fg-4);
      }
      .ck-models-monitor {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 12px;
        color: var(--ck-fg-2);
      }
      .ck-models-monitor[data-tone='watch'],
      .ck-models-monitor[data-tone='alert'] {
        color: var(--ck-signal-warn, #f5c451);
      }
      .ck-models-error {
        position: relative;
        z-index: 1;
        margin-top: 6px;
        font-size: 11px;
        color: var(--ck-signal-neg);
      }
      .ck-muted {
        color: var(--ck-fg-4);
        font-size: 12px;
      }
      .ck-pulse {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--ck-signal-cool, #7dd3fc);
        animation: ck-pulse 1.4s ease-in-out infinite;
      }
      @keyframes ck-pulse {
        0%,
        100% {
          opacity: 0.35;
          transform: scale(0.85);
        }
        50% {
          opacity: 1;
          transform: scale(1.15);
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .ck-pulse {
          animation: none;
        }
      }
      .ck-steps {
        position: relative;
        z-index: 1;
        display: flex;
        flex-wrap: wrap;
        gap: 2px 12px;
        margin-top: 8px;
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }
      .ck-steps__item {
        display: flex;
        align-items: center;
        gap: 5px;
        min-width: 0;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-steps__item[data-state='done'] {
        color: var(--ck-signal-pos, #4ade80);
      }
      .ck-steps__item[data-state='active'] {
        color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-steps__item[data-state='todo'] {
        opacity: 0.5;
      }
      .ck-steps__dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        box-shadow: inset 0 0 0 1px currentColor;
      }
      .ck-score {
        font-size: 15px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-chip {
        font-size: 11px;
        padding: 4px 9px;
        border-radius: 4px;
        color: var(--ck-fg-3, #a6aebc);
        background: transparent;
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-chip:hover {
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-chip--on {
        color: var(--ck-fg-1, #e6e9ef);
        background: rgba(255, 255, 255, 0.06);
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
      }
    `,
  ],
})
export class ModelsListComponent implements OnInit {
  readonly i18n = inject(I18nService);
  protected readonly models = inject(ModelsService);
  protected readonly data = inject(DataService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastrService);

  protected readonly filter = signal<ModelFilter>('all');
  protected readonly studioOpen = signal(false);

  /** Rows seen mid-fit, so the one that settles can be announced rather than
   *  merely stop pulsing. */
  private readonly watched = new Set<string>();

  /** Forecasts get their own filter once the workspace has one to show. */
  protected readonly filters = computed<{ key: ModelFilter; label: string }[]>(() => [
    { key: 'all', label: 'models.list.filter.all' },
    { key: 'classification', label: 'models.list.filter.classification' },
    { key: 'regression', label: 'models.list.filter.regression' },
    ...(this.models.models().some((model) => model.task === 'forecasting')
      ? [{ key: 'forecasting' as ModelFilter, label: 'models.list.filter.forecasting' }]
      : []),
    { key: 'serving', label: 'models.list.filter.serving' },
  ]);

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  protected readonly hasDataset = computed(() =>
    this.data.datasets().some((dataset) => dataset.status === 'ready'),
  );

  protected readonly canTrain = computed(
    () => this.models.catalog().enabled && this.hasDataset(),
  );

  protected readonly visible = computed(() => {
    const filter = this.filter();
    const rows = groupModelsBySlug(this.models.models());
    if (filter === 'all') return rows;
    if (filter === 'serving') return rows.filter((entry) => entry.served_version !== null);
    return rows.filter((entry) => entry.task === filter);
  });

  protected readonly kpis = computed<CkObjectKpi[]>(() => {
    const rows = groupModelsBySlug(this.models.models());
    const serving = rows.filter((entry) => entry.served_version !== null);
    const best = this.bestScore(rows.map((entry) => entry.row));
    const kpis: CkObjectKpi[] = [
      { label: this.i18n.t('models.kpi.models'), value: String(rows.length), tone: 'cool' },
      { label: this.i18n.t('models.kpi.serving'), value: String(serving.length) },
    ];
    if (best) {
      kpis.push({
        label: this.i18n.t('models.kpi.best'),
        value: best.value,
        hint: best.label,
        tone: best.tone === 'neutral' ? undefined : best.tone,
      });
    }
    return kpis;
  });

  ngOnInit(): void {
    void this.reload();
    // A dataset list is what the studio picks from, and what decides whether
    // "train a model" is even offered.
    void this.data.refresh();
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  protected async reload(): Promise<void> {
    await this.models.refresh();
    this.syncPolling();
  }

  protected isActive(model: ModelDto): boolean {
    return isModelActive(model);
  }

  /** The fit as a check-list, drawn from the same function as the card's. */
  protected checklist(model: ModelDto): TrainStep[] {
    return trainChecklist(
      model.status,
      model.status_detail,
      model.cross_validation,
      this.i18n.locale(),
    );
  }

  /** The row's own score, in the metric that produced it. */
  protected scoreOf(
    model: ModelDto,
  ): { value: string; label: string; tone: string } | null {
    if (model.status !== 'ready') return null;
    const score = primaryScore(model);
    if (!score) return null;
    return {
      value: formatMetric(score.key, score.value, this.i18n.locale()),
      label: this.i18n.t('models.metric.' + score.key),
      tone: metricTone(score.key, score.value),
    };
  }

  protected openStudio(): void {
    this.studioOpen.set(true);
  }

  protected onTrained(): void {
    this.studioOpen.set(false);
    this.syncPolling();
  }

  private bestScore(
    rows: readonly ModelDto[],
  ): { value: string; label: string; tone: CkObjectKpi['tone'] } | null {
    const best = bestScore(rows);
    if (!best) return null;
    const tone = metricTone(best.key, best.value);
    return {
      value: formatMetric(best.key, best.value, this.i18n.locale()),
      label: this.i18n.t('models.metric.' + best.key),
      tone: tone === 'neutral' ? undefined : tone,
    };
  }

  /** Poll only while a fit is unsettled, and stop as soon as it settles. */
  private syncPolling(): void {
    this.watch();
    if (this.models.hasActive()) {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(() => {
        void this.models.refresh().then(() => {
          this.announceSettled();
          this.watch();
          if (!this.models.hasActive()) this.stopPolling();
        });
      }, POLL_INTERVAL_MS);
    } else {
      this.stopPolling();
    }
  }

  /** Remember which fits are still running, so their landing can be announced. */
  private watch(): void {
    for (const row of this.models.models()) {
      if (isModelActive(row)) this.watched.add(row.id);
    }
  }

  /**
   * Toast the fits that settled since the last poll.
   *
   * A fit runs in a worker and settles while the reader is looking somewhere
   * else — the studio said "queued" and closed. Without this the row simply
   * stops pulsing, which is the same silence the check-list above exists to
   * remove, and the number is the point: "Churn Radar v4 ready — AUC 0.87" is
   * the sentence a demo wants, not "training finished".
   */
  private announceSettled(): void {
    if (!this.watched.size) return;
    for (const row of this.models.models()) {
      if (!this.watched.has(row.id) || isModelActive(row)) continue;
      this.watched.delete(row.id);
      const named = { name: row.name, version: row.version };
      if (row.status === 'ready') {
        const score = primaryScore(row);
        this.toast.success(
          score
            ? this.i18n.t('models.progress.settled', {
                ...named,
                metric: this.i18n.t('models.metric.' + score.key),
                value: formatMetric(score.key, score.value, this.i18n.locale()),
              })
            : this.i18n.t('models.progress.settled.plain', named),
        );
      } else if (row.status === 'failed') {
        this.toast.error(this.i18n.t('models.progress.failed', named));
      }
    }
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}
