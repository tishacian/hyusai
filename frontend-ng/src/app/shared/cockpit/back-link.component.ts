import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import type { NavLinkInput } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';

/**
 * Sole Cockpit "Retour" (D6): breadcrumb parent, else an explicit fallback
 * surface (connector pages → Resources), else the list of the current surface.
 */
@Component({
  selector: 'ck-back-link',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (visible()) {
      <a
        class="ck-back-link"
        [attr.href]="href()"
        (click)="onClick($event)"
      >
        {{ i18n.t('nav.back_to', { label: label() }) }}
      </a>
    }
  `,
  styles: [`
    .ck-back-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-family: var(--ck-font-sans);
      font-size: 12px;
      letter-spacing: 0;
      text-transform: none;
      color: var(--ck-fg-3);
      text-decoration: none;
    }
    .ck-back-link:hover { color: var(--ck-fg-1); }
  `],
})
export class CkBackLinkComponent {
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly telemetry = inject(NavigationTelemetryService);
  readonly i18n = inject(I18nService);

  readonly fallback = input<NavLinkInput | null>(null);

  readonly visible = computed(() => Boolean(this.href()));
  readonly href = computed(() => {
    if (this.navigation.parentNode()) return this.navigation.parentUrl();
    const fallback = this.fallback();
    if (fallback) return this.navigation.resolveLink(fallback).url;
    const url = this.navigation.parentUrl();
    return url && url !== this.navigation.route().path ? url : '';
  });
  readonly label = computed(() => {
    if (this.navigation.parentNode()) return this.navigation.parentLabel();
    const fallback = this.fallback();
    if (fallback) {
      if ('surface' in fallback) {
        return this.i18n.t(`nav.${fallback.surface}` as 'nav.resources');
      }
      return this.navigation.parentLabel();
    }
    return this.navigation.parentLabel();
  });

  onClick(event: MouseEvent): void {
    if (
      event.defaultPrevented
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) {
      return;
    }
    event.preventDefault();
    const url = this.href();
    if (!url) return;
    this.telemetry.registerTrigger('inpage');
    void this.router.navigateByUrl(url);
  }
}
