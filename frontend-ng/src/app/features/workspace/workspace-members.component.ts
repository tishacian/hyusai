import { Component, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { WorkspaceService } from '@app/core/workspace.service';

interface Member {
  user_id: string;
  email: string;
  role: string;
}

@Component({
  selector: 'app-workspace-members',
  standalone: true,
  imports: [FormsModule],
  template: `
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Workspace Members</h1>

    <!-- Invite form -->
    <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 mb-6">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">Invite Member</h2>
      <form (ngSubmit)="invite()" class="flex gap-3">
        <input
          [(ngModel)]="inviteEmail"
          name="email"
          type="email"
          placeholder="user&#64;company.com"
          class="flex-1 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm"
        />
        <select [(ngModel)]="inviteRole" name="role" class="px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm">
          <option value="member">Member</option>
          <option value="admin">Admin</option>
          <option value="viewer">Viewer</option>
        </select>
        <button type="submit" class="px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-sm">Invite</button>
      </form>
      @if (inviteStatus()) {
        <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">{{ inviteStatus() }}</p>
      }
    </div>

    <!-- Members table -->
    <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th class="px-4 py-3 text-left text-gray-600 dark:text-gray-400 font-medium">Email</th>
            <th class="px-4 py-3 text-left text-gray-600 dark:text-gray-400 font-medium">Role</th>
            <th class="px-4 py-3 text-right text-gray-600 dark:text-gray-400 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          @for (m of members(); track m.user_id) {
            <tr class="border-t border-gray-100 dark:border-gray-800">
              <td class="px-4 py-3 text-gray-900 dark:text-white">{{ m.email }}</td>
              <td class="px-4 py-3 capitalize text-gray-500">{{ m.role }}</td>
              <td class="px-4 py-3 text-right">
                <button (click)="removeMember(m.user_id)" class="text-red-500 hover:text-red-700 text-xs">Remove</button>
              </td>
            </tr>
          } @empty {
            <tr><td colspan="3" class="px-4 py-8 text-center text-gray-400">No members</td></tr>
          }
        </tbody>
      </table>
    </div>
  `,
})
export class WorkspaceMembersComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly ws = inject(WorkspaceService);

  members = signal<Member[]>([]);
  inviteEmail = '';
  inviteRole = 'member';
  inviteStatus = signal<string | null>(null);

  ngOnInit(): void {
    this.loadMembers();
  }

  loadMembers(): void {
    const slug = this.ws.currentSlug();
    if (!slug) return;
    // Members are part of the workspace response; for now, show current user
    this.members.set([]);
  }

  invite(): void {
    const slug = this.ws.currentSlug();
    if (!slug || !this.inviteEmail) return;
    this.http
      .post<any>(`/api/v1/auth/workspaces/${slug}/members`, {
        email: this.inviteEmail,
        role: this.inviteRole,
      })
      .subscribe({
        next: () => {
          this.inviteStatus.set('Invited!');
          this.inviteEmail = '';
          this.loadMembers();
        },
        error: (err) => this.inviteStatus.set(err.error?.detail || 'Failed'),
      });
  }

  removeMember(userId: string): void {
    const slug = this.ws.currentSlug();
    if (!slug) return;
    this.http.delete(`/api/v1/auth/workspaces/${slug}/members/${userId}`).subscribe({
      next: () => this.loadMembers(),
      error: () => {},
    });
  }
}
