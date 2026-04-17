import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';

@Component({
  selector: 'app-account-danger',
  standalone: true,
  imports: [FormsModule],
  template: `
    <h2 class="text-lg font-semibold text-red-600 dark:text-red-400 mb-1">Danger zone</h2>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
      Deleting your account is permanent. You will lose access to your workspaces and all related data.
    </p>

    <div class="rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/10 p-5 space-y-4">
      <div>
        <h3 class="font-semibold text-red-700 dark:text-red-300">Delete my account</h3>
        <p class="text-sm text-red-600/80 dark:text-red-300/70 mt-1">
          This removes your user from Keycloak and Agentium. Workspace ownerships should be transferred first.
        </p>
      </div>

      <div>
        <label class="block text-sm font-medium text-red-700 dark:text-red-300 mb-1">
          Type <code class="px-1 py-0.5 rounded bg-red-100 dark:bg-red-900/40">DELETE</code> to confirm
        </label>
        <input
          type="text"
          [(ngModel)]="confirmText"
          name="confirm"
          class="w-full max-w-sm px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-red-300 dark:border-red-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-red-500"
          placeholder="DELETE"
        />
      </div>

      @if (message()) {
        <p class="text-sm text-red-600">{{ message() }}</p>
      }

      <button
        type="button"
        (click)="deleteAccount()"
        [disabled]="confirmText !== 'DELETE' || deleting()"
        class="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white font-medium transition"
      >
        @if (deleting()) { Deleting… } @else { Delete my account permanently }
      </button>
    </div>
  `,
})
export class DangerComponent {
  private readonly api = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);
  private readonly router = inject(Router);

  confirmText = '';
  deleting = signal(false);
  message = signal<string | null>(null);

  deleteAccount(): void {
    if (this.confirmText !== 'DELETE') return;
    if (!confirm('This cannot be undone. Delete your account permanently?')) return;

    this.deleting.set(true);
    this.message.set(null);
    this.api.deleteAccount().subscribe({
      next: () => {
        this.tokenStorage.clear();
        this.authStore.clear();
        this.router.navigate(['/auth/signin']);
      },
      error: (err) => {
        this.deleting.set(false);
        this.message.set(err.error?.detail || 'Failed to delete account');
      },
    });
  }
}
