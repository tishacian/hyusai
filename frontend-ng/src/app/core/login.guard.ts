import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { TokenStorageService } from './token-storage.service';
import { normalizeAuthRedirect } from './auth-redirect';

export const loginGuard: CanActivateFn = (route) => {
  const tokenStorage = inject(TokenStorageService);
  const router = inject(Router);

  if (tokenStorage.isAuthenticated) {
    const redirect = normalizeAuthRedirect(route.queryParams['redirectURL']);
    router.navigateByUrl(redirect);
    return false;
  }
  return true;
};
