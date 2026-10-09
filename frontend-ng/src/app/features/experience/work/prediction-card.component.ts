import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { predictionAdvice, predictionContract } from './prediction-contract';

@Component({
  selector: 'xp-prediction-card', standalone: true, imports: [NavLinkDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (advice(); as item) {
      <section class="prediction" [attr.aria-label]="item.label">
        <span class="prediction__label">{{ item.label }}</span>
        <strong class="prediction__value">{{ displayValue() }}</strong>
        @if (item.band) { <span class="prediction__band">{{ item.band.label }}</span> }
        @if (item.interval; as interval) {
          <p>{{ i18n.t('experience.prediction.interval') }} : {{ number(interval.lower) }} – {{ number(interval.upper) }} {{ item.unit }}</p>
        }
        @if (item.task === 'classification') {
          <p>{{ i18n.t('experience.prediction.class_hint') }} « {{ config()?.positive_label }} » · {{ config()?.target }}</p>
        }
        @if (item.task === 'clustering') { <p>{{ i18n.t('experience.prediction.segment_hint') }}</p> }
        <footer>
          <a [navLink]="{ leaf: 'model-doc', ref: item.model.id }">{{ i18n.t('experience.prediction.model') }} · v{{ item.model.version }}</a>
          @if (datasetId(); as id) { <a [navLink]="{ leaf: 'data-doc', ref: id }">{{ i18n.t('experience.prediction.dataset') }}</a> }
          <span>{{ i18n.t('experience.prediction.captured') }} {{ captured() }}</span>
        </footer>
      </section>
    } @else {
      <p class="prediction__empty" role="status">{{ i18n.t(config() ? 'experience.prediction.empty' : 'experience.prediction.invalid') }}</p>
    }
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .prediction { display: grid; gap: var(--ck-space-2, 8px); }
    .prediction__label { color: var(--ck-fg-2); font-size: 13px; }
    .prediction__value { color: var(--ck-fg-1); font-size: 1.65rem; font-variant-numeric: tabular-nums; font-weight: 600; }
    .prediction__band { font-size: 13px; color: var(--ck-fg-1); }
    p, footer, .prediction__empty { color: var(--ck-fg-2); font-size: 13px; line-height: 1.5; margin: 0; }
    footer { display: flex; flex-wrap: wrap; gap: var(--ck-space-2, 8px) var(--ck-space-4, 16px); padding-top: var(--ck-space-2, 8px); border-top: 1px solid var(--ck-stroke-2); }
    a { color: var(--ck-fg-2); text-decoration: none; } a:hover { text-decoration: underline; }
  `],
})
export class PredictionCardComponent {
  readonly value = input<unknown>();
  readonly contract = input<unknown>();
  readonly i18n = inject(I18nService);
  private readonly clock = signal(Date.now());
  readonly config = computed(() => predictionContract(this.contract()));
  readonly advice = computed(() => predictionAdvice(this.value(), this.contract(), this.clock()));
  constructor() {
    const timer = setInterval(() => this.clock.set(Date.now()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }
  number(value: number): string { return new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 2 }).format(value); }
  readonly displayValue = computed(() => {
    const item = this.advice();
    if (!item) return '';
    if (item.task === 'classification') return new Intl.NumberFormat(this.i18n.locale(), { style: 'percent', maximumFractionDigits: 1 }).format(item.score!);
    if (item.task === 'clustering') return `${this.i18n.t('experience.prediction.segment')} ${item.value}`;
    return `${this.number(item.value as number)} ${item.unit}`;
  });
  readonly datasetId = computed(() => {
    const value = this.advice()?.provenance['dataset_id'];
    return typeof value === 'string' && value ? value : null;
  });
  readonly captured = computed(() => {
    const value = this.advice()?.captured_at;
    return value ? new Date(value).toLocaleString(this.i18n.locale()) : '';
  });
}
