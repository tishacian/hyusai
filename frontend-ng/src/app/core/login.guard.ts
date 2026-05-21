import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { TokenStorageService } from './token-storage.service';

function normalizeRedirect(value: unknown): string {
  const redirect = typeof value === 'string' && value.startsWith('/') ? value : '/';
  return redirect.startsWith('/auth') ? '/' : redirect;
}

export const loginGuard: CanActivateFn = (route) => {
  const tokenStorage = inject(TokenStorageService);
  const router = inject(Router);

  if (tokenStorage.isAuthenticated) {
    const redirect = normalizeRedirect(route.queryParams['redirectURL']);
    router.navigateByUrl(redirect);
    return false;
  }
  return true;
};
