/**
 * `<ck-forecast-spec>` — a forecast's problem definition, as form fields.
 *
 * One component for the two places a forecast is authored: the Models studio
 * and the Flow training workshop. Same fields, same refusals, same copy, so a
 * forecast asked for on a canvas and one asked for on the Models page are the
 * same question.
 *
 * It renders in two parts because both hosts are two columns:
 *  - `data` — what the series is: date column, shape, series columns, and
 *    which covariates are known in advance (or only up to now);
 *  - `fit` — how it is fitted and judged: horizon, frequency, strategy, lags,
 *    interval level, backtests, gap policy, calendar.
 *
 * Stateless apart from the lags being typed: the host owns the draft (the
 * studio as a signal, the workshop as the node's `spec`) and receives one patch
 * per gesture, so a slider is one undo step on the canvas, not twenty.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  linkedSignal,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  FORECAST_FILLS,
  FORECAST_FREQUENCIES,
  FORECAST_SHAPES,
  covariateCandidates,
  forecastTuningIssue,
  tuningBounds,
  parseLags,
  seriesColumnCandidates,
  strategyApplies,
  timeColumns,
  withTimeColumn,
  type ForecastDraft,
  type ForecastRole,
} from './forecast.vm';
import type { PlanColumn, SpecFieldDescriptor } from './models.vm';

@Component({
  selector: 'ck-forecast-spec',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent],
  template: `
    @if (part() === 'data') {
      <div class="ck-field" data-testid="train-forecast">
        <label class="ck-label" for="train-time">{{ i18n.t('models.spec.time_column') }}</label>
        @if (timeOptions().length) {
          <select
            id="train-time"
            class="ck-input"
            [ngModel]="draft().timeColumn"
            (ngModelChange)="patch({ timeColumn: $event })"
          >
            @for (name of timeOptions(); track name) {
              <option [value]="name">{{ name }}</option>
            }
          </select>
          <div class="ck-hint">{{ i18n.t('models.spec.time_column.hint') }}</div>
        } @else {
          <div class="ck-refusal">
            <app-icon name="alert-triangle" [size]="12" />
            {{ i18n.t('models.studio.forecast.no_time') }}
          </div>
        }
      </div>

      <div class="ck-field">
        <label class="ck-label">{{ i18n.t('models.spec.shape') }}</label>
        <div class="ck-seg">
          @for (shape of shapes(); track shape) {
            <button
              type="button"
              class="ck-seg__btn"
              [class.ck-seg__btn--on]="draft().shape === shape"
              [attr.aria-pressed]="draft().shape === shape"
              (click)="patch({ shape: shape })"
            >
              {{ i18n.t('models.spec.shape.' + shape) }}
            </button>
          }
        </div>
        <div class="ck-hint">{{ i18n.t('models.spec.shape.hint') }}</div>
      </div>

      @if (draft().shape === 'panel') {
        <div class="ck-field">
          <label class="ck-label">{{ i18n.t('models.spec.series_columns') }}</label>
          <div class="ck-chips">
            @for (name of seriesOptions(); track name) {
              <button
                type="button"
                class="ck-chip ck-mono"
                [class.ck-chip--on]="draft().seriesColumns.includes(name)"
                [attr.aria-pressed]="draft().seriesColumns.includes(name)"
                (click)="toggleSeriesColumn(name)"
              >
                {{ name }}
              </button>
            }
          </div>
          <div class="ck-hint">{{ i18n.t('models.spec.series_columns.hint') }}</div>
        </div>
      }

      @if (hasField('exog')) {
      <div class="ck-field">
        <label class="ck-label">{{ i18n.t('models.spec.exog') }}</label>
        <div class="ck-hint">{{ i18n.t('models.spec.exog.hint') }}</div>
        @if (covariates().length) {
          <div class="ck-roles">
            @for (candidate of covariates(); track candidate.name) {
              <div class="ck-role">
                <span class="ck-role__name ck-mono" [title]="candidate.name">{{ candidate.name }}</span>
                <select
                  class="ck-input ck-role__select"
                  [attr.aria-label]="candidate.name"
                  [ngModel]="roleOf(candidate.name)"
                  (ngModelChange)="setRole(candidate.name, $event)"
                >
                  <option value="">{{ i18n.t('models.studio.forecast.unused') }}</option>
                  @for (role of candidate.roles; track role) {
                    <option [value]="role">{{ i18n.t('models.spec.exog.' + role) }}</option>
                  }
                </select>
              </div>
            }
          </div>
        } @else {
          <div class="ck-hint ck-mono">{{ i18n.t('models.studio.forecast.no_covariates') }}</div>
        }
      </div>

      }

      @if (refusal(); as message) {
        <div class="ck-refusal" data-testid="train-forecast-refusal" role="alert">
          <app-icon name="alert-triangle" [size]="12" /> {{ message }}
        </div>
      }
    } @else {
      <div class="ck-field">
        <div class="ck-pair">
          <div class="ck-field">
            <label class="ck-label" for="train-horizon">{{ i18n.t('models.spec.horizon') }}</label>
            <input
              id="train-horizon"
              class="ck-input ck-mono"
              type="number"
              min="1"
              [max]="horizonMax()"
              [value]="draft().horizon"
              (change)="onHorizon($event)"
            />
          </div>
          <div class="ck-field">
            <label class="ck-label" for="train-frequency">{{ i18n.t('models.spec.frequency') }}</label>
            <select
              id="train-frequency"
              class="ck-input"
              [ngModel]="draft().frequency"
              (ngModelChange)="patch({ frequency: $event })"
            >
              @for (frequency of frequencies; track frequency) {
                <option [value]="frequency">
                  {{ i18n.t('models.spec.frequency.' + frequency.toLowerCase()) }}
                </option>
              }
            </select>
          </div>
        </div>
        <div class="ck-hint">{{ i18n.t('models.spec.horizon.hint') }}</div>
      </div>

      @if (showStrategy()) {
        <div class="ck-field">
          <label class="ck-label">{{ i18n.t('models.spec.strategy') }}</label>
          <div class="ck-seg">
            @for (strategy of strategies; track strategy) {
              <button
                type="button"
                class="ck-seg__btn"
                [class.ck-seg__btn--on]="draft().strategy === strategy"
                [attr.aria-pressed]="draft().strategy === strategy"
                (click)="patch({ strategy: strategy })"
              >
                {{ i18n.t('models.spec.strategy.' + strategy) }}
              </button>
            }
          </div>
          <div class="ck-hint">{{ i18n.t('models.spec.strategy.hint') }}</div>
        </div>
      }

      @if (hasField('lags')) {
      <div class="ck-field">
        <label class="ck-label" for="train-lags">{{ i18n.t('models.spec.lags') }}</label>
        <input
          id="train-lags"
          class="ck-input ck-mono"
          type="text"
          [value]="lagsText()"
          (input)="lagsText.set($any($event.target).value)"
          (change)="commitLags()"
          [placeholder]="i18n.t('models.studio.forecast.lags_auto')"
        />
        @if (lagsInvalid()) {
          <div class="ck-refusal">
            <app-icon name="alert-triangle" [size]="12" />
            {{ i18n.t('models.studio.forecast.lags_invalid') }}
          </div>
        } @else {
          <div class="ck-hint">{{ i18n.t('models.spec.lags.hint') }}</div>
        }
      </div>

      }

      <div class="ck-field">
        <div class="ck-knob">
          <div class="ck-knob__head">
            <span class="ck-knob__label">{{ i18n.t('models.spec.interval_level') }}</span>
            <span class="ck-knob__value ck-mono">{{ levelLabel() }}</span>
          </div>
          <input
            type="range"
            class="ck-range"
            min="0.5"
            max="0.95"
            step="0.05"
            [value]="draft().intervalLevel"
            [attr.aria-label]="i18n.t('models.spec.interval_level')"
            (change)="onLevelInput($event)"
          />
        </div>
        <div class="ck-hint">{{ i18n.t('models.spec.interval_level.hint') }}</div>
      </div>

      <div class="ck-field">
        <div class="ck-pair">
          <div class="ck-field">
            <label class="ck-label" for="train-folds">{{ i18n.t('models.spec.backtest_folds') }}</label>
            <select
              id="train-folds"
              class="ck-input"
              [ngModel]="draft().folds"
              (ngModelChange)="patch({ folds: +$event })"
            >
              @for (folds of foldOptions(); track folds) {
                <option [ngValue]="folds">{{ folds }}</option>
              }
            </select>
          </div>
          <div class="ck-field">
            <label class="ck-label" for="train-fill">{{ i18n.t('models.spec.fill') }}</label>
            <select
              id="train-fill"
              class="ck-input"
              [ngModel]="draft().fill"
              (ngModelChange)="patch({ fill: $event })"
            >
              @for (fill of fills(); track fill) {
                <option [value]="fill">{{ i18n.t('models.spec.fill.' + fill) }}</option>
              }
            </select>
          </div>
        </div>
        <div class="ck-hint">{{ i18n.t('models.spec.backtest_folds.hint') }}</div>
      </div>

      @if (hasTuning() || draft().tuning === 'budget') {
        <div class="ck-field" data-testid="forecast-tuning">
          <label class="ck-label" for="forecast-tuning-mode">{{ i18n.t('models.spec.tuning') }}</label>
          <select id="forecast-tuning-mode" class="ck-input" [ngModel]="draft().tuning"
            (ngModelChange)="patch({ tuning: $event })">
            <option value="off">{{ i18n.t('models.spec.tuning.off') }}</option>
            <option value="budget">{{ i18n.t('models.spec.tuning.budget') }}</option>
          </select>
          <div class="ck-hint">{{ i18n.t('models.forecast.tuning.hint') }}</div>
          @if (draft().tuning === 'budget') {
            @for (setting of tuningSettings(); track setting.key) {
              <label class="ck-label" [for]="'forecast-' + setting.key">{{ i18n.t('models.spec.' + setting.key) }}</label>
              <input [id]="'forecast-' + setting.key" class="ck-input ck-mono" type="number" step="1"
                [min]="setting.bounds.min" [max]="setting.bounds.max" [value]="setting.value"
                (change)="onTuningNumber(setting.draftKey, $event)" />
              <div class="ck-hint">{{ i18n.t('models.spec.' + setting.key + '.hint') }}
                {{ i18n.t('models.forecast.tuning.range', { min: setting.bounds.min, max: setting.bounds.max }) }}</div>
            }
            @if (tuningIssue(); as key) {
              <p class="ck-refusal" role="alert" data-testid="forecast-tuning-refusal">{{ i18n.t(key) }}</p>
            }
          }
        </div>
      }

      @if (hasField('calendar')) {
      <label class="ck-check">
        <input
          type="checkbox"
          [ngModel]="draft().calendar"
          (ngModelChange)="patch({ calendar: $event })"
        />
        <span>{{ i18n.t('models.spec.calendar') }}</span>
        <span class="ck-hint">{{ i18n.t('models.spec.calendar.hint') }}</span>
      </label>
      }
    }
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: 16px;
        min-width: 0;
      }
      .ck-field {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 0;
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
      .ck-pair {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 10px;
      }
      .ck-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }
      .ck-chip {
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 4px;
        color: var(--ck-fg-3, #a6aebc);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-chip--on {
        color: var(--ck-fg-1, #e6e9ef);
        background: rgba(125, 211, 252, 0.1);
        box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.4);
      }
      .ck-roles {
        display: flex;
        flex-direction: column;
        gap: 4px;
        max-height: 220px;
        overflow-y: auto;
      }
      .ck-role {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 170px);
        align-items: center;
        gap: 8px;
      }
      .ck-role__name {
        font-size: 11.5px;
        color: var(--ck-fg-2, #c3c9d4);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .ck-role__select {
        padding: 4px 6px;
        font-size: 11.5px;
      }
      .ck-check {
        display: flex;
        align-items: baseline;
        gap: 7px;
        flex-wrap: wrap;
        font-size: 11.5px;
        color: var(--ck-fg-2, #c3c9d4);
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
        accent-color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-refusal {
        display: flex;
        align-items: flex-start;
        gap: 5px;
        font-size: 10.5px;
        line-height: 1.45;
        color: var(--ck-signal-neg, #ef5a6f);
      }
    `,
  ],
})
export class ForecastSpecComponent {
  readonly i18n = inject(I18nService);

  readonly part = input.required<'data' | 'fit'>();
  readonly value = input.required<ForecastDraft>({ alias: 'draft' });
  readonly columns = input<readonly PlanColumn[]>([]);
  readonly target = input('');
  readonly algo = input('');
  readonly horizonMax = input(720);
  readonly fields = input<readonly SpecFieldDescriptor[]>([]);
  /** The plan's refusal about the problem definition, already phrased. */
  readonly refusal = input<string | null>(null);
  /** One patch per gesture; the host merges it into its draft. */
  readonly draftChange = output<Partial<ForecastDraft>>();

  protected readonly hasTuning = computed(() => this.fields().some((field) => field.key === 'tuning'));
  protected readonly tuningIssue = computed(() => forecastTuningIssue(this.draft(), this.algo(), this.fields()));
  protected readonly tuningSettings = computed(() => [
    { key: 'tuning_trials', draftKey: 'tuningTrials', value: this.draft().tuningTrials, bounds: tuningBounds(this.fields(), 'tuning_trials') },
    { key: 'tuning_budget_s', draftKey: 'tuningBudget', value: this.draft().tuningBudget, bounds: tuningBounds(this.fields(), 'tuning_budget_s') },
    { key: 'tuning_folds', draftKey: 'tuningFolds', value: this.draft().tuningFolds, bounds: tuningBounds(this.fields(), 'tuning_folds') },
  ] as const);

  protected readonly shapes = computed(() => FORECAST_SHAPES.filter((shape) => this.choiceAllowed('shape', shape)));
  protected readonly frequencies = FORECAST_FREQUENCIES;
  protected readonly fills = computed(() => FORECAST_FILLS.filter((fill) => this.choiceAllowed('fill', fill)));
  protected readonly strategies = ['recursive', 'direct'] as const;
  protected readonly foldOptions = computed(() => {
    const field = this.fields().find((entry) => entry.key === 'backtest_folds');
    return [1, 2, 3, 4, 5, 6, 8].filter((value) => value >= (field?.min ?? 1) && value <= (field?.max ?? 8));
  });

  protected readonly timeOptions = computed(() => timeColumns(this.columns()));
  /** The draft as shown: a date column it lacks falls back to the first one. */
  protected readonly draft = computed(() => withTimeColumn(this.value(), this.columns()));
  protected readonly seriesOptions = computed(() =>
    seriesColumnCandidates(this.columns(), this.target(), this.draft().timeColumn),
  );
  protected readonly covariates = computed(() =>
    covariateCandidates(this.columns(), this.draft(), this.target()),
  );
  protected readonly showStrategy = computed(() => this.hasField('strategy') && strategyApplies(this.draft().shape, this.algo()));
  /** The lags as typed: committed when the field is left, if they parse. */
  protected readonly lagsText = linkedSignal(() => this.draft().lags);
  protected readonly lagsInvalid = computed(() => parseLags(this.lagsText()) === null);

  protected hasField(key: string): boolean {
    return !this.fields().length || this.fields().some((field) => field.key === key);
  }

  private choiceAllowed(key: string, value: string): boolean {
    const choices = this.fields().find((field) => field.key === key)?.choices;
    return !choices?.length || choices.includes(value);
  }

  protected patch(patch: Partial<ForecastDraft>): void {
    this.draftChange.emit(patch);
  }

  protected toggleSeriesColumn(name: string): void {
    const current = this.draft().seriesColumns;
    const next = current.includes(name) ? current.filter((column) => column !== name) : [...current, name];
    this.patch({ seriesColumns: next.slice(0, 3) });
  }

  protected roleOf(column: string): ForecastRole | '' {
    return this.draft().exog[column] || '';
  }

  protected setRole(column: string, role: ForecastRole | ''): void {
    const exog = { ...this.draft().exog };
    if (role) exog[column] = role;
    else delete exog[column];
    this.patch({ exog });
  }

  protected onTuningNumber(key: 'tuningTrials' | 'tuningBudget' | 'tuningFolds', event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.patch({ [key]: raw.trim() ? Number(raw) : 0 });
  }

  protected onHorizon(event: Event): void {
    const steps = Math.round(Number((event.target as HTMLInputElement).value));
    if (!Number.isFinite(steps) || steps < 1) return;
    this.patch({ horizon: Math.min(steps, this.horizonMax()) });
  }

  protected onLevelInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    if (Number.isFinite(raw)) this.patch({ intervalLevel: Math.round(raw * 100) / 100 });
  }

  protected commitLags(): void {
    if (parseLags(this.lagsText()) !== null) this.patch({ lags: this.lagsText() });
  }

  protected levelLabel(): string {
    return `${Math.round(this.draft().intervalLevel * 100)} %`;
  }
}
