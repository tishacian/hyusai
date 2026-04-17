import { Component, computed, effect, inject, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { WorkspaceDetail, WorkspaceService } from '@app/core/workspace.service';

@Component({
  selector: 'app-workspace-danger',
  standalone: true,
  imports: [FormsModule, NgClass],
  template: `
    <div class="space-y-6">
      <!-- Leave -->
      <section class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Leave workspace</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Leave this workspace. You will lose access to all of its data, but other members will keep working normally.
          @if (isOwner()) {
            <br /><span class="text-amber-600 dark:text-amber-400">As the owner, you must first transfer ownership before you can leave.</span>
          }
        </p>
        <button
          type="button"
          (click)="leave()"
          [disabled]="isOwner() || leaving()"
          class="px-4 py-2 border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {{ leaving() ? 'Leaving…' : 'Leave workspace' }}
        </button>
      </section>

      <!-- Delete -->
      <section class="bg-white dark:bg-gray-900 rounded-xl border-2 border-red-300 dark:border-red-800 p-6">
        <h2 class="text-lg font-semibold text-red-700 dark:text-red-400 mb-1">Delete workspace</h2>
        <p class="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Deleting the workspace archives it and removes it from every member's sidebar.
          You can restore it within <strong>30 days</strong> by contacting an administrator.
          After this grace period, all data (documents, sessions, knowledge) will be permanently removed.
        </p>

        @if (!isOwner()) {
          <div class="text-sm text-gray-500 dark:text-gray-400 italic">
            Only the workspace owner can delete this workspace.
          </div>
        } @else if (detail()?.deleted_at) {
          <div class="flex items-center gap-3">
            <span class="px-2 py-1 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 text-xs rounded">
              Archived
            </span>
            <button
              type="button"
              (click)="restore()"
              [disabled]="restoring()"
              class="px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-sm font-medium transition disabled:opacity-40"
            >
              {{ restoring() ? 'Restoring…' : 'Restore workspace' }}
            </button>
          </div>
        } @else {
          <div class="space-y-3">
            <label class="block text-sm text-gray-700 dark:text-gray-300">
              Type the workspace name
              <strong class="font-mono text-red-600 dark:text-red-400">{{ detail()?.name }}</strong>
              to confirm:
            </label>
            <input
              [(ngModel)]="confirmName"
              type="text"
              [placeholder]="detail()?.name || ''"
              class="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-red-500"
            />
            <button
              type="button"
              (click)="remove()"
              [disabled]="!canDelete() || deleting()"
              class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {{ deleting() ? 'Deleting…' : 'Delete workspace permanently' }}
            </button>
          </div>
        }

        @if (message(); as m) {
          <div
            class="mt-4 px-3 py-2 rounded text-sm"
            [ngClass]="m.error
              ? 'bg-red-50 dark:bg-red-900/30 text-red-800 dark:text-red-300'
              : 'bg-green-50 dark:bg-green-900/30 text-green-800 dark:text-green-300'"
          >
            {{ m.text }}
          </div>
        }
      </section>
    </div>
  `,
})
export class WorkspaceDangerComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly leaving = signal(false);
  readonly deleting = signal(false);
  readonly restoring = signal(false);
  readonly message = signal<{ text: string; error: boolean } | null>(null);

  confirmName = '';

  readonly isOwner = computed(() => this.detail()?.role === 'owner');
  readonly canDelete = computed(() => {
    const d = this.detail();
    return !!d && this.confirmName.trim() === d.name;
  });

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load(slug);
    });
  }

  load(slug: string): void {
    this.workspaceService.getWorkspace(slug).subscribe({
      next: (d) => this.detail.set(d),
      error: () => this.detail.set(null),
    });
  }

  leave(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    const ok = confirm('Leave this workspace? You will lose access to its data.');
    if (!ok) return;
    this.leaving.set(true);
    this.workspaceService.leaveWorkspace(slug).subscribe({
      next: () => {
        this.leaving.set(false);
        this.router.navigate(['/workspace']);
      },
      error: (err) => {
        this.leaving.set(false);
        this.message.set({ text: err?.error?.detail || 'Failed to leave', error: true });
      },
    });
  }

  remove(): void {
    const slug = this.routeSlug();
    const d = this.detail();
    if (!slug || !d) return;
    this.deleting.set(true);
    this.message.set(null);
    this.workspaceService.deleteWorkspace(slug, this.confirmName.trim()).subscribe({
      next: () => {
        this.deleting.set(false);
        this.router.navigate(['/workspace']);
      },
      error: (err) => {
        this.deleting.set(false);
        this.message.set({
          text: err?.error?.detail || 'Failed to delete',
          error: true,
        });
      },
    });
  }

  restore(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    this.restoring.set(true);
    this.workspaceService.restoreWorkspace(slug).subscribe({
      next: () => {
        this.restoring.set(false);
        this.load(slug);
        this.workspaceService.loadWorkspaces().subscribe();
        this.message.set({ text: 'Workspace restored', error: false });
      },
      error: (err) => {
        this.restoring.set(false);
        this.message.set({
          text: err?.error?.detail || 'Failed to restore',
          error: true,
        });
      },
    });
  }
}
