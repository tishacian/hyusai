/**
 * `<app-flow-train-workshop>` — the authoring surface of a training node.
 *
 * Opened from the inspector for the SELECTED `ml_train_sklearn_v1` node. Every
 * edit writes through the store's dotted-path config writers, so the target, the
 * feature set, the estimator and the split are versioned with the flow like any
 * other node config — and reviewable in the semantic diff.
 *
 * Why this node gets a workshop and the serving nodes do not
 * ----------------------------------------------------------
 * A fit is *authored*. What to predict, from which columns, with which
 * estimator, against how large a test split: those are four decisions, they
 * interact, and each one is worth a preview. Picking which model answers is one
 * dropdown, and a dialog for one dropdown is ceremony. So the shapes differ on
 * purpose, and `SERVING_ROLES` in `flow-ml.vm.ts` carries that difference as
 * data rather than as a branch here.
 *
 * The layout is the transform workshop's, transposed: the *spec* on top where
 * the program would be, the *evidence* underneath where the result table would
 * be, the catalog on the side. Same chrome, because switching from authoring a
 * statement to authoring a fit should feel like changing subject, not tool.
 *
 *  - **Spec** — target, task, features, estimator, knobs, split, folds. Nothing
 *    here is typed free-hand: `POST /ml-models/plan` answers what each choice
 *    implies on every edit, so the target list only offers columns that can be
 *    predicted, the task arrives inferred from the column's type, and a column
 *    unique per row is flagged as memorisation before anything is fitted.
 *  - **Evidence** — the live check-list while the fit runs, then the scores it
 *    earned, each against what the previous version of the lineage scored. A
 *    number without a move is not evidence a retrain was worth it.
 *  - **Dataset** — which table this node fits on, pinned by slug so it follows
 *    the latest version; unpinned, the node reads whatever the wire hands it.
 *  - **Output** — the lineage name each run versions.
 *
 * One honesty note the copy carries too: unlike a transform preview, a fit
 * cannot be a dry run. The artifact *is* the product, so "Train" registers a
 * real version, and the panel says which one it registered and links to it.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  output,
  signal,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { DataTableComponent } from '@app/shared/ui/data-table.component';
import type {
  TabularColumn,
  TabularColumnStats,
} from '@app/shared/ui/data-table.vm';
import { DatasetPreviewComponent } from '@app/features/data/dataset-preview.component';
import { I18nService } from '@app/core/i18n.service';
import {
  algoFor,
  algoIcon,
  algosForTask,
  clampKnob,
  defaultKnobs,
  knobIsAuto,
  formatMetric,
  metricDelta,
  metricTone,
  previousVersion,
  primaryScore,
  refusalField,
  refusalKey,
  planColumnStats,
  planColumnsAsTable,
  targetCandidates,
  taskIcon,
  trainChecklist,
  warningKey,
  numericKnobs,
  trainableTasks,
  type AlgoDescriptor,
  type NumericKnobDescriptor,
  type ModelTask,
} from '@app/features/models/models.vm';
import { FlowStore } from './flow.store';
import { FlowMlService } from './flow-ml.service';
import {
  TRAIN_CV_OPTIONS,
  clampFolds,
  clampTestSize,
  isTrainNode,
  pinnedDataset,
  preflightTrain,
  readTrainParams,
  type MlFailure,
  type TrainNodeParams,
} from './flow-ml.vm';

type WorkshopTab = 'dataset' | 'test' | 'output';

/** How long the form waits before asking the server what a choice implies. */
const PLAN_DEBOUNCE_MS = 240;
/** Scores the evidence panel shows; the rest live on the model card. */
const SCORE_LIMIT = 4;

import { ForecastSpecComponent } from '@app/features/models/forecast-spec.component';
import { TabularOptionsComponent } from '@app/features/models/tabular-options.component';
import { tabularFields, tabularSpec } from '@app/features/models/tabular-options.vm';
import {
  FORECASTING_TASK,
  draftFromSpec,
  forecastSpec,
  withTimeColumn,
  type ForecastDraft,
} from '@app/features/models/forecast.vm';

