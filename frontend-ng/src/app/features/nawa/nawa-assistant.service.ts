/**
 * NAWA WE — the knowledge assistant's data access.
 *
 * No new endpoint: the workspace already owns an always-on chat System (created
 * by the platform when the knowledge scope was declared) and the assistant is
 * that System asked through `POST /chat/completion`. The panel resolves it by
 * type rather than by a pinned id, so the surface survives a reseed.
 *
 * `response_language` is set explicitly. Left unset, the backend infers the
 * language from the question and falls back to French when it cannot tell — the
 * WE surface is English, so it says so rather than hoping the guess lands.
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, of, shareReplay, switchMap } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import type { AssistantAnswerPayload } from './nawa-assistant';

/** What the panel needs to ask a question: the System, and what it may read. */
export interface AssistantBinding {
  systemId: string;
  knowledgeScope: string | null;
}

@Injectable({ providedIn: 'root' })
export class NawaAssistantService {
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);

  private binding$: Observable<AssistantBinding | null> | null = null;

  /** The workspace's always-on chat System, resolved once per app load. */
  binding(): Observable<AssistantBinding | null> {
    this.binding$ ??= this.canonical.listSystems().pipe(
      map((systems) => {
        const chat = systems.find((system) => settingsOf(system)['system_type'] === 'workspace_chat');
        if (!chat) return null;
        const scope = settingsOf(chat)['knowledge_scope'];
        return {
          systemId: chat.id,
          knowledgeScope: typeof scope === 'string' && scope ? scope : null,
        };
      }),
      catchError(() => of(null)),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    return this.binding$;
  }

  /**
   * One question, one grounded answer. Non-streaming on purpose: the surface
   * shows the retrieval as a step rather than as a typewriter, and a single
   * response is what makes the citation list arrive with the sentence that
   * refers to it.
   */
  ask(query: string): Observable<AssistantAnswerPayload | null> {
    return this.binding().pipe(
      switchMap((binding) => {
        if (!binding) return of(null);
        return this.http
          .post<AssistantAnswerPayload>('/api/v1/chat/completion', {
            query,
            agent_id: binding.systemId,
            knowledge_scope: binding.knowledgeScope,
            stream: false,
            include_sources: true,
            include_reasoning: false,
            response_language: 'en',
            ui_locale: 'en',
          })
          .pipe(catchError(() => of(null)));
      }),
    );
  }
}

function settingsOf(system: System): Record<string, unknown> {
  return (system.settings ?? {}) as Record<string, unknown>;
}
