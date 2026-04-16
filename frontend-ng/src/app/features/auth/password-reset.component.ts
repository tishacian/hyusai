import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';

@Component({
  selector: 'app-password-reset',
  standalone: true,
  imports: [FormsModule, RouterLink],
  template: `
    <h2 class="text-xl font-semibold text-white mb-6">Reset password</h2>

    @if (sent()) {
      <div class="text-center space-y-3">
        <p class="text-brand-200 text-sm">If that email exists, a reset link has been sent.</p>
        <a routerLink="/auth/signin" class="text-brand-300 hover:text-white underline text-sm">Back to sign in</a>
      </div>
    } @else {
      <form (ngSubmit)="onSubmit()" class="space-y-4">
        <div>
          <label class="block text-sm text-brand-200 mb-1">Email</label>
          <input type="email" [(ngModel)]="email" name="email" required
            class="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400"
            placeholder="you&#64;company.com" />
        </div>

        <button type="submit" [disabled]="loading()"
          class="w-full py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition">
          @if (loading()) { Sending... } @else { Send reset link }
        </button>
      </form>

      <p class="mt-4 text-center text-sm text-brand-200">
        <a routerLink="/auth/signin" class="hover:text-white underline">Back to sign in</a>
      </p>
    }
  `,
})
export class PasswordResetComponent {
  private readonly authApi = inject(AuthApiService);

  email = '';
  loading = signal(false);
  sent = signal(false);

  onSubmit(): void {
    this.loading.set(true);
    this.authApi.passwordReset(this.email).subscribe({
      next: () => {
        this.loading.set(false);
        this.sent.set(true);
      },
      error: () => {
        this.loading.set(false);
        this.sent.set(true);
      },
    });
  }
}
