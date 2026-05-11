import { HttpInterceptorFn, HttpErrorResponse, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError, BehaviorSubject, filter, take } from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { AuthApiService } from './auth-api.service';
import { WorkspaceService } from './workspace.service';

let isRefreshing = false;
const refreshSubject = new BehaviorSubject<string | null>(null);

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
        return handle401(req, next, tokenStorage, authApi, router);
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
  if (!isRefreshing) {
    isRefreshing = true;
    refreshSubject.next(null);

    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) {
      isRefreshing = false;
      tokenStorage.clear();
      router.navigate(['/auth/signin'], { queryParams: { redirectURL: router.url } });
      return throwError(() => new Error('Session expired'));
    }

    return authApi.refresh(refreshToken).pipe(
      switchMap((tokens) => {
        isRefreshing = false;
        tokenStorage.saveToken(tokens.token);
        if (tokens.refresh_token) {
          tokenStorage.saveRefreshToken(tokens.refresh_token);
        }
        refreshSubject.next(tokens.token);
        return next(
          req.clone({ setHeaders: { Authorization: `Bearer ${tokens.token}` } })
        );
      }),
      catchError((err) => {
        isRefreshing = false;
        tokenStorage.clear();
        router.navigate(['/auth/signin'], { queryParams: { redirectURL: router.url } });
        return throwError(() => err);
      })
    );
  }

  return refreshSubject.pipe(
    filter((token) => token !== null),
    take(1),
    switchMap((token) =>
      next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }))
    )
  );
}
