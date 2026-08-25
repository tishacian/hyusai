/**
 * Training studio — the no-code fit, as three decisions and a preview.
 *
 * The form's whole posture is that the platform knows the data and the author
 * does not have to: `POST /ml-models/plan` is called on every meaningful change
 * and answers what the request *would* be. So the target list only offers
 * columns that can actually be predicted, the task arrives inferred from the
 * column's type, and a column that is unique per row is called out as
 * memorisation before anything is fitted rather than after.
 *
 * That is also why a refusal is not an error here: it is rendered against the
 * field that caused it while the author keeps editing. Nothing in this form can
 * be submitted into a run that was going to fail for a reason already known.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ColumnSparkComponent } from '@app/shared/ui/column-spark.component';
import type { DatasetDto } from '@app/features/data/data.service';
import { ModelsService } from './models.service';
import {
  algoFor,
  algoIcon,
  algosForTask,
  clampKnob,
  defaultKnobs,
  knobIsAuto,
  refusalField,
  refusalKey,
  targetCandidates,
  taskIcon,
  warningKey,
  type AlgoDescriptor,
  type CodedRefusal,
  type KnobDescriptor,
  type ModelDto,
  type ModelTask,
  type PlanColumn,
  type TrainingPlan,
} from './models.vm';

/** How long the form waits before asking the server what a choice implies. */
const PLAN_DEBOUNCE_MS = 220;

/** What a retrain carries over from the version it is based on. */
export interface TrainSeed {
  datasetId?: string | null;
  target?: string;
  task?: ModelTask;
  features?: string[];
  algo?: string;
  knobs?: Record<string, number | null>;
  testSize?: number | null;
  crossValidation?: number | null;
}

