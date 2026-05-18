import { Injectable, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter, startWith } from 'rxjs';

const DEFAULT_FAVICON = '/assets/brand/favicon.svg';
const DEFAULT_TITLE = 'Agentium';
const SENTINEL_CI_FAVICON = '/assets/brand/sentinel-ci-favicon.png?v=20260518-1';
const SENTINEL_CI_TITLE = 'SENTINEL-CI';

@Injectable({ providedIn: 'root' })
export class FaviconService {
  private readonly router = inject(Router);
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
    const isSentinel = path.startsWith('/hypervisor/mission-room');
    const href = isSentinel ? SENTINEL_CI_FAVICON : DEFAULT_FAVICON;
    const type = isSentinel ? 'image/png' : 'image/svg+xml';
    const link = this.ensureIconLink();
    if (link.getAttribute('href') !== href) {
      link.setAttribute('href', href);
    }
    link.setAttribute('type', type);
    document.title = isSentinel ? SENTINEL_CI_TITLE : DEFAULT_TITLE;
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
