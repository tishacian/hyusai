import { Injectable, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter, startWith } from 'rxjs';

const DEFAULT_FAVICON = '/assets/brand/favicon.svg';
const SENTINEL_CI_FAVICON = '/assets/brand/sentinel-ci-favicon.svg';

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
    const href = path.startsWith('/hypervisor/mission-room') ? SENTINEL_CI_FAVICON : DEFAULT_FAVICON;
    const link = this.ensureIconLink();
    if (link.getAttribute('href') === href) return;
    link.setAttribute('href', href);
    link.setAttribute('type', 'image/svg+xml');
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
