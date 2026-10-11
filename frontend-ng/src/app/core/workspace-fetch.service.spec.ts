/**
 * Contract tests for authenticated requests that bypass Angular HttpClient.
 *
 * Direct transports must snapshot their tenant scope before dispatch, retain
 * it while a shared token refresh is in flight, and replay no more than once.
 */
import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, runInInjectionContext } from '@angular/core';
import { Router } from '@angular/router';
import { of, Subject } from 'rxjs';
import { AuthApiService, type TokenResponse } from './auth-api.service';
import { AuthRefreshCoordinator } from './auth-refresh-coordinator.service';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceFetchService } from './workspace-fetch.service';
import { WorkspaceService } from './workspace.service';
import { AuthStore } from '../store/auth.store';

class TokenStorageStub {
  token = 'Bearer expired-token';
  refreshToken = 'refresh-token';
  clearCalls = 0;

  getToken(): string | null {
    return this.token;
  }

  getRefreshToken(): string | null {
    return this.refreshToken;
  }

  saveToken(token: string): void {
    this.token = `Bearer ${token}`;
  }

  saveRefreshToken(token: string): void {
    this.refreshToken = token;
  }

  clear(): void {
    this.clearCalls += 1;
    this.token = '';
    this.refreshToken = '';
  }
}

interface FetchAttempt {
  authorization: string | null;
  workspaceSlug: string | null;
}

function createService(options: {
  tokenStorage?: TokenStorageStub;
  currentWorkspace: () => string | null;
  refresh: (refreshToken: string) => ReturnType<AuthApiService['refresh']>;
}): WorkspaceFetchService {
  const injector = Injector.create({
    providers: [
      WorkspaceFetchService,
      AuthRefreshCoordinator,
      { provide: AuthStore, useValue: { clear: () => undefined } },
      { provide: TokenStorageService, useValue: options.tokenStorage ?? new TokenStorageStub() },
      { provide: AuthApiService, useValue: { refresh: options.refresh } },
      {
        provide: Router,
        useValue: { url: '/systems/system-1', navigate: () => Promise.resolve(true) },
      },
      {
        provide: WorkspaceService,
        useValue: {
          currentSlug: options.currentWorkspace,
          captureRequestScope: () => ({ workspaceSlug: options.currentWorkspace(), epoch: 0 }),
        },
      },
    ],
  });
  return runInInjectionContext(injector, () => injector.get(WorkspaceFetchService));
}

function attemptFrom(init: RequestInit | undefined): FetchAttempt {
  const headers = new Headers(init?.headers);
  return {
    authorization: headers.get('Authorization'),
    workspaceSlug: headers.get('X-Workspace-Slug'),
  };
}

