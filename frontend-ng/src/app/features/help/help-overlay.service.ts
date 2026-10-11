import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { navigationLeafUrl } from '@app/core/navigation.catalog';

/** Viewport under which help opens as `/help/:guideId` instead of the side panel. */
export const HELP_PANEL_MIN_WIDTH = 768;

export const HELP_GUIDE_IDS = ['start', 'sources', 'systems', 'runs', 'value'] as const;
export type HelpGuideId = (typeof HELP_GUIDE_IDS)[number];

export interface HelpOrigin {
  label: string;
  url: string;
}

export interface HelpOpenOptions {
  guideId?: string | null;
  originLabel?: string | null;
  originUrl?: string | null;
}

/** History state carried when expanding the panel into `/help/:guideId`. */
export interface HelpNavigationState {
  helpOrigin?: HelpOrigin;
}

export function isHelpGuideId(value: string | null | undefined): value is HelpGuideId {
  return !!value && (HELP_GUIDE_IDS as readonly string[]).includes(value);
}

/** Pick the guide that best matches the open page. */
export function guideIdForUrl(url: string): HelpGuideId {
  const path = (url.split('?')[0] || '').toLowerCase();
  if (path.startsWith('/knowledge')) return 'sources';
  if (
    path.startsWith('/systems')
    || path.startsWith('/skills')
    || path.startsWith('/capabilities')
    || path.startsWith('/create')
  ) {
    return 'systems';
  }
  if (path.startsWith('/runs') || path.startsWith('/steering/review')) return 'runs';
  if (path.startsWith('/hypervisor') || path.includes('/value')) return 'value';
  return 'start';
}

export function helpPrefersPanel(width?: number): boolean {
  const w = width ?? (typeof window !== 'undefined' ? window.innerWidth : HELP_PANEL_MIN_WIDTH);
  return w >= HELP_PANEL_MIN_WIDTH;
}

/**
 * Coordinates the global help side-panel (L16).
 *
 * Entry points: title-bar / Work-bar « ? », and `help-guide` nav links on
 * desktop. Narrow viewports and shared `/help/:guideId` URLs use the
 * full-page fallback (Work chrome + named return).
 */
@Injectable({ providedIn: 'root' })
export class HelpOverlayService {
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);

  readonly isOpen = signal(false);
  readonly guideId = signal<HelpGuideId>('start');
  readonly origin = signal<HelpOrigin | null>(null);
  readonly query = signal('');

  constructor() {
    this.workspace.registerContextReset(() => this.reset());
  }

  open(options?: HelpOpenOptions): void {
    const guide = isHelpGuideId(options?.guideId)
      ? options!.guideId!
      : guideIdForUrl(options?.originUrl || this.router.url);
    this.guideId.set(guide);
    this.query.set('');
    const label = options?.originLabel?.trim() || null;
    const url = options?.originUrl?.trim() || this.router.url;
    this.origin.set(label ? { label, url } : this.originFromRouter());
    this.isOpen.set(true);
  }

  /** Open from a `help-guide` link; returns false when the caller should navigate. */
  openFromLink(guideId: string, origin?: HelpOpenOptions): boolean {
    if (!helpPrefersPanel()) return false;
    this.open({
      guideId: isHelpGuideId(guideId) ? guideId : 'start',
      originLabel: origin?.originLabel,
      originUrl: origin?.originUrl,
    });
    return true;
  }

  close(): void {
    this.isOpen.set(false);
  }

  reset(): void {
    this.isOpen.set(false);
    this.guideId.set('start');
    this.origin.set(null);
    this.query.set('');
  }

  selectGuide(guideId: string): void {
    if (!isHelpGuideId(guideId)) return;
    this.guideId.set(guideId);
  }

  setQuery(value: string): void {
    this.query.set(value);
  }

  /** Expand the panel into `/help/:guideId` without changing the help slug space. */
  openFullPage(): void {
    const guideId = this.guideId();
    const origin = this.origin();
    this.close();
    const url = navigationLeafUrl('help-guide', { guideId });
    const state: HelpNavigationState = origin ? { helpOrigin: origin } : {};
    void this.router.navigateByUrl(url, { state });
  }

  private originFromRouter(): HelpOrigin | null {
    const url = this.router.url;
    if (!url || url.startsWith('/help/')) return null;
    const workspace = this.workspace.current()?.name?.trim();
    return workspace ? { label: workspace, url } : { label: url, url };
  }
}
