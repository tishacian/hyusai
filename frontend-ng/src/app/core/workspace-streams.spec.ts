import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { lastValueFrom, toArray } from 'rxjs';
import { RunStreamService } from './run-stream.service';
import { SseService } from './sse.service';
import { WorkspaceFetchService, type WorkspaceFetchInit } from './workspace-fetch.service';
import { WorkspaceService, type WorkspaceContextTransition } from './workspace.service';

class WorkspaceStub {
  private resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  captureRequestScope() {
    return Object.freeze({ workspaceSlug: 'andritz', epoch: 7 });
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  reset(): void {
    const transition = {
      previousSlug: 'andritz',
      nextSlug: 'sentinel-ci',
      previousEpoch: 7,
      nextEpoch: 8,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
  }
}

test('POST and Run SSE streams use the workspace captured at subscription time', async () => {
  const workspace = new WorkspaceStub();
  const attempts: Array<{ url: string; init: WorkspaceFetchInit }> = [];
  const fetcher = {
    fetch: async (input: RequestInfo | URL, init: WorkspaceFetchInit) => {
      attempts.push({ url: String(input), init });
      const body = String(input).includes('/runs/')
        ? 'event: run_start\ndata: {"run_id":"run-1"}\n\nevent: close\ndata: {}\n\n'
        : 'data: {"chunk_type":"text","content":"bonjour"}\n\ndata: [DONE]\n\n';
      return new Response(body, { status: 200 });
    },
  };
  const injector = Injector.create({
    providers: [
      SseService,
      RunStreamService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: WorkspaceFetchService, useValue: fetcher },
    ],
  });

  const chat = await lastValueFrom(injector.get(SseService).stream('/api/v1/chat/stream', {
    query: 'bonjour',
  }).pipe(toArray()));
  const run = await lastValueFrom(injector.get(RunStreamService).streamRun('run-1').pipe(toArray()));

  assert.deepEqual(chat, [
    { chunk_type: 'text', content: 'bonjour' },
    { type: 'done' },
  ]);
  assert.deepEqual(run.map((event) => event.event), ['run_start', 'close']);
  assert.equal(attempts.length, 2);
  for (const attempt of attempts) {
    assert.equal(attempt.init.workspaceSlug, 'andritz');
    assert.ok(attempt.init.signal, `${attempt.url} is abortable`);
  }
});

test('a workspace switch aborts an open POST stream without leaking an error frame', async () => {
  const workspace = new WorkspaceStub();
  const fetcher = {
    fetch: (_input: RequestInfo | URL, init: WorkspaceFetchInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => {
        reject(new DOMException('Aborted', 'AbortError'));
      }, { once: true });
    }),
  };
  const injector = Injector.create({
    providers: [
      SseService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: WorkspaceFetchService, useValue: fetcher },
    ],
  });

  const result = lastValueFrom(
    injector.get(SseService).stream('/api/v1/chat/stream', {}).pipe(toArray()),
  );
  workspace.reset();

  assert.deepEqual(await result, []);
});

test('a workspace switch aborts an open Run stream without a late event', async () => {
  const workspace = new WorkspaceStub();
  const fetcher = {
    fetch: (_input: RequestInfo | URL, init: WorkspaceFetchInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => {
        reject(new DOMException('Aborted', 'AbortError'));
      }, { once: true });
    }),
  };
  const injector = Injector.create({
    providers: [
      RunStreamService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: WorkspaceFetchService, useValue: fetcher },
    ],
  });

  const result = lastValueFrom(
    injector.get(RunStreamService).streamRun('run-old').pipe(toArray()),
  );
  workspace.reset();

  assert.deepEqual(await result, []);
});
