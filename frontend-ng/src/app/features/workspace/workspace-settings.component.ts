import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { HttpClient } from '@angular/common/http';

@Component({
  selector: 'app-workspace-settings',
  standalone: true,
  imports: [FormsModule, RouterLink],
  template: `
    <div class="max-w-2xl">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Workspace Settings</h1>

      @if (workspaceService.current(); as ws) {
        <div class="space-y-6">
          <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">General</h2>
            <div class="space-y-3">
              <div>
                <label class="text-sm text-gray-500 dark:text-gray-400">Name</label>
                <p class="text-gray-900 dark:text-white">{{ ws.name }}</p>
              </div>
              <div>
                <label class="text-sm text-gray-500 dark:text-gray-400">Slug</label>
                <p class="font-mono text-gray-900 dark:text-white">{{ ws.slug }}</p>
              </div>
              <div>
                <label class="text-sm text-gray-500 dark:text-gray-400">Role</label>
                <p class="text-gray-900 dark:text-white capitalize">{{ ws.role }}</p>
              </div>
            </div>
          </div>

          <a routerLink="members" class="inline-block px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white rounded-lg transition text-sm">
            Manage Members
          </a>

          <!-- Create new workspace -->
          <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Create New Workspace</h2>
            <form (ngSubmit)="createWorkspace()" class="flex gap-3">
              <input
                [(ngModel)]="newWorkspaceName"
                name="wsName"
                placeholder="Workspace name"
                class="flex-1 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm"
              />
              <button type="submit" class="px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-sm">Create</button>
            </form>
            @if (createStatus()) {
              <p class="mt-2 text-sm text-green-600">{{ createStatus() }}</p>
            }
          </div>

          <!-- Workspace switcher -->
          @if (workspaceService.workspaces().length > 1) {
            <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
              <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">Switch Workspace</h2>
              <div class="space-y-2">
                @for (w of workspaceService.workspaces(); track w.slug) {
                  <button
                    (click)="workspaceService.switchWorkspace(w.slug)"
                    class="w-full text-left px-3 py-2 rounded-lg text-sm transition"
                    [class]="w.slug === workspaceService.currentSlug() ? 'bg-brand-100 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300' : 'hover:bg-gray-50 dark:hover:bg-gray-800'"
                  >
                    {{ w.name }} <span class="text-xs text-gray-400">({{ w.role }})</span>
                  </button>
                }
              </div>
            </div>
          }
        </div>
      } @else {
        <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
          <p class="text-gray-500 dark:text-gray-400 mb-4">No workspace selected. Create one to get started.</p>
          <form (ngSubmit)="createWorkspace()" class="flex gap-3">
            <input
              [(ngModel)]="newWorkspaceName"
              name="wsName"
              placeholder="Workspace name"
              class="flex-1 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm"
            />
            <button type="submit" class="px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-sm">Create</button>
          </form>
        </div>
      }
    </div>
  `,
})
export class WorkspaceSettingsComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly http = inject(HttpClient);

  newWorkspaceName = '';
  createStatus = signal<string | null>(null);

  createWorkspace(): void {
    if (!this.newWorkspaceName.trim()) return;
    this.http.post<any>('/api/v1/auth/workspaces', { name: this.newWorkspaceName }).subscribe({
      next: (ws) => {
        this.createStatus.set(`Created: ${ws.name}`);
        this.newWorkspaceName = '';
        this.workspaceService.loadWorkspaces();
      },
      error: (err) => this.createStatus.set(err.error?.detail || 'Failed'),
    });
  }
}
