import { Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceService } from './workspace.service';

export interface SseChunk {
  type: 'text' | 'decision_step' | 'error' | 'done';
  content?: string;
  data?: unknown;
}

@Injectable({ providedIn: 'root' })
export class SseService {
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly workspaceService = inject(WorkspaceService);

  stream(url: string, body: unknown): Observable<SseChunk> {
    const subject = new Subject<SseChunk>();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };

    const token = this.tokenStorage.getToken();
    if (token) headers['Authorization'] = token;

    const wsSlug = this.workspaceService.currentSlug();
    if (wsSlug) headers['X-Workspace-Slug'] = wsSlug;

    fetch(url, { method: 'POST', headers, body: JSON.stringify(body) })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          subject.next({ type: 'error', content: `HTTP ${response.status}` });
          subject.complete();
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            try {
              const parsed = JSON.parse(trimmed);
              subject.next(parsed as SseChunk);
            } catch {
              subject.next({ type: 'text', content: trimmed });
            }
          }
        }

        if (buffer.trim()) {
          try {
            subject.next(JSON.parse(buffer.trim()) as SseChunk);
          } catch {
            subject.next({ type: 'text', content: buffer.trim() });
          }
        }

        subject.next({ type: 'done' });
        subject.complete();
      })
      .catch((err) => {
        subject.next({ type: 'error', content: String(err) });
        subject.complete();
      });

    return subject.asObservable();
  }
}
