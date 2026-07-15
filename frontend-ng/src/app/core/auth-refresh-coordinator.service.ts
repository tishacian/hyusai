import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import {
  Observable,
  catchError,
  defer,
  finalize,
  map,
  of,
  shareReplay,
  tap,
  throwError,
} from 'rxjs';
import { AuthApiService } from './auth-api.service';
import { TokenStorageService } from './token-storage.service';

/**
 * Coordinates access-token renewal across every authenticated transport.
 *
 * The coordinator owns the single in-flight refresh exchange. Callers pass the
 * bearer used by their failed attempt so a late 401 can reuse a token that a
 * concurrent request has already renewed instead of rotating the refresh token
 * a second time.
 */
@Injectable({ providedIn: 'root' })
export class AuthRefreshCoordinator {
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);

  private refreshRequest$: Observable<string> | null = null;

  /** Return the full Authorization value to use for one post-401 retry. */
  authorizationAfter401(requestAuthorization: string | null): Observable<string> {
    const currentAuthorization = this.tokenStorage.getToken();
    if (currentAuthorization && currentAuthorization !== requestAuthorization) {
      return of(currentAuthorization);
    }
    return this.refreshAccessToken().pipe(map((token) => `Bearer ${token}`));
  }

  /** Share one refresh-token exchange between all concurrent transports. */
  refreshAccessToken(): Observable<string> {
    if (this.refreshRequest$) return this.refreshRequest$;

    const refreshToken = this.tokenStorage.getRefreshToken();
    if (!refreshToken) {
      this.expireSession();
      return throwError(() => new Error('Session expired'));
    }

    let request$: Observable<string>;
    request$ = defer(() => this.authApi.refresh(refreshToken)).pipe(
      tap((tokens) => {
        this.tokenStorage.saveToken(tokens.token);
        if (tokens.refresh_token) {
          this.tokenStorage.saveRefreshToken(tokens.refresh_token);
        }
      }),
      map((tokens) => tokens.token),
      catchError((error) => {
        // This boundary covers only the refresh exchange. Business-request
        // failures happen outside it and must never clear a valid new session.
        this.expireSession();
        return throwError(() => error);
      }),
      finalize(() => {
        // The source survives consumer cancellation: rotating refresh tokens
        // makes an already-started exchange indivisible.  The slot is released
        // only when that exchange succeeds or fails.
        if (this.refreshRequest$ === request$) this.refreshRequest$ = null;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    this.refreshRequest$ = request$;
    return request$;
  }

  private expireSession(): void {
    this.tokenStorage.clear();
    void this.router.navigate(['/auth/signin'], {
      queryParams: { redirectURL: this.router.url },
    });
  }
}
