/**
 * Navigation contract tests for authenticated HTTP retries.
 *
 * A refresh retry must remain in the workspace selected when the request was
 * issued. Dropping X-Workspace-Slug lets the backend fall back to another
 * membership, which is a context switch rather than a harmless missing
 * header.
 */
import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  HttpErrorResponse,
  HttpHeaders,
  HttpRequest,
  HttpResponse,
  type HttpEvent,
} from '@angular/common/http';
import { Injector, runInInjectionContext } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom, of, Subject, throwError, type Observable } from 'rxjs';
import { AuthApiService } from './auth-api.service';
import { AuthRefreshCoordinator } from './auth-refresh-coordinator.service';
import { authInterceptor } from './auth.interceptor';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceFetchService } from './workspace-fetch.service';
import { WorkspaceService } from './workspace.service';

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

test('401 refresh retry preserves the active X-Workspace-Slug', async () => {
  const tokenStorage = new TokenStorageStub();
  const seen: HttpRequest<unknown>[] = [];
  const authApi = {
    refresh: (refreshToken: string) => {
      assert.equal(refreshToken, 'refresh-token');
      return of({
        token: 'fresh-token',
        refresh_token: 'fresh-refresh-token',
        expires_in: 300,
        token_type: 'bearer',
      });
    },
  };
  const router = {
    url: '/systems/system-1',
    navigate: () => Promise.resolve(true),
  };
  const workspace = { currentSlug: () => 'andritz' };
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      { provide: AuthApiService, useValue: authApi },
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  const original = new HttpRequest('GET', '/api/v1/systems', {
    headers: new HttpHeaders(),
  });
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    seen.push(request);
    if (seen.length === 1) {
      return throwError(() => new HttpErrorResponse({ status: 401 }));
    }
    return of(new HttpResponse({ status: 200, body: { ok: true } }));
  };

  await firstValueFrom(
    runInInjectionContext(injector, () => authInterceptor(original, next)),
  );

  assert.equal(seen.length, 2, 'the failed request is retried once');
  assert.equal(seen[0].headers.get('Authorization'), 'Bearer expired-token');
  assert.equal(seen[0].headers.get('X-Workspace-Slug'), 'andritz');
  assert.equal(seen[1].headers.get('Authorization'), 'Bearer fresh-token');
  assert.equal(
    seen[1].headers.get('X-Workspace-Slug'),
    'andritz',
    'refresh must not silently move the retry to another workspace',
  );
});

test('an explicit workspace header wins over the current workspace and survives retry', async () => {
  const tokenStorage = new TokenStorageStub();
  const seen: HttpRequest<unknown>[] = [];
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      {
        provide: AuthApiService,
        useValue: {
          refresh: () => of({
            token: 'fresh-token',
            refresh_token: 'fresh-refresh-token',
            expires_in: 300,
            token_type: 'bearer',
          }),
        },
      },
      {
        provide: Router,
        useValue: { url: '/systems/system-1', navigate: () => Promise.resolve(true) },
      },
      { provide: WorkspaceService, useValue: { currentSlug: () => 'sentinel-ci' } },
    ],
  });
  const original = new HttpRequest('GET', '/api/v1/systems', {
    headers: new HttpHeaders({ 'X-Workspace-Slug': 'andritz' }),
  });
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    seen.push(request);
    return seen.length === 1
      ? throwError(() => new HttpErrorResponse({ status: 401 }))
      : of(new HttpResponse({ status: 200, body: { ok: true } }));
  };

  await firstValueFrom(
    runInInjectionContext(injector, () => authInterceptor(original, next)),
  );

  assert.equal(seen.length, 2);
  assert.equal(seen[0].headers.get('X-Workspace-Slug'), 'andritz');
  assert.equal(seen[1].headers.get('X-Workspace-Slug'), 'andritz');
});

