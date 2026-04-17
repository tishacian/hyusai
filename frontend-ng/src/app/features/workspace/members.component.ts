import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { WorkspaceMemberDetail, WorkspaceService } from '@app/core/workspace.service';

@Component({
  selector: 'app-workspace-members',
  standalone: true,
  imports: [FormsModule, DatePipe, NgClass],
  template: `
    <div class="space-y-6">
      <!-- Invite -->
      @if (canAdmin()) {
        <section class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Invite member</h2>
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
            The person must already have signed up to Agentium. Email invites for new users coming soon.
          </p>
          <form (ngSubmit)="invite()" class="flex flex-wrap gap-2">
            <input
              [(ngModel)]="inviteEmail"
              name="email"
              type="email"
              placeholder="user@company.com"
              required
              class="flex-1 min-w-[220px] px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <select
              [(ngModel)]="inviteRole"
              name="role"
              class="px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
            <button
              type="submit"
              [disabled]="!inviteEmail.trim() || inviting()"
              class="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:bg-gray-400 text-white rounded-lg text-sm font-medium transition"
            >
              {{ inviting() ? 'Inviting…' : 'Invite' }}
            </button>
          </form>
          @if (inviteMessage(); as m) {
            <div
              class="mt-3 text-sm px-3 py-2 rounded"
              [ngClass]="m.error
                ? 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
                : 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'"
            >
              {{ m.text }}
            </div>
          }
        </section>
      }

      <!-- Members table -->
      <section class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
            Members ({{ members().length }})
          </h2>
        </div>

        @if (loading()) {
          <div class="p-8 text-center text-gray-500">Loading…</div>
        } @else if (members().length === 0) {
          <div class="p-8 text-center text-gray-500">No members yet.</div>
        } @else {
          <div class="divide-y divide-gray-200 dark:divide-gray-800">
            @for (m of members(); track m.user_id) {
              <div class="px-6 py-4 flex items-center gap-4">
                <div class="w-10 h-10 rounded-full bg-brand-500 text-white flex items-center justify-center text-sm font-semibold shrink-0">
                  {{ initial(m) }}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-gray-900 dark:text-white truncate">
                      @if (m.first_name || m.last_name) {
                        {{ m.first_name }} {{ m.last_name }}
                      } @else {
                        {{ m.username }}
                      }
                    </span>
                    @if (m.is_current_user) {
                      <span class="text-[10px] px-1.5 py-0.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded uppercase tracking-wide">
                        You
                      </span>
                    }
                  </div>
                  <div class="text-sm text-gray-500 dark:text-gray-400 truncate">{{ m.email }}</div>
                  <div class="text-xs text-gray-400 mt-0.5">
                    Joined {{ m.joined_at | date:'mediumDate' }}
                  </div>
                </div>

                <!-- Role -->
                <div class="text-sm">
                  @if (canAdmin() && m.role !== 'owner' && !m.is_current_user) {
                    <select
                      [value]="m.role"
                      (change)="changeRole(m, $event)"
                      [disabled]="savingMember() === m.user_id"
                      class="px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
                    >
                      <option value="admin">Admin</option>
                      <option value="member">Member</option>
                    </select>
                  } @else {
                    <span
                      class="inline-block px-2 py-0.5 text-xs rounded-full capitalize"
                      [ngClass]="roleBadgeClass(m.role)"
                    >
                      {{ m.role }}
                    </span>
                  }
                </div>

                <!-- Actions -->
                @if (canAdmin() && m.role !== 'owner' && !m.is_current_user) {
                  <button
                    type="button"
                    (click)="removeMember(m)"
                    [disabled]="savingMember() === m.user_id"
                    class="text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 px-2 py-1 rounded text-sm transition"
                    title="Remove member"
                  >
                    Remove
                  </button>
                }
              </div>
            }
          </div>
        }
      </section>

      @if (rowMessage(); as m) {
        <div
          class="px-4 py-3 rounded-lg text-sm"
          [ngClass]="m.error
            ? 'bg-red-50 dark:bg-red-900/30 text-red-800 dark:text-red-300'
            : 'bg-green-50 dark:bg-green-900/30 text-green-800 dark:text-green-300'"
        >
          {{ m.text }}
        </div>
      }
    </div>
  `,
})
export class WorkspaceMembersComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly members = signal<WorkspaceMemberDetail[]>([]);
  readonly loading = signal(true);
  readonly inviting = signal(false);
  readonly savingMember = signal<string | null>(null);
  readonly inviteMessage = signal<{ text: string; error: boolean } | null>(null);
  readonly rowMessage = signal<{ text: string; error: boolean } | null>(null);

  inviteEmail = '';
  inviteRole: 'admin' | 'member' = 'member';

  readonly canAdmin = computed(() => {
    const role = this.workspaceService.current()?.role;
    return role === 'owner' || role === 'admin';
  });

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load(slug);
    });
  }

  load(slug: string): void {
    this.loading.set(true);
    this.workspaceService.listMembers(slug).subscribe({
      next: (list) => {
        this.members.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.members.set([]);
      },
    });
  }

  invite(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const email = this.inviteEmail.trim();
    if (!email) return;
    this.inviting.set(true);
    this.inviteMessage.set(null);
    this.workspaceService.inviteMember(slug, email, this.inviteRole).subscribe({
      next: () => {
        this.inviting.set(false);
        this.inviteMessage.set({ text: `Invited ${email} as ${this.inviteRole}`, error: false });
        this.inviteEmail = '';
        this.load(slug);
        setTimeout(() => this.inviteMessage.set(null), 3000);
      },
      error: (err) => {
        this.inviting.set(false);
        this.inviteMessage.set({
          text: err?.error?.detail || 'Failed to invite',
          error: true,
        });
      },
    });
  }

  changeRole(member: WorkspaceMemberDetail, ev: Event): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const newRole = (ev.target as HTMLSelectElement).value as 'admin' | 'member';
    if (newRole === member.role) return;
    this.savingMember.set(member.user_id);
    this.rowMessage.set(null);
    this.workspaceService.updateMemberRole(slug, member.user_id, newRole).subscribe({
      next: () => {
        this.savingMember.set(null);
        this.rowMessage.set({
          text: `${member.email || member.username} is now ${newRole}`,
          error: false,
        });
        this.load(slug);
        setTimeout(() => this.rowMessage.set(null), 3000);
      },
      error: (err) => {
        this.savingMember.set(null);
        this.rowMessage.set({
          text: err?.error?.detail || 'Failed to update role',
          error: true,
        });
      },
    });
  }

  removeMember(member: WorkspaceMemberDetail): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const label = member.email || member.username;
    const ok = confirm(
      `Remove ${label} from this workspace?\n\nThey will lose access to all data in this workspace. This action cannot be undone.`
    );
    if (!ok) return;
    this.savingMember.set(member.user_id);
    this.rowMessage.set(null);
    this.workspaceService.removeMember(slug, member.user_id).subscribe({
      next: () => {
        this.savingMember.set(null);
        this.rowMessage.set({ text: `${label} removed`, error: false });
        this.load(slug);
        setTimeout(() => this.rowMessage.set(null), 3000);
      },
      error: (err) => {
        this.savingMember.set(null);
        this.rowMessage.set({
          text: err?.error?.detail || 'Failed to remove member',
          error: true,
        });
      },
    });
  }

  initial(m: WorkspaceMemberDetail): string {
    if (m.first_name) return m.first_name[0]?.toUpperCase() ?? '?';
    const src = m.email || m.username || '?';
    return src[0]?.toUpperCase() ?? '?';
  }

  roleBadgeClass(role: string): string {
    switch (role) {
      case 'owner':
        return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'admin':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      default:
        return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
    }
  }
}
