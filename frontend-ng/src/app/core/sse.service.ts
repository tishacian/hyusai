import { Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceService } from './workspace.service';

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
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly workspaceService = inject(WorkspaceService);

  /**
   * POSTs `body` to `url` and streams back SSE frames (`data: <json>\n\n`).
   * Non-JSON frames are forwarded as `{ chunk_type: 'text', content: raw }`.
   * A final `{ type: 'done' }` marker is emitted when the upstream connection
   * terminates or the [DONE] sentinel is received.
   */
  stream(url: string, body: unknown): Observable<SseChunk> {
    const subject = new Subject<SseChunk>();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };

    const token = this.tokenStorage.getToken();
    if (token) headers['Authorization'] = token;

    const wsSlug = this.workspaceService.currentSlug();
    if (wsSlug) headers['X-Workspace-Slug'] = wsSlug;

    // `done` must be emitted exactly once per stream, whether triggered by
    // the upstream `[DONE]` sentinel, a natural close, or a transport error.
    let doneEmitted = false;
    const emitDone = () => {
      if (doneEmitted) return;
      doneEmitted = true;
      subject.next({ type: 'done' });
    };

    fetch(url, { method: 'POST', headers, body: JSON.stringify(body) })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          subject.next({ chunk_type: 'error', content: `HTTP ${response.status}`, is_final: true });
          emitDone();
          subject.complete();
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const emitFrame = (raw: string) => {
          // Strip the `data: ` prefix (SSE spec). Comments (`: ...`) are ignored.
          let payload = raw;
          if (payload.startsWith(':')) return;
          if (payload.startsWith('data:')) payload = payload.slice(5).trimStart();
          if (!payload) return;
          if (payload === '[DONE]') {
            emitDone();
            return;
          }
          try {
            subject.next(JSON.parse(payload) as SseChunk);
          } catch {
            subject.next({ chunk_type: 'text', content: payload });
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line (\n\n). Handle CRLF too.
          let sepIndex: number;
          // Normalize CRLF -> LF once per chunk to simplify.
          buffer = buffer.replace(/\r\n/g, '\n');
          while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sepIndex);
            buffer = buffer.slice(sepIndex + 2);
            // A frame may contain multiple `data:` lines — concatenate them.
            const dataLines = frame
              .split('\n')
              .filter((l) => l.startsWith('data:'))
              .map((l) => l.slice(5).trimStart());
            if (dataLines.length === 0) {
              // Unknown frame (e.g. just `event: ...`); forward raw text.
              emitFrame(frame.trim());
            } else {
              emitFrame(`data: ${dataLines.join('\n')}`);
            }
          }
        }

        if (buffer.trim()) emitFrame(buffer.trim());
        emitDone();
        subject.complete();
      })
      .catch((err) => {
        subject.next({ chunk_type: 'error', content: String(err), is_final: true });
        emitDone();
        subject.complete();
      });

    return subject.asObservable();
  }
}
