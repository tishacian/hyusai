import { Injectable, inject, signal } from '@angular/core';
import { type Navigation, NavigationStart, Router } from '@angular/router';
import { matchAgentiumSurface, navigationRouteContext, navigationSurfaceUrl } from './navigation.catalog';
import { WorkspaceService } from './workspace.service';

/** What a screen with unsaved work tells the switcher, instead of opening confirm(). */
export interface PendingChangesSummary {
  readonly label: string;
  readonly count: number;
  discard(): void;
}

export type WorkspaceSwitchState =
  | { readonly phase: 'idle' }
  | { readonly phase: 'pending'; readonly slug: string }
  | { readonly phase: 'suspended'; readonly slug: string; readonly label: string; readonly count: number }
  | { readonly phase: 'failed'; readonly slug: string }
  | { readonly phase: 'cancelled'; readonly slug: string }
  | {
    readonly phase: 'switched';
    readonly slug: string;
    readonly previousSlug: string | null;
    readonly url: string;
  };

interface SwitchAttempt {
  readonly slug: string;
  readonly destination: string | null;
  committed: boolean;
  cancelled: boolean;
  refusal: PendingChangesSummary | null;
}

/**
 * The page the user is on, in the next workspace: same zone and surface, no
 * object id. `/systems/X?facet=runs` becomes `/systems`; a view of the surface
 * itself (`/hypervisor?facet=couts`) is kept.
 */
export function workspaceSwitchTarget(url: string, fromSlug: string | null, toSlug: string): string {
  const context = navigationRouteContext(url);
  const segments = context.path.split('/').filter(Boolean);
  if (segments[0] === 'workspace' && fromSlug && segments[1] === encodeURIComponent(fromSlug)) {
    return `/${['workspace', encodeURIComponent(toSlug), ...segments.slice(2)].join('/')}`;
  }
  const surface = matchAgentiumSurface(context.path);
  const route = surface?.route.split('?')[0] ?? '';
  const home = route.includes('/:') ? matchAgentiumSurface(route.slice(0, route.indexOf('/:'))) : surface;
  if (!home || home.route.includes('/:')) return '/';
  return navigationSurfaceUrl(home.id, {
    lens: context.lens,
    facet: context.path === home.route.split('?')[0] ? context.query['facet'] : null,
  });
}

/**
 * One owner for changing tenant, shared by the Cockpit title bar and the
 * business header. A switch is a single `replaceUrl` navigation: the shell
 * guard publishes the next workspace only once every CanDeactivate guard of
 * the current one has let the page go.
 */
@Injectable({ providedIn: 'root' })
export class WorkspaceSwitchService {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  private readonly current = signal<WorkspaceSwitchState>({ phase: 'idle' });
  private attempt: SwitchAttempt | null = null;
  private suspended: SwitchAttempt | null = null;

  readonly state = this.current.asReadonly();

  constructor() {
    this.router.events.subscribe((event) => {
      if (!(event instanceof NavigationStart) || this.attempt) return;
      this.suspended = null;
      if (this.current().phase !== 'idle') this.current.set({ phase: 'idle' });
    });
  }

  async switch(slug: string, destination: string | null = null): Promise<WorkspaceSwitchState> {
    const from = this.workspace.currentSlug();
    if (
      this.attempt
      || slug === from
      || !this.workspace.workspaces().some((workspace) => workspace.slug === slug)
    ) {
      return this.current();
    }
    const attempt: SwitchAttempt = { slug, destination, committed: false, cancelled: false, refusal: null };
    this.attempt = attempt;
    this.suspended = null;
    this.current.set({ phase: 'pending', slug });
    await this.router
      .navigateByUrl(destination ?? workspaceSwitchTarget(this.router.url, from, slug), {
        replaceUrl: true,
        onSameUrlNavigation: 'reload',
        info: attempt,
      })
      .catch(() => false);
    this.attempt = null;
    this.current.set(this.outcome(attempt, from));
    return this.current();
  }

  /**
   * Called by the shell guard. `null` means the navigation is not a switch;
   * otherwise publishes the pending workspace and tells whether it may proceed.
   */
  commit(navigation: Navigation | null): boolean | null {
    const attempt = this.attempt;
    if (!attempt || navigation?.extras.info !== attempt) return null;
    if (attempt.cancelled) return false;
    if (!attempt.committed) attempt.committed = this.workspace.switchWorkspace(attempt.slug);
    return attempt.committed;
  }

  /** A CanDeactivate guard hands over its refusal; true when a switch takes it. */
  suspend(summary: PendingChangesSummary): boolean {
    const attempt = this.attempt;
    if (!attempt || attempt.committed || this.router.currentNavigation()?.extras.info !== attempt) {
      return false;
    }
    attempt.refusal = summary;
    return true;
  }

  /** Escape or « Rester ici »: true when a switch was abandoned before B was published. */
  cancel(): boolean {
    const state = this.current();
    if (state.phase === 'suspended') {
      this.suspended = null;
      this.current.set({ phase: 'cancelled', slug: state.slug });
      return true;
    }
    const attempt = this.attempt;
    if (!attempt || attempt.committed) return false;
    attempt.cancelled = true;
    const navigation = this.router.currentNavigation();
    if (navigation?.extras.info === attempt) navigation.abort();
    return true;
  }

  /** « Abandonner et changer ». */
  discardAndSwitch(): Promise<WorkspaceSwitchState> {
    const suspended = this.suspended;
    if (!suspended?.refusal) return Promise.resolve(this.current());
    this.suspended = null;
    suspended.refusal.discard();
    return this.switch(suspended.slug, suspended.destination);
  }

  /** Clears an announcement once it has been read. */
  dismiss(): void {
    const { phase } = this.current();
    if (phase === 'switched' || phase === 'failed' || phase === 'cancelled') {
      this.current.set({ phase: 'idle' });
    }
  }

  private outcome(attempt: SwitchAttempt, from: string | null): WorkspaceSwitchState {
    const { slug } = attempt;
    if (attempt.committed) return { phase: 'switched', slug, previousSlug: from, url: this.router.url };
    if (attempt.refusal) {
      this.suspended = attempt;
      return { phase: 'suspended', slug, label: attempt.refusal.label, count: attempt.refusal.count };
    }
    return { phase: attempt.cancelled ? 'cancelled' : 'failed', slug };
  }
}
