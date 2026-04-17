import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthApiService, UserProfile } from '@app/core/auth-api.service';

@Component({
  selector: 'app-account-profile',
  standalone: true,
  imports: [FormsModule],
  template: `
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Profile</h2>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
      Your profile is stored in Keycloak and visible to your workspace members.
    </p>

    @if (loading()) {
      <p class="text-sm text-gray-500">Loading…</p>
    } @else if (profile(); as p) {
      <form (ngSubmit)="save()" class="space-y-4 max-w-xl">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">First name</label>
            <input
              [(ngModel)]="firstName"
              name="firstName"
              class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Last name</label>
            <input
              [(ngModel)]="lastName"
              name="lastName"
              class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Email</label>
          <input
            [value]="p.email"
            disabled
            class="w-full px-3 py-2 border rounded-lg bg-gray-100 dark:bg-gray-800/50 border-gray-200 dark:border-gray-700 text-gray-500 cursor-not-allowed"
          />
          <p class="text-xs text-gray-500 mt-1">Contact an administrator to change your email.</p>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Phone</label>
            <input
              [(ngModel)]="phone"
              name="phone"
              class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Company</label>
            <input
              [(ngModel)]="company"
              name="company"
              class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Job title</label>
          <input
            [(ngModel)]="jobTitle"
            name="jobTitle"
            class="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        @if (message()) {
          <p class="text-sm" [class.text-green-600]="!error()" [class.text-red-600]="error()">
            {{ message() }}
          </p>
        }

        <div class="flex gap-3 pt-2">
          <button
            type="submit"
            [disabled]="saving()"
            class="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition"
          >
            @if (saving()) { Saving… } @else { Save changes }
          </button>
        </div>
      </form>
    }
  `,
})
export class ProfileComponent {
  private readonly api = inject(AuthApiService);

  loading = signal(true);
  saving = signal(false);
  profile = signal<UserProfile | null>(null);
  message = signal<string | null>(null);
  error = signal(false);

  firstName = '';
  lastName = '';
  phone = '';
  company = '';
  jobTitle = '';

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.api.me().subscribe({
      next: (p) => {
        this.profile.set(p);
        this.firstName = p.first_name || '';
        this.lastName = p.last_name || '';
        this.phone = p.phone || '';
        this.company = p.company || '';
        this.jobTitle = p.job_title || '';
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  save(): void {
    this.saving.set(true);
    this.message.set(null);
    this.error.set(false);
    this.api
      .updateProfile({
        first_name: this.firstName,
        last_name: this.lastName,
        phone: this.phone,
        company: this.company,
        job_title: this.jobTitle,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.message.set('Profile updated successfully');
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(true);
          this.message.set(err.error?.detail || 'Failed to update profile');
        },
      });
  }
}
