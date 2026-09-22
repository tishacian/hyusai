import { Injectable, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { navigationRouteContext } from '@app/core/navigation.catalog';
import { filter, map, startWith } from 'rxjs';
import { toSignal } from '@angular/core/rxjs-interop';

export type AssistantObjectKind = 'system' | 'run' | 'skill_invocation';

export interface AssistantObjectContext {
  type: AssistantObjectKind;
  id: string;
  system_id?: string;
  run_id?: string;
  node_id?: string;
  facet?: string;
}

/** Derives the object the user is looking at from canonical routes. */
@Injectable({ providedIn: 'root' })
export class AssistantObjectContextService {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  private readonly pinnedContext = signal<AssistantObjectContext | null>(null);
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly current = computed(() => {
    const url = this.url();
    const route = navigationRouteContext(url);
    const query = new URLSearchParams(url.includes('?') ? url.slice(url.indexOf('?') + 1) : '');
    const id = route.selectedRef;
    if (!id) return null;
    const node_id = query.get('focus_node') || undefined;
    if (route.selectedType === 'system') {
      return { type: 'system' as const, id, system_id: id, node_id, facet: route.query['facet'] };
    }
    if (route.selectedType === 'run') {
      return {
        type: 'run' as const,
        id,
        run_id: id,
        system_id: route.systemId || undefined,
        node_id,
        facet: route.query['facet'],
      };
    }
    if (route.selectedType === 'skill_invocation' && route.runId) {
      return {
        type: 'skill_invocation' as const,
        id,
        run_id: route.runId,
        system_id: route.systemId || undefined,
        node_id,
        facet: route.query['facet'],
      };
    }
    return null;
  });

  readonly effective = computed(() => this.pinnedContext() ?? this.current());
  readonly pinned = this.pinnedContext.asReadonly();

  constructor() {
    this.workspace.registerContextReset(() => {
      this.pinnedContext.set(null);
      this.writePin(null);
    });
    this.pinnedContext.set(this.readPin());
  }

  pin(context: AssistantObjectContext | null = this.current()): void {
    if (!context) return;
    this.pinnedContext.set(context);
    this.writePin(context);
  }

  unpin(): void {
    this.pinnedContext.set(null);
    this.writePin(null);
  }

  isPinned(context: AssistantObjectContext | null): boolean {
    const pinned = this.pinnedContext();
    return !!context && !!pinned && JSON.stringify(pinned) === JSON.stringify(context);
  }

  private readPin(): AssistantObjectContext | null {
    try {
      const raw = globalThis.sessionStorage?.getItem('agentium.assistant-object-pin');
      if (!raw) return null;
      const value = JSON.parse(raw) as AssistantObjectContext;
      if (!value || typeof value.id !== 'string') return null;
      if (value.type !== 'system' && value.type !== 'run' && value.type !== 'skill_invocation') return null;
      return value;
    } catch {
      return null;
    }
  }

  private writePin(context: AssistantObjectContext | null): void {
    try {
      if (!context) globalThis.sessionStorage?.removeItem('agentium.assistant-object-pin');
      else globalThis.sessionStorage?.setItem('agentium.assistant-object-pin', JSON.stringify(context));
    } catch {
      // A blocked browser store still keeps the pin for this page.
    }
  }
}
