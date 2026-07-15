import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { WorkspaceService } from './workspace.service';
import { WorkspaceFetchService } from './workspace-fetch.service';

/**
 * Raw chunk type — matches the `chunk_type` field produced by the FastAPI
 * orchestrator (see backend/app/api/v1/endpoints/chat.py). We deliberately
 * forward the original shape rather than re-mapping, so callers have access
 * to `decision_step`, `sources`, `reasoning_trace`, etc.
 */
export interface SseChunk {
  chunk_type?: 'text' | 'decision_step' | 'error' | 'eval_pending' | string;
  content?: string;
  decision_step?: unknown;
  sources?: unknown;
  reasoning_trace?: unknown;
  is_final?: boolean;
  // Emitted by ``/api/v1/chat/stream`` at the end of a turn, carrying
  // the canonical Run id so the chat panel can poll
  // ``/evaluation/by-run/{run_id}`` and surface a breach toast.
  run_id?: string;
  // Sentinel emitted by this service once the stream closes cleanly.
  type?: 'done';
  // Back-compat alias some callers used before the chunk_type migration.
  data?: unknown;
}

@Injectable({ providedIn: 'root' })
export class SseService {
  private readonly workspaceService = inject(WorkspaceService);
  private readonly workspaceFetch = inject(WorkspaceFetchService);

  /**
   * POSTs `body` to `url` and streams back SSE frames (`data: <json>\n\n`).
   * Non-JSON frames are forwarded as `{ chunk_type: 'text', content: raw }`.
   * A final `{ type: 'done' }` marker is emitted when the upstream connection
   * terminates or the [DONE] sentinel is received.
   */
  stream(url: string, body: unknown): Observable<SseChunk> {
    return new Observable<SseChunk>((subscriber) => {
      const scope = this.workspaceService.captureRequestScope();
      const controller = new AbortController();
      const streamTimeoutMs = 190_000;
      let invalidated = false;
      let doneEmitted = false;
      let settled = false;

      const unregisterReset = this.workspaceService.registerContextReset(() => {
        invalidated = true;
        controller.abort();
      });
      const emitDone = () => {
        if (doneEmitted || subscriber.closed) return;
        doneEmitted = true;
        subscriber.next({ type: 'done' });
      };
      const cleanup = () => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timeoutHandle);
        unregisterReset();
      };
      const finish = () => {
        // A workspace transition is a cancellation, not a successful end of
        // turn.  Emitting the synthetic `done` marker here would let consumers
        // commit the partial buffer from the previous workspace after the
        // context reset has already started.
        if (!invalidated) emitDone();
        if (!subscriber.closed) subscriber.complete();
        cleanup();
      };
      const timeoutHandle = globalThis.setTimeout(() => {
        if (!subscriber.closed && !invalidated) {
          subscriber.next({
            chunk_type: 'error',
            content: 'La réponse prend trop de temps. La session a été arrêtée proprement.',
            is_final: true,
          });
        }
        controller.abort();
        finish();
      }, streamTimeoutMs);

      void this.workspaceFetch.fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
        workspaceSlug: scope.workspaceSlug,
      }).then(async (response) => {
        if (invalidated || subscriber.closed) {
          finish();
          return;
        }
        if (!response.ok || !response.body) {
          subscriber.next({ chunk_type: 'error', content: `HTTP ${response.status}`, is_final: true });
          finish();
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const emitFrame = (raw: string): boolean => {
          if (invalidated || subscriber.closed) return true;
          let payload = raw;
          if (payload.startsWith(':')) return false;
          if (payload.startsWith('data:')) payload = payload.slice(5).trimStart();
          if (!payload) return false;
          if (payload === '[DONE]') {
            emitDone();
            return true;
          }
          try {
            subscriber.next(JSON.parse(payload) as SseChunk);
          } catch {
            subscriber.next({ chunk_type: 'text', content: payload });
          }
          return false;
        };

        let endOfStream = false;
        while (!endOfStream) {
          const { done, value } = await reader.read();
          if (done || invalidated) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, '\n');

          let sepIndex: number;
          while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sepIndex);
            buffer = buffer.slice(sepIndex + 2);
            const dataLines = frame
              .split('\n')
              .filter((line) => line.startsWith('data:'))
              .map((line) => line.slice(5).trimStart());
            endOfStream = dataLines.length === 0
              ? emitFrame(frame.trim())
              : emitFrame(`data: ${dataLines.join('\n')}`);
            if (endOfStream) break;
          }
        }

        if (!endOfStream && buffer.trim()) emitFrame(buffer.trim());
        if (endOfStream) await reader.cancel().catch(() => undefined);
        finish();
      }).catch((error: unknown) => {
        if (!invalidated && !subscriber.closed && (error as { name?: string })?.name !== 'AbortError') {
          subscriber.next({ chunk_type: 'error', content: String(error), is_final: true });
        }
        finish();
      });

      return () => {
        controller.abort();
        cleanup();
      };
    });
  }
}
