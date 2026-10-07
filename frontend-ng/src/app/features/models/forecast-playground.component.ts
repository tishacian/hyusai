/**
 * `<ck-forecast-playground>` — ask a trained forecast for the next steps.
 *
 * The Play tab of a forecasting model: a horizon, an interval level, the
 * series to forecast (in a panel) and the planned value of each covariate
 * known in advance. The answer is drawn right after the context the backtest
 * ended on, so a reader sees where the forecast leaves from, and it is read
 * back as one sentence — when it peaks, and how high the interval says it
 * could go — because an operator's question is "will this cell saturate".
 *
 * The request it sends is emitted upward, so the playground's cURL is always
 * this exact call.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ForecastChartComponent } from '@app/features/data/viz/forecast-chart.component';
import {
  forecastChartSeries,
  formatForecastStamp,
} from '@app/features/data/viz/forecast-chart.vm';
import { ModelsService } from './models.service';
import {
  answerPoints,
  forecastPeak,
  forecastRequest,
  futureStamps,
  isForecast,
  recentActuals,
  type ForecastAnswer,
  type ForecastRequestBody,
} from './forecast.vm';
import { servingErrorKey, type ModelDto, type ServingBlock } from './models.vm';

@Component({
  selector: 'ck-forecast-playground',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent, ForecastChartComponent],
  template: `
    <div class="ck-fplay" data-testid="forecast-playground">
      <section class="ck-panel">
        <div class="ck-section-label">{{ i18n.t('models.play.forecast.ask') }}</div>
        <div class="ck-fplay__controls">
          <label class="ck-fplay__field">
            <span class="ck-fplay__label">{{ i18n.t('models.spec.horizon') }}</span>
            <input
              class="ck-fplay__input ck-mono"
              type="number"
              min="1"
              [max]="maxSteps()"
              [ngModel]="horizon()"
              (ngModelChange)="onHorizon($event)"
              data-testid="forecast-horizon"
            />
          </label>
          <label class="ck-fplay__field">
            <span class="ck-fplay__label">
              {{ i18n.t('models.spec.interval_level') }} · {{ percent(level()) }}
            </span>
            <input
              class="ck-fplay__range"
              type="range"
              min="0.5"
              max="0.95"
              step="0.05"
              [value]="level()"
              (input)="onLevel($event)"
            />
          </label>
          @if (levels().length > 1) {
            <label class="ck-fplay__field">
              <span class="ck-fplay__label">{{ i18n.t('models.evidence.forecast.series') }}</span>
              <select
                class="ck-fplay__input ck-mono"
                [ngModel]="series()"
                (ngModelChange)="series.set($event)"
                data-testid="forecast-series"
              >
                @for (name of levels(); track name) {
                  <option [value]="name">{{ name }}</option>
                }
              </select>
            </label>
          }
          @for (name of covariates(); track name) {
            <label class="ck-fplay__field">
              <span class="ck-fplay__label ck-mono">{{ name }}</span>
              <input
                class="ck-fplay__input ck-mono"
                type="number"
                [ngModel]="plannedValue(name)"
                (ngModelChange)="onPlanned(name, $event)"
              />
            </label>
          }
          <button
            type="button"
            class="ck-fplay__run inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-sky-500 hover:bg-sky-600 text-white transition disabled:opacity-50"
            [disabled]="running() || !canAsk()"
            (click)="run()"
            data-testid="forecast-run"
          >
            <app-icon [name]="running() ? 'loader-2' : 'play'" [size]="14" [class.animate-spin]="running()" />
            {{ i18n.t('models.play.forecast.run') }}
          </button>
        </div>
        @if (covariates().length) {
          <div class="ck-hint">
            {{
              stamps()
                ? i18n.t('models.play.forecast.covariates', { names: covariates().join(', ') })
                : i18n.t('models.play.forecast.covariates_undated')
            }}
          </div>
        }
        @if (error(); as message) {
          <div class="ck-fplay__error">
            <app-icon name="alert-triangle" [size]="12" /> {{ message }}
          </div>
        }
      </section>

      <section class="ck-panel">
        <div class="flex items-baseline justify-between gap-2 flex-wrap">
          <div class="ck-section-label">{{ i18n.t('models.play.forecast.answer') }}</div>
          @if (answer(); as reply) {
            <span class="ck-hint ck-mono" style="margin-top: 0">
              {{
                i18n.t(reply.cached ? 'models.play.forecast.timing.cached' : 'models.play.forecast.timing.cold', {
                  ms: round(reply.duration_ms),
                  load: round(reply.load_ms ?? 0)
                })
              }}
            </span>
          }
        </div>
        @if (answer()) {
          <ck-forecast-chart
            [series]="chart()"
            [frequency]="frequency()"
            [locale]="i18n.locale()"
            [label]="i18n.t('models.play.forecast.answer')"
            [names]="names()"
            [format]="valueFormat"
          />
          @if (peakLine(); as line) {
            <div class="ck-fplay__peak" data-testid="forecast-peak">{{ line }}</div>
          }
        } @else {
          <div class="ck-hint">{{ i18n.t('models.play.forecast.empty') }}</div>
        }
      </section>
    </div>
  `,
  styles: [
    `
      .ck-fplay {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        gap: 12px;
      }
      .ck-panel {
        padding: 12px 14px;
        border-radius: 6px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.02));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
      }
      .ck-section-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--ck-fg-4, #8891a0);
        margin-bottom: 8px;
      }
      .ck-hint {
        font-size: 10.5px;
        line-height: 1.45;
        color: var(--ck-fg-4, #8891a0);
        margin-top: 8px;
      }
      .ck-fplay__controls {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        gap: 12px;
      }
      .ck-fplay__field {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 120px;
      }
      .ck-fplay__label {
        font-size: 10.5px;
        color: var(--ck-fg-3, #a6aebc);
      }
      .ck-fplay__input {
        font-size: 12.5px;
        padding: 6px 8px;
        border-radius: 4px;
        width: 140px;
        color: var(--ck-fg-1, #e6e9ef);
        background: var(--ck-bg-panel, rgba(255, 255, 255, 0.03));
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-fplay__range {
        width: 160px;
        accent-color: var(--ck-accent, #7dd3fc);
      }
      .ck-fplay__run {
        margin-left: auto;
      }
      .ck-fplay__error {
        display: flex;
        gap: 5px;
        align-items: flex-start;
        margin-top: 8px;
        font-size: 11px;
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-fplay__peak {
        margin-top: 8px;
        font-size: 12px;
        color: var(--ck-fg-2, #c3c9d4);
      }
    `,
  ],
})
export class ForecastPlaygroundComponent {
  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);

  readonly model = input.required<ModelDto>();
  readonly serving = input.required<ServingBlock>();
  /** The exact body the next call sends, for the playground's cURL. */
  readonly requestChange = output<ForecastRequestBody>();

  protected readonly horizon = signal(24);
  protected readonly level = signal(0.8);
  protected readonly series = signal('');
  protected readonly planned = signal<Record<string, number>>({});
  protected readonly running = signal(false);
  protected readonly answer = signal<ForecastAnswer | null>(null);
  protected readonly error = signal<string | null>(null);

  private readonly metrics = computed(() => {
    const metrics = this.model().metrics;
    return isForecast(metrics) ? metrics : null;
  });

  protected readonly frequency = computed(() => this.metrics()?.forecast?.frequency);

  /** The series of a panel, as the model's contract names them. */
  protected readonly levels = computed<string[]>(() => {
    return [...(this.model().signature?.output?.levels ?? [])];
  });

  protected readonly covariates = computed<string[]>(() =>
    (this.model().signature?.inputs ?? [])
      .filter((field) => field.role === 'future')
      .map((field) => field.name),
  );

  /** One step past the horizon the model was built for is not on offer for a direct model. */
  protected readonly maxSteps = computed(() => {
    const spec = this.model().spec ?? {};
    const direct = spec['strategy'] === 'direct' || spec['shape'] === 'multivariate';
    return direct ? Number(spec['horizon'] ?? 24) : 720;
  });

  protected readonly stamps = computed(() =>
    futureStamps(this.metrics()?.forecast?.last_timestamp, this.frequency(), this.horizon()),
  );

  protected readonly canAsk = computed(() => !this.covariates().length || this.stamps() !== null);

  protected readonly request = computed<ForecastRequestBody>(() => {
    const planned = this.planned();
    const covariates = Object.fromEntries(this.covariates().map((name) => [name, Number(planned[name] ?? 0)]));
    return forecastRequest({
      horizon: this.horizon(),
      level: this.level(),
      series: this.levels().length > 1 ? this.series() || this.levels()[0] : null,
      covariates,
      stamps: this.stamps(),
    });
  });

  protected readonly chart = computed(() => {
    const series = this.series() || this.levels()[0] || undefined;
    // Three horizons of the latest actuals: enough to see the daily shape the
    // forecast continues, not so much that the forecast is a sliver.
    const history = recentActuals(this.metrics(), series, Math.max(48, 3 * this.horizon()));
    const answered = answerPoints(this.answer(), this.levels().length > 1 ? series : null);
    return forecastChartSeries(history, answered);
  });

  protected readonly names = computed(() => ({
    actual: this.i18n.t('models.evidence.forecast.actual'),
    pred: this.i18n.t('models.evidence.forecast.pred'),
    interval: this.i18n.t('models.evidence.forecast.interval'),
  }));

  protected readonly peakLine = computed(() => {
    const series = this.levels().length > 1 ? this.series() || this.levels()[0] : null;
    const peak = forecastPeak(answerPoints(this.answer(), series));
    if (!peak) return null;
    return this.i18n.t(peak.upper !== null ? 'models.play.forecast.peak' : 'models.play.forecast.peak_plain', {
      value: this.valueFormat(peak.pred),
      upper: peak.upper !== null ? this.valueFormat(peak.upper) : '',
      when: formatForecastStamp(peak.t, this.frequency(), this.i18n.locale()),
      level: this.percent(this.answer()?.interval_level ?? this.level()),
    });
  });

  protected readonly valueFormat = (value: number): string =>
    value.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 2 });

  constructor() {
    // Open on the question the model was trained to answer.
    effect(() => {
      const spec = this.model().spec ?? {};
      if (typeof spec['horizon'] === 'number') this.horizon.set(spec['horizon'] as number);
      if (typeof spec['interval_level'] === 'number') this.level.set(spec['interval_level'] as number);
    });
    effect(() => this.requestChange.emit(this.request()));
  }

  protected onHorizon(value: unknown): void {
    const steps = Math.round(Number(value));
    if (Number.isFinite(steps) && steps >= 1) this.horizon.set(Math.min(steps, this.maxSteps()));
  }

  protected onLevel(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    if (Number.isFinite(raw)) this.level.set(Math.round(raw * 100) / 100);
  }

  protected plannedValue(name: string): number {
    return this.planned()[name] || 0;
  }

  protected onPlanned(name: string, value: unknown): void {
    const number = Number(value);
    this.planned.update((planned) => ({ ...planned, [name]: Number.isFinite(number) ? number : 0 }));
  }

  protected async run(): Promise<void> {
    if (this.running()) return;
    this.running.set(true);
    this.error.set(null);
    try {
      this.answer.set(await this.models.forecast(this.model().id, this.request()));
    } catch (failure) {
      const detail = (failure as { error?: { detail?: { code?: string; message?: string } } })?.error?.detail;
      const key = servingErrorKey(detail?.code);
      this.error.set(key ? this.i18n.t(key) : (detail?.message ?? this.i18n.t('models.play.forecast.failed')));
    } finally {
      this.running.set(false);
    }
  }

  protected percent(share: number): string {
    return `${Math.round(share * 100)} %`;
  }

  protected round(value: number): number {
    return Math.round(value);
  }
}