test('the current workspace is captured before dispatch and pinned across a 401 retry', async () => {
  const originalFetch = globalThis.fetch;
  const tokenStorage = new TokenStorageStub();
  let currentWorkspace = 'andritz';
  let refreshCalls = 0;
  const attempts: FetchAttempt[] = [];
  const service = createService({
    tokenStorage,
    currentWorkspace: () => currentWorkspace,
    refresh: (refreshToken) => {
      refreshCalls += 1;
      assert.equal(refreshToken, 'refresh-token');
      return of({
        token: 'fresh-token',
        refresh_token: 'fresh-refresh-token',
        expires_in: 300,
        token_type: 'bearer',
      });
    },
  });

  globalThis.fetch = (async (_input, init) => {
    attempts.push(attemptFrom(init));
    if (attempts.length === 1) {
      currentWorkspace = 'sentinel-ci';
      return new Response(null, { status: 401 });
    }
    return new Response('{"ok":true}', { status: 200 });
  }) as typeof fetch;

  try {
    const response = await service.fetch('https://agentium.test/api/v1/systems', {
      method: 'POST',
      body: '{"query":"status"}',
    });

    assert.equal(response.status, 200);
    assert.equal(refreshCalls, 1);
    assert.deepEqual(attempts, [
      { authorization: 'Bearer expired-token', workspaceSlug: 'andritz' },
      { authorization: 'Bearer fresh-token', workspaceSlug: 'andritz' },
    ]);
    assert.equal(tokenStorage.token, 'Bearer fresh-token');
    assert.equal(tokenStorage.refreshToken, 'fresh-refresh-token');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an explicit X-Workspace-Slug header wins over requested and current workspaces', async () => {
  const originalFetch = globalThis.fetch;
  const attempts: FetchAttempt[] = [];
  const service = createService({
    currentWorkspace: () => 'sentinel-ci',
    refresh: () => {
      throw new Error('refresh is not expected');
    },
  });

  globalThis.fetch = (async (_input, init) => {
    attempts.push(attemptFrom(init));
    return new Response(null, { status: 200 });
  }) as typeof fetch;

  try {
    const response = await service.fetch('https://agentium.test/api/v1/systems', {
      workspaceSlug: 'octocity',
      headers: { 'X-Workspace-Slug': 'andritz' },
    });

    assert.equal(response.status, 200);
    assert.deepEqual(attempts, [
      { authorization: 'Bearer expired-token', workspaceSlug: 'andritz' },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a repeated 401 is returned after one retry and is never replayed again', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  let refreshCalls = 0;
  const service = createService({
    currentWorkspace: () => 'andritz',
    refresh: () => {
      refreshCalls += 1;
      return of({
        token: 'fresh-token',
        refresh_token: 'fresh-refresh-token',
        expires_in: 300,
        token_type: 'bearer',
      });
    },
  });

  globalThis.fetch = (async () => {
    fetchCalls += 1;
    return new Response(null, { status: 401 });
  }) as typeof fetch;

  try {
    const response = await service.fetch('https://agentium.test/api/v1/systems');

    assert.equal(response.status, 401);
    assert.equal(fetchCalls, 2);
    assert.equal(refreshCalls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('concurrent direct requests share one refresh exchange', async () => {
  const originalFetch = globalThis.fetch;
  const refreshResult = new Subject<TokenResponse>();
  let refreshCalls = 0;
  const attempts = new Map<string, FetchAttempt[]>();
  const service = createService({
    currentWorkspace: () => 'andritz',
    refresh: () => {
      refreshCalls += 1;
      return refreshResult;
    },
  });

  globalThis.fetch = (async (input, init) => {
    const url = String(input);
    const requestAttempts = attempts.get(url) ?? [];
    const attempt = attemptFrom(init);
    requestAttempts.push(attempt);
    attempts.set(url, requestAttempts);
    return new Response(null, {
      status: attempt.authorization === 'Bearer expired-token' ? 401 : 200,
    });
  }) as typeof fetch;

  try {
    const first = service.fetch('https://agentium.test/api/v1/systems', {
      workspaceSlug: 'andritz',
    });
    const second = service.fetch('https://agentium.test/api/v1/client360/summary', {
      workspaceSlug: 'sentinel-ci',
    });

    await Promise.resolve();
    await Promise.resolve();
    assert.equal(refreshCalls, 1, 'both 401 responses must share the coordinator');

    refreshResult.next({
      token: 'fresh-token',
      refresh_token: 'fresh-refresh-token',
      expires_in: 300,
      token_type: 'bearer',
    });
    refreshResult.complete();

    const responses = await Promise.all([first, second]);
    assert.deepEqual(responses.map((response) => response.status), [200, 200]);
    assert.equal(refreshCalls, 1);
    for (const [url, requestAttempts] of attempts) {
      const expectedWorkspace = url.includes('/client360/') ? 'sentinel-ci' : 'andritz';
      assert.deepEqual(requestAttempts, [
        { authorization: 'Bearer expired-token', workspaceSlug: expectedWorkspace },
        { authorization: 'Bearer fresh-token', workspaceSlug: expectedWorkspace },
      ], `${url} keeps its workspace while waiting for refresh`);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an abort during refresh prevents the retry dispatch', async () => {
  const originalFetch = globalThis.fetch;
  const refreshResult = new Subject<TokenResponse>();
  let fetchCalls = 0;
  const service = createService({
    currentWorkspace: () => 'andritz',
    refresh: () => refreshResult,
  });
  const controller = new AbortController();

  globalThis.fetch = (async () => {
    fetchCalls += 1;
    return new Response(null, { status: 401 });
  }) as typeof fetch;

  try {
    const pending = service.fetch('https://agentium.test/api/v1/systems', {
      signal: controller.signal,
    });
    await Promise.resolve();
    await Promise.resolve();
    controller.abort();
    refreshResult.next({
      token: 'fresh-token',
      refresh_token: 'fresh-refresh-token',
      expires_in: 300,
      token_type: 'bearer',
    });
    refreshResult.complete();

    await assert.rejects(pending, (error: unknown) => (
      error instanceof DOMException && error.name === 'AbortError'
    ));
    assert.equal(fetchCalls, 1, 'an aborted stream must not enter its retry attempt');
  } finally {
    globalThis.fetch = originalFetch;
  }
});