@Component({
  selector: 'app-model-train',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, ColumnSparkComponent, FormsModule, IconComponent],
  template: `
    <div class="fixed inset-0 z-50 flex items-start justify-center p-4 md:p-6 overflow-auto">
      <div class="absolute inset-0" style="background: var(--ck-scrim)" (click)="dismiss()"></div>
      <div
        class="relative ck-surface rounded-md w-full"
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-train-title"
        cdkTrapFocus
        [cdkTrapFocusAutoCapture]="true"
        style="max-width: 1040px; border: 1px solid var(--ck-stroke-strong)"
      >
        <header
          class="flex items-start justify-between gap-4 px-6 py-4"
          style="border-bottom: 1px solid var(--ck-stroke-2)"
        >
          <div>
            <div
              class="ck-mono flex items-center gap-2"
              style="font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ck-fg-4)"
            >
              <app-icon name="brain" [size]="12" />
              {{ i18n.t('models.eyebrow') }}
            </div>
            <h2
              id="model-train-title"
              class="text-lg font-medium"
              style="color: var(--ck-fg-1); margin-top: 6px"
            >
              {{ i18n.t('models.studio.title') }}
            </h2>
            <p class="ck-mono" style="font-size: 10.5px; color: var(--ck-fg-4); margin-top: 4px">
              {{ i18n.t('models.studio.subtitle') }}
            </p>
          </div>
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[11px]"
            (click)="dismiss()"
          >
            <app-icon name="x" [size]="13" /> {{ i18n.t('models.studio.close') }}
          </button>
        </header>

        <div class="ck-studio">
          <!-- ── Column 1: what to train on, and what to predict ──────────── -->
          <section class="ck-studio__col">
            <div class="ck-field">
              <label class="ck-label" for="train-dataset">
                {{ i18n.t('models.studio.dataset.label') }}
              </label>
              <select
                id="train-dataset"
                class="ck-input"
                [ngModel]="datasetId()"
                (ngModelChange)="onDatasetChange($event)"
              >
                <option value="">{{ i18n.t('models.studio.dataset.placeholder') }}</option>
                @for (dataset of readyDatasets(); track dataset.id) {
                  <option [value]="dataset.id">{{ dataset.name }}</option>
                }
              </select>
              @if (dataset(); as ds) {
                <div class="ck-hint ck-mono">
                  {{
                    i18n.t('models.studio.dataset.meta', {
                      rows: (ds.row_count ?? 0).toLocaleString(i18n.locale()),
                      columns: ds.column_count ?? 0
                    })
                  }}
                </div>
              }
              @if (refusalFor('dataset'); as message) {
                <div class="ck-refusal">
                  <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                </div>
              }
            </div>

            <div class="ck-field">
              <label class="ck-label">{{ i18n.t('models.studio.target.label') }}</label>
              <div class="ck-hint">{{ i18n.t('models.studio.target.hint') }}</div>
              @if (candidates().length) {
                <div class="ck-picker" role="radiogroup" [attr.aria-label]="i18n.t('models.studio.target.label')">
                  @for (column of candidates(); track column.name) {
                    <button
                      type="button"
                      role="radio"
                      [attr.aria-checked]="target() === column.name"
                      class="ck-picker__row"
                      [class.ck-picker__row--on]="target() === column.name"
                      (click)="onTargetChange(column.name)"
                    >
                      <app-icon [name]="taskIcon(column.suggested_task)" [size]="13" />
                      <span class="ck-picker__name ck-mono">{{ column.name }}</span>
                      <span class="ck-kind">{{ i18n.t('data.kind.' + column.kind) }}</span>
                      <span class="ck-picker__spark">
                        <ck-column-spark
                          [stats]="column.profile ?? null"
                          [kind]="column.kind"
                        />
                      </span>
                      <span class="ck-picker__meta ck-mono">
                        {{ i18n.t('models.studio.target.distinct', { count: column.distinct }) }}
                      </span>
                    </button>
                  }
                </div>
              } @else if (datasetId()) {
                <div class="ck-hint ck-mono">{{ i18n.t('models.evidence.none') }}</div>
              }
              @if (refusalFor('target'); as message) {
                <div class="ck-refusal">
                  <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                </div>
              }
            </div>

            @if (target()) {
              <div class="ck-field">
                <label class="ck-label">{{ i18n.t('models.studio.task.label') }}</label>
                <div class="ck-seg">
                  @for (option of tasks; track option) {
                    <button
                      type="button"
                      class="ck-seg__btn"
                      [class.ck-seg__btn--on]="effectiveTask() === option"
                      (click)="onTaskChange(option)"
                    >
                      <app-icon [name]="taskIcon(option)" [size]="13" />
                      {{ i18n.t('models.task.' + option) }}
                    </button>
                  }
                </div>
                <div class="ck-hint">{{ i18n.t('models.task.' + effectiveTask() + '.hint') }}</div>
                @if (!taskOverride() && suggestedTask()) {
                  <div class="ck-hint ck-mono" style="color: var(--ck-signal-cool)">
                    {{ i18n.t('models.studio.task.suggested') }}
                  </div>
                }
              </div>

              <div class="ck-field">
                <div class="flex items-center justify-between gap-2">
                  <label class="ck-label">{{ i18n.t('models.studio.features.label') }}</label>
                  <div class="flex items-center gap-1.5">
                    <span class="ck-mono" style="font-size: 10px; color: var(--ck-fg-4)">
                      {{
                        i18n.t('models.studio.features.count', {
                          selected: selectedFeatures().length,
                          total: featureColumns().length
                        })
                      }}
                    </span>
                    <button type="button" class="ck-mini-btn" (click)="selectAllFeatures()">
                      {{ i18n.t('models.studio.features.all') }}
                    </button>
                    <button type="button" class="ck-mini-btn" (click)="clearFeatures()">
                      {{ i18n.t('models.studio.features.none') }}
                    </button>
                  </div>
                </div>
                <div class="ck-hint">{{ i18n.t('models.studio.features.hint') }}</div>
                <div class="ck-chips">
                  @for (column of featureColumns(); track column.name) {
                    <button
                      type="button"
                      class="ck-chip"
                      [class.ck-chip--on]="isFeature(column.name)"
                      [class.ck-chip--flagged]="flaggedFeatures().has(column.name)"
                      [attr.aria-pressed]="isFeature(column.name)"
                      [title]="featureTitle(column)"
                      (click)="toggleFeature(column.name)"
                    >
                      @if (flaggedFeatures().has(column.name)) {
                        <app-icon name="alert-triangle" [size]="10" />
                      }
                      <ck-column-spark
                        [stats]="column.profile ?? null"
                        [kind]="column.kind"
                        [width]="20"
                        [height]="9"
                      />
                      {{ column.name }}
                    </button>
                  }
                </div>
                @if (refusalFor('features'); as message) {
                  <div class="ck-refusal">
                    <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                  </div>
                }
              </div>
            }
          </section>

          <!-- ── Column 2: how to train it ─────────────────────────────────── -->
          <section class="ck-studio__col">
            @if (target()) {
              <div class="ck-field">
                <label class="ck-label">{{ i18n.t('models.studio.algo.label') }}</label>
                <div class="ck-algos">
                  @for (algo of availableAlgos(); track algo.key) {
                    <button
                      type="button"
                      class="ck-algo"
                      [class.ck-algo--on]="algoKey() === algo.key"
                      [attr.aria-pressed]="algoKey() === algo.key"
                      (click)="onAlgoChange(algo.key)"
                    >
                      <div class="ck-algo__head">
                        <app-icon [name]="algoIcon(algo.key)" [size]="15" />
                        <span class="ck-algo__name">{{ i18n.t('models.algo.' + algo.key) }}</span>
                      </div>
                      <div class="ck-algo__tags">
                        @for (tag of algo.tags; track tag) {
                          <span class="ck-tag">{{ i18n.t('models.tag.' + tag) }}</span>
                        }
                      </div>
                      <div class="ck-algo__hint">{{ i18n.t('models.algo.' + algo.key + '.hint') }}</div>
                    </button>
                  }
                </div>
                @if (refusalFor('algo'); as message) {
                  <div class="ck-refusal">
                    <app-icon name="alert-triangle" [size]="12" /> {{ message }}
                  </div>
                }
              </div>

              @if (activeAlgo(); as algo) {
                @if (algo.knobs.length) {
                  <div class="ck-field">
                    <div class="flex items-center justify-between gap-2">
                      <label class="ck-label">{{ i18n.t('models.studio.knobs.label') }}</label>
                      <button type="button" class="ck-mini-btn" (click)="resetKnobs()">
                        {{ i18n.t('models.studio.knobs.reset') }}
                      </button>
                    </div>
                    @for (knob of algo.knobs; track knob.key) {
                      <div class="ck-knob">
                        <div class="ck-knob__head">
                          <span class="ck-knob__label">
                            {{ i18n.t('models.studio.knob.' + knob.key) }}
                          </span>
                          <span class="ck-knob__value ck-mono">{{ knobLabel(knob) }}</span>
                        </div>
                        <input
                          type="range"
                          class="ck-range"
                          [min]="knob.min"
                          [max]="knob.max"
                          [step]="knob.step"
                          [value]="knobValue(knob)"
                          [attr.aria-label]="i18n.t('models.studio.knob.' + knob.key)"
                          (input)="onKnobInput(knob, $event)"
                        />
                      </div>
                    }
                  </div>
                }
              }

              <div class="ck-field">
                <div class="ck-knob">
                  <div class="ck-knob__head">
                    <span class="ck-knob__label">{{ i18n.t('models.studio.split.label') }}</span>
                    <span class="ck-knob__value ck-mono">{{ splitLabel() }}</span>
                  </div>
                  <input
                    type="range"
                    class="ck-range"
                    min="0.05"
                    max="0.5"
                    step="0.05"
                    [value]="testSize()"
                    [attr.aria-label]="i18n.t('models.studio.split.label')"
                    (input)="onSplitInput($event)"
                  />
                </div>
                <div class="ck-hint">{{ i18n.t('models.studio.split.hint') }}</div>
              </div>

              <div class="ck-field">
                <label class="ck-label" for="train-cv">{{ i18n.t('models.studio.cv.label') }}</label>
                <select
                  id="train-cv"
                  class="ck-input"
                  [ngModel]="crossValidation()"
                  (ngModelChange)="crossValidation.set(+$event)"
                >
                  <option [ngValue]="0">{{ i18n.t('models.studio.cv.off') }}</option>
                  @for (folds of cvOptions; track folds) {
                    <option [ngValue]="folds">
                      {{ i18n.t('models.studio.cv.folds', { folds: folds }) }}
                    </option>
                  }
                </select>
                <div class="ck-hint">{{ i18n.t('models.studio.cv.hint') }}</div>
              </div>

              <div class="ck-field">
                <label class="ck-label" for="train-name">{{ i18n.t('models.studio.name.label') }}</label>
                <input
                  id="train-name"
                  class="ck-input"
                  type="text"
                  maxlength="200"
                  [ngModel]="name()"
                  (ngModelChange)="name.set($event)"
                  [placeholder]="plan()?.name || i18n.t('models.studio.name.placeholder')"
                />
              </div>
            }
          </section>
        </div>

        <!-- ── The preview: what is about to happen, and the one button ───── -->
        <footer class="ck-studio__foot">
          <div class="flex-1 min-w-0">
            @if (plan(); as preview) {
              <div class="ck-mono" style="font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ck-fg-4)">
                {{ i18n.t('models.studio.plan.title') }}
              </div>
              <div class="flex items-center gap-2 flex-wrap mt-1.5">
                <span class="ck-plan-pill">
                  <app-icon [name]="taskIcon(preview.task)" [size]="12" />
                  {{ i18n.t('models.task.' + preview.task) }}
                </span>
                <span class="ck-plan-pill ck-mono">{{ preview.estimator }}</span>
                <span class="ck-plan-pill ck-mono">
                  {{
                    i18n.t('models.studio.plan.rows', {
                      rows: preview.rows.toLocaleString(i18n.locale()),
                      test: testRows(preview).toLocaleString(i18n.locale())
                    })
                  }}
                </span>
                <span class="ck-plan-pill ck-mono">
                  {{ i18n.t('models.studio.plan.features', { count: preview.features.length }) }}
                </span>
              </div>
              @for (warning of preview.warnings; track $index) {
                <div class="ck-warning">
                  <app-icon name="alert-triangle" [size]="12" />
                  {{ warningMessage(warning) }}
                </div>
              }
            } @else if (refusalUnplaced(); as message) {
              <div class="ck-refusal">
                <app-icon name="alert-triangle" [size]="12" /> {{ message }}
              </div>
            } @else {
              <div class="ck-mono" style="font-size: 10.5px; color: var(--ck-fg-4)">
                {{ i18n.t('models.studio.subtitle') }}
              </div>
            }
          </div>
          <button
            type="button"
            class="ck-submit"
            [disabled]="!canSubmit()"
            (click)="submit()"
          >
            @if (submitting()) {
              <app-icon name="loader-2" [size]="14" class="animate-spin" />
              {{ i18n.t('models.studio.submitting') }}
            } @else {
              <app-icon name="play" [size]="14" />
              {{ i18n.t('models.studio.submit') }}
            }
          </button>
        </footer>
      </div>
    </div>
  `,
  styles: [
    `
      .ck-studio {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0;
        max-height: min(66vh, 620px);
        overflow-y: auto;
      }
      @media (min-width: 900px) {
        .ck-studio {
          grid-template-columns: 1fr 1fr;
        }
        .ck-studio__col + .ck-studio__col {
          border-left: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
        }
      }
      .ck-studio__col {
        padding: 16px 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .ck-field {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .ck-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-weight: 600;
        color: var(--ck-fg-3, #a6aebc);
      }
      .ck-hint {
        font-size: 10.5px;
        line-height: 1.45;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-input {
        width: 100%;
        font-size: 12.5px;
        padding: 7px 9px;
        border-radius: 4px;
        color: var(--ck-fg-1, #e6e9ef);
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-input:focus {
        outline: none;
        border-color: var(--ck-signal-cool, #7dd3fc);
      }
      /* The target list is the one place a scroll is welcome: a wide table has
         many columns and the picker must not push the algorithm off screen. */
      .ck-picker {
        display: flex;
        flex-direction: column;
        gap: 2px;
        max-height: 208px;
        overflow-y: auto;
        padding: 3px;
        border-radius: 5px;
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-picker__row {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        text-align: left;
        padding: 6px 8px;
        border-radius: 4px;
        color: var(--ck-fg-2, #c3c9d4);
        background: transparent;
        transition: background var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-picker__row:hover {
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.04));
      }
      .ck-picker__row--on {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.12);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.3);
      }
      .ck-picker__name {
        flex: 1 1 auto;
        min-width: 0;
        font-size: 12px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .ck-picker__meta {
        font-size: 10px;
        color: var(--ck-fg-4, #8891a0);
        flex-shrink: 0;
      }
      /* Pushes the distribution glyph to the right edge of the row, so the
         names stay left-aligned and the shapes read as one column of shapes. */
      .ck-picker__spark {
        margin-left: auto;
        display: inline-flex;
      }
      .ck-kind {
        font-size: 9.5px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 1.5px 4px;
        border-radius: 3px;
        color: var(--ck-signal-violet, #a78bfa);
        background: rgba(167, 139, 250, 0.12);
        flex-shrink: 0;
      }
      .ck-seg {
        display: flex;
        gap: 3px;
        padding: 3px;
        border-radius: 5px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
      }
      .ck-seg__btn {
        flex: 1 1 0;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
        font-size: 11.5px;
        padding: 5px 8px;
        border-radius: 4px;
        color: var(--ck-fg-3, #a6aebc);
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-seg__btn--on {
        color: var(--ck-fg-1, #e6e9ef);
        background: rgba(125, 211, 252, 0.16);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.3);
      }
      .ck-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        max-height: 132px;
        overflow-y: auto;
      }
      .ck-chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 10.5px;
        padding: 3px 8px;
        border-radius: 999px;
        color: var(--ck-fg-4, #8891a0);
        background: transparent;
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-chip--on {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.32);
      }
      /* A column the plan flagged stays selectable — the author may know
         better — but it cannot be selected without having been warned. */
      .ck-chip--flagged.ck-chip--on {
        color: var(--ck-signal-warn, #fbbf24);
        background: rgba(251, 191, 36, 0.1);
        box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.35);
      }
      .ck-mini-btn {
        font-size: 10px;
        padding: 2px 6px;
        border-radius: 3px;
        color: var(--ck-fg-4, #8891a0);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-mini-btn:hover {
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-algos {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
      }
      .ck-algo {
        display: flex;
        flex-direction: column;
        gap: 5px;
        text-align: left;
        padding: 9px 10px;
        border-radius: 5px;
        color: var(--ck-fg-3, #a6aebc);
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.02));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-algo:hover {
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.28);
      }
      .ck-algo--on {
        color: var(--ck-fg-1, #e6e9ef);
        background: rgba(125, 211, 252, 0.08);
        box-shadow: inset 0 0 0 1.5px rgba(125, 211, 252, 0.45);
      }
      .ck-algo__head {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .ck-algo__name {
        font-size: 12px;
        font-weight: 500;
      }
      .ck-algo__tags {
        display: flex;
        flex-wrap: wrap;
        gap: 3px;
      }
      .ck-tag {
        font-size: 9px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 1px 4px;
        border-radius: 2px;
        color: var(--ck-fg-4, #8891a0);
        background: rgba(255, 255, 255, 0.05);
      }
      .ck-algo__hint {
        font-size: 10px;
        line-height: 1.4;
        color: var(--ck-fg-4, #8891a0);
      }
      .ck-knob {
        display: flex;
        flex-direction: column;
        gap: 3px;
      }
      .ck-knob__head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
      }
      .ck-knob__label {
        font-size: 11px;
        color: var(--ck-fg-3, #a6aebc);
      }
      .ck-knob__value {
        font-size: 11px;
        color: var(--ck-signal-cool, #7dd3fc);
        font-variant-numeric: tabular-nums;
      }
      .ck-range {
        width: 100%;
        height: 3px;
        appearance: none;
        border-radius: 2px;
        background: var(--ck-stroke-2, rgba(255, 255, 255, 0.1));
      }
      .ck-range::-webkit-slider-thumb {
        appearance: none;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--ck-signal-cool, #7dd3fc);
        cursor: pointer;
      }
      .ck-range::-moz-range-thumb {
        width: 12px;
        height: 12px;
        border: none;
        border-radius: 50%;
        background: var(--ck-signal-cool, #7dd3fc);
        cursor: pointer;
      }
      .ck-studio__foot {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 12px 20px;
        border-top: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
        background: linear-gradient(0deg, rgba(125, 211, 252, 0.04) 0%, transparent 100%);
        flex-wrap: wrap;
      }
      .ck-plan-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 10.5px;
        padding: 3px 8px;
        border-radius: 999px;
        color: var(--ck-fg-2, #c3c9d4);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-refusal,
      .ck-warning {
        display: flex;
        align-items: flex-start;
        gap: 5px;
        font-size: 10.5px;
        line-height: 1.45;
        margin-top: 4px;
      }
      .ck-refusal {
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-warning {
        color: var(--ck-signal-warn, #fbbf24);
      }
      .ck-submit {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        font-size: 12.5px;
        font-weight: 500;
        padding: 8px 16px;
        border-radius: 5px;
        color: #06131c;
        background: var(--ck-signal-cool, #7dd3fc);
        transition: all var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
        flex-shrink: 0;
      }
      .ck-submit:hover:not(:disabled) {
        filter: brightness(1.08);
      }
      .ck-submit:disabled {
        opacity: 0.4;
        cursor: not-allowed;
      }
    `,
  ],
})
export class ModelTrainComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly toast = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);

  readonly datasets = input<DatasetDto[]>([]);
  readonly seed = input<TrainSeed | null>(null);

  readonly close = output<void>();
  readonly trained = output<ModelDto>();

  protected readonly tasks: ModelTask[] = ['classification', 'regression'];
  protected readonly cvOptions = [3, 5, 10];

  protected readonly datasetId = signal('');
  protected readonly target = signal('');
  protected readonly taskOverride = signal<ModelTask | null>(null);
  protected readonly algoKey = signal('');
  protected readonly testSize = signal(0.25);
  protected readonly crossValidation = signal(0);
  protected readonly name = signal('');
  protected readonly submitting = signal(false);

  protected readonly columns = signal<PlanColumn[]>([]);
  protected readonly plan = signal<TrainingPlan | null>(null);
  protected readonly refusal = signal<CodedRefusal | null>(null);

  /** `null` means "every column but the target", which is also the server's default. */
  private readonly featureOverride = signal<string[] | null>(null);
  private readonly knobOverrides = signal<Record<string, number>>({});

  private planTimer: ReturnType<typeof setTimeout> | null = null;

  protected readonly catalog = this.models.catalog;

  protected readonly readyDatasets = computed(() =>
    this.datasets().filter((dataset) => dataset.status === 'ready'),
  );

  protected readonly dataset = computed(
    () => this.readyDatasets().find((row) => row.id === this.datasetId()) ?? null,
  );

  protected readonly candidates = computed(() =>
    targetCandidates(this.columns(), this.catalog().limits.max_classes),
  );

  protected readonly suggestedTask = computed<ModelTask | null>(
    () =>
      this.columns().find((column) => column.name === this.target())?.suggested_task ??
      null,
  );

  protected readonly effectiveTask = computed<ModelTask>(
    () =>
      this.taskOverride() ??
      this.suggestedTask() ??
      this.catalog().defaults.task ??
      'classification',
  );

  protected readonly availableAlgos = computed<AlgoDescriptor[]>(() =>
    algosForTask(this.catalog(), this.effectiveTask()),
  );

  protected readonly activeAlgo = computed(() =>
    algoFor(this.catalog(), this.algoKey()),
  );

  /** Every column but the target: what the feature chips are drawn from. */
  protected readonly featureColumns = computed(() =>
    this.columns().filter((column) => column.name !== this.target()),
  );

  protected readonly selectedFeatures = computed<string[]>(() => {
    const override = this.featureOverride();
    const available = this.featureColumns().map((column) => column.name);
    if (!override) return available;
    const allowed = new Set(available);
    return override.filter((feature) => allowed.has(feature));
  });

  /** Columns the plan called out — rendered on the chip, not only in the footer. */
  protected readonly flaggedFeatures = computed(
    () =>
      new Set(
        (this.plan()?.warnings ?? [])
          .map((warning) => warning.feature)
          .filter((feature): feature is string => !!feature),
      ),
  );

  protected readonly canSubmit = computed(
    () => !!this.plan() && !this.submitting() && !this.refusal(),
  );

  ngOnInit(): void {
    const seed = this.seed();
    const first = this.readyDatasets()[0];
    this.datasetId.set(seed?.datasetId || first?.id || '');
    if (seed?.target) this.target.set(seed.target);
    if (seed?.task) this.taskOverride.set(seed.task);
    if (seed?.features?.length) this.featureOverride.set([...seed.features]);
    if (seed?.algo) this.algoKey.set(seed.algo);
    if (seed?.testSize) this.testSize.set(seed.testSize);
    if (seed?.crossValidation) this.crossValidation.set(seed.crossValidation);
    if (seed?.knobs) {
      const knobs: Record<string, number> = {};
      for (const [key, value] of Object.entries(seed.knobs)) {
        if (typeof value === 'number' && Number.isFinite(value)) knobs[key] = value;
      }
      this.knobOverrides.set(knobs);
    }
    this.destroyRef.onDestroy(() => this.cancelPlan());
    void this.refreshPlan();
  }

  @HostListener('document:keydown.escape', ['$event'])
  protected onEscape(event: Event): void {
    event.preventDefault();
    this.dismiss();
  }

  protected dismiss(): void {
    this.close.emit();
  }

  protected taskIcon(task: ModelTask): string {
    return taskIcon(task);
  }

  protected algoIcon(algo: string): string {
    return algoIcon(algo);
  }

  protected onDatasetChange(datasetId: string): void {
    this.datasetId.set(datasetId);
    // A new table invalidates every choice made against the old one.
    this.target.set('');
    this.taskOverride.set(null);
    this.featureOverride.set(null);
    this.columns.set([]);
    this.plan.set(null);
    this.refusal.set(null);
    void this.refreshPlan();
  }

  protected onTargetChange(target: string): void {
    this.target.set(target);
    this.taskOverride.set(null);
    this.featureOverride.set(null);
    this.schedulePlan();
  }

  protected onTaskChange(task: ModelTask): void {
    this.taskOverride.set(task);
    // An algorithm that cannot do the new task must not stay selected.
    if (!algosForTask(this.catalog(), task).some((algo) => algo.key === this.algoKey())) {
      this.algoKey.set('');
      this.knobOverrides.set({});
    }
    this.schedulePlan();
  }

  protected onAlgoChange(key: string): void {
    this.algoKey.set(key);
    this.knobOverrides.set({});
    this.schedulePlan();
  }

  protected isFeature(name: string): boolean {
    return this.selectedFeatures().includes(name);
  }

  protected toggleFeature(name: string): void {
    const current = this.selectedFeatures();
    const next = current.includes(name)
      ? current.filter((feature) => feature !== name)
      : [...current, name];
    this.featureOverride.set(next);
    this.schedulePlan();
  }

  protected selectAllFeatures(): void {
    this.featureOverride.set(null);
    this.schedulePlan();
  }

  protected clearFeatures(): void {
    this.featureOverride.set([]);
    this.schedulePlan();
  }

  protected featureTitle(column: PlanColumn): string {
    const flagged = this.flaggedFeatures().has(column.name);
    const kind = this.i18n.t('data.kind.' + column.kind);
    if (!flagged) return kind;
    return `${kind} — ${this.i18n.t('models.warning.ml_feature_identifier', {
      feature: column.name,
    })}`;
  }

  protected knobValue(knob: KnobDescriptor): number {
    const override = this.knobOverrides()[knob.key];
    const fallback = this.plan()?.knobs?.[knob.key];
    const raw =
      override !== undefined
        ? override
        : typeof fallback === 'number'
          ? fallback
          : knob.default;
    return clampKnob(knob, raw);
  }

  protected knobLabel(knob: KnobDescriptor): string {
    const value = this.knobValue(knob);
    if (knobIsAuto(knob, value)) return this.i18n.t('models.studio.knobs.auto');
    return value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 4 });
  }

  protected onKnobInput(knob: KnobDescriptor, event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.knobOverrides.update((knobs) => ({
      ...knobs,
      [knob.key]: clampKnob(knob, raw),
    }));
  }

  protected resetKnobs(): void {
    this.knobOverrides.set(defaultKnobs(this.activeAlgo()));
  }

  protected onSplitInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    if (Number.isFinite(raw)) this.testSize.set(raw);
  }

  protected splitLabel(): string {
    return `${Math.round(this.testSize() * 100)}%`;
  }

  protected testRows(plan: TrainingPlan): number {
    return Math.round(plan.rows * this.testSize());
  }

  /** A refusal rendered against the field that caused it, or nothing. */
  protected refusalFor(field: 'target' | 'features' | 'algo' | 'dataset'): string | null {
    const refusal = this.refusal();
    if (!refusal || refusalField(refusal.code) !== field) return null;
    return this.refusalMessage(refusal);
  }

  /** A refusal no field owns still has to be read, so the footer takes it. */
  protected refusalUnplaced(): string | null {
    const refusal = this.refusal();
    if (!refusal || refusalField(refusal.code)) return null;
    return this.refusalMessage(refusal);
  }

  protected warningMessage(warning: { code: string; feature?: string }): string {
    const key = warningKey(warning.code);
    if (!key) return warning.code;
    return this.i18n.t(key, { feature: warning.feature ?? '' });
  }

  protected async submit(): Promise<void> {
    const preview = this.plan();
    if (!preview || this.submitting()) return;
    this.submitting.set(true);
    try {
      const model = await this.models.train({
        dataset_id: this.datasetId(),
        target: preview.target,
        task: preview.task,
        features: preview.features,
        algo: preview.algo,
        knobs: this.knobPayload(),
        test_size: this.testSize(),
        cross_validation: this.crossValidation(),
        ...(this.name().trim() ? { name: this.name().trim() } : {}),
      });
      this.toast.info(this.i18n.t('models.studio.queued', { name: model.name }));
      this.trained.emit(model);
    } catch {
      this.toast.error(this.i18n.t('models.studio.failed'));
    } finally {
      this.submitting.set(false);
    }
  }

  private refusalMessage(refusal: CodedRefusal): string {
    const key = refusalKey(refusal.code);
    return key ? this.i18n.t(key) : refusal.message;
  }

  /** Only knobs the author actually moved; the rest are the estimator's own. */
  private knobPayload(): Record<string, number> {
    const algo = this.activeAlgo();
    if (!algo) return {};
    const payload: Record<string, number> = {};
    const overrides = this.knobOverrides();
    for (const knob of algo.knobs) {
      const value = overrides[knob.key];
      if (value !== undefined) payload[knob.key] = clampKnob(knob, value);
    }
    return payload;
  }

  private schedulePlan(): void {
    this.cancelPlan();
    this.planTimer = setTimeout(() => void this.refreshPlan(), PLAN_DEBOUNCE_MS);
  }

  private cancelPlan(): void {
    if (this.planTimer) {
      clearTimeout(this.planTimer);
      this.planTimer = null;
    }
  }

  private async refreshPlan(): Promise<void> {
    const datasetId = this.datasetId();
    if (!datasetId) {
      this.columns.set([]);
      this.plan.set(null);
      this.refusal.set(null);
      return;
    }
    try {
      const response = await this.models.plan({
        dataset_id: datasetId,
        ...(this.target() ? { target: this.target() } : {}),
        ...(this.taskOverride() ? { task: this.taskOverride()! } : {}),
        ...(this.featureOverride() ? { features: this.selectedFeatures() } : {}),
        ...(this.algoKey() ? { algo: this.algoKey() } : {}),
      });
      this.columns.set(response.columns ?? []);
      this.plan.set(response.plan);
      this.refusal.set(response.refusal);
      this.adoptPlan(response.plan);
    } catch {
      this.plan.set(null);
    }
  }

  /**
   * Let the server's answer fill in what the author has not decided.
   *
   * Only the untouched fields: an author who picked "random forest" keeps it
   * even though the plan would have defaulted to boosting, and the split they
   * dragged is not snapped back on the next keystroke.
   */
  private adoptPlan(plan: TrainingPlan | null): void {
    if (!plan) return;
    if (!this.algoKey()) this.algoKey.set(plan.algo);
    if (!this.target() && plan.target) this.target.set(plan.target);
  }
}
