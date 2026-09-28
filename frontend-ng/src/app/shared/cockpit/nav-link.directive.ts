import { Directive, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import type { NavigationTransitionTrigger } from '@app/core/navigation-telemetry.service';
import type { NavLinkInput } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { HelpOverlayService } from '@app/features/help/help-overlay.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';

/**
 * Catalogue-backed in-page link. Keeps zone and ancestry by default (I3).
 *
 *   [navLink]="{ type: 'system', ref }"
 *   [navLink]="{ surface: 'knowledge' }"
 *   [navLink]="{ leaf: 'system-flow', ref }"
 *   [navLink]="{ facet: 'runs' }"   // replaceUrl (D3)
 *
 * `help-guide` opens the help panel on desktop (L16); shared / narrow
 * clicks keep the `/help/:guideId` href navigation.
 */
@Directive({
  selector: 'a[navLink]',
  standalone: true,
  host: {
    '[attr.href]': 'href()',
    '(click)': 'onClick($event)',
  },
})
export class NavLinkDirective {
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly telemetry = inject(NavigationTelemetryService);
  private readonly help = inject(HelpOverlayService);
  private readonly workspace = inject(WorkspaceService);
  private readonly i18n = inject(I18nService);

  readonly navLink = input.required<NavLinkInput>();
  readonly navTrigger = input<NavigationTransitionTrigger>('inpage');
  /** Optional `history.state` (L10 provenance). Not encoded in the URL. */
  readonly navState = input<Record<string, unknown> | null>(null);

  readonly href = computed(() => this.navigation.resolveLink(this.navLink()).url);

  onClick(event: MouseEvent): void {
    const anchor = event.currentTarget as HTMLAnchorElement | null;
    if (
      event.defaultPrevented
      || (anchor?.target && anchor.target !== '_self')
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) {
      return;
    }
    const input = this.navLink();
    if ('leaf' in input && input.leaf === 'help-guide') {
      const guideId = input.params?.['guideId'] || input.ref || 'start';
      // L16 — same origin rule as title-bar « ? »: page title, not workspace name.
      const heading = typeof document !== 'undefined'
        ? document.querySelector<HTMLElement>('main h1, [role="main"] h1, h1')?.textContent?.trim()
        : '';
      const originLabel = heading || this.i18n.t('experience.work.title');
      if (this.help.openFromLink(guideId, {
        originLabel,
        originUrl: this.router.url,
      })) {
        event.preventDefault();
        this.telemetry.registerTrigger(this.navTrigger());
        return;
      }
    }
    event.preventDefault();
    const resolved = this.navigation.resolveLink(input);
    this.telemetry.registerTrigger(this.navTrigger());
    const state = this.navState();
    void this.router.navigateByUrl(resolved.url, {
      replaceUrl: resolved.replaceUrl,
      ...(state ? { state } : {}),
    });
  }
}
