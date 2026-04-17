import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { WorkspaceDetail, WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';

const FIELD =
  'flex-1 px-3 py-2 rounded bg-black/20 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/60 transition';

@Component({
  selector: 'app-workspace-general',
  standalone: true,
  imports: [FormsModule, DatePipe, IconComponent, StatusPulseComponent, SkeletonComponent],
  template: `
    <div class="space-y-6">
      <section class="t-card t-elevated rounded-md p-6">
        <div class="flex items-start gap-3 mb-5">
          <div class="w-10 h-10 rounded-md flex items-center justify-center bg-brand-500/10 text-brand-400 ring-1 ring-brand-500/30">
            <app-icon name="settings" [size]="18" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-white">Identity</h2>
            <p class="text-sm text-gray-400 mt-0.5 max-w-xl">
              The display name appears everywhere; the slug is a stable identifier used in URLs and API headers.
            </p>
          </div>
        </div>

        @if (detail(); as d) {
          <div class="space-y-4">
            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">
                Workspace name
              </label>
              <div class="flex gap-2">
                <input
                  [(ngModel)]="name"
                  name="name"
                  type="text"
                  [class]="field"
                  [disabled]="!canEdit()"
                />
                <button
                  type="button"
                  (click)="saveName()"
                  [disabled]="!dirty() || saving() || !canEdit()"
                  class="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-sm font-medium transition shadow-glow-sm inline-flex items-center gap-1.5"
                >
                  <app-icon name="save" [size]="14" />
                  {{ saving() ? 'Saving…' : 'Save' }}
                </button>
              </div>
              @if (!canEdit()) {
                <p class="text-xs text-gray-500 mt-1">Only owners and admins can rename the workspace.</p>
              }
            </div>

            <div>
              <label class="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wider">Slug</label>
              <div class="flex gap-2">
                <input
                  [value]="d.slug"
                  readonly
                  class="flex-1 px-3 py-2 rounded bg-black/40 border border-white/5 text-gray-300 font-mono text-sm"
                />
                <button
                  type="button"
                  (click)="copy(d.slug)"
                  class="px-3 py-2 bg-white/5 hover:bg-white/10 text-gray-200 rounded text-sm inline-flex items-center gap-1.5 transition"
                >
                  <app-icon [name]="copied() ? 'check' : 'copy'" [size]="14" />
                  {{ copied() ? 'Copied' : 'Copy' }}
                </button>
              </div>
              <p class="text-xs text-gray-500 mt-1">Slugs cannot be changed once created.</p>
            </div>
          </div>
        } @else {
          <div class="space-y-3">
            <app-skeleton height="40px" />
            <app-skeleton height="40px" />
          </div>
        }
      </section>

      @if (detail(); as d) {
        <section class="t-card t-elevated rounded-md p-6">
          <h2 class="text-base font-semibold text-white mb-4 flex items-center gap-2">
            <app-icon name="info" [size]="16" class="text-brand-400" />
            Metadata
          </h2>
          <dl class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Your role</dt>
              <dd class="text-white capitalize font-medium">{{ d.role }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Members</dt>
              <dd class="text-white font-medium">{{ d.member_count }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Created</dt>
              <dd class="text-white">{{ d.created_at | date: 'mediumDate' }}</dd>
            </div>
            <div>
              <dt class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Status</dt>
              <dd>
                @if (d.is_active) {
                  <app-status-pulse tone="success" label="Active" />
                } @else {
                  <span class="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    <app-icon name="archive" [size]="11" />
                    Archived
                  </span>
                }
              </dd>
            </div>
          </dl>
        </section>
      }
    </div>
  `,
})
export class WorkspaceGeneralComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);

  protected readonly field = FIELD;

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly saving = signal(false);
  readonly copied = signal(false);

  name = '';

  readonly canEdit = computed(() => {
    const role = this.detail()?.role;
    return role === 'owner' || role === 'admin';
  });

  readonly dirty = computed(() => {
    const d = this.detail();
    if (!d) return false;
    return this.name.trim() !== d.name && this.name.trim().length > 0;
  });

  constructor() {
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load(slug);
    });
  }

  load(slug: string): void {
    this.workspaceService.getWorkspace(slug).subscribe({
      next: (d) => {
        this.detail.set(d);
        this.name = d.name;
      },
      error: (err) => this.toastr.error(err?.error?.detail || 'Failed to load workspace', 'Error'),
    });
  }

  saveName(): void {
    const d = this.detail();
    if (!d) return;
    const trimmed = this.name.trim();
    if (!trimmed) return;
    this.saving.set(true);
    this.workspaceService.renameWorkspace(d.slug, trimmed).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.detail.set(updated);
        this.name = updated.name;
        this.toastr.success(`Workspace renamed to "${updated.name}"`, 'Saved');
      },
      error: (err) => {
        this.saving.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to rename workspace', 'Error');
      },
    });
  }

  copy(slug: string): void {
    navigator.clipboard?.writeText(slug).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }
}
