/**
 * Model card — the evidence, the contract, the lineage and the settings.
 *
 * One request serves the whole page: the training worker already folded the
 * metrics, the curves, the class balance, the permutation importances and the
 * input contract into the row, so there is nothing to compute per tab and
 * nothing to fetch when the user switches one.
 *
 * The Results tab is the "this is an ML platform" moment, and it is arranged as
 * an argument rather than as a dashboard: the class balance sits *next to* the
 * scores because an 82% accuracy on a 4% churn rate is not a result; the
 * confusion matrix is shaded by row so the mistake that matters — the churner
 * called loyal — cannot be hidden by the majority class; and the importances
 * name what the model actually leaned on.
 *
 * Promotion is the one write that changes behaviour elsewhere: a lineage serves
 * exactly one version, and it is chosen here, by hand. Retraining never steals
 * that place.
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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabComponent, CkTabsComponent } from '@app/shared/cockpit/tabs.component';
import { formatBytes } from '@app/shared/ui/data-table.vm';
import { I18nService } from '@app/core/i18n.service';
import { DataService } from '@app/features/data/data.service';
import { ModelPlaygroundComponent } from './model-playground.component';
import { ModelTrainComponent, type TrainSeed } from './model-train.component';
import { ModelsService, isModelActive, type ModelDetailDto } from './models.service';
import {
  UNIT_DOMAIN,
  balanceBars,
  comparisonRows,
  confusionView,
  curveDomain,
  curvePath,
  formatMetric,
  importanceBars,
  metricDelta,
  metricTone,
  previousVersion,
  primaryScore,
  splitError,
  trainStepKey,
  trainingErrorKey,
  type ComparisonRow,
  type CurveBox,
  type CvBlock,
  type MetricTone,
  type ModelDto,
  type ServingBlock,
  type SignatureField,
} from './models.vm';

const POLL_INTERVAL_MS = 1500;

/** The drawing box every chart on this page shares, in user units. */
const CHART: CurveBox = { width: 300, height: 190 };

