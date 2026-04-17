import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';

const PASSWORD_REGEX = /^(?=.*[0-9])(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9])(?=\S+$).{8,}$/;

@Component({
  selector: 'app-signup',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    @if (success()) {
      <div class="text-center space-y-4">
        <div class="mx-auto w-12 h-12 rounded-full bg-brand-500/15 ring-1 ring-brand-500/30 flex items-center justify-center text-brand-400">
          <app-icon name="mail" [size]="22" />
        </div>
        <h2 class="text-xl font-semibold text-white">Check your email</h2>
        <p class="text-brand-200 text-sm">We've sent a confirmation link. Please verify your email to continue.</p>
        <a routerLink="/auth/signin" class="inline-block mt-4 text-brand-300 hover:text-white underline">Back to sign in</a>
      </div>
    } @else {
      <h2 class="text-xl font-semibold text-white mb-6">Create account</h2>

      <form (ngSubmit)="onSubmit()" class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <input [(ngModel)]="firstName" name="firstName" required placeholder="First name"
              class="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm" />
          </div>
          <div>
            <input [(ngModel)]="lastName" name="lastName" required placeholder="Last name"
              class="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm" />
          </div>
        </div>

        <input [(ngModel)]="email" name="email" type="email" required placeholder="Email"
          class="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm" />

        <input [(ngModel)]="password" name="password" type="password" required placeholder="Password (8+ chars, upper, lower, digit, special)"
          class="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm" />

        <input [(ngModel)]="confirmPassword" name="confirmPassword" type="password" required placeholder="Confirm password"
          class="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm" />

        <input [(ngModel)]="company" name="company" placeholder="Company (optional)"
          class="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm" />

        @if (error()) {
          <p class="text-red-300 text-sm">{{ error() }}</p>
        }

        <button type="submit" [disabled]="loading()"
          class="w-full py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition text-sm">
          @if (loading()) { Creating... } @else { Create account }
        </button>
      </form>

      <p class="mt-4 text-center text-sm text-brand-200">
        Already have an account? <a routerLink="/auth/signin" class="hover:text-white underline">Sign in</a>
      </p>
    }
  `,
})
export class SignupComponent {
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);

  firstName = '';
  lastName = '';
  email = '';
  password = '';
  confirmPassword = '';
  company = '';
  loading = signal(false);
  error = signal<string | null>(null);
  success = signal(false);

  onSubmit(): void {
    if (this.password !== this.confirmPassword) {
      this.error.set('Passwords do not match');
      return;
    }
    if (!PASSWORD_REGEX.test(this.password)) {
      this.error.set('Password must be 8+ characters with uppercase, lowercase, digit, and special character');
      return;
    }

    this.loading.set(true);
    this.error.set(null);

    this.authApi
      .signup({
        first_name: this.firstName,
        last_name: this.lastName,
        email: this.email,
        password: this.password,
        company: this.company || undefined,
      })
      .subscribe({
        next: () => {
          this.loading.set(false);
          this.success.set(true);
        },
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Registration failed');
        },
      });
  }
}
