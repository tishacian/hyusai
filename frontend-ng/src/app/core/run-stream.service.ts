import { Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceService } from './workspace.service';

/**
 * One parsed frame from the ``GET /runs/:id/stream`` SSE endpoint.
 *
 * The backend tags every frame with an ``event:`` name that mirrors
 * walker checkpoints (``run_start``, ``node_start``, ``node_end``,
 * ``hitl_pause``, ``hitl_resume``, ``run_end``) plus two meta events
 * (``snapshot``, ``close``). Consumers switch on `event` and treat
 * `data` as opaque JSON.
 */
export interface RunStreamEvent {
  event: string;
  data: Record<string, unknown>;
}

/**
 * Lightweight SSE client tailored for Run streaming.
 *
 * We cannot use the native ``EventSource`` because it cannot set the
 * ``Authorization`` and ``X-Workspace-Slug`` headers that the API
 * contract requires. ``fetch`` with a streaming body reader solves
 * this cleanly while preserving the SSE ``event: <name>`` grammar that
 * {@link SseService} strips.
 */
@Injectable({ providedIn: 'root' })
export class RunStreamService {
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly workspaceService = inject(WorkspaceService);

  /**
   * Subscribe to the SSE stream for a single Run. The returned
   * Observable completes when either the backend emits a ``close``
   * event, the connection drops, or the consumer unsubscribes (which
   * aborts the underlying ``fetch``).
   */
  streamRun(runId: string): Observable<RunStreamEvent> {
    const subject = new Subject<RunStreamEvent>();
    const abort = new AbortController();
    const headers: Record<string, string> = { Accept: 'text/event-stream' };

    const token = this.tokenStorage.getToken();
    if (token) headers['Authorization'] = token;
    const wsSlug = this.workspaceService.currentSlug();
    if (wsSlug) headers['X-Workspace-Slug'] = wsSlug;

    const url = `/api/v1/runs/${encodeURIComponent(runId)}/stream`;

    fetch(url, { method: 'GET', headers, signal: abort.signal })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          subject.error(new Error(`HTTP ${response.status}`));
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, '\n');

          let sep: number;
          while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            const parsed = this.parseFrame(frame);
            if (parsed) subject.next(parsed);
          }
        }

        if (buffer.trim()) {
          const parsed = this.parseFrame(buffer.trim());
          if (parsed) subject.next(parsed);
        }

        subject.complete();
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') {
          subject.complete();
        } else {
          subject.error(err);
        }
      });

    return new Observable<RunStreamEvent>((observer) => {
      const sub = subject.subscribe(observer);
      return () => {
        sub.unsubscribe();
        abort.abort();
      };
    });
  }

  /**
   * Parse a single SSE frame of shape::
   *
   *     event: node_start
   *     data: {"run_id":"...","node_id":"n1"}
   *
   * Comment-only frames (``: keep-alive``) and malformed frames are
   * silently dropped so callers only see semantic events.
   */
  private parseFrame(frame: string): RunStreamEvent | null {
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const line of frame.split('\n')) {
      if (!line || line.startsWith(':')) continue;
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) return null;
    const raw = dataLines.join('\n');
    try {
      const data = JSON.parse(raw) as Record<string, unknown>;
      return { event: eventName, data };
    } catch {
      return { event: eventName, data: { raw } };
    }
  }
}
