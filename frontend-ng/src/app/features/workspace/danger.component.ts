import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceDetail, WorkspaceService } from '@app/core/workspace.service';
import { navigationLeafUrl } from '@app/core/navigation.catalog';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { NavLinkDirective } from '@app/shared/cockpit';

@Component({
  selector: 'app-workspace-danger',
  standalone: true,
  imports: [IconComponent, ConfirmDialogComponent, NavLinkDirective],
  template: `
    <div class="space-y-6">
      <section class="ck-surface rounded-md p-6">
        <div class="flex items-start gap-3 mb-4">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/30">
            <app-icon name="log-out" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-white">{{ i18n.t('workspace.danger.leave.title') }}</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              {{ i18n.t('workspace.danger.leave.description') }}
            </p>
            @if (isOwner()) {
              <p class="text-xs text-amber-400 mt-1.5">
                {{ i18n.t('workspace.danger.leave.owner_hint') }}
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
          {{ leaving() ? i18n.t('workspace.danger.leave.leaving') : i18n.t('workspace.danger.leave.title') }}
        </button>
      </section>

      <section class="ck-surface rounded-md p-6 border-red-500/30">
        <div class="flex items-start gap-3 mb-4">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-red-500/10 text-red-400 ring-1 ring-red-500/30">
            <app-icon name="shield-alert" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-red-400">{{ i18n.t('workspace.danger.delete.title') }}</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              {{ i18n.t('workspace.danger.delete.description_before') }}
              <strong class="text-white">{{ i18n.t('workspace.danger.delete.description_days') }}</strong>{{ i18n.t('workspace.danger.delete.description_after') }}
            </p>
            <p>{{ i18n.t('governance.workspace.archive_scope') }}</p>
            @if (restoreDeadline()) { <p>{{ i18n.t('governance.workspace.restore_until', { date: restoreDeadline() }) }}</p> }
          </div>
        </div>

        @if (!isOwner()) {
          <p class="text-sm text-gray-500 italic">{{ i18n.t('workspace.danger.owner_only') }}</p>
        } @else if (detail()?.deleted_at) {
          <div class="flex items-center gap-3 flex-wrap">
            <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30 text-xs font-medium">
              <app-icon name="archive" [size]="11" /> {{ i18n.t('workspace.status.archived') }}
            </span>
            <button
              type="button"
              (click)="restore()"
              [disabled]="restoring()"
              class="inline-flex items-center gap-1.5 px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-white rounded text-sm font-medium transition disabled:opacity-40"
            >
              <app-icon name="archive-restore" [size]="14" />
              {{ restoring() ? i18n.t('workspace.danger.restore.restoring') : i18n.t('workspace.danger.restore.cta') }}
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
            {{ i18n.t('workspace.danger.delete.cta') }}
          </button>
        }
      </section>
      @if (connections() !== null) {
        <section class="ck-surface rounded-md p-6" data-testid="workspace-reconnections">
          <h3>{{ i18n.t('governance.workspace.connections') }}</h3>
          <p>{{ i18n.t('governance.workspace.reconnect_hint') }}</p>
          <ul>@for (connection of connections(); track connection.id) { <li>{{ connection.name }} · {{ i18n.t(connection.status === 'verified' ? 'governance.workspace.verified' : 'governance.workspace.reconnect') }}</li> }</ul>
          <a [navLink]="{leaf:'connector-connections'}">{{ i18n.t('governance.workspace.open_connections') }}</a>
          <button type="button" (click)="checkConnections()">{{ i18n.t('common.refresh') }}</button>
        </section>
      }
    </div>

    <app-confirm-dialog
      [open]="leaveOpen()"
      [title]="i18n.t('workspace.danger.leave.confirm_title')"
      [description]="i18n.t('workspace.danger.leave.confirm_description')"
      [confirmLabel]="i18n.t('workspace.danger.leave.confirm_cta')"
      tone="danger"
      icon="log-out"
      (cancel)="leaveOpen.set(false)"
      (confirm)="leave()"
    />

    <app-confirm-dialog
      [open]="deleteOpen()"
      [title]="i18n.t('workspace.danger.delete.confirm_title')"
      [description]="i18n.t('workspace.danger.delete.confirm_description') + ' ' + i18n.t('governance.workspace.archive_scope')"
      [confirmLabel]="i18n.t('workspace.danger.delete.confirm_cta')"
      [confirmPhrase]="detail()?.name || ''"
      tone="danger"
      icon="trash-2"
      (cancel)="deleteOpen.set(false)"
      (confirm)="remove()"
    />
  `,
})
export class WorkspaceDangerComponent {
  readonly i18n = inject(I18nService);
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toastr = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);

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
  readonly connections = signal<Array<{id:string;name:string;status:string}> | null>(null);
  readonly restoreDeadline = computed(() => {
    const deleted = this.detail()?.deleted_at;
    return deleted ? new Date(new Date(deleted).getTime() + 30 * 86400000).toLocaleString(this.i18n.locale()) : '';
  });

  readonly isOwner = computed(() => this.detail()?.role === 'owner');

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      this.detail.set(null); this.connections.set(null);
      this.leaveOpen.set(false); this.deleteOpen.set(false);
      this.leaving.set(false); this.deleting.set(false); this.restoring.set(false);
      if (slug) this.load(slug);
    });
  }

  load(slug: string): void {
    this.workspaceService.getWorkspace(slug).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (d) => { if (this.routeSlug() === slug) this.detail.set(d); },
      error: () => { if (this.routeSlug() === slug) this.detail.set(null); },
    });
  }

  leave(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    this.leaveOpen.set(false);
    this.leaving.set(true);
    this.workspaceService.leaveWorkspace(slug).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        if (this.routeSlug() !== slug) return;
        this.leaving.set(false);
        this.toastr.success(
          this.i18n.t('workspace.danger.toast.left'),
          this.i18n.t('workspace.danger.toast.left_title'),
        );
        void this.router.navigateByUrl(navigationLeafUrl('workspace-list'));
      },
      error: (err) => {
        if (this.routeSlug() !== slug) return;
        this.leaving.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.danger.toast.leave_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
    });
  }

  remove(): void {
    const slug = this.routeSlug();
    const d = this.detail();
    if (!slug || !d) return;
    this.deleteOpen.set(false);
    this.deleting.set(true);
    this.workspaceService.deleteWorkspace(slug, d.name).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        if (this.routeSlug() !== slug) return;
        this.deleting.set(false);
        this.toastr.success(
          this.i18n.t('workspace.danger.toast.deleted', { name: d.name }),
          this.i18n.t('workspace.danger.toast.deleted_title'),
        );
        void this.router.navigateByUrl(navigationLeafUrl('workspace-list'));
      },
      error: (err) => {
        if (this.routeSlug() !== slug) return;
        this.deleting.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.danger.toast.delete_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
    });
  }

  restore(): void {
    const slug = this.routeSlug();
    if (!slug) return;
    this.restoring.set(true);
    this.workspaceService.restoreWorkspace(slug).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (result) => {
        if (this.routeSlug() !== slug) return;
        this.restoring.set(false);
        this.connections.set(result.connections ?? []);
        this.load(slug);
        this.workspaceService.loadWorkspaces().subscribe();
        this.toastr.success(
          this.i18n.t('workspace.danger.toast.restored'),
          this.i18n.t('workspace.danger.toast.restored_title'),
        );
      },
      error: (err) => {
        if (this.routeSlug() !== slug) return;
        this.restoring.set(false);
        this.toastr.error(
          err?.error?.detail || this.i18n.t('workspace.danger.toast.restore_failed'),
          this.i18n.t('workspace.toast.error_title'),
        );
      },
    });
  }

  checkConnections(): void {
    const slug = this.routeSlug(); if (!slug) return;
    this.workspaceService.workspaceReconnectStatus(slug).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({ next: result => { if (this.routeSlug() === slug) this.connections.set(result.connections); }, error: () => { if (this.routeSlug() === slug) this.toastr.error(this.i18n.t('governance.workspace.check_failed')); } });
  }
}