test('a wrapped 500 auth error preserves the historical refresh retry', async () => {
  const tokenStorage = new TokenStorageStub();
  let refreshCalls = 0;
  let attempts = 0;
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      {
        provide: AuthApiService,
        useValue: {
          refresh: () => {
            refreshCalls += 1;
            return of({
              token: 'fresh-token',
              refresh_token: 'fresh-refresh-token',
              expires_in: 300,
              token_type: 'bearer',
            });
          },
        },
      },
      {
        provide: Router,
        useValue: { url: '/systems/system-1', navigate: () => Promise.resolve(true) },
      },
      { provide: WorkspaceService, useValue: { currentSlug: () => 'andritz' } },
    ],
  });
  const wrappedAuthError = new HttpErrorResponse({
    status: 500,
    error: { detail: 'Unauthorized downstream job returned 401' },
  });
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    attempts += 1;
    return attempts === 1
      ? throwError(() => wrappedAuthError)
      : of(new HttpResponse({ status: 200, body: { authorization: request.headers.get('Authorization') } }));
  };

  const response = await firstValueFrom(
    runInInjectionContext(injector, () =>
      authInterceptor(new HttpRequest('POST', '/api/v1/systems/system-1/runs', {}), next),
    ),
  );

  assert.equal(attempts, 2);
  assert.equal(refreshCalls, 1);
  assert.equal((response as HttpResponse<{ authorization: string }>).body?.authorization, 'Bearer fresh-token');
});

test('concurrent 401 retries preserve the workspace on every queued request', async () => {
  const tokenStorage = new TokenStorageStub();
  const refreshResult = new Subject<{
    token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
  }>();
  let refreshCalls = 0;
  const authApi = {
    refresh: () => {
      refreshCalls += 1;
      return refreshResult;
    },
  };
  const router = {
    url: '/client360',
    navigate: () => Promise.resolve(true),
  };
  const workspace = { currentSlug: () => 'andritz' };
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      { provide: AuthApiService, useValue: authApi },
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  const seen = new Map<string, HttpRequest<unknown>[]>();
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    const attempts = seen.get(request.url) ?? [];
    attempts.push(request);
    seen.set(request.url, attempts);
    if (attempts.length === 1) {
      return throwError(() => new HttpErrorResponse({ status: 401 }));
    }
    return of(new HttpResponse({ status: 200, body: { ok: true } }));
  };
  const intercept = (url: string) =>
    firstValueFrom(
      runInInjectionContext(injector, () =>
        authInterceptor(new HttpRequest('GET', url), next),
      ),
    );

  const first = intercept('/api/v1/systems');
  const second = intercept('/api/v1/client360/summary');
  assert.equal(refreshCalls, 1, 'concurrent failures share one refresh request');

  refreshResult.next({
    token: 'fresh-token',
    refresh_token: 'fresh-refresh-token',
    expires_in: 300,
    token_type: 'bearer',
  });
  refreshResult.complete();
  await Promise.all([first, second]);

  for (const [url, attempts] of seen) {
    assert.equal(attempts.length, 2, `${url} is retried exactly once`);
    assert.equal(attempts[0].headers.get('X-Workspace-Slug'), 'andritz');
    assert.equal(attempts[1].headers.get('Authorization'), 'Bearer fresh-token');
    assert.equal(
      attempts[1].headers.get('X-Workspace-Slug'),
      'andritz',
      `${url} must not lose its workspace while waiting for refresh`,
    );
  }
});