@Component({
  selector: 'app-model-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    ModelPlaygroundComponent,
    ModelTrainComponent,
  ],
  template: `
    <a
      routerLink="/models"
      class="inline-flex items-center gap-1.5 text-[11px] ck-mono mb-3 transition"
      style="color: var(--ck-fg-4)"
    >
      <app-icon name="chevron-left" [size]="13" /> {{ i18n.t('models.detail.back') }}
    </a>

    @if (model(); as row) {
      <ck-object-header
        [eyebrow]="i18n.t('models.algo.' + row.algo)"
        [title]="row.name"
        [subtitle]="subtitle(row)"
        [kpis]="kpis()"
      >
        <div status class="flex items-center gap-1.5">
          @if (row.is_champion) {
            <span class="ck-badge ck-badge--champion ck-mono">
              <app-icon name="crown" [size]="10" /> {{ i18n.t('models.detail.serving') }}
            </span>
          }
          <span
            class="ck-badge ck-mono"
            [class.ck-badge--warn]="row.status === 'failed'"
            [class.ck-badge--live]="isActive(row)"
          >
            {{ i18n.t('models.status.' + row.status) }}
          </span>
        </div>
        <div actions class="flex items-center gap-1.5 flex-wrap">
          @if (row.status === 'ready' && !row.is_champion) {
            <button
              type="button"
              class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-emerald-500 hover:bg-emerald-600 text-white transition"
              [title]="i18n.t('models.detail.promote_hint')"
              (click)="promote()"
            >
              <app-icon name="crown" [size]="14" /> {{ i18n.t('models.detail.promote') }}
            </button>
          }
          @if (isActive(row)) {
            <button
              type="button"
              class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
              [disabled]="row.cancel_requested"
              (click)="cancel()"
            >
              <app-icon name="square" [size]="14" /> {{ i18n.t('models.detail.cancel') }}
            </button>
          } @else {
            <button
              type="button"
              class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
              (click)="retrain()"
            >
              <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('models.detail.retrain') }}
            </button>
          }
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
            (click)="remove()"
          >
            <app-icon name="trash-2" [size]="14" /> {{ i18n.t('models.detail.delete') }}
          </button>
        </div>
      </ck-object-header>

      @if (isActive(row)) {
        <div class="ck-progress rounded-md px-4 py-3 mb-3">
          <div class="flex items-center gap-2 text-sm" style="color: var(--ck-fg-1)">
            <app-icon name="loader-2" [size]="14" class="animate-spin" />
            {{ i18n.t('models.detail.progress.title') }}
          </div>
          <div class="text-[11px] ck-mono mt-1" style="color: var(--ck-signal-cool)">
            {{ i18n.t(stepKey(row.status_detail)) }}
          </div>
        </div>
      } @else if (row.status === 'failed') {
        <div class="ck-error rounded-md px-4 py-3 mb-3">
          <div class="text-sm font-medium" style="color: var(--ck-signal-neg)">
            {{ i18n.t('models.detail.error.title') }}
          </div>
          <div class="text-[12px] mt-1" style="color: var(--ck-fg-2)">{{ errorSentence() }}</div>
          @if (errorDetail(); as detail) {
            <code class="text-[11px] block mt-1" style="color: var(--ck-fg-4)">{{ detail }}</code>
          }
        </div>
      }

      <ck-tabs [active]="tab()" (activeChange)="tab.set($event)">
        <!-- ── Results ──────────────────────────────────────────────────── -->
        <ck-tab id="evidence" [label]="i18n.t('models.detail.tab.evidence')">
          @if (!scores().length) {
            <app-empty-state icon="brain" [title]="i18n.t('models.evidence.none')" />
          } @else {
            <div class="space-y-4">
              <section>
                <div class="ck-section-label">{{ i18n.t('models.evidence.scores') }}</div>
                <div class="ck-scores">
                  @for (score of scores(); track score.key) {
                    <div class="ck-score-card" [title]="i18n.t('models.metric.' + score.key + '.hint')">
                      <div class="ck-score-card__value" [attr.data-tone]="score.tone">
                        {{ score.display }}
                      </div>
                      <div class="ck-score-card__label">
                        {{ i18n.t('models.metric.' + score.key) }}
                      </div>
                      @if (score.delta; as delta) {
                        <div
                          class="ck-delta ck-mono"
                          [attr.data-move]="delta.flat ? 'flat' : delta.better ? 'up' : 'down'"
                          [title]="deltaTitle()"
                        >
                          {{ delta.display }}
                        </div>
                      }
                    </div>
                  }
                </div>
                <div class="flex items-baseline gap-2 flex-wrap mt-2">
                  @if (rowsLine(); as line) {
                    <span class="text-[11px] ck-mono" style="color: var(--ck-fg-4)">{{ line }}</span>
                  }
                  @if (against(); as earlier) {
                    <a
                      [routerLink]="['/models', earlier.id]"
                      class="text-[11px] ck-mono transition"
                      style="color: var(--ck-fg-4)"
                    >
                      {{ deltaTitle() }}
                    </a>
                  }
                </div>
              </section>

              <div class="ck-charts">
                @if (rocPath()) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.roc') }}</div>
                    <svg
                      [attr.viewBox]="'0 0 ' + chart.width + ' ' + chart.height"
                      class="ck-plot"
                      role="img"
                      [attr.aria-label]="i18n.t('models.evidence.roc')"
                    >
                      <line
                        [attr.x1]="0"
                        [attr.y1]="chart.height"
                        [attr.x2]="chart.width"
                        [attr.y2]="0"
                        class="ck-plot__ref"
                      />
                      <path [attr.d]="rocArea()" class="ck-plot__area" />
                      <path [attr.d]="rocPath()" class="ck-plot__line" />
                    </svg>
                    <div class="ck-hint">{{ i18n.t('models.evidence.roc.hint') }}</div>
                  </section>
                }
                @if (prPath()) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.pr') }}</div>
                    <svg
                      [attr.viewBox]="'0 0 ' + chart.width + ' ' + chart.height"
                      class="ck-plot"
                      role="img"
                      [attr.aria-label]="i18n.t('models.evidence.pr')"
                    >
                      @if (baselineY() !== null) {
                        <line
                          [attr.x1]="0"
                          [attr.y1]="baselineY()"
                          [attr.x2]="chart.width"
                          [attr.y2]="baselineY()"
                          class="ck-plot__ref"
                        />
                      }
                      <path [attr.d]="prPath()" class="ck-plot__line ck-plot__line--violet" />
                    </svg>
                    <div class="ck-hint">{{ i18n.t('models.evidence.pr.hint') }}</div>
                  </section>
                }
                @if (fitPath()) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.fit') }}</div>
                    <svg
                      [attr.viewBox]="'0 0 ' + chart.width + ' ' + chart.height"
                      class="ck-plot"
                      role="img"
                      [attr.aria-label]="i18n.t('models.evidence.fit')"
                    >
                      <path [attr.d]="idealPath()" class="ck-plot__ref" />
                      <path [attr.d]="fitPath()" class="ck-plot__line" />
                    </svg>
                    <div class="ck-hint">{{ i18n.t('models.evidence.fit.hint') }}</div>
                  </section>
                }
                @if (confusion(); as grid) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.confusion') }}</div>
                    <table class="ck-matrix">
                      <thead>
                        <tr>
                          <th class="ck-matrix__corner ck-mono">
                            {{ i18n.t('models.evidence.confusion.actual') }} \\
                            {{ i18n.t('models.evidence.confusion.predicted') }}
                          </th>
                          @for (label of grid.labels; track label) {
                            <th class="ck-matrix__th ck-mono">{{ label }}</th>
                          }
                        </tr>
                      </thead>
                      <tbody>
                        @for (line of grid.rows; track line.actual) {
                          <tr>
                            <th class="ck-matrix__rh ck-mono">{{ line.actual }}</th>
                            @for (cell of line.cells; track cell.predicted) {
                              <td
                                class="ck-matrix__td ck-mono"
                                [class.ck-matrix__td--ok]="cell.correct"
                                [style.background]="cellShade(cell.share, cell.correct)"
                                [title]="cellTitle(cell.actual, cell.predicted, cell.share)"
                              >
                                {{ cell.count.toLocaleString(i18n.locale()) }}
                              </td>
                            }
                          </tr>
                        }
                      </tbody>
                    </table>
                    <div class="ck-hint">{{ i18n.t('models.evidence.confusion.hint') }}</div>
                  </section>
                }
                @if (balance().length) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.balance') }}</div>
                    <div class="space-y-1.5">
                      @for (bar of balance(); track bar.label) {
                        <div>
                          <div class="ck-bar__head ck-mono">
                            <span>{{ bar.label }}</span>
                            <span style="color: var(--ck-fg-4)">
                              {{ bar.count.toLocaleString(i18n.locale()) }} ·
                              {{ percent(bar.share) }}
                            </span>
                          </div>
                          <div class="ck-bar">
                            <div
                              class="ck-bar__fill ck-bar__fill--violet"
                              [style.width.%]="bar.width"
                            ></div>
                          </div>
                        </div>
                      }
                    </div>
                    <div class="ck-hint">{{ i18n.t('models.evidence.balance.hint') }}</div>
                  </section>
                }
              </div>

              @if (importances().length) {
                <section>
                  <div class="ck-section-label">{{ i18n.t('models.evidence.importances') }}</div>
                  <div class="space-y-1.5">
                    @for (bar of importances(); track bar.feature) {
                      <div>
                        <div class="ck-bar__head ck-mono">
                          <span [style.color]="bar.negative ? 'var(--ck-signal-neg)' : 'inherit'">
                            {{ bar.feature }}
                          </span>
                          <span
                            style="color: var(--ck-fg-4)"
                            [title]="
                              bar.negative ? i18n.t('models.evidence.importances.negative') : ''
                            "
                          >
                            {{ bar.value.toLocaleString(i18n.locale(), { maximumFractionDigits: 4 }) }}
                          </span>
                        </div>
                        <div class="ck-bar">
                          <div
                            class="ck-bar__fill"
                            [class.ck-bar__fill--neg]="bar.negative"
                            [style.width.%]="bar.width"
                          ></div>
                        </div>
                      </div>
                    }
                  </div>
                  <div class="ck-hint">{{ i18n.t('models.evidence.importances.hint') }}</div>
                </section>
              }

              @if (cv(); as folds) {
                <section>
                  <div class="ck-section-label">{{ i18n.t('models.evidence.cv') }}</div>
                  @if (folds.error) {
                    <div class="text-[11px] ck-mono" style="color: var(--ck-signal-warn)">
                      {{ i18n.t('models.evidence.cv.failed') }}
                    </div>
                  } @else {
                    <div class="text-[12px] ck-mono" style="color: var(--ck-fg-2)">
                      {{ cvSummary(folds) }}
                    </div>
                    <div class="flex items-center gap-1.5 flex-wrap mt-1.5">
                      @for (row of folds.metrics ?? []; track row.key) {
                        <span class="ck-fold ck-mono">
                          {{ i18n.t('models.metric.' + row.key) }}
                          {{ formatMetric(row.key, row.mean) }}
                          @if (row.std !== null && row.std !== undefined) {
                            <span style="color: var(--ck-fg-3)"
                              >± {{ formatMetric(row.key, row.std) }}</span
                            >
                          }
                        </span>
                      }
                    </div>
                  }
                </section>
              }

              @if (dropped().length) {
                <section>
                  <div class="ck-section-label">{{ i18n.t('models.evidence.dropped') }}</div>
                  <div class="flex items-center gap-1.5 flex-wrap">
                    @for (column of dropped(); track column.name) {
                      <span class="ck-fold ck-mono">
                        {{
                          i18n.t('models.evidence.dropped.' + column.reason, { name: column.name })
                        }}
                      </span>
                    }
                  </div>
                </section>
              }
            </div>
          }
        </ck-tab>

        <!-- ── Playground ──────────────────────────────────────────────────── -->
        <ck-tab id="play" [label]="i18n.t('models.detail.tab.play')">
          @if (serving(); as plane) {
            <app-model-playground
              [model]="row"
              [serving]="plane"
              (servingChange)="serving.set($event)"
              (changed)="reload()"
            />
          }
        </ck-tab>

        <!-- ── Comparison ──────────────────────────────────────────────────── -->
        <ck-tab id="compare" [label]="i18n.t('models.detail.tab.compare')">
          @if (!comparison().length) {
            <app-empty-state
              icon="git-compare"
              [title]="i18n.t('models.compare.none.title')"
              [description]="i18n.t('models.compare.none.description')"
            />
          } @else {
            <div class="space-y-3">
              <div class="ck-hint">{{ i18n.t('models.compare.hint') }}</div>
              <div class="ck-versus">
                @for (side of sides(); track side.id) {
                  <div class="ck-versus__side" [attr.data-role]="side.role">
                    <div class="ck-section-label">
                      {{ i18n.t('models.versions.label', { version: side.version }) }}
                    </div>
                    <div class="text-[12px]" style="color: var(--ck-fg-1)">{{ side.name }}</div>
                    <div class="text-[10.5px] ck-mono" style="color: var(--ck-fg-4)">
                      {{ side.line }}
                    </div>
                  </div>
                }
              </div>
              <div class="ck-surface rounded-md overflow-hidden">
                <table class="w-full text-sm ck-schema">
                  <thead>
                    <tr>
                      <th class="ck-schema__th">{{ i18n.t('models.compare.metric') }}</th>
                      <th class="ck-schema__th">{{ i18n.t('models.compare.before') }}</th>
                      <th class="ck-schema__th">{{ i18n.t('models.compare.after') }}</th>
                      <th class="ck-schema__th">{{ i18n.t('models.compare.move') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (line of comparison(); track line.key) {
                      <tr class="ck-schema__tr">
                        <td class="ck-schema__td">{{ i18n.t('models.metric.' + line.key) }}</td>
                        <td
                          class="ck-schema__td ck-mono"
                          [class.ck-versus__win]="line.winner === 'left'"
                        >
                          {{ line.left }}
                        </td>
                        <td
                          class="ck-schema__td ck-mono"
                          [class.ck-versus__win]="line.winner === 'right'"
                        >
                          {{ line.right }}
                        </td>
                        <td class="ck-schema__td">
                          @if (line.delta; as delta) {
                            <span
                              class="ck-delta ck-mono"
                              [attr.data-move]="
                                delta.flat ? 'flat' : delta.better ? 'up' : 'down'
                              "
                            >
                              {{ delta.display }}
                            </span>
                          }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              @if (verdict(); as sentence) {
                <div class="text-[12px]" style="color: var(--ck-fg-2)">{{ sentence }}</div>
              }
            </div>
          }
        </ck-tab>

        <!-- ── Input contract ──────────────────────────────────────────────── -->
        <ck-tab id="contract" [label]="i18n.t('models.detail.tab.contract')">
          @if (!fields().length) {
            <app-empty-state icon="braces" [title]="i18n.t('models.evidence.none')" />
          } @else {
            <div class="space-y-4">
              <div>
                <div class="ck-section-label">{{ i18n.t('models.contract.title') }}</div>
                <div class="ck-hint">{{ i18n.t('models.contract.hint') }}</div>
              </div>
              <div class="ck-surface rounded-md overflow-hidden">
                <table class="w-full text-sm ck-schema">
                  <thead>
                    <tr>
                      <th class="ck-schema__th">{{ i18n.t('models.contract.field') }}</th>
                      <th class="ck-schema__th">{{ i18n.t('models.contract.kind') }}</th>
                      <th class="ck-schema__th">{{ i18n.t('models.contract.range') }}</th>
                      <th class="ck-schema__th">{{ i18n.t('models.contract.default') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (field of fields(); track field.name) {
                      <tr class="ck-schema__tr">
                        <td class="ck-schema__td ck-mono" style="color: var(--ck-fg-1)">
                          {{ field.name }}
                        </td>
                        <td class="ck-schema__td">
                          <span class="ck-kind">
                            {{ i18n.t('models.contract.kind.' + field.kind) }}
                          </span>
                        </td>
                        <td class="ck-schema__td ck-mono">{{ rangeOf(field) }}</td>
                        <td class="ck-schema__td ck-mono">{{ defaultOf(field) }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              <div>
                <div class="ck-section-label">{{ i18n.t('models.contract.output') }}</div>
                <div class="text-[12px]" style="color: var(--ck-fg-2)">{{ outputLine() }}</div>
              </div>
              @if (example(); as sample) {
                <div>
                  <div class="ck-section-label">{{ i18n.t('models.contract.example') }}</div>
                  <pre class="ck-code">{{ sample }}</pre>
                </div>
              }
            </div>
          }
        </ck-tab>

        <!-- ── Versions ─────────────────────────────────────────────────────── -->
        <ck-tab id="versions" [label]="i18n.t('models.detail.tab.versions')">
          <div class="space-y-2">
            <div class="ck-hint">{{ i18n.t('models.versions.hint') }}</div>
            <ul class="space-y-2">
              @for (version of versions(); track version.id) {
                <li>
                  <a
                    [routerLink]="['/models', version.id]"
                    class="flex items-center gap-3 ck-surface rounded-md px-4 py-2.5 transition ck-row"
                  >
                    <span class="ck-badge ck-mono">{{
                      i18n.t('models.versions.label', { version: version.version })
                    }}</span>
                    @if (version.is_champion) {
                      <span class="ck-badge ck-badge--champion ck-mono">
                        <app-icon name="crown" [size]="9" /> {{ i18n.t('models.versions.serving') }}
                      </span>
                    }
                    <span class="flex-1 text-[11px] ck-mono" style="color: var(--ck-fg-4)">
                      {{ versionLine(version) }}
                    </span>
                    @if (scoreOf(version); as score) {
                      <span class="ck-score-inline" [attr.data-tone]="score.tone">
                        {{ score.display }}
                      </span>
                    }
                    @if (version.id === model()?.id) {
                      <span class="ck-badge ck-badge--on ck-mono">
                        {{ i18n.t('models.versions.current') }}
                      </span>
                    }
                  </a>
                </li>
              }
            </ul>
          </div>
        </ck-tab>

        <!-- ── Settings ─────────────────────────────────────────────────────── -->
        <ck-tab id="setup" [label]="i18n.t('models.detail.tab.setup')">
          <div class="ck-surface rounded-md overflow-hidden">
            <table class="w-full text-sm ck-schema">
              <tbody>
                @for (entry of setup(); track entry.label) {
                  <tr class="ck-schema__tr">
                    <td class="ck-schema__td" style="width: 34%; color: var(--ck-fg-4)">
                      {{ entry.label }}
                    </td>
                    <td class="ck-schema__td ck-mono" style="color: var(--ck-fg-1)">
                      {{ entry.value }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          @if (dataset(); as ds) {
            <a
              [routerLink]="['/data', ds.id]"
              class="inline-flex items-center gap-1.5 text-[11px] ck-mono mt-3 transition"
              style="color: var(--ck-signal-cool)"
            >
              <app-icon name="table" [size]="12" /> {{ i18n.t('models.detail.dataset.open') }}
            </a>
          }
        </ck-tab>
      </ck-tabs>
    } @else if (loading()) {
      <div class="ck-surface rounded-md p-6 animate-pulse">
        <div class="h-3 w-48 rounded" style="background: rgba(255,255,255,0.05)"></div>
      </div>
    } @else {
      <app-empty-state
        icon="brain"
        [title]="i18n.t('models.list.empty.title')"
        [description]="i18n.t('models.list.empty.description')"
      />
    }

    @if (studioOpen()) {
      <app-model-train
        [datasets]="data.datasets()"
        [seed]="seed()"
        (close)="studioOpen.set(false)"
        (trained)="onRetrained($event)"
      />
    }
  `,
  styles: [
    `
      .ck-progress {
        border: 1px solid rgba(125, 211, 252, 0.25);
        background: rgba(125, 211, 252, 0.05);
      }
      .ck-error {
        border: 1px solid rgba(239, 90, 111, 0.25);
        background: rgba(239, 90, 111, 0.05);
      }
      .ck-section-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--ck-fg-4, #8891a0);
        margin-bottom: 7px;
      }
      .ck-hint {
        font-size: 10.5px;
        line-height: 1.45;
        color: var(--ck-fg-4, #8891a0);
        margin-top: 6px;
      }
      .ck-scores {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
      }
      .ck-score-card {
        min-width: 104px;
        padding: 9px 12px;
        border-radius: 6px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-score-card__value {
        font-size: 19px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--ck-fg-1, #e6e9ef);
        line-height: 1.15;
      }
      .ck-score-card__value[data-tone='pos'] {
        color: var(--ck-signal-pos, #34d399);
      }
      .ck-score-card__value[data-tone='warn'] {
        color: var(--ck-signal-warn, #fbbf24);
      }
      .ck-score-card__value[data-tone='neg'] {
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-score-card__label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: var(--ck-fg-4, #8891a0);
        margin-top: 2px;
      }
      /* The delta is the sentence "this retrain was worth keeping", so it is
         coloured by verdict rather than by sign: a smaller MAE reads as green. */
      .ck-delta {
        display: inline-block;
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
        margin-top: 3px;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-delta[data-move='up'] {
        color: var(--ck-signal-pos, #34d399);
      }
      .ck-delta[data-move='down'] {
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-versus {
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
      }
      @media (min-width: 720px) {
        .ck-versus {
          grid-template-columns: 1fr 1fr;
        }
      }
      .ck-versus__side {
        padding: 10px 12px;
        border-radius: 6px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-versus__side[data-role='after'] {
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.28);
      }
      .ck-versus__win {
        color: var(--ck-fg-1, #e6e9ef) !important;
        font-weight: 600;
      }
      .ck-charts {
        display: grid;
        grid-template-columns: 1fr;
        gap: 12px;
      }
      @media (min-width: 820px) {
        .ck-charts {
          grid-template-columns: 1fr 1fr;
        }
      }
      .ck-chart {
        padding: 12px 14px;
        border-radius: 6px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.02));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
      }
      .ck-plot {
        width: 100%;
        height: auto;
        overflow: visible;
      }
      .ck-plot__ref {
        fill: none;
        stroke: var(--ck-stroke-2, rgba(255, 255, 255, 0.16));
        stroke-width: 1;
        stroke-dasharray: 3 3;
      }
      .ck-plot__line {
        fill: none;
        stroke: var(--ck-signal-cool, #7dd3fc);
        stroke-width: 2;
        stroke-linejoin: round;
        stroke-linecap: round;
      }
      .ck-plot__line--violet {
        stroke: var(--ck-signal-violet, #a78bfa);
      }
      .ck-plot__area {
        fill: rgba(125, 211, 252, 0.12);
        stroke: none;
      }
      .ck-matrix {
        border-collapse: separate;
        border-spacing: 2px;
        width: 100%;
      }
      .ck-matrix__corner,
      .ck-matrix__th,
      .ck-matrix__rh {
        font-size: 9.5px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--ck-fg-4, #8891a0);
        padding: 3px 5px;
        text-align: center;
      }
      .ck-matrix__corner,
      .ck-matrix__rh {
        text-align: left;
      }
      .ck-matrix__td {
        text-align: center;
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        padding: 8px 6px;
        border-radius: 3px;
        color: var(--ck-fg-2, #c3c9d4);
      }
      .ck-matrix__td--ok {
        color: var(--ck-fg-1, #e6e9ef);
        font-weight: 600;
      }
      .ck-bar__head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        font-size: 10.5px;
        color: var(--ck-fg-2, #c3c9d4);
        margin-bottom: 2px;
      }
      .ck-bar {
        height: 6px;
        border-radius: 3px;
        background: var(--ck-stroke-1, rgba(255, 255, 255, 0.05));
        overflow: hidden;
      }
      .ck-bar__fill {
        height: 100%;
        border-radius: 3px;
        background: linear-gradient(
          90deg,
          rgba(125, 211, 252, 0.45) 0%,
          var(--ck-signal-cool, #7dd3fc) 100%
        );
      }
      .ck-bar__fill--violet {
        background: linear-gradient(
          90deg,
          rgba(167, 139, 250, 0.45) 0%,
          var(--ck-signal-violet, #a78bfa) 100%
        );
      }
      .ck-bar__fill--neg {
        background: linear-gradient(
          90deg,
          rgba(239, 90, 111, 0.45) 0%,
          var(--ck-signal-neg, #ef5a6f) 100%
        );
      }
      .ck-fold {
        font-size: 10.5px;
        padding: 2px 7px;
        border-radius: 999px;
        color: var(--ck-fg-3, #a6aebc);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-schema {
        border-collapse: separate;
        border-spacing: 0;
      }
      .ck-schema__th {
        text-align: left;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-weight: 600;
        color: var(--ck-fg-4, #8891a0);
        padding: 8px 12px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-schema__td {
        padding: 7px 12px;
        border-bottom: 1px solid var(--ck-stroke-1, rgba(255, 255, 255, 0.03));
        color: var(--ck-fg-2, #c3c9d4);
        font-size: 12px;
      }
      .ck-schema__tr:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
      }
      .ck-kind {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 5px;
        border-radius: 3px;
        color: var(--ck-signal-violet, #a78bfa);
        background: rgba(167, 139, 250, 0.1);
      }
      .ck-code {
        font-size: 11px;
        line-height: 1.5;
        padding: 10px 12px;
        border-radius: 5px;
        overflow-x: auto;
        color: var(--ck-fg-2, #c3c9d4);
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-row:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.04));
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
      .ck-badge--on {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      .ck-badge--warn {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.08);
      }
      .ck-badge--live {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      .ck-score-inline {
        font-size: 12px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-score-inline[data-tone='pos'] {
        color: var(--ck-signal-pos, #34d399);
      }
      .ck-score-inline[data-tone='warn'] {
        color: var(--ck-signal-warn, #fbbf24);
      }
      .ck-score-inline[data-tone='neg'] {
        color: var(--ck-signal-neg, #ef5a6f);
      }
    `,
  ],
})
export class ModelViewComponent implements OnInit {
  readonly i18n = inject(I18nService);
  protected readonly data = inject(DataService);
  private readonly models = inject(ModelsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly chart = CHART;

  protected readonly detail = signal<ModelDetailDto | null>(null);
  protected readonly loading = signal(false);
  protected readonly tab = signal('evidence');
  protected readonly studioOpen = signal(false);
  /**
   * The serving plane, held apart from the detail it arrived with.
   *
   * A mint, a revoke or a publish returns a fresh block, and re-reading the whole
   * card to learn that a key now exists would throw away the secret the Playground
   * is still showing — a secret this platform cannot show twice.
   */
  protected readonly serving = signal<ServingBlock | null>(null);

  private modelId = '';
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  protected readonly model = computed(() => this.detail()?.model ?? null);
  protected readonly dataset = computed(() => this.detail()?.dataset ?? null);
  protected readonly versions = computed(() => this.detail()?.versions ?? []);
  private readonly metrics = computed(() => this.model()?.metrics ?? null);

  /**
   * The version this one's scores are read against.
   *
   * The newest *trained* version below it, not the champion and not `n-1`: a
   * lineage can hold a failed retrain, and measuring against a run that never
   * produced a score would silence the delta on the version after it.
   */
  protected readonly against = computed(() =>
    previousVersion(this.model(), this.versions()),
  );

  protected readonly scores = computed(() => {
    const earlier = new Map(
      (this.against()?.metrics?.scores ?? []).map((score) => [score.key, score.value]),
    );
    return (this.metrics()?.scores ?? []).map((score) => ({
      key: score.key,
      display: formatMetric(score.key, score.value, this.i18n.locale()),
      tone: metricTone(score.key, score.value),
      delta: metricDelta(
        score.key,
        score.value,
        earlier.get(score.key),
        this.i18n.locale(),
      ),
    }));
  });

  protected readonly comparison = computed<ComparisonRow[]>(() =>
    comparisonRows(this.against(), this.model(), this.i18n.locale()),
  );

  protected readonly confusion = computed(() => confusionView(this.metrics()?.confusion));
  protected readonly importances = computed(() => importanceBars(this.metrics()?.importances));
  protected readonly balance = computed(() => balanceBars(this.metrics()?.target?.balance));
  protected readonly cv = computed(() => this.metrics()?.cv ?? null);
  protected readonly dropped = computed(() => this.metrics()?.columns?.dropped ?? []);
  protected readonly fields = computed<SignatureField[]>(
    () => this.model()?.signature?.inputs ?? [],
  );

  protected readonly rocPath = computed(() =>
    curvePath(this.metrics()?.curves?.roc, CHART, UNIT_DOMAIN),
  );

  protected readonly prPath = computed(() =>
    curvePath(this.metrics()?.curves?.pr, CHART, UNIT_DOMAIN),
  );

  /** The regression fit and its ideal share one domain, or they cannot be read together. */
  private readonly fitDomain = computed(() =>
    curveDomain([this.metrics()?.curves?.fit ?? [], this.metrics()?.curves?.ideal ?? []]),
  );

  protected readonly fitPath = computed(() =>
    curvePath(this.metrics()?.curves?.fit, CHART, this.fitDomain()),
  );

  protected readonly idealPath = computed(() =>
    curvePath(this.metrics()?.curves?.ideal, CHART, this.fitDomain()),
  );

  protected readonly kpis = computed<CkObjectKpi[]>(() => {
    const row = this.model();
    if (!row) return [];
    const kpis: CkObjectKpi[] = [];
    const score = this.scoreOf(row);
    if (score) {
      kpis.push({
        label: this.i18n.t('models.metric.' + score.key),
        value: score.display,
        tone: score.tone === 'neutral' ? 'cool' : score.tone,
      });
    }
    kpis.push({
      label: this.i18n.t('models.kpi.rows'),
      value: (row.row_count ?? 0).toLocaleString(this.i18n.locale()),
    });
    kpis.push({
      label: this.i18n.t('models.kpi.features'),
      value: String(row.features.length),
    });
    kpis.push({
      label: this.i18n.t('models.kpi.duration'),
      value: this.duration(row.train_duration_ms),
    });
    if (row.artifact_bytes) {
      kpis.push({
        label: this.i18n.t('models.kpi.artifact'),
        value: formatBytes(row.artifact_bytes, this.i18n.locale()),
      });
    }
    return kpis;
  });

  /** What a retrain opens the studio on: this version's own choices. */
  protected readonly seed = computed<TrainSeed | null>(() => {
    const row = this.model();
    if (!row) return null;
    return {
      datasetId: row.dataset_id,
      target: row.target,
      task: row.task,
      features: row.features,
      algo: row.algo,
      knobs: row.params?.knobs ?? {},
      testSize: row.test_size,
      crossValidation: row.cross_validation,
    };
  });

  protected readonly setup = computed<{ label: string; value: string }[]>(() => {
    const row = this.model();
    if (!row) return [];
    const params = row.params ?? {};
    const knobs = params.knobs ?? {};
    const knobLine = Object.entries(knobs)
      .map(([key, value]) => `${key}=${value === null ? 'auto' : value}`)
      .join(' · ');
    const entries: { label: string; value: string }[] = [
      { label: this.i18n.t('models.setup.estimator'), value: params.estimator ?? row.algo },
      { label: this.i18n.t('models.setup.target'), value: row.target },
      {
        label: this.i18n.t('models.setup.features'),
        value: row.features.join(', ') || '—',
      },
      {
        label: this.i18n.t('models.setup.split'),
        value: row.test_size ? `${Math.round(row.test_size * 100)}%` : '—',
      },
      {
        label: this.i18n.t('models.setup.cv'),
        value: row.cross_validation
          ? this.i18n.t('models.studio.cv.folds', { folds: row.cross_validation })
          : this.i18n.t('models.studio.cv.off'),
      },
      {
        label: this.i18n.t('models.setup.preprocessing'),
        value: this.i18n.t('models.setup.preprocessing.value'),
      },
    ];
    if (knobLine) {
      entries.splice(1, 0, { label: this.i18n.t('models.setup.knobs'), value: knobLine });
    }
    if (params.scale) {
      entries.push({ label: this.i18n.t('models.setup.scale'), value: '✓' });
    }
    if (row.artifact_bytes) {
      entries.push({
        label: this.i18n.t('models.setup.artifact'),
        value: formatBytes(row.artifact_bytes, this.i18n.locale()),
      });
    }
    return entries;
  });

  ngOnInit(): void {
    // Subscribed rather than snapshotted: the Versions tab links to a sibling
    // version, which Angular serves by reusing this component instance.
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        const next = params.get('modelId') ?? '';
        if (next === this.modelId) return;
        this.modelId = next;
        void this.load();
      });
    void this.data.refresh();
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  protected isActive(model: ModelDto): boolean {
    return isModelActive(model);
  }

