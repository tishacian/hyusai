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
        @if (receipt(); as result) {
          <section role="status" data-testid="account-delete-receipt">
            <h3>{{ i18n.t(result.profile_deleted ? 'governance.account.deleted' : 'governance.account.partial') }}</h3>
            <p>{{ i18n.t('governance.account.identity') }}: {{ i18n.t(result.identity_deleted ? 'common.yes' : 'common.no') }}</p>
            <p>{{ i18n.t('governance.account.profile') }}: {{ i18n.t(result.profile_deleted ? 'common.yes' : 'common.no') }}</p>
            <p>{{ i18n.t('governance.account.connections') }}: {{ i18n.t(result.connections_revoked ? 'common.yes' : 'common.no') }}</p>
            <p>{{ i18n.t('governance.account.retained') }}</p>
            @if (!result.profile_deleted) { <p role="alert">{{ i18n.t('governance.account.partial_help') }}</p> }
            <button type="button" class="px-3 py-2" (click)="leave()">{{ i18n.t('governance.account.signin') }}</button>
          </section>
        } @else if (outcomeUnknown()) {
          <p role="alert">{{ i18n.t('governance.account.unknown') }}</p>
          <button type="button" (click)="leave()">{{ i18n.t('governance.account.signin') }}</button>
        } @else {
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
        }
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
  readonly outcomeUnknown = signal(false);
  confirmOpen = signal(false);
  readonly receipt = signal<{identity_deleted:boolean;profile_deleted:boolean;connections_revoked:boolean;retained:string[]} | null>(null);

  leave(): void { this.tokenStorage.clear(); this.authStore.clear(); void this.router.navigate(['/auth/signin']); }

  deleteAccount(): void {
    if (this.deleting() || this.outcomeUnknown() || this.receipt()) return;
    this.confirmOpen.set(false);
    this.deleting.set(true);
    this.api.deleteAccount().subscribe({
      next: (result) => {
        this.tokenStorage.clear();
        this.deleting.set(false);
        this.receipt.set(result.receipt);
      },
      error: (err) => {
        this.deleting.set(false);
        if (err.error?.detail?.code === 'ACCOUNT_DELETE_PARTIAL' && err.error.detail.receipt) {
          this.tokenStorage.clear(); this.receipt.set(err.error.detail.receipt); return;
        }
        if (!err.status || err.status >= 500) { this.outcomeUnknown.set(true); return; }
        this.toastr.error(
          typeof err.error?.detail === 'string' ? err.error.detail : this.i18n.t('account.danger.toast.failed'),
          this.i18n.t('account.toast.error_title'),
        );
      },
    });
  }
}
