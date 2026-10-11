import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import type { ModelResolution } from '@app/core/model-catalog';
import type { I18nKey } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';

/** The same public resolution on a draft preview and on a recorded invocation. */
@Component({
  selector: 'app-model-execution',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (resolution(); as model) {
      <dl class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm m-0" data-testid="model-execution">
        <div><dt style="color:var(--ck-fg-3)">{{ i18n.t('skills.models.effective_provider') }}</dt><dd class="m-0">{{ model.provider }}</dd></div>
        <div><dt style="color:var(--ck-fg-3)">{{ i18n.t('skills.param.model') }}</dt><dd class="m-0 break-words">{{ model.returned_model || model.model }}</dd></div>
        <div><dt style="color:var(--ck-fg-3)">{{ i18n.t('skills.models.connection_source') }}</dt><dd class="m-0">{{ source(model.credential_source) }}</dd></div>
        <div><dt style="color:var(--ck-fg-3)">{{ i18n.t('skills.models.model_source') }}</dt><dd class="m-0">{{ source(model.model_source) }}</dd></div>
      </dl>
      @if (model.legacy_provider === 'azure') {
        <p class="text-xs mt-3" style="color:var(--ck-fg-3)">{{ i18n.t('skills.models.legacy_azure_hint') }}</p>
      }
      @if (model.fallback) {
        <p class="text-xs mt-3" style="color:var(--ck-fg-3)">{{ i18n.t('skills.models.fallback_used') }}</p>
      }
      @if (model.fallback_plan?.length) {
        <div class="text-xs mt-3" style="color:var(--ck-fg-3)">
          <span>{{ i18n.t('skills.models.fallback_plan') }}</span>
          @for (candidate of model.fallback_plan; track $index) {
            <p class="m-0 mt-1">{{ candidate['provider'] }} · {{ candidate['model'] }}</p>
          }
        </div>
      }
    }
  `,
})
export class ModelExecutionComponent {
  readonly i18n = inject(I18nService);
  readonly resolution = input<ModelResolution | null>(null);

  source(value: string): string {
    const normalized = value === 'legacy_default' || value === 'published_legacy_default' ? 'legacy' : value;
    const key = `skills.models.source.${normalized}` as I18nKey;
    const translated = this.i18n.t(key);
    return translated === key ? this.i18n.t('skills.models.source.unknown') : translated;
  }
}