  /** The worker names its step as a code; the locale supplies the sentence. */
  protected stepKey(detail: string | null | undefined): string {
    return trainStepKey(detail);
  }

  protected formatMetric(key: string, value: number | null | undefined): string {
    return formatMetric(key, value, this.i18n.locale());
  }

  protected subtitle(model: ModelDto): string {
    const predicts = this.i18n.t('models.list.target', { target: model.target });
    const from = model.dataset_slug
      ? this.i18n.t('models.list.dataset', { dataset: model.dataset_slug })
      : '';
    const trained = model.trained_at
      ? this.i18n.t('models.detail.trained_at', {
          date: new Date(model.trained_at).toLocaleString(this.i18n.locale()),
        })
      : '';
    return [predicts, from, trained].filter(Boolean).join(' · ');
  }

  protected rowsLine(): string {
    const rows = this.metrics()?.rows;
    if (!rows?.total) return '';
    return this.i18n.t('models.evidence.rows', {
      total: rows.total.toLocaleString(this.i18n.locale()),
      train: (rows.train ?? 0).toLocaleString(this.i18n.locale()),
      test: (rows.test ?? 0).toLocaleString(this.i18n.locale()),
    });
  }

  /** ROC is the one curve worth filling: the area under it *is* the metric. */
  protected rocArea(): string {
    const path = this.rocPath();
    if (!path) return '';
    return `${path} L${CHART.width},${CHART.height} L0,${CHART.height} Z`;
  }

