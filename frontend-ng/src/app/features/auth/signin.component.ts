import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, ActivatedRoute } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';
import { WorkspaceService } from '@app/core/workspace.service';

@Component({
  selector: 'app-signin',
  standalone: true,
  imports: [FormsModule, RouterLink],
  template: `
    <h2 class="text-xl font-semibold text-white mb-6">Sign in</h2>

    <form (ngSubmit)="onSubmit()" class="space-y-4">
      <div>
        <label class="block text-sm text-brand-200 mb-1">Email</label>
        <input
          type="email"
          [(ngModel)]="email"
          name="email"
          required
          class="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400"
          placeholder="you&#64;company.com"
        />
      </div>

      <div>
        <label class="block text-sm text-brand-200 mb-1">Password</label>
        <div class="relative">
          <input
            [type]="showPassword() ? 'text' : 'password'"
            [(ngModel)]="password"
            name="password"
            required
            class="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 pr-10"
            placeholder="••••••••"
          />
          <button
            type="button"
            (click)="showPassword.set(!showPassword())"
            class="absolute right-3 top-1/2 -translate-y-1/2 text-white/50 hover:text-white"
          >
            {{ showPassword() ? '🙈' : '👁' }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <input
          type="checkbox"
          [(ngModel)]="rememberMe"
          name="rememberMe"
          id="rememberMe"
          class="rounded border-white/30"
        />
        <label for="rememberMe" class="text-sm text-brand-200">Remember me</label>
      </div>

      @if (error()) {
        <p class="text-red-300 text-sm">{{ error() }}</p>
      }

      <button
        type="submit"
        [disabled]="loading()"
        class="w-full py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition"
      >
        @if (loading()) { Signing in... } @else { Sign in }
      </button>
    </form>

    <div class="mt-6 text-center text-sm text-brand-200 space-y-1">
      <p>
        <a routerLink="/auth/password-reset" class="hover:text-white underline">Forgot password?</a>
      </p>
      <p>
        Don't have an account?
        <a routerLink="/auth/signup" class="hover:text-white underline">Sign up</a>
      </p>
    </div>
  `,
})
export class SigninComponent {
  private readonly authApi = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);
  private readonly workspaceService = inject(WorkspaceService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  email = '';
  password = '';
  rememberMe = false;
  showPassword = signal(false);
  loading = signal(false);
  error = signal<string | null>(null);

  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);

    this.authApi
      .login({ email: this.email, password: this.password, remember_me: this.rememberMe })
      .subscribe({
        next: (tokens) => {
          this.tokenStorage.saveToken(tokens.token);
          if (tokens.refresh_token) {
            this.tokenStorage.saveRefreshToken(tokens.refresh_token);
          }
          this.authStore.setAuthenticated({
            userId: '',
            email: this.email,
            role: 'user',
          });
          this.workspaceService.loadWorkspaces();
          const redirect = this.route.snapshot.queryParams['redirectURL'] || '/';
          this.router.navigateByUrl(redirect);
        },
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Invalid credentials');
        },
      });
  }
}
