import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { isCataloguedReturnTo } from './work-return';

/**
 * Shared Work app header (L15): named back link, eyebrow, emblem, title,
 * identifier, status; projected actions on the right.
 */
@Component({
  selector: 'app-work-app-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work-app-header" data-work-chrome="app-header">
      <div class="xp-work-app-header-main">
        <a class="xp-work-back" [routerLink]="backHref()" [attr.title]="backLabel()">
          ← {{ backLabel() }}
        </a>
        <div class="xp-work-app-identity">
          @if (emblem()) {
            <span class="xp-work-app-icon" aria-hidden="true">{{ emblem() }}</span>
          }
          <div class="xp-work-brand">
            @if (eyebrow()) {
              <p class="xp-work-eyebrow">{{ eyebrow() }}</p>
            }
            <h1 [id]="titleId()">{{ title() }}</h1>
            @if (identifier() || status()) {
              <p class="xp-work-app-meta">
                @if (identifier()) { <span>{{ identifier() }}</span> }
                @if (identifier() && status()) { <span aria-hidden="true">·</span> }
                @if (status()) { <span>{{ status() }}</span> }
              </p>
            }
            @if (description()) {
              <p>{{ description() }}</p>
            }
          </div>
        </div>
      </div>
      <div class="xp-work-app-header-actions">
        <ng-content />
      </div>
    </div>
  `,
})
export class WorkAppHeaderComponent {
  private readonly i18n = inject(I18nService);

  readonly title = input.required<string>();
  readonly titleId = input('work-app-title');
  readonly emblem = input<string | null>(null);
  readonly eyebrow = input<string | null>(null);
  readonly identifier = input<string | null>(null);
  readonly status = input<string | null>(null);
  readonly description = input<string | null>(null);
  /** Cockpit returnTo (validated) — when set, back names Cockpit. */
  readonly returnTo = input<string | null>(null);
  readonly returnLabel = input<string | null>(null);
  /** Default back when no returnTo. */
  readonly defaultBackHref = input('/work');
  readonly defaultBackKey = input('experience.work.back_apps');

  readonly backHref = computed(() => {
    const target = this.returnTo();
    return target && isCataloguedReturnTo(target) ? target : this.defaultBackHref();
  });

  readonly backLabel = computed(() => {
    const target = this.returnTo();
    if (target && isCataloguedReturnTo(target)) {
      const object = this.returnLabel()?.trim();
      return object
        ? this.i18n.t('experience.work.back_cockpit_object', { object })
        : this.i18n.t('experience.work.back_cockpit');
    }
    return this.i18n.t(this.defaultBackKey());
  });
}
