import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthApiService } from '@app/core/auth-api.service';

interface Rule {
  label: string;
  test: (v: string) => boolean;
}

@Component({
  selector: 'app-account-password',
  standalone: true,
  imports: [FormsModule],
  template: `
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Change password</h2>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
      Choose a strong password. You'll be signed out of other sessions afterwards if needed.
    </p>

    <form (ngSubmit)="submit()" class="space-y-4 max-w-md">
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Current password</label>
        <input
          type="password"
          [(ngModel)]="currentPwd"
          name="current"
          required
          autocomplete="current-password"
          class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">New password</label>
        <input
          type="password"
          [(ngModel)]="newPwd"
          (ngModelChange)="newPwdValue.set($event)"
          name="new"
          required
          autocomplete="new-password"
          class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Confirm new password</label>
        <input
          type="password"
          [(ngModel)]="confirmPwd"
          name="confirm"
          required
          autocomplete="new-password"
          class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
        @if (confirmPwd && confirmPwd !== newPwd) {
          <p class="text-xs text-red-500 mt-1">Passwords don't match.</p>
        }
      </div>

      <div class="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-3 space-y-1">
        @for (r of rules; track r.label) {
          <div class="flex items-center gap-2 text-xs">
            <span [class.text-green-500]="r.test(newPwdValue())" [class.text-gray-400]="!r.test(newPwdValue())">
              {{ r.test(newPwdValue()) ? '✓' : '○' }}
            </span>
            <span class="text-gray-600 dark:text-gray-300">{{ r.label }}</span>
          </div>
        }
      </div>

      @if (message()) {
        <p class="text-sm" [class.text-green-600]="!error()" [class.text-red-600]="error()">{{ message() }}</p>
      }

      <button
        type="submit"
        [disabled]="!canSubmit() || saving()"
        class="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition"
      >
        @if (saving()) { Updating… } @else { Update password }
      </button>
    </form>
  `,
})
export class PasswordComponent {
  private readonly api = inject(AuthApiService);

  currentPwd = '';
  newPwd = '';
  confirmPwd = '';
  newPwdValue = signal('');
  saving = signal(false);
  message = signal<string | null>(null);
  error = signal(false);

  rules: Rule[] = [
    { label: 'At least 8 characters', test: (v) => v.length >= 8 },
    { label: 'Contains a lowercase letter', test: (v) => /[a-z]/.test(v) },
    { label: 'Contains an uppercase letter', test: (v) => /[A-Z]/.test(v) },
    { label: 'Contains a digit', test: (v) => /\d/.test(v) },
    { label: 'Contains a special character', test: (v) => /[^A-Za-z0-9]/.test(v) },
  ];

  canSubmit = computed(() => {
    const v = this.newPwdValue();
    return (
      this.currentPwd.length > 0 &&
      v.length >= 8 &&
      this.rules.every((r) => r.test(v)) &&
      v === this.confirmPwd
    );
  });

  submit(): void {
    if (!this.canSubmit()) return;
    this.saving.set(true);
    this.message.set(null);
    this.error.set(false);
    this.api
      .changePassword({ current_password: this.currentPwd, new_password: this.newPwd })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.message.set('Password updated successfully');
          this.currentPwd = '';
          this.newPwd = '';
          this.confirmPwd = '';
          this.newPwdValue.set('');
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(true);
          this.message.set(err.error?.detail || 'Failed to update password');
        },
      });
  }
}
