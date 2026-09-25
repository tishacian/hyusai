import { Directive, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import type { NavigationTransitionTrigger } from '@app/core/navigation-telemetry.service';
import type { NavLinkInput } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';

/**
 * Catalogue-backed in-page link. Keeps zone and ancestry by default (I3).
 *
 *   [navLink]="{ type: 'system', ref }"
 *   [navLink]="{ surface: 'knowledge' }"
 *   [navLink]="{ leaf: 'system-flow', ref }"
 *   [navLink]="{ facet: 'runs' }"   // replaceUrl (D3)
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
    event.preventDefault();
    const resolved = this.navigation.resolveLink(this.navLink());
    this.telemetry.registerTrigger(this.navTrigger());
    const state = this.navState();
    void this.router.navigateByUrl(resolved.url, {
      replaceUrl: resolved.replaceUrl,
      ...(state ? { state } : {}),
    });
  }
}