test('HttpClient and direct fetch share one refresh while retaining distinct workspaces', async () => {
  const originalFetch = globalThis.fetch;
  const tokenStorage = new TokenStorageStub();
  const refreshResult = new Subject<{
    token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
  }>();
  let refreshCalls = 0;
  const workspace = {
    currentSlug: () => 'andritz',
    captureRequestScope: () => ({ workspaceSlug: 'andritz', epoch: 1 }),
  };
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      WorkspaceFetchService,
      { provide: TokenStorageService, useValue: tokenStorage },
      {
        provide: AuthApiService,
        useValue: {
          refresh: () => {
            refreshCalls += 1;
            return refreshResult;
          },
        },
      },
      {
        provide: Router,
        useValue: { url: '/client360', navigate: () => Promise.resolve(true) },
      },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  const httpAttempts: HttpRequest<unknown>[] = [];
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    httpAttempts.push(request);
    return request.headers.get('Authorization') === 'Bearer expired-token'
      ? throwError(() => new HttpErrorResponse({ status: 401 }))
      : of(new HttpResponse({ status: 200 }));
  };
  const fetchAttempts: Array<{ authorization: string | null; workspace: string | null }> = [];
  globalThis.fetch = (async (_input, init) => {
    const headers = new Headers(init?.headers);
    fetchAttempts.push({
      authorization: headers.get('Authorization'),
      workspace: headers.get('X-Workspace-Slug'),
    });
    return new Response(null, {
      status: headers.get('Authorization') === 'Bearer expired-token' ? 401 : 200,
    });
  }) as typeof fetch;

  try {
    const http = firstValueFrom(runInInjectionContext(injector, () => authInterceptor(
      new HttpRequest('GET', '/api/v1/client360/summary', null, {
        headers: new HttpHeaders({ 'X-Workspace-Slug': 'andritz' }),
      }),
      next,
    )));
    const direct = injector.get(WorkspaceFetchService).fetch('/api/v1/chat/stream', {
      workspaceSlug: 'sentinel-ci',
    });

    await Promise.resolve();
    await Promise.resolve();
    assert.equal(refreshCalls, 1);
    refreshResult.next({
      token: 'fresh-token',
      refresh_token: 'fresh-refresh-token',
      expires_in: 300,
      token_type: 'bearer',
    });
    refreshResult.complete();
    await Promise.all([http, direct]);

    assert.deepEqual(httpAttempts.map((request) => ({
      authorization: request.headers.get('Authorization'),
      workspace: request.headers.get('X-Workspace-Slug'),
    })), [
      { authorization: 'Bearer expired-token', workspace: 'andritz' },
      { authorization: 'Bearer fresh-token', workspace: 'andritz' },
    ]);
    assert.deepEqual(fetchAttempts, [
      { authorization: 'Bearer expired-token', workspace: 'sentinel-ci' },
      { authorization: 'Bearer fresh-token', workspace: 'sentinel-ci' },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a late 401 reuses the token refreshed by an earlier request', async () => {
  const tokenStorage = new TokenStorageStub();
  const refreshResult = new Subject<{
    token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
  }>();
  const lateFailure = new Subject<HttpEvent<unknown>>();
  let refreshCalls = 0;
  const authApi = {
    refresh: () => {
      refreshCalls += 1;
      return refreshCalls === 1
        ? refreshResult
        : of({
            token: 'unwanted-second-token',
            refresh_token: 'unwanted-second-refresh-token',
            expires_in: 300,
            token_type: 'bearer',
          });
    },
  };
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      { provide: AuthApiService, useValue: authApi },
      {
        provide: Router,
        useValue: { url: '/client360', navigate: () => Promise.resolve(true) },
      },
      { provide: WorkspaceService, useValue: { currentSlug: () => 'andritz' } },
    ],
  });
  const seen = new Map<string, HttpRequest<unknown>[]>();
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    const attempts = seen.get(request.url) ?? [];
    attempts.push(request);
    seen.set(request.url, attempts);
    if (attempts.length > 1) {
      return of(new HttpResponse({ status: 200, body: { ok: true } }));
    }
    if (request.url === '/api/v1/client360/summary') return lateFailure;
    return throwError(() => new HttpErrorResponse({ status: 401 }));
  };
  const intercept = (url: string) => firstValueFrom(
    runInInjectionContext(injector, () =>
      authInterceptor(new HttpRequest('GET', url), next),
    ),
  );

  const first = intercept('/api/v1/systems');
  const late = intercept('/api/v1/client360/summary');
  const outcomes = Promise.allSettled([first, late]);
  assert.equal(refreshCalls, 1);

  refreshResult.next({
    token: 'fresh-token',
    refresh_token: 'fresh-refresh-token',
    expires_in: 300,
    token_type: 'bearer',
  });
  refreshResult.complete();
  lateFailure.error(new HttpErrorResponse({ status: 401 }));

  const settled = await outcomes;
  assert.deepEqual(settled.map((outcome) => outcome.status), ['fulfilled', 'fulfilled']);
  assert.equal(refreshCalls, 1, 'the delayed 401 must not rotate the refresh token again');
  const lateAttempts = seen.get('/api/v1/client360/summary') ?? [];
  assert.equal(lateAttempts.length, 2);
  assert.equal(lateAttempts[0].headers.get('Authorization'), 'Bearer expired-token');
  assert.equal(lateAttempts[1].headers.get('Authorization'), 'Bearer fresh-token');
  assert.equal(lateAttempts[1].headers.get('X-Workspace-Slug'), 'andritz');
  assert.equal(tokenStorage.token, 'Bearer fresh-token');
  assert.equal(tokenStorage.refreshToken, 'fresh-refresh-token');
});

