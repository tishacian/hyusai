import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { AuthApiService } from '@app/core/auth-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';

interface Rule {
  labelKey: string;
  test: (v: string) => boolean;
}

@Component({
  selector: 'app-account-password',
  standalone: true,
  imports: [FormsModule, IconComponent],
  template: `
    <div class="ck-surface t-elevated rounded-md p-6">
      <div class="flex items-start gap-3 mb-5">
        <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
          <app-icon name="key-round" [size]="18" />
        </div>
        <div>
          <h2 class="text-base font-semibold text-white">{{ i18n.t('account.password.title') }}</h2>
          <p class="text-sm text-gray-400 mt-0.5">
            {{ i18n.t('account.password.description') }}
          </p>
        </div>
      </div>

    <form (ngSubmit)="submit()" class="space-y-4 max-w-md">
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{{ i18n.t('account.password.current') }}</label>
        <input
          type="password"
          [(ngModel)]="currentPwd"
          name="current"
          required
          autocomplete="current-password"
          class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{{ i18n.t('account.password.new') }}</label>
        <input
          type="password"
          [(ngModel)]="newPwd"
          (ngModelChange)="newPwdValue.set($event)"
          name="new"
          required
          autocomplete="new-password"
          class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{{ i18n.t('account.password.confirm') }}</label>
        <input
          type="password"
          [(ngModel)]="confirmPwd"
          name="confirm"
          required
          autocomplete="new-password"
          class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
        @if (confirmPwd && confirmPwd !== newPwd) {
          <p class="text-xs text-red-500 mt-1">{{ i18n.t('account.password.mismatch') }}</p>
        }
      </div>

      <div class="bg-black/20 rounded-md p-3 space-y-1.5 border border-white/5">
        @for (r of rules; track r.labelKey) {
          <div class="flex items-center gap-2 text-xs">
            <app-icon
              [name]="r.test(newPwdValue()) ? 'check-circle-2' : 'circle'"
              [size]="12"
              [class]="r.test(newPwdValue()) ? 'text-emerald-400' : 'text-gray-500'"
            />
            <span class="text-gray-300">{{ i18n.t(r.labelKey) }}</span>
          </div>
        }
      </div>

      @if (message()) {
        <p class="text-sm" [class.text-green-600]="!error()" [class.text-red-600]="error()">{{ message() }}</p>
      }

      <button
        type="submit"
        [disabled]="!canSubmit() || saving()"
        class="inline-flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white font-medium rounded transition shadow-glow-sm"
      >
        <app-icon name="save" [size]="14" />
        @if (saving()) { {{ i18n.t('account.password.updating') }} } @else { {{ i18n.t('account.password.update_cta') }} }
      </button>
    </form>
    </div>
  `,
})
export class PasswordComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(AuthApiService);
  private readonly toastr = inject(ToastrService);

  currentPwd = '';
  newPwd = '';
  confirmPwd = '';
  newPwdValue = signal('');
  saving = signal(false);
  message = signal<string | null>(null);
  error = signal(false);

  rules: Rule[] = [
    { labelKey: 'account.password.rule.length', test: (v) => v.length >= 8 },
    { labelKey: 'account.password.rule.lowercase', test: (v) => /[a-z]/.test(v) },
    { labelKey: 'account.password.rule.uppercase', test: (v) => /[A-Z]/.test(v) },
    { labelKey: 'account.password.rule.digit', test: (v) => /\d/.test(v) },
    { labelKey: 'account.password.rule.special', test: (v) => /[^A-Za-z0-9]/.test(v) },
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
          this.currentPwd = '';
          this.newPwd = '';
          this.confirmPwd = '';
          this.newPwdValue.set('');
          this.toastr.success(
            this.i18n.t('account.password.toast.updated'),
            this.i18n.t('account.password.toast.done_title'),
          );
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(true);
          this.toastr.error(
            err.error?.detail || this.i18n.t('account.password.toast.failed'),
            this.i18n.t('account.toast.error_title'),
          );
        },
      });
  }
}
