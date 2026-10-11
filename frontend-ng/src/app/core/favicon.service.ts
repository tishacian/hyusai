import { Injectable, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter, merge, startWith } from 'rxjs';
import { WorkspaceService } from './workspace.service';
import { platformBrand } from './platform-brand';
import {
  MISSION_ROOM_EXTENSION,
  missionRoomExtensionState,
} from '@app/features/mission-room/mission-room.extension';

const DEFAULT_FAVICON = '/assets/brand/favicon.svg';
const DEFAULT_TITLE = 'Agentium';

function faviconType(href: string): string {
  if (href.endsWith('.png')) return 'image/png';
  if (href.endsWith('.ico')) return 'image/x-icon';
  return 'image/svg+xml';
}

@Injectable({ providedIn: 'root' })
export class FaviconService {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  private initialized = false;

  init(): void {
    if (this.initialized) return;
    this.initialized = true;

    merge(
      this.router.events.pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      ),
      // Membership settings hydrate after the first navigation. Without this a
      // white-labelled workspace would wear our brand until the next one.
      this.workspace.contextRefresh$,
    )
      .pipe(startWith(null))
      .subscribe(() => this.apply(this.router.url || '/'));
  }

  private apply(url: string): void {
    const path = url.split('?')[0].split('#')[0];
    // A white-labelled workspace owns the tab everywhere it is browsed, the
    // business app and the platform screens alike.
    const brand = platformBrand(this.workspace.current()?.settings);
    const href = brand?.emblem || DEFAULT_FAVICON;
    const link = this.ensureIconLink();
    if (link.getAttribute('href') !== href) {
      link.setAttribute('href', href);
    }
    link.setAttribute('type', faviconType(href));
    if (brand) {
      document.title = brand.label;
      return;
    }
    document.title = (
      path.startsWith(MISSION_ROOM_EXTENSION.routeRoot) &&
      missionRoomExtensionState(this.workspace.current()).enabled
    )
      ? 'Agentium Mission Room'
      : DEFAULT_TITLE;
  }

  private ensureIconLink(): HTMLLinkElement {
    const existing = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (existing) return existing;
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    document.head.appendChild(link);
    return link;
  }
}