test('a failed shared refresh rejects every concurrent request and expires once', async () => {
  const tokenStorage = new TokenStorageStub();
  const refreshResult = new Subject<{
    token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
  }>();
  let refreshCalls = 0;
  let navigations = 0;
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      {
        provide: AuthApiService,
        useValue: {
          refresh: () => {
            refreshCalls += 1;
            return refreshResult;
          },
        },
      },
      {
        provide: Router,
        useValue: {
          url: '/client360',
          navigate: () => {
            navigations += 1;
            return Promise.resolve(true);
          },
        },
      },
      { provide: WorkspaceService, useValue: { currentSlug: () => 'andritz' } },
    ],
  });
  const next = (): Observable<HttpEvent<unknown>> =>
    throwError(() => new HttpErrorResponse({ status: 401 }));
  const intercept = (url: string) => firstValueFrom(
    runInInjectionContext(injector, () =>
      authInterceptor(new HttpRequest('GET', url), next),
    ),
  );

  const outcomes = Promise.allSettled([
    intercept('/api/v1/systems'),
    intercept('/api/v1/client360/summary'),
  ]);
  assert.equal(refreshCalls, 1, 'concurrent failures share the refresh exchange');

  const refreshError = new HttpErrorResponse({ status: 401, statusText: 'refresh rejected' });
  refreshResult.error(refreshError);
  const settled = await outcomes;

  assert.deepEqual(settled.map((outcome) => outcome.status), ['rejected', 'rejected']);
  for (const outcome of settled) {
    assert.equal((outcome as PromiseRejectedResult).reason, refreshError);
  }
  assert.equal(tokenStorage.clearCalls, 1, 'the shared refresh expires the session once');
  assert.equal(navigations, 1, 'the shared refresh triggers one signin redirect');
});

test('cancelling the refresh leader does not strand a concurrent follower', () => {
  const tokenStorage = new TokenStorageStub();
  const refreshResult = new Subject<{
    token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
  }>();
  let refreshCalls = 0;
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      {
        provide: AuthApiService,
        useValue: {
          refresh: () => {
            refreshCalls += 1;
            return refreshResult;
          },
        },
      },
      {
        provide: Router,
        useValue: { url: '/client360', navigate: () => Promise.resolve(true) },
      },
      { provide: WorkspaceService, useValue: { currentSlug: () => 'andritz' } },
    ],
  });
  const attempts = new Map<string, number>();
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    const attempt = (attempts.get(request.url) ?? 0) + 1;
    attempts.set(request.url, attempt);
    return attempt === 1
      ? throwError(() => new HttpErrorResponse({ status: 401 }))
      : of(new HttpResponse({ status: 200, body: { ok: true } }));
  };
  const intercept = (url: string) => runInInjectionContext(injector, () =>
    authInterceptor(new HttpRequest('GET', url), next),
  );
  let followerSucceeded = false;
  let followerError: unknown;

  const leader = intercept('/api/v1/systems').subscribe({ error: () => undefined });
  const follower = intercept('/api/v1/client360/summary').subscribe({
    next: () => {
      followerSucceeded = true;
    },
    error: (error) => {
      followerError = error;
    },
  });
  assert.equal(refreshCalls, 1);

  leader.unsubscribe();
  refreshResult.next({
    token: 'fresh-token',
    refresh_token: 'fresh-refresh-token',
    expires_in: 300,
    token_type: 'bearer',
  });
  refreshResult.complete();

  assert.equal(followerError, undefined);
  assert.equal(followerSucceeded, true, 'the remaining subscriber receives the refreshed token');
  assert.equal(attempts.get('/api/v1/client360/summary'), 2);
  assert.equal(tokenStorage.token, 'Bearer fresh-token');
  follower.unsubscribe();
});