  protected baselineY(): number | null {
    const baseline = this.metrics()?.curves?.baseline;
    if (baseline === null || baseline === undefined || !Number.isFinite(baseline)) {
      return null;
    }
    return CHART.height - baseline * CHART.height;
  }

  protected cellShade(share: number, correct: boolean): string {
    const alpha = Math.min(0.42, Math.max(0, share) * 0.42);
    if (!alpha) return 'rgba(255,255,255,0.02)';
    return correct
      ? `rgba(52, 211, 153, ${alpha.toFixed(3)})`
      : `rgba(239, 90, 111, ${alpha.toFixed(3)})`;
  }

  protected cellTitle(actual: string, predicted: string, share: number): string {
    return `${this.i18n.t('models.evidence.confusion.actual')} ${actual} → ${this.i18n.t(
      'models.evidence.confusion.predicted',
    )} ${predicted} · ${this.percent(share)}`;
  }

  protected percent(share: number): string {
    return `${(share * 100).toLocaleString(this.i18n.locale(), {
      maximumFractionDigits: 1,
    })}%`;
  }

  protected cvSummary(folds: CvBlock): string {
    return this.i18n.t('models.evidence.cv.summary', {
      mean: this.formatMetric(folds.metric, folds.mean),
      folds: folds.folds,
      std: this.formatMetric(folds.metric, folds.std),
    });
  }

