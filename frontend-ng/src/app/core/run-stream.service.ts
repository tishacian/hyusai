import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { WorkspaceService } from './workspace.service';
import { WorkspaceFetchService } from './workspace-fetch.service';

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
  private readonly workspaceService = inject(WorkspaceService);
  private readonly workspaceFetch = inject(WorkspaceFetchService);

  /**
   * Subscribe to the SSE stream for a single Run. The returned
   * Observable completes when either the backend emits a ``close``
   * event, the connection drops, or the consumer unsubscribes (which
   * aborts the underlying ``fetch``).
   */
  streamRun(runId: string): Observable<RunStreamEvent> {
    return new Observable<RunStreamEvent>((observer) => {
      const scope = this.workspaceService.captureRequestScope();
      const abort = new AbortController();
      const url = `/api/v1/runs/${encodeURIComponent(runId)}/stream`;
      let invalidated = false;
      let settled = false;
      const unregisterReset = this.workspaceService.registerContextReset(() => {
        invalidated = true;
        abort.abort();
      });
      const cleanup = () => {
        if (settled) return;
        settled = true;
        unregisterReset();
      };

      void this.workspaceFetch.fetch(url, {
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
        signal: abort.signal,
        workspaceSlug: scope.workspaceSlug,
      }).then(async (response) => {
        if (invalidated || observer.closed) {
          if (!observer.closed) observer.complete();
          cleanup();
          return;
        }
        if (!response.ok || !response.body) {
          observer.error(new Error(`HTTP ${response.status}`));
          cleanup();
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!invalidated) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, '\n');

          let sep: number;
          while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            const parsed = this.parseFrame(frame);
            if (parsed && !invalidated && !observer.closed) observer.next(parsed);
          }
        }

        if (!invalidated && buffer.trim()) {
          const parsed = this.parseFrame(buffer.trim());
          if (parsed && !observer.closed) observer.next(parsed);
        }

        if (!observer.closed) observer.complete();
        cleanup();
      }).catch((error: unknown) => {
        if (invalidated || (error as { name?: string })?.name === 'AbortError') {
          if (!observer.closed) observer.complete();
        } else if (!observer.closed) {
          observer.error(error);
        }
        cleanup();
      });

      return () => {
        abort.abort();
        cleanup();
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