@Component({
  selector: 'app-flow-train-workshop',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    A11yModule,
    DataTableComponent,
    DatasetPreviewComponent,
    NavLinkDirective,
    IconComponent,
    ForecastSpecComponent,
    TabularOptionsComponent,
  ],
  styleUrl: './flow-train-workshop.component.scss',
  template: `
    <div
      class="ck-train-workshop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ck-train-workshop-title"
      cdkTrapFocus
      [cdkTrapFocusAutoCapture]="true"
      (keydown.escape)="close.emit()"
    >
      <div class="ck-train-workshop__backdrop" (click)="close.emit()"></div>
      <section class="ck-train-workshop__panel">
        <header class="ck-train-workshop__head">
          <div class="ck-train-workshop__identity">
            <span class="ck-train-workshop__badge">
              <app-icon name="brain" [size]="15" />
            </span>
            <div>
              <h2 id="ck-train-workshop-title">{{ i18n.t('flow.ml.train.title') }}</h2>
              <p>{{ node()?.label || node()?.id }}</p>
            </div>
          </div>
          <div class="ck-train-workshop__head-actions">
            @if (ml.busy() && current(); as step) {
              <span class="ck-train-workshop__phase" data-testid="train-phase">
                <app-icon name="loader-2" [size]="12" />
                {{ i18n.t(step.key, step.params) }}
              </span>
            }
            @if (cancellable()) {
              <button
                type="button"
                class="ck-train-workshop__action"
                data-testid="cancel-train-run"
                (click)="ml.cancel()"
              >
                <app-icon name="x" [size]="13" />
                {{ i18n.t('flow.ml.train.cancel') }}
              </button>
            }
            <button
              type="button"
              class="ck-train-workshop__action ck-train-workshop__action--primary"
              data-testid="run-train-test"
              [disabled]="ml.busy()"
              (click)="runTest()"
            >
              <app-icon [name]="ml.busy() ? 'loader-2' : 'play'" [size]="13" />
              {{ ml.busy() ? i18n.t('flow.ml.train.busy') : i18n.t('flow.ml.train.run') }}
            </button>
            <button
              type="button"
              class="ck-train-workshop__close"
              (click)="close.emit()"
              [attr.aria-label]="i18n.t('flow.ml.train.close')"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </div>
        </header>

        @if (node()) {
          <div class="ck-train-workshop__body">
            <div class="ck-train-workshop__main">
              <div class="ck-train-workshop__spec">
                <!-- ── What to predict ─────────────────────────────────── -->
                <section class="ck-train-workshop__col">
                  <div class="ck-train-workshop__field">
                    <span class="ck-train-workshop__label">
                      {{ i18n.t('flow.ml.train.target') }}
                    </span>
                    <p class="ck-train-workshop__hint">
                      {{ i18n.t('flow.ml.train.target.hint') }}
                    </p>
                    @if (candidates().length) {
                      <ck-data-table
                        data-testid="train-target"
                        [columns]="targetTableColumns()"
                        [rows]="[]"
                        [stats]="targetTableStats()"
                        [showRowNumbers]="false"
                        [showShape]="false"
                        selectMode="single"
                        [selected]="params().target ? [params().target] : []"
                        maxHeight="220px"
                        (selectedChange)="onTargetPicked($event)"
                      />
                    } @else {
                      <p class="ck-train-workshop__hint" data-testid="train-no-columns">
                        {{
                          pinned()
                            ? i18n.t('flow.ml.train.target.none')
                            : i18n.t('flow.ml.train.dataset.required')
                        }}
                      </p>
                    }
                    @if (refusalFor('target'); as message) {
                      <p class="ck-train-workshop__refusal" role="alert">
                        <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                      </p>
                    }
                  </div>

                  @if (params().target) {
                    <div class="ck-train-workshop__field">
                      <span class="ck-train-workshop__label">
                        {{ i18n.t('flow.ml.train.task') }}
                      </span>
                      <div class="ck-train-workshop__seg">
                        @for (option of tasks(); track option) {
                          <button
                            type="button"
                            class="ck-train-workshop__seg-btn"
                            [class.ck-train-workshop__seg-btn--on]="effectiveTask() === option"
                            (click)="onTask(option)"
                          >
                            <app-icon [name]="taskIcon(option)" [size]="13" />
                            {{ i18n.t('models.task.' + option) }}
                          </button>
                        }
                      </div>
                      @if (!params().task && suggestedTask()) {
                        <p class="ck-train-workshop__inferred">
                          {{ i18n.t('flow.ml.train.task.suggested') }}
                        </p>
                      }
                    </div>

                    @if (isForecasting()) {
                      <ck-forecast-spec
                        part="data"
                        [draft]="forecastDraft()"
                        [columns]="columns()"
                        [target]="params().target"
                        [algo]="effectiveAlgo()"
                        [refusal]="refusalFor('spec')"
                        (draftChange)="onForecastDraft($event)"
                      />
                    } @else {
                    <div class="ck-train-workshop__field">
                      <div class="ck-train-workshop__field-head">
                        <span class="ck-train-workshop__label">
                          {{ i18n.t('flow.ml.train.features') }}
                        </span>
                        <span class="ck-train-workshop__count">
                          {{
                            i18n.t('flow.ml.train.features.count', {
                              selected: selectedFeatures().length,
                              total: featureColumns().length
                            })
                          }}
                        </span>
                        <button
                          type="button"
                          class="ck-train-workshop__mini"
                          (click)="allFeatures()"
                        >
                          {{ i18n.t('flow.ml.train.features.all') }}
                        </button>
                      </div>
                      <p class="ck-train-workshop__hint">
                        {{ i18n.t('flow.ml.train.features.hint') }}
                      </p>
                      <ck-data-table
                        data-testid="train-features"
                        [columns]="featureTableColumns()"
                        [rows]="[]"
                        [stats]="featureTableStats()"
                        [showRowNumbers]="false"
                        [showShape]="false"
                        selectMode="multi"
                        [selected]="selectedFeatures()"
                        [flagged]="flaggedFeatureNames()"
                        maxHeight="220px"
                        (selectedChange)="onFeaturesPicked($event)"
                      />
                      @if (refusalFor('features'); as message) {
                        <p class="ck-train-workshop__refusal" role="alert">
                          <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                        </p>
                      }
                    </div>
                    }
                  }
                </section>

                <!-- ── How to fit it ───────────────────────────────────── -->
                <section class="ck-train-workshop__col">
                  @if (params().target) {
                    <div class="ck-train-workshop__field">
                      <span class="ck-train-workshop__label">
                        {{ i18n.t('flow.ml.train.algo') }}
                      </span>
                      <div class="ck-train-workshop__algos" data-testid="train-algos">
                        @for (algo of availableAlgos(); track algo.key) {
                          <button
                            type="button"
                            class="ck-train-workshop__algo"
                            [class.ck-train-workshop__algo--on]="effectiveAlgo() === algo.key"
                            [attr.aria-pressed]="effectiveAlgo() === algo.key"
                            (click)="onAlgo(algo.key)"
                          >
                            <span class="ck-train-workshop__algo-head">
                              <app-icon [name]="algoIcon(algo.key)" [size]="14" />
                              {{ i18n.t('models.algo.' + algo.key) }}
                            </span>
                            <span class="ck-train-workshop__algo-hint">
                              {{ i18n.t('models.algo.' + algo.key + '.hint') }}
                            </span>
                          </button>
                        }
                      </div>
                      @if (refusalFor('algo'); as message) {
                        <p class="ck-train-workshop__refusal" role="alert">
                          <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                        </p>
                      }
                    </div>

                    @if (activeAlgo(); as algo) {
                      @if (numericKnobs(algo).length) {
                        <div class="ck-train-workshop__field">
                          <div class="ck-train-workshop__field-head">
                            <span class="ck-train-workshop__label">
                              {{ i18n.t('flow.ml.train.knobs') }}
                            </span>
                            <button
                              type="button"
                              class="ck-train-workshop__mini"
                              (click)="resetKnobs()"
                            >
                              {{ i18n.t('flow.ml.train.knobs.reset') }}
                            </button>
                          </div>
                          @for (knob of numericKnobs(algo); track knob.key) {
                            <div class="ck-train-workshop__knob">
                              <div class="ck-train-workshop__knob-head">
                                <span>{{ i18n.t('models.studio.knob.' + knob.key) }}</span>
                                <code>{{ knobLabel(knob) }}</code>
                              </div>
                              <input
                                type="range"
                                [min]="knob.min"
                                [max]="knob.max"
                                [step]="knob.step"
                                [value]="knobValue(knob)"
                                [attr.aria-label]="i18n.t('models.studio.knob.' + knob.key)"
                                (change)="onKnob(knob, $event)"
                              />
                            </div>
                          }
                        </div>
                      }
                    }

                    @if (isForecasting()) {
                      <ck-forecast-spec
                        part="fit"
                        [draft]="forecastDraft()"
                        [columns]="columns()"
                        [target]="params().target"
                        [algo]="effectiveAlgo()"
                        [horizonMax]="horizonMax()"
                        (draftChange)="onForecastDraft($event)"
                      />
                    } @else {
                    <div class="ck-train-workshop__field">
                      <div class="ck-train-workshop__knob">
                        <div class="ck-train-workshop__knob-head">
                          <span>{{ i18n.t('flow.ml.train.split') }}</span>
                          <code>{{ splitLabel() }}</code>
                        </div>
                        <input
                          type="range"
                          min="0.05"
                          max="0.5"
                          step="0.05"
                          data-testid="train-split"
                          [value]="params().test_size"
                          [attr.aria-label]="i18n.t('flow.ml.train.split')"
                          (change)="onSplit($event)"
                        />
                      </div>
                      <p class="ck-train-workshop__hint">
                        {{ i18n.t('flow.ml.train.split.hint') }}
                      </p>
                    </div>

                    <label class="ck-train-workshop__input-field">
                      <span>{{ i18n.t('flow.ml.train.cv') }}</span>
                      <select
                        data-testid="train-cv"
                        [value]="params().cross_validation"
                        (change)="onFolds($event)"
                      >
                        <option [value]="0">{{ i18n.t('flow.ml.train.cv.off') }}</option>
                        @for (folds of cvOptions; track folds) {
                          <option [value]="folds">
                            {{ i18n.t('flow.ml.train.cv.folds', { folds: folds }) }}
                          </option>
                        }
                      </select>
                    </label>
                    <p class="ck-train-workshop__hint">{{ i18n.t('flow.ml.train.cv.hint') }}</p>
                    <ck-tabular-options [fields]="tabularFields()" [spec]="params().spec" [task]="effectiveTask()" [columns]="columns()" [target]="params().target" [refusal]="refusalFor('spec')" (specChange)="onTabularSpec($event)" />
                    }
                  }
                </section>
              </div>

            </div>

            <aside class="ck-train-workshop__side">
              <div
                class="ck-train-workshop__tabs"
                role="tablist"
                [attr.aria-label]="i18n.t('flow.ml.train.tabs.aria')"
              >
                <button
                  type="button"
                  role="tab"
                  [attr.aria-selected]="tab() === 'dataset'"
                  (click)="tab.set('dataset')"
                >
                  <app-icon name="table" [size]="13" />
                  {{ i18n.t('flow.ml.train.tab.dataset') }}
                </button>
                <button
                  type="button"
                  role="tab"
                  data-testid="tab-train-test"
                  [attr.aria-selected]="tab() === 'test'"
                  (click)="tab.set('test')"
                >
                  <app-icon name="play" [size]="13" />
                  {{ i18n.t('flow.ml.train.tab.test') }}
                </button>
                <button
                  type="button"
                  role="tab"
                  [attr.aria-selected]="tab() === 'output'"
                  (click)="tab.set('output')"
                >
                  <app-icon name="git-branch" [size]="13" />
                  {{ i18n.t('flow.ml.train.tab.output') }}
                </button>
              </div>

              <div class="ck-train-workshop__tabpane">
                @switch (tab()) {
                  @case ('dataset') {
                    <p class="ck-train-workshop__hint">
                      {{ i18n.t('flow.ml.train.dataset.hint') }}
                    </p>
                    <label class="ck-train-workshop__input-field">
                      <span>{{ i18n.t('flow.ml.train.dataset') }}</span>
                      <select
                        data-testid="pin-train-dataset"
                        [value]="pinned()?.dataset_slug ?? ''"
                        [disabled]="ml.datasetsLoading()"
                        (change)="onPin($event)"
                      >
                        <option value="">
                          {{
                            ml.datasetsLoading()
                              ? i18n.t('flow.ml.train.dataset.loading')
                              : i18n.t('flow.ml.train.dataset.wire')
                          }}
                        </option>
                        @for (dataset of ml.datasets(); track dataset.slug) {
                          <option [value]="dataset.slug">
                            {{ dataset.name }} · v{{ dataset.version }}
                          </option>
                        }
                      </select>
                    </label>
                    @if (dataset(); as ds) {
                      <div class="ck-train-workshop__source" data-testid="train-source">
                        <code>{{ ds.slug }}</code>
                        <p>
                          {{
                            i18n.t('flow.ml.train.dataset.meta', {
                              rows: (ds.row_count ?? 0).toLocaleString(i18n.locale()),
                              columns: ds.column_count ?? 0
                            })
                          }}
                        </p>
                      </div>
                    }
                    @if (refusalFor('dataset'); as message) {
                      <p class="ck-train-workshop__refusal" role="alert">
                        <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                      </p>
                    }
                    @if (plan(); as preview) {
                      <span class="ck-train-workshop__label">
                        {{ i18n.t('flow.ml.train.plan') }}
                      </span>
                      <div class="ck-train-workshop__plan" data-testid="train-plan">
                        <span>
                          <app-icon [name]="taskIcon(preview.task)" [size]="11" />
                          {{ i18n.t('models.task.' + preview.task) }}
                        </span>
                        <code>{{ preview.estimator }}</code>
                        <span>
                          @if (isForecasting()) {
                            {{
                              i18n.t('models.studio.plan.forecast', {
                                horizon: forecastDraft().horizon,
                                folds: forecastDraft().folds
                              })
                            }}
                          } @else {
                            {{
                              i18n.t('flow.ml.train.plan.rows', {
                                rows: preview.rows.toLocaleString(i18n.locale()),
                                test: testRows().toLocaleString(i18n.locale())
                              })
                            }}
                          }
                        </span>
                        <span>
                          {{
                            i18n.t('flow.ml.train.plan.features', {
                              count: preview.features.length
                            })
                          }}
                        </span>
                      </div>
                      @for (warning of preview.warnings; track $index) {
                        <p class="ck-train-workshop__warning">
                          <app-icon name="alert-triangle" [size]="12" />
                          {{ warningMessage(warning) }}
                        </p>
                      }
                    } @else if (refusalUnplaced(); as message) {
                      <p class="ck-train-workshop__refusal" role="alert">
                        <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                      </p>
                    }
                  }

                  @case ('test') {
                    <div class="ck-train-workshop__evidence">
                      @if (failure(); as reason) {
                        <p
                          class="ck-train-workshop__error"
                          role="alert"
                          data-testid="train-failure"
                        >
                          {{ i18n.t(reason.key) }}
                          @if (reason.detail) {
                            <code class="ck-train-workshop__detail">{{ reason.detail }}</code>
                          }
                        </p>
                      }
                      @if (ml.busy() || ml.run()) {
                        <ol class="ck-train-workshop__steps" data-testid="train-steps">
                          @for (step of steps(); track step.step) {
                            <li [attr.data-state]="step.state">
                              <app-icon
                                [name]="
                                  step.state === 'done'
                                    ? 'check'
                                    : step.state === 'active'
                                      ? 'loader-2'
                                      : 'circle'
                                "
                                [size]="11"
                              />
                              {{ i18n.t(step.key, step.params) }}
                            </li>
                          }
                        </ol>
                      }
                      @if (settled(); as trained) {
                        <div class="ck-train-workshop__scores" data-testid="train-scores">
                          @for (score of scores(); track score.key) {
                            <div
                              class="ck-train-workshop__score"
                              [attr.data-tone]="metricTone(score.key, score.value)"
                            >
                              <span class="ck-train-workshop__score-name">
                                {{ metricName(score.key) }}
                              </span>
                              <strong>{{ formatMetric(score.key, score.value) }}</strong>
                              @if (deltaFor(score.key); as delta) {
                                <em [attr.data-better]="delta.better ? 'true' : 'false'">
                                  {{ delta.display }}
                                </em>
                              }
                            </div>
                          }
                        </div>
                        <p class="ck-train-workshop__registered" data-testid="train-registered">
                          {{
                            i18n.t('flow.ml.train.registered', {
                              name: trained.name,
                              version: trained.version
                            })
                          }}
                          <a
                            class="ck-train-workshop__mini"
                            [navLink]="{ leaf: 'model-doc', ref: trained.id }"
                          >
                            {{ i18n.t('flow.ml.train.open_card') }}
                          </a>
                        </p>
                      } @else if (!ml.busy() && !failure()) {
                        @if (dataset(); as pinnedDataset) {
                          <div class="ck-train-workshop__sample" data-testid="train-sample">
                            <span class="ck-train-workshop__label">
                              {{ i18n.t('flow.ml.train.sample') }}
                            </span>
                            <ck-dataset-preview
                              [datasetId]="pinnedDataset.id"
                              [columnsHint]="sampleColumns()"
                              [statsHint]="sampleStats()"
                              maxHeight="196px"
                            />
                          </div>
                        } @else {
                          <div class="ck-train-workshop__placeholder">
                            <app-icon name="brain" [size]="18" />
                            <p>{{ i18n.t('flow.ml.train.evidence.empty') }}</p>
                          </div>
                        }
                      }
                    </div>
                  }

                  @case ('output') {
                    <label class="ck-train-workshop__input-field">
                      <span>{{ i18n.t('flow.ml.train.name') }}</span>
                      <input
                        type="text"
                        spellcheck="false"
                        maxlength="200"
                        data-testid="train-model-name"
                        [value]="params().model_name"
                        [attr.placeholder]="namePlaceholder()"
                        (change)="onName($event)"
                      />
                    </label>
                    <p class="ck-train-workshop__hint">{{ i18n.t('flow.ml.train.name.hint') }}</p>
                    <p class="ck-train-workshop__hint">
                      {{ i18n.t('flow.ml.train.versioning') }}
                    </p>
                    <a class="ck-train-workshop__action" [navLink]="{ surface: 'models' }">
                      <app-icon name="brain" [size]="13" />
                      {{ i18n.t('flow.ml.train.open_models') }}
                    </a>
                  }
                }
              </div>
            </aside>
          </div>
        }
      </section>
    </div>
  `,
})
export class FlowTrainWorkshopComponent {
  protected readonly store = inject(FlowStore);
  protected readonly ml = inject(FlowMlService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  readonly close = output<void>();

  // The tasks of the families a worker can train right now, from the catalog.
  // The workshop renders a family's spec fields, so it offers forecasting too.
  protected readonly tasks = computed<ModelTask[]>(() =>
    trainableTasks(this.ml.catalog(), { specFields: true }),
  );
  // Only sliders render here; a knob of another kind keeps its server default.
  protected readonly numericKnobs = numericKnobs;
  protected readonly cvOptions = TRAIN_CV_OPTIONS;

  protected readonly node = this.store.selectedNode;
  protected readonly params = computed<TrainNodeParams>(() =>
    readTrainParams(this.node()),
  );
  protected readonly pinned = computed(() => pinnedDataset(this.params().sources));
  protected readonly tab = signal<WorkshopTab>('dataset');
  /** A client-side refusal shadows the server's last answer, as elsewhere. */
  protected readonly preflight = signal<MlFailure | null>(null);
  protected readonly failure = computed(() => this.preflight() ?? this.ml.failure());

  protected readonly plan = this.ml.plan;
  protected readonly columns = this.ml.columns;

  /** Only a run still in flight can be stopped. */
  protected readonly cancellable = computed(() => {
    const row = this.ml.run();
    return this.ml.busy() && !!row && !row.cancel_requested;
  });

  protected readonly dataset = computed(() => {
    const pin = this.pinned();
    if (!pin) return null;
    return (
      this.ml
        .datasets()
        .find(
          (row) => row.slug === pin.dataset_slug || row.id === pin.dataset_id,
        ) ?? null
    );
  });

  /**
   * The plan's columns, in the shape the shared table reads.
   *
   * Handing them over rather than letting the preview fetch its own schema keeps
   * one profile on screen: the sparkline on a table header and the one on the
   * feature chip beside it are then literally the same numbers.
   */
  protected readonly sampleColumns = computed<TabularColumn[]>(() =>
    this.columns().map((column) => ({
      name: column.name,
      kind: column.kind as TabularColumn['kind'],
      dtype: column.kind,
    })),
  );

  protected readonly sampleStats = computed<Record<string, TabularColumnStats>>(() => {
    const stats: Record<string, TabularColumnStats> = {};
    for (const column of this.columns()) {
      if (column.profile) stats[column.name] = column.profile;
    }
    return stats;
  });

  protected readonly candidates = computed(() =>
    targetCandidates(this.columns(), this.ml.catalog().limits.max_classes),
  );

  protected readonly targetTableColumns = computed(() =>
    planColumnsAsTable(this.candidates()),
  );

  protected readonly targetTableStats = computed(() =>
    planColumnStats(this.candidates()),
  );

  protected readonly featureTableColumns = computed(() =>
    planColumnsAsTable(this.featureColumns()),
  );

  protected readonly featureTableStats = computed(() =>
    planColumnStats(this.featureColumns()),
  );

  protected readonly flaggedFeatureNames = computed(() => [...this.flagged()]);

  protected readonly suggestedTask = computed<ModelTask | null>(
    () =>
      this.columns().find((column) => column.name === this.params().target)
        ?.suggested_task ?? null,
  );

  protected readonly effectiveTask = computed<ModelTask>(
    () =>
      this.params().task ??
      this.suggestedTask() ??
      this.ml.catalog().defaults.task ??
      'classification',
  );

  protected readonly availableAlgos = computed<AlgoDescriptor[]>(() =>
    algosForTask(this.ml.catalog(), this.effectiveTask()),
  );

  /** The node's algorithm, or the one the plan would pick if it names none. */
  protected readonly effectiveAlgo = computed(
    () => this.params().algo || this.plan()?.algo || '',
  );

  protected readonly activeAlgo = computed(() =>
    algoFor(this.ml.catalog(), this.effectiveAlgo()),
  );

  protected readonly isForecasting = computed(() => this.effectiveTask() === FORECASTING_TASK);
  protected readonly tabularFields = computed(() => tabularFields(this.ml.catalog(), this.effectiveTask()));
  protected readonly tabularSpec = computed(() => tabularSpec(this.tabularFields(), this.params().spec, this.effectiveTask()));

  /** The node's forecast spec as form fields; it lives on the node as `spec`. */
  protected readonly forecastDraft = computed<ForecastDraft>(() =>
    withTimeColumn(draftFromSpec(this.params().spec), this.columns()),
  );

  /** The ceiling the forecasting family declares for its horizon. */
  protected readonly horizonMax = computed(() => {
    const family = this.ml.catalog().families?.find((entry) => entry.key === FORECASTING_TASK);
    return family?.spec_fields.find((field) => field.key === 'horizon')?.max ?? 720;
  });

  protected readonly featureColumns = computed(() =>
    this.columns().filter((column) => column.name !== this.params().target),
  );

  /** `null` on the node means "every column but the target" — the server default. */
  protected readonly selectedFeatures = computed<string[]>(() => {
    const override = this.params().features;
    const available = this.featureColumns().map((column) => column.name);
    if (!override) return available;
    const allowed = new Set(available);
    return override.filter((feature) => allowed.has(feature));
  });

  protected readonly flagged = computed(
    () =>
      new Set(
        (this.plan()?.warnings ?? [])
          .map((warning) => warning.feature)
          .filter((feature): feature is string => !!feature),
      ),
  );

  protected readonly steps = computed(() =>
    trainChecklist(
      this.ml.run()?.status,
      this.ml.run()?.status_detail,
      // The requested fold count, not one the run reported: the validating line
      // has to be in the list before the fit reaches it, or the check-list grows
      // a step halfway through and the reader loses their place.
      this.ml.run()?.cross_validation ?? this.params().cross_validation,
      this.i18n.locale(),
      this.ml.run()?.task ?? this.effectiveTask(),
      this.ml.run()?.spec ?? this.params().spec,
    ),
  );

  /** The line the header chip names: the one the run is on. */
  protected readonly current = computed(
    () => this.steps().find((step) => step.state === 'active') ?? null,
  );

  /** The run, once it produced a model worth reading. */
  protected readonly settled = computed(() => {
    const row = this.ml.run();
    return row && row.status === 'ready' ? row : null;
  });

  protected readonly scores = computed(() => {
    const row = this.settled();
    if (!row) return [];
    const all = row.metrics?.scores ?? [];
    const primary = primaryScore(row);
    // The primary first even when the harness did not list it first: it is the
    // number this fit is judged on.
    const ranked = primary
      ? [primary, ...all.filter((score) => score.key !== primary.key)]
      : [...all];
    return ranked.slice(0, SCORE_LIMIT);
  });

  private readonly earlier = computed(() =>
    previousVersion(this.settled(), this.ml.runVersions()),
  );

  protected readonly namePlaceholder = computed(
    () => this.plan()?.name || this.i18n.t('flow.ml.train.name.placeholder'),
  );

  private planTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPlanned = '';

  constructor() {
    // The workshop exists FOR the selected training node; if it stops being one
    // (deletion, undo, external selection change) the dialog closes itself.
    effect(() => {
      if (!isTrainNode(this.node())) this.close.emit();
    });
    // The plan is the whole feedback loop, so it follows the spec rather than
    // being asked for on a button: every field that changes what a fit would be
    // is in this signature, and nothing else is.
    effect(() => {
      const params = this.params();
      const signature = JSON.stringify([
        params.sources,
        params.target,
        params.task,
        params.features,
        params.algo,
        params.spec,
      ]);
      if (signature === this.lastPlanned) return;
      this.lastPlanned = signature;
      this.schedulePlan();
    });
    void this.ml.ensureDatasets();
    void this.ml.ensureRegistry();
    this.destroyRef.onDestroy(() => this.cancelPlan());
  }

  protected taskIcon(task: ModelTask): string {
    return taskIcon(task);
  }

  protected algoIcon(algo: string): string {
    return algoIcon(algo);
  }

  protected formatMetric(key: string, value: number | null | undefined): string {
    return formatMetric(key, value, this.i18n.locale());
  }

  protected metricTone(key: string, value: number | null | undefined): string {
    return metricTone(key, value);
  }

  /** The metric's name as the model card spells it, so "AUC" is "AUC" here too. */
  protected metricName(key: string): string {
    const resolved = this.i18n.t(`models.metric.${key}`);
    return resolved === `models.metric.${key}` ? key.toUpperCase() : resolved;
  }

  /** What this fit moved, against the previous ready version of the lineage. */
  protected deltaFor(key: string) {
    const current = this.scores().find((score) => score.key === key)?.value;
    const before = this.earlier();
    if (!before) return null;
    const previous =
      before.metrics?.scores?.find((score) => score.key === key)?.value ??
      (primaryScore(before)?.key === key ? primaryScore(before)?.value : undefined);
    return metricDelta(key, current, previous, this.i18n.locale());
  }

  protected testRows(): number {
    const preview = this.plan();
    return preview ? Math.round(preview.rows * this.params().test_size) : 0;
  }

  protected knobValue(knob: NumericKnobDescriptor): number {
    const authored = this.params().knobs[knob.key];
    const planned = this.plan()?.knobs?.[knob.key];
    const raw =
      authored !== undefined
        ? authored
        : typeof planned === 'number'
          ? planned
          : knob.default;
    return clampKnob(knob, raw);
  }

  protected knobLabel(knob: NumericKnobDescriptor): string {
    const value = this.knobValue(knob);
    if (knobIsAuto(knob, value)) return this.i18n.t('models.studio.knobs.auto');
    return value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 4 });
  }

  protected splitLabel(): string {
    return `${Math.round(this.params().test_size * 100)}%`;
  }

  protected warningMessage(warning: { code: string; feature?: string; field?: string; estimated_s?: number; budget_s?: number }): string {
    const key = warningKey(warning.code);
    return key ? this.i18n.t(key, { feature: warning.feature ?? '', field: warning.field ?? '', estimated_s: warning.estimated_s ?? 0, budget_s: warning.budget_s ?? 0 }) : warning.code;
  }

  /** A plan refusal rendered against the field that caused it, or nothing. */
  protected refusalFor(field: 'target' | 'features' | 'algo' | 'dataset' | 'spec'): string | null {
    const refusal = this.ml.refusal();
    if (!refusal || refusalField(refusal.code) !== field) return null;
    const key = refusalKey(refusal.code);
    return key ? this.i18n.t(key) : refusal.message;
  }

  /** A refusal no field owns still has to be read. */
  protected refusalUnplaced(): string | null {
    const refusal = this.ml.refusal();
    if (!refusal || refusalField(refusal.code)) return null;
    const key = refusalKey(refusal.code);
    return key ? this.i18n.t(key) : refusal.message;
  }

  // -------------------------------------------------------------------------
  // Edits — each one store write, so each one is one Ctrl+Z
  // -------------------------------------------------------------------------

  protected onTargetPicked(names: string[]): void {
    this.onTarget(names[0] ?? '');
  }

  protected onFeaturesPicked(names: string[]): void {
    const available = this.featureColumns().map((column) => column.name);
    if (
      names.length === available.length &&
      available.every((name) => names.includes(name))
    ) {
      this.allFeatures();
      return;
    }
    this.writeParams({ features: names });
  }

  protected onTarget(target: string): void {
    // A new target invalidates the choices made against the old one: the task it
    // suggests and the feature set that excluded it are both stale.
    this.writeParams({ target, task: null, features: null });
  }

  protected onTask(task: ModelTask): void {
    const patch: Record<string, unknown> = { task };
    // A forecast is a question with more than a target: it starts from the
    // form's defaults, so the node is runnable before any field is touched.
    if (task === FORECASTING_TASK && !this.params().spec) {
      patch['spec'] = forecastSpec(this.forecastDraft(), this.params().algo);
    }
    // An estimator that cannot do the new task must not stay selected.
    if (!algosForTask(this.ml.catalog(), task).some((a) => a.key === this.params().algo)) {
      patch['algo'] = '';
      patch['knobs'] = {};
    }
    this.writeParams(patch);
  }

  protected onAlgo(algo: string): void {
    // The knobs belong to the estimator, so they do not survive it — and a
    // forecast's strategy only means something for a regressor.
    this.writeParams({
      algo,
      knobs: {},
      ...(this.isForecasting() ? { spec: forecastSpec(this.forecastDraft(), algo) } : {}),
    });
  }

  /** One gesture in the forecast fields, as one store write of the node's spec. */
  protected onForecastDraft(patch: Partial<ForecastDraft>): void {
    this.writeParams({ spec: forecastSpec({ ...this.forecastDraft(), ...patch }, this.effectiveAlgo()) });
  }

  protected onTabularSpec(spec: Record<string, unknown>): void {
    this.writeParams({ spec });
  }

  /** Back to the default: every column but the target, decided at run time. */
  protected allFeatures(): void {
    this.writeParams({ features: null });
  }

  protected onKnob(knob: NumericKnobDescriptor, event: Event): void {
    const value = clampKnob(knob, (event.target as HTMLInputElement).value);
    this.writeParams({ knobs: { ...this.params().knobs, [knob.key]: value } });
  }

  protected resetKnobs(): void {
    this.writeParams({ knobs: defaultKnobs(this.activeAlgo()) });
  }

  protected onSplit(event: Event): void {
    this.writeParams({
      test_size: clampTestSize((event.target as HTMLInputElement).value),
    });
  }

  protected onFolds(event: Event): void {
    this.writeParams({
      cross_validation: clampFolds((event.target as HTMLSelectElement).value),
    });
  }

  protected onName(event: Event): void {
    this.writeParams({
      model_name: (event.target as HTMLInputElement).value.trim(),
    });
  }

  /**
   * Pin the picked dataset by slug, so the node follows its latest version.
   *
   * Emptying the picker un-pins rather than pinning nothing: a training node
   * with no pin reads the dataset the wire hands it, which is how a node fits on
   * the output of the transform above it.
   */
  protected onPin(event: Event): void {
    const slug = (event.target as HTMLSelectElement).value;
    const dataset = this.ml.datasets().find((row) => row.slug === slug);
    // A different table invalidates every column-level choice on the node.
    this.writeParams({
      sources: dataset ? [{ dataset_slug: dataset.slug }] : [],
      target: '',
      task: null,
      features: null,
    });
    this.ml.clearRun();
  }

  protected async runTest(): Promise<void> {
    this.tab.set('test');
    const params = this.params();
    const refusal = preflightTrain(params, { wired: false });
    this.preflight.set(refusal);
    if (refusal) return;
    const pin = this.pinned();
    await this.ml.test({
      ...(pin?.dataset_id ? { dataset_id: pin.dataset_id } : {}),
      ...(pin?.dataset_slug ? { dataset_slug: pin.dataset_slug } : {}),
      target: params.target,
      ...(params.task ? { task: params.task } : {}),
      ...(params.algo ? { algo: params.algo } : {}),
      ...(Object.keys(params.knobs).length ? { knobs: params.knobs } : {}),
      // A forecast is judged by its backtest, not by a random split.
      ...(this.isForecasting()
        ? { spec: forecastSpec(this.forecastDraft(), this.effectiveAlgo()) }
        : {
            ...(params.features ? { features: this.selectedFeatures() } : {}),
            test_size: params.test_size,
            cross_validation: params.cross_validation,
            ...(Object.keys(this.tabularSpec()).length ? { spec: this.tabularSpec() } : {}),
          }),
      ...(params.model_name ? { name: params.model_name } : {}),
    });
  }

  /**
   * Apply a patch as ONE store write.
   *
   * Picking a target changes three fields, and three `updateNodeConfig` calls
   * would be three undo steps for one gesture. Merging into the RAW params bag
   * rather than the read one also preserves any key this view model does not
   * know about.
   */
  private writeParams(patch: Record<string, unknown>): void {
    const node = this.node();
    if (!node) return;
    const config = (node.config ?? {}) as Record<string, unknown>;
    const raw = config['params'];
    const current =
      raw !== null && typeof raw === 'object' && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};
    this.store.updateNodeConfig(node.id, 'params', { ...current, ...patch });
    this.preflight.set(null);
  }

  private schedulePlan(): void {
    this.cancelPlan();
    this.planTimer = setTimeout(() => {
      this.planTimer = null;
      const params = this.params();
      const pin = pinnedDataset(params.sources);
      void this.ml.refreshPlan({
        ...(pin?.dataset_id ? { dataset_id: pin.dataset_id } : {}),
        ...(pin?.dataset_slug ? { dataset_slug: pin.dataset_slug } : {}),
        ...(params.target ? { target: params.target } : {}),
        ...(params.task ? { task: params.task } : {}),
        ...(params.algo ? { algo: params.algo } : {}),
        ...(this.isForecasting()
          ? { spec: forecastSpec(this.forecastDraft(), this.effectiveAlgo()) }
          : {
              ...(params.features ? { features: params.features } : {}),
              ...(Object.keys(this.tabularSpec()).length ? { spec: this.tabularSpec() } : {}),
            }),
      });
    }, PLAN_DEBOUNCE_MS);
  }

  private cancelPlan(): void {
    if (this.planTimer !== null) {
      clearTimeout(this.planTimer);
      this.planTimer = null;
    }
  }
}