  protected rangeOf(field: SignatureField): string {
    if (field.kind === 'number' && field.min !== null && field.min !== undefined) {
      return `${this.number(field.min)} → ${this.number(field.max)}`;
    }
    if (field.choices?.length) {
      const shown = field.choices.slice(0, 4).join(', ');
      return field.choices.length > 4 ? `${shown}, …` : shown;
    }
    return '—';
  }

  protected defaultOf(field: SignatureField): string {
    const value = field.default;
    if (value === null || value === undefined) return '—';
    return typeof value === 'number' ? this.number(value) : String(value);
  }

  protected outputLine(): string {
    const output = this.model()?.signature?.output;
    if (!output?.task) return '—';
    if (output.task === 'classification') {
      return this.i18n.t('models.contract.output.classification', {
        classes: (output.classes ?? []).join(', ') || '—',
      });
    }
    return this.i18n.t('models.contract.output.regression', {
      target: output.target ?? this.model()?.target ?? '—',
    });
  }

  protected example(): string {
    const rows = this.model()?.input_example ?? [];
    if (!rows.length) return '';
    return JSON.stringify(rows[0], null, 2);
  }

  protected versionLine(version: ModelDto): string {
    const trained = version.trained_at
      ? this.i18n.t('models.versions.trained', {
          date: new Date(version.trained_at).toLocaleDateString(this.i18n.locale()),
        })
      : this.i18n.t('models.status.' + version.status);
    return `${this.i18n.t('models.algo.' + version.algo)} · ${trained}`;
  }