test('a started refresh survives cancellation and a later 401 joins it', () => {
  const tokenStorage = new TokenStorageStub();
  const refreshResult = new Subject<{
    token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
  }>();
  let refreshCalls = 0;
  const injector = Injector.create({
    providers: [
      AuthRefreshCoordinator,
      { provide: TokenStorageService, useValue: tokenStorage },
      {
        provide: AuthApiService,
        useValue: {
          refresh: () => {
            refreshCalls += 1;
            return refreshResult;
          },
        },
      },
      {
        provide: Router,
        useValue: { url: '/client360', navigate: () => Promise.resolve(true) },
      },
      { provide: WorkspaceService, useValue: { currentSlug: () => 'andritz' } },
    ],
  });
  const attempts = new Map<string, number>();
  const next = (request: HttpRequest<unknown>): Observable<HttpEvent<unknown>> => {
    const attempt = (attempts.get(request.url) ?? 0) + 1;
    attempts.set(request.url, attempt);
    return attempt === 1
      ? throwError(() => new HttpErrorResponse({ status: 401 }))
      : of(new HttpResponse({ status: 200, body: { ok: true } }));
  };
  const intercept = (url: string) => runInInjectionContext(injector, () =>
    authInterceptor(new HttpRequest('GET', url), next),
  );

  const cancelled = intercept('/api/v1/systems').subscribe({ error: () => undefined });
  assert.equal(refreshCalls, 1);
  cancelled.unsubscribe();

  let successorSucceeded = false;
  const successor = intercept('/api/v1/client360/summary').subscribe({
    next: () => {
      successorSucceeded = true;
    },
  });
  assert.equal(refreshCalls, 1, 'the successor must join the indivisible refresh exchange');
  refreshResult.next({
    token: 'successor-token',
    refresh_token: 'successor-refresh-token',
    expires_in: 300,
    token_type: 'bearer',
  });
  refreshResult.complete();

  assert.equal(successorSucceeded, true);
  assert.equal(tokenStorage.token, 'Bearer successor-token');
  successor.unsubscribe();
});

for (const retryStatus of [401, 403, 500]) {
  test(`a ${retryStatus} from the retried business request does not clear the refreshed session`, async () => {
    const tokenStorage = new TokenStorageStub();
    let navigations = 0;
    const injector = Injector.create({
      providers: [
        AuthRefreshCoordinator,
        { provide: TokenStorageService, useValue: tokenStorage },
        {
          provide: AuthApiService,
          useValue: {
            refresh: () => of({
              token: 'fresh-token',
              refresh_token: 'fresh-refresh-token',
              expires_in: 300,
              token_type: 'bearer',
            }),
          },
        },
        {
          provide: Router,
          useValue: {
            url: '/client360',
            navigate: () => {
              navigations += 1;
              return Promise.resolve(true);
            },
          },
        },
        { provide: WorkspaceService, useValue: { currentSlug: () => 'andritz' } },
      ],
    });
    let attempts = 0;
    const retryError = new HttpErrorResponse({ status: retryStatus });
    const next = (): Observable<HttpEvent<unknown>> => {
      attempts += 1;
      return throwError(() => attempts === 1
        ? new HttpErrorResponse({ status: 401 })
        : retryError);
    };

    await assert.rejects(
      firstValueFrom(runInInjectionContext(injector, () =>
        authInterceptor(new HttpRequest('GET', '/api/v1/client360/summary'), next),
      )),
      (error) => error === retryError,
    );

    assert.equal(attempts, 2);
    assert.equal(tokenStorage.token, 'Bearer fresh-token');
    assert.equal(tokenStorage.refreshToken, 'fresh-refresh-token');
    assert.equal(tokenStorage.clearCalls, 0);
    assert.equal(navigations, 0);
  });
}
