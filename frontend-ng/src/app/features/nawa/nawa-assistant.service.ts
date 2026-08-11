/**
 * NAWA WE — the assistant's data access.
 *
 * One endpoint, `POST /api/v1/assistant/turns`. The screen no longer resolves a
 * chat System, no longer picks a knowledge scope and no longer decides what
 * kind of question it is holding: the engine reads all of that from the
 * workspace configuration and answers one turn, calling whatever tools it needs
 * on the way.
 *
 * What stays here is the one thing the server cannot do: the published policies
 * are served from this app's own assets, so a citation can quote the sentence
 * the answer rests on instead of the 1200-character window retrieval returned.
 * The files fetched are the files that were indexed, so nothing is quoted that
 * the customer cannot open.
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, forkJoin, map, of, shareReplay, switchMap } from 'rxjs';
import { catchError } from 'rxjs/operators';
import type { NawaUseCase } from './nawa-itsd.model';
import {
  ASSISTANT_TURNS_URL,
  citedDocuments,
  projectEngineTurn,
  type AssistantTurnPayload,
  type AssistantTurnRequest,
  type EngineTurn,
} from './nawa-engine';

/** A turn as the screen consumes it: what to render, and the thread it belongs to. */
export interface NawaAnsweredTurn {
  /** Null when the engine could not be reached. `turn` then says so. */
  payload: AssistantTurnPayload | null;
  turn: EngineTurn;
}

export interface NawaRenderOptions {
  catalogue: readonly NawaUseCase[];
  elapsedMs?: number;
}

@Injectable({ providedIn: 'root' })
export class NawaAssistantService {
  private readonly http = inject(HttpClient);

  private readonly documents = new Map<string, Observable<string | null>>();

  /**
   * One utterance, one turn.
   *
   * An engine error is not thrown at the screen: the surface has a transcript
   * to keep and a thread to hold, so a failure comes back as a null payload and
   * a turn that states plainly that nothing was searched.
   */
  ask(request: AssistantTurnRequest, options: NawaRenderOptions): Observable<NawaAnsweredTurn> {
    const started = Date.now();
    return this.http
      .post<AssistantTurnPayload>(ASSISTANT_TURNS_URL, {
        text: request.text,
        session_id: request.session_id ?? null,
        surface: request.surface ?? 'text',
        session_context: request.session_context ?? {},
      })
      .pipe(
        catchError(() => of(null)),
        switchMap((payload) =>
          this.render(request.text, payload, {
            ...options,
            elapsedMs: options.elapsedMs ?? Date.now() - started,
          }).pipe(map((turn) => ({ payload, turn }))),
        ),
      );
  }

  /**
   * Render a turn payload, whichever surface it arrived on.
   *
   * The voice gateway emits the body of `POST /assistant/turns` verbatim in its
   * `assistant.answer` event, so a spoken turn and a typed turn are rendered by
   * the same call — that identity is the contract, and it is what stops the two
   * surfaces from becoming two assistants.
   */
  render(
    question: string,
    payload: AssistantTurnPayload | null,
    options: NawaRenderOptions,
  ): Observable<EngineTurn> {
    const names = citedDocuments(payload);
    if (!names.length) {
      return of(projectEngineTurn(question, payload, { catalogue: options.catalogue, elapsedMs: options.elapsedMs }));
    }
    return forkJoin(names.map((name) => this.document(name))).pipe(
      map((texts) => {
        const documents: Record<string, string | null> = {};
        names.forEach((name, position) => (documents[name] = texts[position]));
        return projectEngineTurn(question, payload, {
          catalogue: options.catalogue,
          documents,
          elapsedMs: options.elapsedMs,
        });
      }),
    );
  }

  /** One published policy, by file name, fetched once per app load. */
  private document(filename: string | null | undefined): Observable<string | null> {
    // Only ever a bare file name: the value comes from a server payload and is
    // about to become a URL.
    const name = String(filename ?? '').replace(/^.*\//, '');
    if (!/^[a-z0-9._-]+\.md$/i.test(name)) return of(null);
    this.documents.set(
      name,
      this.documents.get(name)
        ?? this.http
          .get(`assets/nawa/knowledge/${name}`, { responseType: 'text' })
          .pipe(
            catchError(() => of(null)),
            shareReplay({ bufferSize: 1, refCount: false }),
          ),
    );
    return this.documents.get(name)!;
  }
}