  protected scoreOf(
    model: ModelDto,
  ): { key: string; display: string; tone: MetricTone } | null {
    const score = primaryScore(model);
    if (!score) return null;
    return {
      key: score.key,
      display: formatMetric(score.key, score.value, this.i18n.locale()),
      tone: metricTone(score.key, score.value),
    };
  }

  /** What a delta is measured against, said once instead of on every tile. */
  protected deltaTitle(): string {
    const earlier = this.against();
    if (!earlier) return '';
    return this.i18n.t('models.evidence.delta.against', { version: earlier.version });
  }

  protected sides(): {
    id: string;
    role: 'before' | 'after';
    version: number;
    name: string;
    line: string;
  }[] {
    const earlier = this.against();
    const current = this.model();
    if (!earlier || !current) return [];
    return [
      {
        id: earlier.id,
        role: 'before' as const,
        version: earlier.version,
        name: earlier.name,
        line: this.versionLine(earlier),
      },
      {
        id: current.id,
        role: 'after' as const,
        version: current.version,
        name: current.name,
        line: this.versionLine(current),
      },
    ];
  }

  /**
   * The comparison in one sentence, on the metric the task is judged by.
   *
   * A table of six deltas states facts; the room wants to know whether the
   * retrain was worth keeping, which is a claim about one number.
   */
  protected verdict(): string {
    const current = this.model();
    const earlier = this.against();
    if (!current || !earlier) return '';
    const score = primaryScore(current);
    if (!score) return '';
    const before = (earlier.metrics?.scores ?? []).find((row) => row.key === score.key);
    const delta = metricDelta(
      score.key,
      score.value,
      before?.value,
      this.i18n.locale(),
    );
    if (!delta) return '';
    const key = delta.flat
      ? 'models.compare.verdict.flat'
      : delta.better
        ? 'models.compare.verdict.better'
        : 'models.compare.verdict.worse';
    return this.i18n.t(key, {
      metric: this.i18n.t('models.metric.' + score.key),
      delta: delta.display,
      version: current.version,
      previous: earlier.version,
    });
  }

