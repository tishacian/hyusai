import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AuthApiService, KcSession } from '@app/core/auth-api.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';

@Component({
  selector: 'app-account-sessions',
  standalone: true,
  template: `
    <div class="flex items-start justify-between gap-4 mb-6">
      <div>
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Active sessions</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Review where you are signed in. Sign out everywhere to revoke all sessions including this one.
        </p>
      </div>
      <button
        type="button"
        (click)="logoutAll()"
        [disabled]="signingOut()"
        class="shrink-0 px-4 py-2 text-sm font-medium rounded-lg border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20 transition disabled:opacity-50"
      >
        @if (signingOut()) { Signing out… } @else { Sign out everywhere }
      </button>
    </div>

    @if (loading()) {
      <p class="text-sm text-gray-500">Loading…</p>
    } @else if (sessions().length === 0) {
      <p class="text-sm text-gray-500">No active sessions found.</p>
    } @else {
      <div class="space-y-2">
        @for (s of sessions(); track s.id) {
          <div class="flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/40">
            <div>
              <div class="text-sm font-medium text-gray-900 dark:text-white">
                {{ s.ip_address }}
                @if (s.clients?.length) {
                  <span class="text-xs text-gray-500 dark:text-gray-400 ml-2">· {{ s.clients.join(', ') }}</span>
                }
              </div>
              <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                Started {{ formatDate(s.start) }} · Last active {{ formatDate(s.last_access) }}
              </div>
            </div>
          </div>
        }
      </div>
    }

    @if (message()) {
      <p class="mt-4 text-sm" [class.text-green-600]="!error()" [class.text-red-600]="error()">{{ message() }}</p>
    }
  `,
})
export class SessionsComponent {
  private readonly api = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);
  private readonly router = inject(Router);

  loading = signal(true);
  signingOut = signal(false);
  sessions = signal<KcSession[]>([]);
  message = signal<string | null>(null);
  error = signal(false);

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
    if (!confirm('Sign out of every device, including this one?')) return;
    this.signingOut.set(true);
    this.message.set(null);
    this.error.set(false);
    this.api.logoutAll().subscribe({
      next: () => {
        this.tokenStorage.clear();
        this.authStore.clear();
        this.router.navigate(['/auth/signin']);
      },
      error: (err) => {
        this.signingOut.set(false);
        this.error.set(true);
        this.message.set(err.error?.detail || 'Failed to sign out all sessions');
      },
    });
  }
}
