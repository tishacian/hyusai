import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { WorkspaceMemberDetail, WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

@Component({
  selector: 'app-workspace-members',
  standalone: true,
  imports: [
    FormsModule,
    DatePipe,
    NgClass,
    IconComponent,
    SkeletonComponent,
    EmptyStateComponent,
    ConfirmDialogComponent,
  ],
  template: `
    <div class="space-y-6">
      @if (canAdmin()) {
        <section class="t-card t-elevated rounded-md p-6">
          <div class="flex items-start gap-3 mb-4">
            <div class="w-10 h-10 rounded-md flex items-center justify-center bg-brand-500/10 text-brand-400 ring-1 ring-brand-500/30">
              <app-icon name="user-plus" [size]="18" />
            </div>
            <div>
              <h2 class="text-base font-semibold text-white">Invite member</h2>
              <p class="text-sm text-gray-400 mt-0.5">
                Invite anyone by email. Existing Agentium users are added instantly; new addresses are provisioned in Keycloak and receive a password-setup email.
              </p>
            </div>
          </div>
          <form (ngSubmit)="invite()" class="flex flex-wrap gap-2">
            <input
              [(ngModel)]="inviteEmail"
              name="email"
              type="email"
              placeholder="user@company.com"
              required
              class="flex-1 min-w-[220px] px-3 py-2 rounded bg-black/20 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 transition"
            />
            <select
              [(ngModel)]="inviteRole"
              name="role"
              class="px-3 py-2 rounded bg-black/20 border border-white/10 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/60"
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
            <button
              type="submit"
              [disabled]="!inviteEmail.trim() || inviting()"
              class="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-40 text-white rounded text-sm font-medium transition shadow-glow-sm inline-flex items-center gap-1.5"
            >
              <app-icon name="send" [size]="14" />
              {{ inviting() ? 'Inviting…' : 'Invite' }}
            </button>
          </form>
        </section>
      }

      <section class="t-card t-elevated rounded-md overflow-hidden">
        <div class="px-6 py-4 border-b border-white/5 flex items-center justify-between">
          <h2 class="text-base font-semibold text-white flex items-center gap-2">
            <app-icon name="users" [size]="16" class="text-brand-400" />
            Members <span class="text-gray-500 font-normal">· {{ members().length }}</span>
          </h2>
        </div>

        @if (loading()) {
          <div class="p-6 space-y-3">
            <app-skeleton height="56px" />
            <app-skeleton height="56px" />
            <app-skeleton height="56px" />
          </div>
        } @else if (members().length === 0) {
          <app-empty-state icon="users" title="No members yet" description="Invite teammates to get started." />
        } @else {
          <div class="divide-y divide-white/5">
            @for (m of members(); track m.user_id) {
              <div class="px-6 py-4 flex items-center gap-4">
                <div
                  class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 text-white bg-gradient-to-br from-brand-500 to-violet-500"
                >
                  {{ initial(m) }}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium text-white truncate">
                      @if (m.first_name || m.last_name) {
                        {{ m.first_name }} {{ m.last_name }}
                      } @else {
                        {{ m.username }}
                      }
                    </span>
                    @if (m.is_current_user) {
                      <span class="text-[9px] px-1.5 py-0.5 bg-white/10 text-gray-300 rounded uppercase tracking-wider font-semibold">
                        You
                      </span>
                    }
                  </div>
                  <div class="text-sm text-gray-400 truncate">{{ m.email }}</div>
                  <div class="text-xs text-gray-500 mt-0.5 inline-flex items-center gap-1">
                    <app-icon name="clock" [size]="11" />
                    Joined {{ m.joined_at | date: 'mediumDate' }}
                  </div>
                </div>

                <div class="text-sm">
                  @if (canAdmin() && m.role !== 'owner' && !m.is_current_user) {
                    <select
                      [value]="m.role"
                      (change)="changeRole(m, $event)"
                      [disabled]="savingMember() === m.user_id"
                      class="px-2 py-1 rounded bg-black/20 border border-white/10 text-white text-sm"
                    >
                      <option value="admin">Admin</option>
                      <option value="member">Member</option>
                    </select>
                  } @else {
                    <span
                      class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full capitalize font-medium"
                      [ngClass]="roleBadgeClass(m.role)"
                    >
                      @if (m.role === 'owner') {
                        <app-icon name="crown" [size]="11" />
                      } @else if (m.role === 'admin') {
                        <app-icon name="shield-check" [size]="11" />
                      } @else {
                        <app-icon name="user-round" [size]="11" />
                      }
                      {{ m.role }}
                    </span>
                  }
                </div>

                @if (canAdmin() && m.role !== 'owner' && !m.is_current_user) {
                  <button
                    type="button"
                    (click)="requestRemove(m)"
                    [disabled]="savingMember() === m.user_id"
                    class="text-red-400 hover:bg-red-500/10 p-2 rounded transition"
                    title="Remove member"
                  >
                    <app-icon name="trash-2" [size]="14" />
                  </button>
                }
              </div>
            }
          </div>
        }
      </section>
    </div>

    <app-confirm-dialog
      [open]="!!pendingRemove()"
      title="Remove member?"
      [description]="pendingRemove() ? 'Remove ' + (pendingRemove()?.email || pendingRemove()?.username) + ' from this workspace? They will lose access to all data.' : ''"
      confirmLabel="Remove member"
      tone="danger"
      icon="trash-2"
      (cancel)="pendingRemove.set(null)"
      (confirm)="confirmRemove()"
    />
  `,
})
export class WorkspaceMembersComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly members = signal<WorkspaceMemberDetail[]>([]);
  readonly loading = signal(true);
  readonly inviting = signal(false);
  readonly savingMember = signal<string | null>(null);
  readonly pendingRemove = signal<WorkspaceMemberDetail | null>(null);

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
    this.workspaceService.inviteMember(slug, email, this.inviteRole).subscribe({
      next: (res) => {
        this.inviting.set(false);
        const verb = res?.invitation_email_sent
          ? 'Invitation email sent'
          : 'Member added';
        this.toastr.success(`${email} is now ${this.inviteRole}`, verb);
        this.inviteEmail = '';
        this.load(slug);
      },
      error: (err) => {
        this.inviting.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to invite', 'Error');
      },
    });
  }

  changeRole(member: WorkspaceMemberDetail, ev: Event): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const newRole = (ev.target as HTMLSelectElement).value as 'admin' | 'member';
    if (newRole === member.role) return;
    this.savingMember.set(member.user_id);
    this.workspaceService.updateMemberRole(slug, member.user_id, newRole).subscribe({
      next: () => {
        this.savingMember.set(null);
        this.toastr.success(`${member.email || member.username} is now ${newRole}`, 'Role updated');
        this.load(slug);
      },
      error: (err) => {
        this.savingMember.set(null);
        this.toastr.error(err?.error?.detail || 'Failed to update role', 'Error');
      },
    });
  }

  requestRemove(member: WorkspaceMemberDetail): void {
    this.pendingRemove.set(member);
  }

  confirmRemove(): void {
    const member = this.pendingRemove();
    const slug = this.routeSlug();
    if (!member || !slug) return;
    this.pendingRemove.set(null);
    const label = member.email || member.username;
    this.savingMember.set(member.user_id);
    this.workspaceService.removeMember(slug, member.user_id).subscribe({
      next: () => {
        this.savingMember.set(null);
        this.toastr.success(`${label} removed`, 'Member removed');
        this.load(slug);
      },
      error: (err) => {
        this.savingMember.set(null);
        this.toastr.error(err?.error?.detail || 'Failed to remove member', 'Error');
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
        return 'bg-amber-500/15 text-amber-400 border border-amber-500/30';
      case 'admin':
        return 'bg-brand-500/15 text-brand-400 border border-brand-500/30';
      default:
        return 'bg-white/5 text-gray-300 border border-white/10';
    }
  }
}
