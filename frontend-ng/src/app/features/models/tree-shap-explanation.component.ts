/**
 * TreeSHAP on the Play tab: from the base value, field by field, to the output.
 *
 * Signed bars grow left or right of one axis, in neutral tones: the direction
 * is the information, not a verdict, so nothing here is coloured as good or
 * bad. The method and the output space are written out in plain words because
 * a log-odds contribution read as a probability would be a wrong reading of a
 * right number. The "other fields" row keeps the sum closed on screen.
 */
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import {
  formatExplained,
  methodKey,
  outputSpaceKey,
  shapView,
  signed,
  type TreeShapExplanation,
} from './explanations.vm';

@Component({
  selector: 'ck-tree-shap-explanation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (view(); as shap) {
      <section class="ck-shap" data-testid="shap-explanation">
        <div class="ck-section-label">{{ i18n.t('models.play.explain.title') }}</div>
        <p class="ck-hint" data-testid="shap-method">
          {{ i18n.t(methodKey(explanation())) }} ·
          {{ i18n.t(spaceKey(), { label: explanation().class ?? '' }) }}
        </p>
        <div class="ck-shap__row ck-shap__row--edge">
          <span>{{ i18n.t('models.play.explain.base') }}</span>
          <span></span>
          <span class="ck-mono">{{ format(shap.base) }}</span>
        </div>
        @for (bar of shap.bars; track bar.key) {
          <div class="ck-shap__row" [attr.data-testid]="bar.other ? 'shap-other' : 'shap-bar'">
            <span class="ck-shap__name ck-mono">
              @if (bar.other) {
                {{ i18n.t('models.play.explain.other', { count: bar.fields ?? 0 }) }}
              } @else {
                {{ bar.field }} = {{ bar.value }}
              }
            </span>
            <span class="ck-shap__track" aria-hidden="true">
              <span
                class="ck-shap__fill"
                [class.ck-shap__fill--down]="!bar.positive"
                [style.left.%]="bar.positive ? 50 : 50 - bar.width"
                [style.width.%]="bar.width"
              ></span>
            </span>
            <span class="ck-mono ck-shap__value">{{ delta(bar.contribution) }}</span>
          </div>
        }
        <div class="ck-shap__row ck-shap__row--edge">
          <span>{{ i18n.t('models.play.explain.output') }}</span>
          <span></span>
          <span class="ck-mono">{{ format(shap.output) }}</span>
        </div>
        <p class="ck-hint">{{ i18n.t('models.play.explain.hint') }}</p>
      </section>
    }
  `,
  styles: [`
    .ck-shap { margin-top: 16px; }
    .ck-section-label { color: var(--ck-fg-2); font-size: 12px; margin-bottom: 6px; }
    .ck-hint { color: var(--ck-fg-4); font-size: 11px; line-height: 1.5; margin: 6px 0; }
    .ck-shap__row { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(80px, 1fr) auto; gap: 8px; align-items: center; font-size: 11.5px; color: var(--ck-fg-2); padding: 3px 0; }
    .ck-shap__row--edge { color: var(--ck-fg-3); border-top: 1px solid var(--ck-stroke-2); }
    .ck-shap__name { overflow-wrap: anywhere; }
    .ck-shap__track { position: relative; height: 8px; border-left: 0; background: linear-gradient(to right, transparent calc(50% - 0.5px), var(--ck-stroke-2) calc(50% - 0.5px), var(--ck-stroke-2) calc(50% + 0.5px), transparent calc(50% + 0.5px)); }
    .ck-shap__fill { position: absolute; top: 0; height: 100%; background: var(--ck-fg-3); border-radius: 2px; }
    .ck-shap__fill--down { background: var(--ck-fg-4); }
    .ck-shap__value { font-variant-numeric: tabular-nums; text-align: right; }
  `],
})
export class TreeShapExplanationComponent {
  readonly i18n = inject(I18nService);
  readonly explanation = input.required<TreeShapExplanation>();
  protected readonly view = computed(() => shapView(this.explanation()));
  protected readonly methodKey = methodKey;
  protected spaceKey(): string {
    return outputSpaceKey(this.explanation().output_space);
  }
  protected format(value: number): string {
    return formatExplained(value, this.explanation().output_space, this.i18n.locale());
  }
  protected delta(value: number): string {
    return signed(value, this.explanation().output_space, this.i18n.locale());
  }
}
