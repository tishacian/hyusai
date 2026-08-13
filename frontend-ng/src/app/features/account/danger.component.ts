import { Component, inject, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { AuthApiService } from '@app/core/auth-api.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

@Component({
  selector: 'app-account-danger',
  standalone: true,
  imports: [IconComponent, ConfirmDialogComponent],
  template: `
    <div class="ck-surface t-elevated rounded-md p-6 border-red-500/20">
      <div class="flex items-start gap-3 mb-4">
        <div class="w-10 h-10 rounded-md flex items-center justify-center bg-red-500/10 text-red-400 ring-1 ring-red-500/30">
          <app-icon name="shield-alert" [size]="18" />
        </div>
        <div>
          <h2 class="text-base font-semibold text-red-400">{{ i18n.t('account.danger') }}</h2>
          <p class="text-sm text-gray-400 mt-0.5">
            {{ i18n.t('account.danger.description') }}
          </p>
        </div>
      </div>

      <div class="rounded-md border border-red-500/20 bg-red-500/5 p-5">
        <h3 class="font-semibold text-red-300">{{ i18n.t('account.danger.delete.title') }}</h3>
        <p class="text-sm text-gray-400 mt-1 mb-4">
          {{ i18n.t('account.danger.delete.description') }}
        </p>
        <button
          type="button"
          (click)="confirmOpen.set(true)"
          [disabled]="deleting()"
          class="inline-flex items-center gap-2 px-4 py-2 rounded bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white font-medium transition"
        >
          <app-icon name="trash-2" [size]="14" />
          @if (deleting()) { {{ i18n.t('account.danger.deleting') }} } @else { {{ i18n.t('account.danger.delete.cta') }} }
        </button>
      </div>
    </div>

    <app-confirm-dialog
      [open]="confirmOpen()"
      [title]="i18n.t('account.danger.confirm_title')"
      [description]="i18n.t('account.danger.confirm_description')"
      [confirmLabel]="i18n.t('account.danger.confirm_cta')"
      confirmPhrase="DELETE"
      tone="danger"
      icon="trash-2"
      (cancel)="confirmOpen.set(false)"
      (confirm)="deleteAccount()"
    />
  `,
})
export class DangerComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  deleting = signal(false);
  confirmOpen = signal(false);

  deleteAccount(): void {
    this.confirmOpen.set(false);
    this.deleting.set(true);
    this.api.deleteAccount().subscribe({
      next: () => {
        this.tokenStorage.clear();
        this.authStore.clear();
        this.router.navigate(['/auth/signin']);
      },
      error: (err) => {
        this.deleting.set(false);
        this.toastr.error(
          err.error?.detail || this.i18n.t('account.danger.toast.failed'),
          this.i18n.t('account.toast.error_title'),
        );
      },
    });
  }
}