  /** Publishing a lineage changes the row, so the card re-reads it. */
  protected reload(): void {
    void this.load();
  }

  /** The failure named in the product's own words, not the harness's. */
  protected errorSentence(): string {
    const { code, detail } = splitError(this.model()?.error);
    const key = trainingErrorKey(code);
    return key ? this.i18n.t(key) : detail || this.i18n.t('models.detail.error.title');
  }

  /** The harness's own last line, kept because it is what a fix starts from. */
  protected errorDetail(): string {
    const { code, detail } = splitError(this.model()?.error);
    return trainingErrorKey(code) ? detail : '';
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

  protected async promote(): Promise<void> {
    const row = this.model();
    if (!row) return;
    try {
      await this.models.promote(row.id);
      this.toast.success(
        this.i18n.t('models.detail.promoted', { name: row.name, version: row.version }),
      );
      await this.load();
    } catch {
      this.toast.error(this.i18n.t('models.studio.failed'));
    }
  }

  protected async cancel(): Promise<void> {
    const row = this.model();
    if (!row) return;
    await this.models.cancel(row.id);
    this.toast.info(this.i18n.t('models.detail.cancelled'));
    await this.load();
  }

  protected retrain(): void {
    this.studioOpen.set(true);
  }

  protected onRetrained(model: ModelDto): void {
    this.studioOpen.set(false);
    void this.router.navigate(['/models', model.id]);
  }

  protected async remove(): Promise<void> {
    const row = this.model();
    if (!row) return;
    const confirmed = confirm(
      this.i18n.t('models.detail.delete_confirm', {
        name: row.name,
        version: row.version,
      }),
    );
    if (!confirmed) return;
    await this.models.remove(row.id);
    this.toast.success(this.i18n.t('models.detail.deleted', { name: row.name }));
    void this.router.navigate(['/models']);
  }

  private number(value: unknown): string {
    const raw = Number(value);
    if (!Number.isFinite(raw)) return '—';
    return raw.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 });
  }

  private async load(): Promise<void> {
    if (!this.modelId) return;
    this.loading.set(true);
    try {
      const detail = await this.models.detail(this.modelId);
      this.detail.set(detail);
      this.serving.set(detail.serving ?? null);
      this.syncPolling();
    } catch {
      this.detail.set(null);
      this.serving.set(null);
    } finally {
      this.loading.set(false);
    }
  }

  private syncPolling(): void {
    const row = this.model();
    if (row && isModelActive(row)) {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(() => void this.load(), POLL_INTERVAL_MS);
    } else {
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}
