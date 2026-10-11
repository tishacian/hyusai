import { Component, inject, signal } from '@angular/core';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { AuthApiService } from '@app/core/auth-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';

@Component({
  selector: 'app-account-security',
  standalone: true,
  imports: [IconComponent, SkeletonComponent],
  template: `
    <div class="ck-surface t-elevated rounded-md p-6">
      <div class="flex items-start gap-3 mb-5">
        <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
          <app-icon name="shield" [size]="18" />
        </div>
        <div>
          <h2 class="text-base font-semibold text-white">{{ i18n.t('account.security') }}</h2>
          <p class="text-sm text-gray-400 mt-0.5">
            {{ i18n.t('account.security.description') }}
          </p>
        </div>
      </div>

      @if (loading()) {
        <div class="space-y-3">
          <app-skeleton height="56px" />
          <app-skeleton height="20px" width="60%" />
        </div>
      } @else {
        <div class="flex items-start justify-between gap-4 p-4 rounded-md bg-black/20 border border-white/5">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <app-icon name="mail" [size]="16" class="text-cyan-400" />
              <span class="font-medium text-white">{{ i18n.t('account.security.mfa.title') }}</span>
              @if (enabled()) {
                <span class="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-semibold">
                  {{ i18n.t('account.security.mfa.enabled') }}
                </span>
              } @else {
                <span class="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-gray-500/15 text-gray-400 border border-gray-500/30 font-semibold">
                  {{ i18n.t('account.security.mfa.disabled') }}
                </span>
              }
            </div>
            <p class="text-sm text-gray-400 mt-1">
              {{ i18n.t('account.security.mfa.description') }}
            </p>
          </div>
          <button
            type="button"
            (click)="toggle()"
            [disabled]="saving()"
            class="shrink-0 px-4 py-2 rounded text-sm font-medium transition disabled:opacity-50 inline-flex items-center gap-1.5"
            [class.bg-cyan-500]="!enabled()"
            [class.text-white]="!enabled()"
            [class.hover:bg-cyan-600]="!enabled()"
            [class.shadow-glow-sm]="!enabled()"
            [class.bg-white\\/5]="enabled()"
            [class.text-gray-200]="enabled()"
            [class.hover:bg-white\\/10]="enabled()"
            [class.ring-1]="enabled()"
            [class.ring-white\\/10]="enabled()"
          >
            @if (saving()) {
              <app-icon name="loader-2" [size]="14" class="animate-spin" />
              {{ i18n.t('account.saving') }}
            } @else if (enabled()) {
              <app-icon name="unlock" [size]="14" /> {{ i18n.t('account.security.mfa.disable') }}
            } @else {
              <app-icon name="lock" [size]="14" /> {{ i18n.t('account.security.mfa.enable') }}
            }
          </button>
        </div>
      }
    </div>
  `,
})
export class SecurityComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(AuthApiService);
  private readonly toastr = inject(ToastrService);

  loading = signal(true);
  saving = signal(false);
  enabled = signal(false);

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
    this.api.toggleMfa(next).subscribe({
      next: (res) => {
        this.enabled.set(res.mfa_enabled);
        this.saving.set(false);
        this.toastr.success(
          res.mfa_enabled
            ? this.i18n.t('account.security.toast.enabled')
            : this.i18n.t('account.security.toast.disabled'),
          res.mfa_enabled
            ? this.i18n.t('account.security.toast.enabled_title')
            : this.i18n.t('account.security.toast.disabled_title'),
        );
      },
      error: (err) => {
        this.saving.set(false);
        this.toastr.error(
          err.error?.detail || this.i18n.t('account.security.toast.failed'),
          this.i18n.t('account.toast.error_title'),
        );
      },
    });
  }
}
