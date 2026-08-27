/**
 * Models (Build > Models) — the registry, and the door into the training studio.
 *
 * Three things make this page carry a demo rather than merely list rows:
 *
 * - the one version that answers wears a crown, so "which model is live" is a
 *   glance and not a click;
 * - a run in flight shows the worker's own step (`status_detail`) with a live
 *   pulse, so the seconds between "start training" and a score read as work;
 * - every row states its score in the metric that scored it, coloured only when
 *   the metric's scale makes a verdict possible.
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
import { RouterLink } from '@angular/router';
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
  algoIcon,
  bestScore,
  formatMetric,
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
    RouterLink,
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
            class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
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
        @for (option of filters; track option.key) {
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
              class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
              (click)="openStudio()"
            >
              <app-icon name="brain" [size]="14" /> {{ i18n.t('models.list.train') }}
            </button>
          } @else {
            <a
              routerLink="/data"
              class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-cyan-500 hover:bg-cyan-600 text-white transition"
            >
              <app-icon name="table" [size]="14" /> {{ i18n.t('models.list.import_data') }}
            </a>
          }
        </app-empty-state>
      } @else {
        <ul class="space-y-2">
          @for (row of visible(); track row.id) {
            <li>
              <a
                [routerLink]="['/models', row.id]"
                class="flex items-center gap-3 ck-surface rounded-md px-4 py-3 transition group ck-row"
              >
                <div
                  class="ck-icon-tile"
                  [class.ck-icon-tile--warn]="row.status === 'failed'"
                  [class.ck-icon-tile--champion]="row.is_champion"
                >
                  <app-icon [name]="algoIcon(row.algo)" [size]="16" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-sm font-medium truncate" style="color: var(--ck-fg-1)">
                      {{ row.name }}
                    </span>
                    <span class="ck-badge ck-mono">{{
                      i18n.t('models.versions.label', { version: row.version })
                    }}</span>
                    <span class="ck-badge ck-mono">
                      {{ i18n.t('models.task.' + row.task) }}
                    </span>
                    @if (row.is_champion) {
                      <span class="ck-badge ck-badge--champion ck-mono">
                        <app-icon name="crown" [size]="9" />
                        {{ i18n.t('models.detail.serving') }}
                      </span>
                    }
                    @if (row.monitor_status) {
                      <span
                        class="ck-badge ck-mono"
                        data-testid="monitor-badge"
                        [attr.data-tone]="row.monitor_status"
                        [class.ck-badge--warn]="
                          row.monitor_status === 'watch' || row.monitor_status === 'alert'
                        "
                        [class.ck-badge--live]="row.monitor_status === 'ok'"
                      >
                        {{ i18n.t('models.list.monitor.' + row.monitor_status) }}
                      </span>
                    }
                    @if (row.status !== 'ready') {
                      <span
                        class="ck-badge ck-mono"
                        [class.ck-badge--warn]="row.status === 'failed'"
                        [class.ck-badge--live]="isActive(row)"
                      >
                        {{ i18n.t('models.status.' + row.status) }}
                      </span>
                    }
                  </div>
                  @if (isActive(row)) {
                    <ol class="ck-steps" data-testid="train-checklist">
                      @for (step of checklist(row); track step.step) {
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
                  } @else if (row.status === 'failed') {
                    <div class="text-[11px] ck-mono mt-1" style="color: var(--ck-signal-neg)">
                      {{ row.error }}
                    </div>
                  } @else {
                    <div class="text-[11px] ck-mono mt-1" style="color: var(--ck-fg-4)">
                      {{ i18n.t('models.list.target', { target: row.target }) }} ·
                      {{
                        i18n.t('models.list.meta', {
                          rows: (row.row_count ?? 0).toLocaleString(i18n.locale()),
                          features: row.features.length,
                          duration: duration(row.train_duration_ms)
                        })
                      }}
                    </div>
                  }
                </div>
                @if (scoreOf(row); as score) {
                  <div class="text-right shrink-0">
                    <div class="ck-score" [attr.data-tone]="score.tone">{{ score.value }}</div>
                    <div class="text-[10px] ck-mono" style="color: var(--ck-fg-4)">
                      {{ score.label }}
                    </div>
                  </div>
                }
                <app-icon
                  name="chevron-right"
                  [size]="14"
                  class="shrink-0 transition"
                  style="color: var(--ck-fg-4)"
                />
              </a>
            </li>
          }
        </ul>
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
      .ck-row:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.04));
      }
      .ck-icon-tile {
        width: 36px;
        height: 36px;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.12);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.25);
      }
      /* The version that answers is the one fact worth a colour of its own. */
      .ck-icon-tile--champion {
        color: var(--ck-signal-pos, #34d399);
        background: rgba(52, 211, 153, 0.12);
        box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.3);
      }
      .ck-icon-tile--warn {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.12);
        box-shadow: inset 0 0 0 1px rgba(239, 90, 111, 0.25);
      }
      .ck-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 5px;
        border-radius: 3px;
        color: var(--ck-fg-4, #8891a0);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
      }
      .ck-badge--champion {
        color: var(--ck-signal-pos, #34d399);
        background: rgba(52, 211, 153, 0.1);
        box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.28);
      }
      .ck-badge--warn {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.08);
      }
      .ck-badge--live {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
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
      /* Same check-list as the ingest plane's and the model card's: the steps
         already passed stay visible and ticked, so the seconds a fit takes read
         as distance covered rather than as a stall. */
      .ck-steps {
        display: flex;
        flex-wrap: wrap;
        gap: 2px 12px;
        margin-top: 4px;
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }
      .ck-steps__item {
        display: flex;
        align-items: center;
        gap: 5px;
        min-width: 0;
        color: var(--ck-fg-4, #8891a0);
        transition: color var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
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
      .ck-score[data-tone='pos'] {
        color: var(--ck-signal-pos, #34d399);
      }
      .ck-score[data-tone='warn'] {
        color: var(--ck-signal-warn, #fbbf24);
      }
      .ck-score[data-tone='neg'] {
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-chip {
        font-size: 11px;
        padding: 4px 9px;
        border-radius: 999px;
        color: var(--ck-fg-3, #a6aebc);
        background: transparent;
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-chip:hover {
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-chip--on {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.35);
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

  protected readonly filters: { key: ModelFilter; label: string }[] = [
    { key: 'all', label: 'models.list.filter.all' },
    { key: 'classification', label: 'models.list.filter.classification' },
    { key: 'regression', label: 'models.list.filter.regression' },
    { key: 'serving', label: 'models.list.filter.serving' },
  ];

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  protected readonly hasDataset = computed(() =>
    this.data.datasets().some((dataset) => dataset.status === 'ready'),
  );

  protected readonly canTrain = computed(
    () => this.models.catalog().enabled && this.hasDataset(),
  );

  protected readonly visible = computed(() => {
    const filter = this.filter();
    const rows = this.models.models();
    if (filter === 'all') return rows;
    if (filter === 'serving') return rows.filter((row) => row.is_champion);
    return rows.filter((row) => row.task === filter);
  });

  protected readonly kpis = computed<CkObjectKpi[]>(() => {
    const rows = this.models.models();
    const serving = rows.filter((row) => row.is_champion);
    const best = this.bestScore(rows);
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

  protected algoIcon(algo: string): string {
    return algoIcon(algo);
  }

  protected duration(ms: number | null | undefined): string {
    if (!ms || ms <= 0) return '—';
    if (ms < 1000) return `${Math.round(ms)} ms`;
    const seconds = ms / 1000;
    if (seconds < 60) {
      return `${seconds.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 1 })} s`;
    }
    const minutes = Math.floor(seconds / 60);
    return `${minutes} min ${Math.round(seconds % 60)} s`;
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
