export interface SseFrame { event: string; id?: string; data: string; }
export type StreamState = 'connecting' | 'live' | 'reconnecting' | 'disconnected' | 'revoked';

/** Incremental UTF-8 decoding is performed by the caller; this parser accepts split CRLF and multiline data. */
export class ActivitySseParser {
  private buffer = '';
  private data: string[] = [];
  private event = '';
  private id: string | undefined;
  private size = 0;
  constructor(private readonly emit: (frame: SseFrame) => void, private readonly pulse: () => void = () => undefined) {}

  push(chunk: string): void {
    this.buffer += chunk;
    if (this.buffer.length + this.size > 256 * 1024) throw new Error('SSE_FRAME_TOO_LARGE');
    let match: RegExpExecArray | null;
    while ((match = /\r\n|\n|\r(?!$)/.exec(this.buffer))) {
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      this.line(line);
    }
  }

  private line(line: string): void {
    this.pulse();
    if (!line) {
      if (this.data.length) this.emit({ event: this.event || 'message', id: this.id, data: this.data.join('\n') });
      this.data = []; this.event = ''; this.id = undefined; this.size = 0;
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'data') { this.data.push(value); this.size += value.length; }
    if (field === 'event') this.event = value;
    if (field === 'id' && !value.includes('\0')) this.id = value;
  }
}

export interface StreamOptions {
  url: string; cursor?: string; signal: AbortSignal;
  fetch: (url: string, init: RequestInit) => Promise<Response>;
  frame: (frame: SseFrame) => void;
  state: (state: StreamState) => void;
  resync: () => void;
  pulse?: () => void;
  /** Injection points make retry and stalled-stream behavior testable without a live server. */
  delay?: (ms: number, signal: AbortSignal) => Promise<void>;
  staleAfterMs?: number;
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const stop = () => { clearTimeout(timer); signal.removeEventListener('abort', stop); resolve(); };
    const timer = setTimeout(stop, ms);
    signal.addEventListener('abort', stop, { once: true });
    if (signal.aborted) stop();
  });
}

/** Read-only stream reconnects. Mutating commands are never retried by this transport. */
export async function followActivityStream(options: StreamOptions): Promise<void> {
  let cursor = options.cursor || '';
  let failures = 0;
  let revoked = false;
  while (!options.signal.aborted) {
    options.state(failures ? 'reconnecting' : 'connecting');
    const request = new AbortController();
    const abort = () => request.abort();
    options.signal.addEventListener('abort', abort, { once: true });
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const pulse = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => request.abort(), options.staleAfterMs ?? 45000);
      options.pulse?.();
    };
    try {
      const headers: Record<string, string> = { Accept: 'text/event-stream' };
      if (cursor) headers['Last-Event-ID'] = cursor;
      const separator = options.url.includes('?') ? '&' : '?';
      pulse();
      const response = await options.fetch(options.url + (cursor ? `${separator}cursor=${encodeURIComponent(cursor)}` : ''), {
        headers, signal: request.signal, cache: 'no-store',
      });
      if ([401, 403, 404].includes(response.status)) { options.state('revoked'); return; }
      if ([409, 410].includes(response.status)) { cursor = ''; options.resync(); throw new Error('SSE_CURSOR_EXPIRED'); }
      if (!response.ok || !response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('SSE_UNAVAILABLE');
      options.state('live');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = new ActivitySseParser(frame => {
        const permissionError = frame.event === 'error' && JSON.parse(frame.data)?.code === 'ACTIVITY_ACCESS_REVOKED';
        if (permissionError || ['permission_revoked', 'access.revoked', 'revoked'].includes(frame.event)) {
          revoked = true; options.state('revoked'); request.abort(); return;
        }
        if (['reset', 'resync', 'resync_required'].includes(frame.event)) {
          // Discard this connection's remaining frames: they cannot repair a missing journal range.
          cursor = ''; options.resync(); throw new Error('SSE_RESYNC_REQUIRED');
        }
        // Commit the cursor only after the consumer accepted a valid frame.
        options.frame(frame);
        if (frame.id !== undefined) cursor = frame.id;
        failures = 0;
      }, pulse);
      try {
        while (!options.signal.aborted) {
          const chunk = await reader.read();
          if (chunk.done) break;
          parser.push(decoder.decode(chunk.value, { stream: true }));
        }
      } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
    } catch {
      if (options.signal.aborted) break;
    } finally {
      clearTimeout(watchdog); request.abort(); options.signal.removeEventListener('abort', abort);
    }
    if (revoked) return;
    if (options.signal.aborted) break;
    failures++;
    options.state('reconnecting');
    await (options.delay ?? delay)(Math.min(30000, 500 * 2 ** Math.min(failures - 1, 6)), options.signal);
  }
  options.state('disconnected');
}
