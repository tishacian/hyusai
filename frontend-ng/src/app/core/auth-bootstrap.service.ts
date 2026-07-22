import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthApiService } from './auth-api.service';
import { TokenStorageService } from './token-storage.service';
import { AuthStore } from '../store/auth.store';

/**
 * Validates the current token ONCE at app bootstrap (via APP_INITIALIZER) and
 * exposes a synchronous `authReady` signal. The route guard reads this signal
 * instead of hitting `/auth/validate` on every navigation.
 *
 * Re-validation happens lazily only when the token changes (login/logout/refresh).
 */
@Injectable({ providedIn: 'root' })
export class AuthBootstrapService {
  private readonly authApi = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);

  private readonly _ready = signal(false);
  private readonly _valid = signal(false);

  readonly ready = this._ready.asReadonly();
  readonly valid = this._valid.asReadonly();
  readonly authenticated = computed(() => this._valid());

  async bootstrap(): Promise<void> {
    if (!this.tokenStorage.isAuthenticated) {
      if (this.authStore.isAuthenticated()) this.authStore.clear();
      this._valid.set(false);
      this._ready.set(true);
      return;
    }
    try {
      const res = await firstValueFrom(this.authApi.validate());
      this.authStore.setAuthenticated({
        userId: res.user_id,
        email: res.email ?? null,
        role: res.role,
      });
      this._valid.set(true);
    } catch {
      this.tokenStorage.clear();
      this.authStore.clear();
      this._valid.set(false);
    } finally {
      this._ready.set(true);
    }
  }

  markValid(): void {
    this._valid.set(true);
    this._ready.set(true);
  }

  markInvalid(): void {
    if (this.authStore.isAuthenticated()) this.authStore.clear();
    this._valid.set(false);
    this._ready.set(true);
  }
}
