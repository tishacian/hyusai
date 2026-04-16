import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { TokenStorageService } from './token-storage.service';

export const loginGuard: CanActivateFn = (route) => {
  const tokenStorage = inject(TokenStorageService);
  const router = inject(Router);

  if (tokenStorage.isAuthenticated) {
    const redirect = route.queryParams['redirectURL'] || '/';
    router.navigate([redirect]);
    return false;
  }
  return true;
};
