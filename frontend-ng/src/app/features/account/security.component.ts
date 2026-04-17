import { Component, inject, signal } from '@angular/core';
import { AuthApiService } from '@app/core/auth-api.service';

@Component({
  selector: 'app-account-security',
  standalone: true,
  template: `
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Security</h2>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
      Two-factor authentication adds an extra layer by emailing you a one-time code at each sign-in.
    </p>

    @if (loading()) {
      <p class="text-sm text-gray-500">Loading…</p>
    } @else {
      <div class="flex items-start justify-between gap-4 p-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/40">
        <div class="flex-1">
          <div class="flex items-center gap-2">
            <span class="text-lg">📧</span>
            <span class="font-medium text-gray-900 dark:text-white">Email two-factor authentication</span>
            @if (enabled()) {
              <span class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">Enabled</span>
            } @else {
              <span class="text-xs px-2 py-0.5 rounded-full bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300">Disabled</span>
            }
          </div>
          <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
            A 6-digit code will be sent to your email address each time you sign in.
          </p>
        </div>
        <button
          type="button"
          (click)="toggle()"
          [disabled]="saving()"
          class="shrink-0 px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
          [class.bg-brand-500]="!enabled()"
          [class.text-white]="!enabled()"
          [class.hover:bg-brand-600]="!enabled()"
          [class.bg-gray-200]="enabled()"
          [class.dark:bg-gray-700]="enabled()"
          [class.text-gray-700]="enabled()"
          [class.dark:text-gray-200]="enabled()"
          [class.hover:bg-gray-300]="enabled()"
        >
          @if (saving()) { Saving… } @else if (enabled()) { Disable } @else { Enable }
        </button>
      </div>

      @if (message()) {
        <p class="mt-4 text-sm" [class.text-green-600]="!error()" [class.text-red-600]="error()">{{ message() }}</p>
      }
    }
  `,
})
export class SecurityComponent {
  private readonly api = inject(AuthApiService);

  loading = signal(true);
  saving = signal(false);
  enabled = signal(false);
  message = signal<string | null>(null);
  error = signal(false);

  constructor() {
    this.api.me().subscribe({
      next: (p) => {
        this.enabled.set(p.mfa_enabled);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  toggle(): void {
    const next = !this.enabled();
    this.saving.set(true);
    this.message.set(null);
    this.error.set(false);
    this.api.toggleMfa(next).subscribe({
      next: (res) => {
        this.enabled.set(res.mfa_enabled);
        this.saving.set(false);
        this.message.set(
          res.mfa_enabled
            ? 'Two-factor authentication is now enabled. A code will be emailed on next sign-in.'
            : 'Two-factor authentication has been disabled.'
        );
      },
      error: (err) => {
        this.saving.set(false);
        this.error.set(true);
        this.message.set(err.error?.detail || 'Failed to update 2FA setting');
      },
    });
  }
}
