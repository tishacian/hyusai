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
    const href = DEFAULT_FAVICON;
    const type = 'image/svg+xml';
    const link = this.ensureIconLink();
    if (link.getAttribute('href') !== href) {
      link.setAttribute('href', href);
    }
    link.setAttribute('type', type);
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
