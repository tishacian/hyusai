import { Injectable, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter, startWith } from 'rxjs';
import { WorkspaceService } from './workspace.service';
import {
  MISSION_ROOM_EXTENSION,
  missionRoomExtensionState,
} from '@app/features/mission-room/mission-room.extension';

const DEFAULT_FAVICON = '/assets/brand/favicon.svg';
const DEFAULT_TITLE = 'Agentium';

/** White-labelled customer app: the browser tab carries its brand, not ours. */
const NAWA_ROUTE_ROOT = '/nawa';
const NAWA_FAVICON = '/assets/nawa/nawa-logo.png';
const NAWA_TITLE = 'NAWA WE';

@Injectable({ providedIn: 'root' })
export class FaviconService {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  private initialized = false;

  init(): void {
    if (this.initialized) return;
    this.initialized = true;

    this.router.events
      .pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
        startWith(null),
      )
      .subscribe((event) => {
        const url = event?.urlAfterRedirects || this.router.url || '/';
        this.apply(url);
      });
  }

  private apply(url: string): void {
    const path = url.split('?')[0].split('#')[0];
    const nawa = path === NAWA_ROUTE_ROOT || path.startsWith(`${NAWA_ROUTE_ROOT}/`);
    const href = nawa ? NAWA_FAVICON : DEFAULT_FAVICON;
    const type = nawa ? 'image/png' : 'image/svg+xml';
    const link = this.ensureIconLink();
    if (link.getAttribute('href') !== href) {
      link.setAttribute('href', href);
    }
    link.setAttribute('type', type);
    if (nawa) {
      document.title = NAWA_TITLE;
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
