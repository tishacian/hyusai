import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';

/**
 * Author-only strip above Nawa screens (L18). Guests never see Agentium
 * pivots; authors get edit, library and return to Work.
 */
@Component({
  selector: 'app-nawa-creator-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <aside class="nawa-creator-banner" role="status">
      <p class="nawa-creator-banner-copy">
        <strong>{{ i18n.t('experience.nawa.creator.label') }}</strong>
        —
        {{ i18n.t('experience.nawa.creator.hint') }}
      </p>
      <nav class="nawa-creator-banner-links" [attr.aria-label]="i18n.t('experience.nawa.creator.label')">
        <a [routerLink]="editHref()">{{ i18n.t('experience.nawa.creator.edit') }}</a>
        <span class="nawa-creator-banner-sep" aria-hidden="true">·</span>
        <a routerLink="/knowledge">{{ i18n.t('experience.nawa.creator.library') }}</a>
        <span class="nawa-creator-banner-sep" aria-hidden="true">·</span>
        <a routerLink="/work">{{ i18n.t('experience.nawa.creator.back') }}</a>
      </nav>
    </aside>
  `,
})
export class NawaCreatorBannerComponent {
  readonly i18n = inject(I18nService);
  /** Builder / Flow entry; defaults to the Systems list. */
  readonly editHref = input<string | readonly string[]>('/systems');
}
