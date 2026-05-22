import { Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { WorkspaceDetail, WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

@Component({
  selector: 'app-workspace-danger',
  standalone: true,
  imports: [IconComponent, ConfirmDialogComponent],
  template: `
    <div class="space-y-6">
      <section class="t-card t-elevated rounded-md p-6">
        <div class="flex items-start gap-3 mb-4">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/30">
            <app-icon name="log-out" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-white">Leave workspace</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              You will lose access to all data in this workspace. Other members keep working normally.
            </p>
            @if (isOwner()) {
              <p class="text-xs text-amber-400 mt-1.5">
                As owner you must transfer ownership before leaving.
              </p>
            }
          </div>
        </div>
        <button
          type="button"
          (click)="leaveOpen.set(true)"
          [disabled]="isOwner() || leaving()"
          class="inline-flex items-center gap-1.5 px-4 py-2 border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 rounded text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <app-icon name="log-out" [size]="14" />
          {{ leaving() ? 'Leaving…' : 'Leave workspace' }}
        </button>
      </section>

      <section class="t-card t-elevated rounded-md p-6 border-red-500/30">
        <div class="flex items-start gap-3 mb-4">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-red-500/10 text-red-400 ring-1 ring-red-500/30">
            <app-icon name="shield-alert" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-red-400">Delete workspace</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              Archives it and removes it from every member's sidebar. Restore it within
              <strong class="text-white">30 days</strong>. After that, all data is permanently purged.
            </p>
          </div>
        </div>

        @if (!isOwner()) {
          <p class="text-sm text-gray-500 italic">Only the workspace owner can delete this workspace.</p>
        } @else if (detail()?.deleted_at) {
          <div class="flex items-center gap-3 flex-wrap">
            <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30 text-xs font-medium">
              <app-icon name="archive" [size]="11" /> Archived
            </span>
            <button
              type="button"
              (click)="restore()"
              [disabled]="restoring()"
              class="inline-flex items-center gap-1.5 px-4 py-2 bg-brand-500 hover:bg-brand-400 text-white rounded text-sm font-medium transition disabled:opacity-40"
            >
              <app-icon name="archive-restore" [size]="14" />
              {{ restoring() ? 'Restoring…' : 'Restore workspace' }}
            </button>
          </div>
        } @else {
          <button
            type="button"
            (click)="deleteOpen.set(true)"
            [disabled]="deleting()"
            class="inline-flex items-center gap-1.5 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded text-sm font-medium transition disabled:opacity-40"
          >
            <app-icon name="trash-2" [size]="14" />
            Delete workspace permanently
          </button>
        }
      </section>
    </div>

    <app-confirm-dialog
      [open]="leaveOpen()"
      title="Leave this workspace?"
      description="You will lose access to its data."
      confirmLabel="Leave"
      tone="danger"
      icon="log-out"
      (cancel)="leaveOpen.set(false)"
      (confirm)="leave()"
    />

    <app-confirm-dialog
      [open]="deleteOpen()"
      title="Delete this workspace?"
      description="This archives the workspace for 30 days before permanent deletion. Type the workspace name to confirm."
      confirmLabel="Delete workspace"
      [confirmPhrase]="detail()?.name || ''"
      tone="danger"
      icon="trash-2"
      (cancel)="deleteOpen.set(false)"
      (confirm)="remove()"
    />
  `,
})
export class WorkspaceDangerComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly leaving = signal(false);
  readonly deleting = signal(false);
  readonly restoring = signal(false);
  readonly leaveOpen = signal(false);
  readonly deleteOpen = signal(false);

  readonly isOwner = computed(() => this.detail()?.role === 'owner');

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
    this.leaveOpen.set(false);
    this.leaving.set(true);
    this.workspaceService.leaveWorkspace(slug).subscribe({
      next: () => {
        this.leaving.set(false);
        this.toastr.success('You left the workspace', 'Left');
        this.router.navigate(['/workspace']);
      },
      error: (err) => {
        this.leaving.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to leave', 'Error');
      },
    });
  }

  remove(): void {
    const slug = this.routeSlug();
    const d = this.detail();
    if (!slug || !d) return;
    this.deleteOpen.set(false);
    this.deleting.set(true);
    this.workspaceService.deleteWorkspace(slug, d.name).subscribe({
      next: () => {
        this.deleting.set(false);
        this.toastr.success(`"${d.name}" archived`, 'Deleted');
        this.router.navigate(['/workspace']);
      },
      error: (err) => {
        this.deleting.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to delete', 'Error');
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
        this.toastr.success('Workspace restored', 'Restored');
      },
      error: (err) => {
        this.restoring.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to restore', 'Error');
      },
    });
  }
}
