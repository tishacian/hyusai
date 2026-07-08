import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { AuthApiService, UserProfile } from '@app/core/auth-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';

const FIELD_CLASS =
  'w-full px-3 py-2 rounded bg-black/20 dark:bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/40 transition';

@Component({
  selector: 'app-account-profile',
  standalone: true,
  imports: [FormsModule, IconComponent, SkeletonComponent],
  template: `
    <div class="ck-surface t-elevated rounded-md p-6">
      <div class="flex items-start gap-3 mb-5">
        <div class="w-10 h-10 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
          <app-icon name="user-round" [size]="18" />
        </div>
        <div>
          <h2 class="text-base font-semibold text-white">Profile</h2>
          <p class="text-sm text-gray-400 mt-0.5">
            Your identity across Agentium, shared with workspace members.
          </p>
        </div>
      </div>

      @if (loading()) {
        <div class="space-y-3">
          <app-skeleton height="40px" />
          <app-skeleton height="40px" />
          <app-skeleton height="40px" width="60%" />
        </div>
      } @else if (profile(); as p) {
        <form (ngSubmit)="save()" class="space-y-4">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">First name</label>
              <input [(ngModel)]="firstName" name="firstName" [class]="field" />
            </div>
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Last name</label>
              <input [(ngModel)]="lastName" name="lastName" [class]="field" />
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Email</label>
            <input
              [value]="p.email"
              disabled
              class="w-full px-3 py-2 rounded bg-black/40 border border-white/5 text-gray-500 cursor-not-allowed"
            />
            <p class="text-xs text-gray-500 mt-1">Contact an administrator to change your email.</p>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Phone</label>
              <input [(ngModel)]="phone" name="phone" [class]="field" />
            </div>
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Company</label>
              <input [(ngModel)]="company" name="company" [class]="field" />
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Job title</label>
            <input [(ngModel)]="jobTitle" name="jobTitle" [class]="field" />
          </div>

          <div class="flex gap-3 pt-2">
            <button
              type="submit"
              [disabled]="saving()"
              class="inline-flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white font-medium rounded transition shadow-glow-sm"
            >
              <app-icon name="save" [size]="14" />
              @if (saving()) { Saving… } @else { Save changes }
            </button>
          </div>
        </form>
      }
    </div>
  `,
})
export class ProfileComponent {
  private readonly api = inject(AuthApiService);
  private readonly toastr = inject(ToastrService);

  protected readonly field = FIELD_CLASS;

  loading = signal(true);
  saving = signal(false);
  profile = signal<UserProfile | null>(null);

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
          this.toastr.success('Profile updated', 'Saved');
        },
        error: (err) => {
          this.saving.set(false);
          this.toastr.error(err.error?.detail || 'Failed to update profile', 'Error');
        },
      });
  }
}
