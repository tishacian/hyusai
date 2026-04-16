import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { catchError, map, of } from 'rxjs';
import { AuthApiService } from './auth-api.service';
import { TokenStorageService } from './token-storage.service';

export const authGuard: CanActivateFn = (route, state) => {
  const tokenStorage = inject(TokenStorageService);
  const authApi = inject(AuthApiService);
  const router = inject(Router);

  if (!tokenStorage.isAuthenticated) {
    router.navigate(['/auth/signin'], {
      queryParams: { redirectURL: state.url },
    });
    return false;
  }

  return authApi.validate().pipe(
    map(() => true),
    catchError(() => {
      tokenStorage.clear();
      router.navigate(['/auth/signin'], {
        queryParams: { redirectURL: state.url },
      });
      return of(false);
    })
  );
};
