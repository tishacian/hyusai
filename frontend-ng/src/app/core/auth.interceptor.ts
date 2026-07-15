import { HttpInterceptorFn, HttpErrorResponse, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import {
  catchError,
  switchMap,
  throwError,
} from 'rxjs';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceService } from './workspace.service';
import { AuthRefreshCoordinator } from './auth-refresh-coordinator.service';

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
  const refreshCoordinator = inject(AuthRefreshCoordinator);
  const workspaceService = inject(WorkspaceService);

  const token = tokenStorage.getToken();
  const wsSlug = workspaceService.currentSlug();

  const headers: Record<string, string> = {};
  if (token && !req.headers.has('Authorization') && !isPublicDepositRequest(req.url)) {
    headers['Authorization'] = token;
  }
  if (
    wsSlug &&
    !req.headers.has('X-Workspace-Slug') &&
    !isPublicDepositRequest(req.url)
  ) {
    headers['X-Workspace-Slug'] = wsSlug;
  }

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
        return handle401(authReq, next, refreshCoordinator);
      }
      return throwError(() => error);
    })
  );
};

function handle401(
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
  refreshCoordinator: AuthRefreshCoordinator,
) {
  return refreshCoordinator.authorizationAfter401(req.headers.get('Authorization')).pipe(
    // Keep the retry outside the refresh error boundary. A valid new token does
    // not become invalid merely because the business endpoint returns 403/500.
    switchMap((authorization) => next(
      req.clone({ setHeaders: { Authorization: authorization } })
    ))
  );
}
