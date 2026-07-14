import { HttpInterceptorFn, HttpErrorResponse, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import {
  Observable,
  catchError,
  defer,
  finalize,
  map,
  shareReplay,
  switchMap,
  tap,
  throwError,
} from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { AuthApiService } from './auth-api.service';
import { WorkspaceService } from './workspace.service';

let refreshRequest$: Observable<string> | null = null;

function isWrappedAuthError(error: HttpErrorResponse): boolean {
  if (error.status !== 500) return false;
  const body = typeof error.error === 'string' ? error.error : JSON.stringify(error.error ?? '');
  return (
    body.includes('Invalid bearer token') ||
    body.includes('invalid_grant') ||
    body.includes('401') ||
    body.includes('Unauthorized')
  );
}

function isPublicDepositRequest(url: string): boolean {
  return url.includes('/api/v1/deposit-links/');
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const tokenStorage = inject(TokenStorageService);
  const authApi = inject(AuthApiService);
  const router = inject(Router);
  const workspaceService = inject(WorkspaceService);

  const token = tokenStorage.getToken();
  const wsSlug = workspaceService.currentSlug();

  const headers: Record<string, string> = {};
  if (token && !req.headers.has('Authorization') && !isPublicDepositRequest(req.url)) {
    headers['Authorization'] = token;
  }
  if (wsSlug && !isPublicDepositRequest(req.url)) headers['X-Workspace-Slug'] = wsSlug;

  const authReq = Object.keys(headers).length ? req.clone({ setHeaders: headers }) : req;

  return next(authReq).pipe(
    catchError((error: HttpErrorResponse) => {
      if (
        (error.status === 401 || isWrappedAuthError(error)) &&
        !req.url.includes('/auth/') &&
        !isPublicDepositRequest(req.url)
      ) {
        // Retry the fully scoped request. Passing the original request here
        // drops X-Workspace-Slug and lets the backend fall back to another
        // membership after a token refresh.
        return handle401(authReq, next, tokenStorage, authApi, router);
      }
      return throwError(() => error);
    })
  );
};

function handle401(
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
  tokenStorage: TokenStorageService,
  authApi: AuthApiService,
  router: Router
) {
  const requestToken = req.headers.get('Authorization');
  const currentToken = tokenStorage.getToken();
  if (currentToken && currentToken !== requestToken) {
    // Another request already completed the shared refresh while this response
    // was still in flight. Replay once with the current bearer instead of
    // rotating the refresh token a second time; keep the request's workspace.
    return next(req.clone({ setHeaders: { Authorization: currentToken } }));
  }

  return sharedAccessTokenRefresh(tokenStorage, authApi, router).pipe(
    // Keep the retry outside the refresh error boundary. A valid new token does
    // not become invalid merely because the business endpoint returns 403/500.
    switchMap((token) => next(
      req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    ))
  );
}

function sharedAccessTokenRefresh(
  tokenStorage: TokenStorageService,
  authApi: AuthApiService,
  router: Router,
): Observable<string> {
  if (refreshRequest$) return refreshRequest$;

  const refreshToken = tokenStorage.getRefreshToken();
  if (!refreshToken) {
    expireSession(tokenStorage, router);
    return throwError(() => new Error('Session expired'));
  }

  let request$: Observable<string>;
  request$ = defer(() => authApi.refresh(refreshToken)).pipe(
    tap((tokens) => {
      tokenStorage.saveToken(tokens.token);
      if (tokens.refresh_token) {
        tokenStorage.saveRefreshToken(tokens.refresh_token);
      }
    }),
    map((tokens) => tokens.token),
    catchError((error) => {
      // This boundary covers only the refresh exchange. Every subscriber sees
      // the same terminal error and no queued request can remain suspended.
      expireSession(tokenStorage, router);
      return throwError(() => error);
    }),
    finalize(() => {
      // refCount also runs this path when all callers cancel. A later 401 can
      // therefore start a fresh exchange instead of waiting on stale state.
      if (refreshRequest$ === request$) refreshRequest$ = null;
    }),
    shareReplay({ bufferSize: 1, refCount: true }),
  );
  refreshRequest$ = request$;
  return request$;
}

function expireSession(tokenStorage: TokenStorageService, router: Router): void {
  tokenStorage.clear();
  void router.navigate(['/auth/signin'], { queryParams: { redirectURL: router.url } });
}
