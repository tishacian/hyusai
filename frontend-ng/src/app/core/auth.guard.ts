import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { TokenStorageService } from './token-storage.service';
import { AuthBootstrapService } from './auth-bootstrap.service';

/**
 * Synchronous auth guard. Relies on the boot-time validation performed by
 * {@link AuthBootstrapService}. The server is only contacted again when a
 * request actually comes back 401 (handled by the HTTP interceptor), so
 * navigations feel instant.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const tokenStorage = inject(TokenStorageService);
  const authBootstrap = inject(AuthBootstrapService);
  const router = inject(Router);

  if (tokenStorage.isAuthenticated && authBootstrap.valid()) {
    return true;
  }

  if (!tokenStorage.isAuthenticated) {
    router.navigate(['/auth/signin'], {
      queryParams: { redirectURL: state.url },
    });
    return false;
  }

  // Token is present but bootstrap said it was invalid — send back to signin.
  tokenStorage.clear();
  authBootstrap.markInvalid();
  router.navigate(['/auth/signin'], {
    queryParams: { redirectURL: state.url },
  });
  return false;
};
