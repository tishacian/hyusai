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
import { HttpErrorResponse } from '@angular/common/http';
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
import { BarListComponent } from '@app/features/data/viz/bar-list.component';
import { ConfusionMatrixComponent } from '@app/features/data/viz/confusion-matrix.component';
import {
  CurveChartComponent,
  type CurveReference,
} from '@app/features/data/viz/curve-chart.component';
import {
  confusionView,
  curveDomain,
  type ConfusionCell,
  type CurvePoint,
  type VizBar,
} from '@app/features/data/viz/viz.vm';
import {
  balanceBars,
  comparisonPair,
  comparisonRows,
  compareErrorKey,
  formatMetric,
  higherIsBetter,
  importanceBars,
  metricDelta,
  metricTone,
  previousVersion,
  primaryScore,
  splitError,
  trainStepKey,
  trainingErrorKey,
  type ComparisonDto,
  type ComparisonMetricRow,
  type ComparisonRow,
  type CvBlock,
  type MetricTone,
  type ModelDto,
  type ServingBlock,
  type SignatureField,
} from './models.vm';

const POLL_INTERVAL_MS = 1500;

/** The shape every chart on this page shares. A ROC squashed flat lies. */
const CHART_ASPECT = 300 / 190;

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
    BarListComponent,
    ConfusionMatrixComponent,
    CurveChartComponent,
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
          <!-- Which version this page is. Every other version of the lineage
               shares this page's title, so without it the reader has to open the
               Versions tab to learn whether they are looking at the one that
               serves. -->
          <span class="ck-badge ck-mono" data-testid="hero-version">
            {{ i18n.t('models.versions.label', { version: row.version }) }}
          </span>
          @if (row.is_champion) {
            <span class="ck-badge ck-badge--champion ck-mono">
              <app-icon name="crown" [size]="10" /> {{ i18n.t('models.detail.serving') }}
            </span>
          } @else if (row.id === challengerId()) {
            <!-- The other half of champion/challenger, and the same fact the
                 registry alias records: this is what promotion would serve. -->
            <span
              class="ck-badge ck-badge--challenger ck-mono"
              [title]="i18n.t('models.detail.challenger_hint')"
            >
              <app-icon name="medal" [size]="10" />
              {{ i18n.t('models.detail.challenger') }}
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
                @if (roc().length) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.roc') }}</div>
                    <ck-curve-chart
                      [points]="roc()"
                      [aspect]="chart"
                      [reference]="DIAGONAL"
                      [fill]="true"
                      [label]="i18n.t('models.evidence.roc')"
                      [xLabel]="i18n.t('models.evidence.roc.x')"
                      [yLabel]="i18n.t('models.evidence.roc.y')"
                      [pointLabel]="describeRoc"
                    />
                    <div class="ck-hint">{{ i18n.t('models.evidence.roc.hint') }}</div>
                  </section>
                }
                @if (pr().length) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.pr') }}</div>
                    <ck-curve-chart
                      [points]="pr()"
                      [aspect]="chart"
                      [reference]="prevalence()"
                      tone="violet"
                      [label]="i18n.t('models.evidence.pr')"
                      [xLabel]="i18n.t('models.evidence.pr.x')"
                      [yLabel]="i18n.t('models.evidence.pr.y')"
                      [pointLabel]="describePr"
                    />
                    <div class="ck-hint">{{ i18n.t('models.evidence.pr.hint') }}</div>
                  </section>
                }
                @if (fit().length) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.fit') }}</div>
                    <ck-curve-chart
                      [points]="fit()"
                      [aspect]="chart"
                      [domain]="fitDomain()"
                      [reference]="identity()"
                      [label]="i18n.t('models.evidence.fit')"
                      [xLabel]="i18n.t('models.evidence.fit.x')"
                      [yLabel]="i18n.t('models.evidence.fit.y')"
                      [pointLabel]="describeFit"
                    />
                    <div class="ck-hint">{{ i18n.t('models.evidence.fit.hint') }}</div>
                  </section>
                }
                @if (confusion()) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.confusion') }}</div>
                    <ck-confusion-matrix
                      [view]="confusion()"
                      [label]="i18n.t('models.evidence.confusion')"
                      [actualLabel]="i18n.t('models.evidence.confusion.actual')"
                      [predictedLabel]="i18n.t('models.evidence.confusion.predicted')"
                      [format]="countFormat"
                      [describe]="cellDescription"
                    />
                    <div class="ck-hint">{{ i18n.t('models.evidence.confusion.hint') }}</div>
                  </section>
                }
                @if (balance().length) {
                  <section class="ck-chart">
                    <div class="ck-section-label">{{ i18n.t('models.evidence.balance') }}</div>
                    <ck-bar-list [bars]="balanceBars()" />
                    <div class="ck-hint">{{ i18n.t('models.evidence.balance.hint') }}</div>
                  </section>
                }
              </div>

              @if (importances().length) {
                <section>
                  <div class="ck-section-label">{{ i18n.t('models.evidence.importances') }}</div>
                  <ck-bar-list [bars]="importanceBars()" />
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

              <!-- Same rows: skore's joint table, on request -->
              <section class="pt-1">
                <div class="ck-section-label">{{ i18n.t('models.compare.same.title') }}</div>
                <div class="ck-hint">{{ i18n.t('models.compare.same.hint') }}</div>
                @if (!sameRows()) {
                  <button
                    type="button"
                    class="ck-btn-primary inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium mt-2"
                    [disabled]="scoring()"
                    (click)="scoreOnTheSameRows()"
                  >
                    <app-icon name="scale" [size]="14" />
                    {{
                      scoring()
                        ? i18n.t('models.compare.same.running')
                        : i18n.t('models.compare.same.action')
                    }}
                  </button>
                } @else if (sameRows(); as joint) {
                  <div class="mt-2 space-y-2">
                    <div class="text-[11px] ck-mono" style="color: var(--ck-fg-3)">
                      {{
                        i18n.t('models.compare.same.provenance', {
                          rows: joint.split.rows,
                          dataset: joint.dataset.name,
                          version: joint.dataset.version,
                        })
                      }}
                    </div>
                    @for (caveat of joint.warnings; track caveat.code + caveat.model_id) {
                      <div
                        class="text-[11px] ck-mono"
                        style="color: var(--ck-signal-warn)"
                      >
                        {{ i18n.t('models.compare.same.warn.' + caveat.code) }}
                      </div>
                    }
                    <div class="ck-surface rounded-md overflow-hidden">
                      <table class="w-full text-sm ck-schema">
                        <thead>
                          <tr>
                            <th class="ck-schema__th">
                              {{ i18n.t('models.compare.metric') }}
                            </th>
                            @for (side of joint.models; track side.model_id) {
                              <th class="ck-schema__th">
                                {{
                                  i18n.t('models.versions.label', {
                                    version: side.version,
                                  })
                                }}
                              </th>
                            }
                          </tr>
                        </thead>
                        <tbody>
                          @for (line of joint.metrics; track line.key) {
                            <tr class="ck-schema__tr">
                              <td
                                class="ck-schema__td"
                                [title]="i18n.t('models.metric.' + line.key + '.hint')"
                              >
                                {{ i18n.t('models.metric.' + line.key) }}
                              </td>
                              @for (side of joint.models; track side.model_id) {
                                <td
                                  class="ck-schema__td ck-mono"
                                  [class.ck-versus__win]="
                                    sameRowsWinner(line, side.model_id)
                                  "
                                >
                                  {{ sameRowsCell(line, side.model_id) }}
                                </td>
                              }
                            </tr>
                          }
                        </tbody>
                      </table>
                    </div>
                  </div>
                }
              </section>
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
            <!-- The lineage as one line, oldest to newest. The list below says
                 the same thing in more words; this says it in a shape, which is
                 what makes "v3 is the third attempt and it is the one serving"
                 legible without reading three rows. -->
            @if (lineage().length > 1) {
              <ol class="ck-lineage" data-testid="lineage-chain">
                @for (link of lineage(); track link.id) {
                  <li class="ck-lineage__item">
                    <a
                      [routerLink]="['/models', link.id]"
                      class="ck-lineage__link"
                      [attr.data-current]="link.current"
                      [attr.data-champion]="link.champion"
                      [title]="link.hint"
                    >
                      @if (link.champion) {
                        <app-icon name="crown" [size]="9" />
                      }
                      {{ i18n.t('models.versions.label', { version: link.version }) }}
                      @if (link.score) {
                        <em>{{ link.score }}</em>
                      }
                    </a>
                  </li>
                }
              </ol>
            }
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
                    } @else if (version.id === challengerId()) {
                      <span class="ck-badge ck-badge--challenger ck-mono">
                        <app-icon name="medal" [size]="9" />
                        {{ i18n.t('models.versions.challenger') }}
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
      /* The lineage as a chain. The arrows are drawn with ::after rather than
         put in the markup so they are not read out as content — a screen reader
         announcing "v1 arrow v2 arrow v3" is worse than reading three links. */
      .ck-lineage {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0;
        margin: 0 0 4px;
        padding: 0;
        list-style: none;
      }
      .ck-lineage__item:not(:last-child)::after {
        content: '→';
        margin: 0 6px;
        color: var(--ck-fg-4, #8891a0);
        font-size: 11px;
      }
      .ck-lineage__item {
        display: flex;
        align-items: center;
      }
      .ck-lineage__link {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 8px;
        border-radius: 999px;
        font: 10.5px / 1 var(--ck-font-mono, monospace);
        color: var(--ck-fg-3, #a6aebc);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        transition:
          color var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease),
          box-shadow var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-lineage__link em {
        font-style: normal;
        font-variant-numeric: tabular-nums;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-lineage__link:hover {
        color: var(--ck-fg-1, #e6e9ee);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-3, rgba(255, 255, 255, 0.16));
      }
      /* The version being read is filled; the one that serves is outlined. Two
         different facts, so two different cues rather than two shades of one. */
      .ck-lineage__link[data-current='true'] {
        color: var(--ck-fg-1, #e6e9ee);
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.06));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-3, rgba(255, 255, 255, 0.18));
      }
      .ck-lineage__link[data-champion='true'] {
        color: var(--ck-signal-pos, #4ade80);
        box-shadow: inset 0 0 0 1px
          color-mix(in srgb, var(--ck-signal-pos, #4ade80) 45%, transparent);
      }
      .ck-lineage__link:focus-visible {
        outline: 2px solid var(--ck-signal-cool, #7dd3fc);
        outline-offset: 1px;
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
      /* Deliberately cooler than the champion's green: a contender, not a peer. */
      .ck-badge--challenger {
        color: var(--ck-signal-warm, #fbbf24);
        background: rgba(251, 191, 36, 0.1);
        box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.28);
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

  protected readonly chart = CHART_ASPECT;

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
  /**
   * skore's joint table, once asked for.
   *
   * Not loaded with the card: it re-scores two pipelines over a test split, so
   * it costs a model load and a pass over the rows. The recorded-vs-recorded
   * table above it is free and already on screen.
   */
  protected readonly sameRows = signal<ComparisonDto | null>(null);
  protected readonly scoring = signal(false);

  private modelId = '';
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  protected readonly model = computed(() => this.detail()?.model ?? null);
  protected readonly dataset = computed(() => this.detail()?.dataset ?? null);
  protected readonly versions = computed(() => this.detail()?.versions ?? []);
  /** Named by the API, because the registry alias is derived from the same rule. */
  protected readonly challengerId = computed(
    () => this.detail()?.challenger_id ?? null,
  );
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

  /**
   * The pair the comparison tab weighs, which is not always this one and the
   * one below it: see `comparisonPair`. Kept apart from `against` because the
   * delta beside a score is a claim about a retrain, and v1 did not have one.
   */
  protected readonly pair = computed(() => comparisonPair(this.model(), this.versions()));

  protected readonly comparison = computed<ComparisonRow[]>(() => {
    const pair = this.pair();
    return pair ? comparisonRows(pair.before, pair.after, this.i18n.locale()) : [];
  });

  protected readonly confusion = computed(() => confusionView(this.metrics()?.confusion));
  protected readonly importances = computed(() => importanceBars(this.metrics()?.importances));
  protected readonly balance = computed(() => balanceBars(this.metrics()?.target?.balance));

  /**
   * The two bar blocks, adapted to the kit's shape.
   *
   * The number's *formatting* is the only thing the kit cannot decide: it needs
   * a locale, and a component that draws rectangles has no business holding one.
   * The widths were already computed against the set by `importanceBars` and
   * `balanceBars`, which is where scaling belongs.
   */
  protected readonly importanceBars = computed<VizBar[]>(() =>
    this.importances().map((bar) => ({
      label: bar.feature,
      display: bar.value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 4 }),
      width: bar.width,
      negative: bar.negative,
      emphasis: false,
    })),
  );

  protected readonly balanceBars = computed<VizBar[]>(() => {
    const bars = this.balance();
    // The majority class is the one an accuracy figure hides behind, so it is
    // the one drawn loud: 82% on a 4% churn rate should look like what it is.
    const largest = Math.max(...bars.map((bar) => bar.share), 0);
    return bars.map((bar) => ({
      label: bar.label,
      display: `${bar.count.toLocaleString(this.i18n.locale())} · ${this.percent(bar.share)}`,
      width: bar.width,
      negative: false,
      emphasis: bars.length > 1 && bar.share === largest,
    }));
  });

  /** A ROC is judged against a coin flip; the diagonal never changes. */
  protected readonly DIAGONAL: CurveReference = { kind: 'diagonal' };

  protected readonly roc = computed(() => this.metrics()?.curves?.roc ?? []);
  protected readonly pr = computed(() => this.metrics()?.curves?.pr ?? []);
  protected readonly fit = computed(() => this.metrics()?.curves?.fit ?? []);

  /**
   * A precision/recall curve is judged against prevalence, not against 0.5.
   *
   * Without this line an imbalanced problem looks solved: a 4% churn rate makes
   * any precision above 0.04 an improvement, and the curve alone does not say
   * where that floor is.
   */
  protected readonly prevalence = computed<CurveReference>(() => ({
    kind: 'level',
    value: this.metrics()?.curves?.baseline ?? null,
  }));

  /** A regression fit is judged against the line where prediction equals truth. */
  protected readonly identity = computed<CurveReference>(() => ({
    kind: 'series',
    points: this.metrics()?.curves?.ideal ?? [],
  }));
  protected readonly cv = computed(() => this.metrics()?.cv ?? null);
  protected readonly dropped = computed(() => this.metrics()?.columns?.dropped ?? []);
  protected readonly fields = computed<SignatureField[]>(
    () => this.model()?.signature?.inputs ?? [],
  );

  /** The fit and its ideal share one domain, or they cannot be read together. */
  protected readonly fitDomain = computed(() =>
    curveDomain([this.metrics()?.curves?.fit ?? [], this.metrics()?.curves?.ideal ?? []]),
  );

  /**
   * What a hovered point on each curve is called.
   *
   * Bound as fields rather than methods so the identity is stable: an arrow
   * created in the template would be a new function on every change detection
   * pass, and chart.js rebuilds its tooltip when its options change.
   *
   * The sentences are the reason the curves moved to a canvas. "TPR 0,82 at FPR
   * 0,11" is an operating point a room can argue about — catch 82% of churners
   * and bother 11% of the loyal ones — where a bare pair of coordinates is
   * something a reader has to translate first.
   */
  protected readonly describeRoc = (point: CurvePoint): string =>
    this.i18n.t('models.evidence.roc.point', {
      tpr: this.rate(point.y),
      fpr: this.rate(point.x),
    });

  protected readonly describePr = (point: CurvePoint): string =>
    this.i18n.t('models.evidence.pr.point', {
      precision: this.rate(point.y),
      recall: this.rate(point.x),
    });

  protected readonly describeFit = (point: CurvePoint): string =>
    this.i18n.t('models.evidence.fit.point', {
      predicted: this.amount(point.y),
      actual: this.amount(point.x),
    });

  /** A rate in the reader's locale, to three decimals but without the padding. */
  private rate(value: number): string {
    return value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 });
  }

  /** A value on the target's own scale: an ARPU of 1 284 is not "1284". */
  private amount(value: number): string {
    return value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 2 });
  }

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
    const evaluation = row.metrics?.report;
    if (evaluation?.bytes) {
      // Says the evaluation itself was kept, not just its summary: the split and
      // the predictions behind every number on this card are still on disk.
      entries.push({
        label: this.i18n.t('models.setup.evaluation'),
        value: this.i18n.t('models.setup.evaluation.value', {
          size: formatBytes(evaluation.bytes, this.i18n.locale()),
          skore: evaluation.skore ?? '',
        }),
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

  /**
   * Cell text and tooltip, passed to the matrix as functions.
   *
   * Bound fields rather than methods: `[format]` is an input, and a method
   * reference would be a new closure on every change detection pass, which
   * re-renders the whole grid for nothing.
   */
  protected readonly countFormat = (count: number): string =>
    count.toLocaleString(this.i18n.locale());

  protected readonly cellDescription = (cell: ConfusionCell): string =>
    `${this.i18n.t('models.evidence.confusion.actual')} ${cell.actual} → ${this.i18n.t(
      'models.evidence.confusion.predicted',
    )} ${cell.predicted} · ${this.percent(cell.share)}`;

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

  /**
   * The lineage oldest-first, as links carrying their own verdict.
   *
   * Oldest-first even though the list below is newest-first, because a chain is
   * read as a progression and a progression runs forwards: `v1 → v2 → v3` says
   * the work improved, and the same three reversed says nothing at all.
   */
  protected readonly lineage = computed(() => {
    const current = this.model()?.id;
    return [...this.versions()]
      .sort((left, right) => left.version - right.version)
      .map((version) => {
        const score = this.scoreOf(version);
        return {
          id: version.id,
          version: version.version,
          champion: version.is_champion,
          current: version.id === current,
          score: score?.display ?? '',
          hint: this.versionLine(version),
        };
      });
  });

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
    const pair = this.pair();
    if (!pair) return [];
    return [
      {
        id: pair.before.id,
        role: 'before' as const,
        version: pair.before.version,
        name: pair.before.name,
        line: this.versionLine(pair.before),
      },
      {
        id: pair.after.id,
        role: 'after' as const,
        version: pair.after.version,
        name: pair.after.name,
        line: this.versionLine(pair.after),
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
    const pair = this.pair();
    if (!pair) return '';
    const score = primaryScore(pair.after);
    if (!score) return '';
    const before = (pair.before.metrics?.scores ?? []).find((row) => row.key === score.key);
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
      version: pair.after.version,
      previous: pair.before.version,
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

  /** Re-score both versions over one split, and render skore's joint table. */
  protected async scoreOnTheSameRows(): Promise<void> {
    const pair = this.pair();
    if (!pair) return;
    this.scoring.set(true);
    try {
      // The route reads `against` as the left column, so the pair's order is
      // the table's order on both the recorded and the re-scored tables.
      this.sameRows.set(await this.models.comparison(pair.after.id, pair.before.id));
    } catch (error) {
      // The refusals are coded and each one names what does not line up, so the
      // code is worth translating rather than replacing with "failed".
      this.toast.error(this.compareFailure(error));
    } finally {
      this.scoring.set(false);
    }
  }

  /** A coded comparison refusal in the product's words, or the server's own. */
  private compareFailure(error: unknown): string {
    const detail =
      error instanceof HttpErrorResponse
        ? (error.error?.detail ?? error.error)
        : null;
    const code = typeof detail === 'object' && detail ? String(detail.code ?? '') : '';
    const key = compareErrorKey(code);
    if (key) return this.i18n.t(key);
    const message =
      typeof detail === 'object' && detail ? String(detail.message ?? '') : '';
    return message || this.i18n.t('models.compare.failed');
  }

  /** One cell of skore's table: keyed by model id, formatted in its own unit. */
  protected sameRowsCell(row: ComparisonMetricRow, modelId: string): string {
    const value = row[modelId];
    return formatMetric(
      row.key,
      typeof value === 'number' ? value : null,
      this.i18n.locale(),
    );
  }

  /** Which side of skore's table won a metric, for the highlight. */
  protected sameRowsWinner(row: ComparisonMetricRow, modelId: string): boolean {
    const table = this.sameRows();
    if (!table) return false;
    const values = table.models
      .map((side) => row[side.model_id])
      .filter((value): value is number => typeof value === 'number');
    if (values.length < 2) return false;
    const mine = row[modelId];
    if (typeof mine !== 'number') return false;
    const best = higherIsBetter(row.key)
      ? Math.max(...values)
      : Math.min(...values);
    return mine === best && values[0] !== values[1];
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
