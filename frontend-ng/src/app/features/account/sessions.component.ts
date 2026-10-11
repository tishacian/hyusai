import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { AuthApiService, KcSession } from '@app/core/auth-api.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';

@Component({
  selector: 'app-account-sessions',
  standalone: true,
  imports: [IconComponent, SkeletonComponent, ConfirmDialogComponent, EmptyStateComponent],
  template: `
    <div class="ck-surface t-elevated rounded-md p-6">
      <div class="flex items-start justify-between gap-4 mb-5">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
            <app-icon name="monitor" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-white">{{ i18n.t('account.sessions.title') }}</h2>
            <p class="text-sm text-gray-400 mt-0.5">
              {{ i18n.t('account.sessions.description') }}
            </p>
          </div>
        </div>
        <button
          type="button"
          (click)="confirmOpen.set(true)"
          [disabled]="signingOut()"
          class="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded border border-red-500/30 text-red-400 hover:bg-red-500/10 transition disabled:opacity-50"
        >
          <app-icon name="log-out" [size]="14" />
          @if (signingOut()) { {{ i18n.t('account.sessions.signing_out') }} } @else { {{ i18n.t('account.sessions.signout_all') }} }
        </button>
      </div>

      @if (loading()) {
        <div class="space-y-2">
          <app-skeleton height="56px" />
          <app-skeleton height="56px" />
        </div>
      } @else if (sessions().length === 0) {
        <app-empty-state
          icon="monitor"
          [title]="i18n.t('account.sessions.empty.title')"
          [description]="i18n.t('account.sessions.empty.description')"
        />
      } @else {
        <div class="space-y-2">
          @for (s of sessions(); track s.id) {
            <div class="flex items-center justify-between p-3 rounded-md border border-white/5 bg-black/20">
              <div class="flex items-center gap-3 min-w-0">
                <div class="w-9 h-9 rounded bg-cyan-500/10 text-cyan-400 flex items-center justify-center shrink-0">
                  <app-icon name="laptop" [size]="16" />
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-medium text-white font-mono">
                    {{ s.ip_address }}
                    @if (s.clients.length) {
                      <span class="text-xs text-gray-500 ml-2 font-sans">· {{ s.clients.join(', ') }}</span>
                    }
                  </div>
                  <div class="text-xs text-gray-500 mt-0.5 flex items-center gap-3 flex-wrap">
                    <span class="inline-flex items-center gap-1"><app-icon name="clock" [size]="11" /> {{ formatDate(s.start) }}</span>
                    <span class="inline-flex items-center gap-1"><app-icon name="activity" [size]="11" /> {{ formatDate(s.last_access) }}</span>
                  </div>
                </div>
              </div>
            </div>
          }
        </div>
      }
    </div>

    <app-confirm-dialog
      [open]="confirmOpen()"
      [title]="i18n.t('account.sessions.confirm_title')"
      [description]="i18n.t('account.sessions.confirm_description')"
      [confirmLabel]="i18n.t('account.sessions.signout_all')"
      tone="danger"
      icon="log-out"
      (cancel)="confirmOpen.set(false)"
      (confirm)="logoutAll()"
    />
  `,
})
export class SessionsComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  loading = signal(true);
  signingOut = signal(false);
  sessions = signal<KcSession[]>([]);
  confirmOpen = signal(false);

  constructor() {
    this.api.listSessions().subscribe({
      next: (list) => {
        this.sessions.set(list);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  formatDate(ts: number | undefined): string {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return String(ts);
    }
  }

  logoutAll(): void {
    this.confirmOpen.set(false);
    this.signingOut.set(true);
    this.api.logoutAll().subscribe({
      next: () => {
        this.tokenStorage.clear();
        this.authStore.clear();
        this.router.navigate(['/auth/signin']);
      },
      error: (err) => {
        this.signingOut.set(false);
        this.toastr.error(
          err.error?.detail || this.i18n.t('account.sessions.toast.failed'),
          this.i18n.t('account.toast.error_title'),
        );
      },
    });
  }
}
