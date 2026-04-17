import { Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { WorkspaceDetail, WorkspaceService } from '@app/core/workspace.service';

@Component({
  selector: 'app-workspace-general',
  standalone: true,
  imports: [FormsModule, DatePipe],
  template: `
    <div class="space-y-6">
      <!-- Identity -->
      <section class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-1">Identity</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
          The display name appears in the sidebar switcher and reports. The slug is a stable
          identifier used in URLs and API headers.
        </p>

        @if (detail(); as d) {
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Workspace name
              </label>
              <div class="flex gap-2">
                <input
                  [(ngModel)]="name"
                  name="name"
                  type="text"
                  class="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-brand-500"
                  [disabled]="!canEdit()"
                />
                <button
                  type="button"
                  (click)="saveName()"
                  [disabled]="!dirty() || saving() || !canEdit()"
                  class="px-4 py-2 bg-brand-500 hover:bg-brand-600 disabled:bg-gray-400 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition"
                >
                  {{ saving() ? 'Saving…' : 'Save' }}
                </button>
              </div>
              @if (!canEdit()) {
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Only owners and admins can rename the workspace.
                </p>
              }
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Slug
              </label>
              <div class="flex gap-2">
                <input
                  [value]="d.slug"
                  readonly
                  class="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-gray-50 dark:bg-gray-950 text-gray-700 dark:text-gray-300 font-mono text-sm"
                />
                <button
                  type="button"
                  (click)="copy(d.slug)"
                  class="px-3 py-2 bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg text-sm"
                >
                  {{ copied() ? 'Copied!' : 'Copy' }}
                </button>
              </div>
              <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Slugs cannot be changed once created.
              </p>
            </div>
          </div>
        } @else {
          <div class="text-sm text-gray-500">Loading…</div>
        }
      </section>

      <!-- Metadata -->
      @if (detail(); as d) {
        <section class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Metadata</h2>
          <dl class="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt class="text-gray-500 dark:text-gray-400 mb-1">Your role</dt>
              <dd class="text-gray-900 dark:text-white capitalize font-medium">{{ d.role }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400 mb-1">Members</dt>
              <dd class="text-gray-900 dark:text-white font-medium">{{ d.member_count }}</dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400 mb-1">Created</dt>
              <dd class="text-gray-900 dark:text-white">
                {{ d.created_at | date:'mediumDate' }}
              </dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400 mb-1">Status</dt>
              <dd>
                @if (d.is_active) {
                  <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                    <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                    Active
                  </span>
                } @else {
                  <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                    Archived
                  </span>
                }
              </dd>
            </div>
          </dl>
        </section>
      }

      @if (message(); as m) {
        <div
          class="px-4 py-3 rounded-lg text-sm"
          [class.bg-green-50]="!m.error"
          [class.dark:bg-green-900]="!m.error"
          [class.text-green-800]="!m.error"
          [class.dark:text-green-300]="!m.error"
          [class.bg-red-50]="m.error"
          [class.dark:bg-red-900]="m.error"
          [class.text-red-800]="m.error"
          [class.dark:text-red-300]="m.error"
        >
          {{ m.text }}
        </div>
      }
    </div>
  `,
})
export class WorkspaceGeneralComponent {
  protected readonly workspaceService = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null }
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly saving = signal(false);
  readonly copied = signal(false);
  readonly message = signal<{ text: string; error: boolean } | null>(null);

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
      error: (err) => {
        this.message.set({
          text: err?.error?.detail || 'Failed to load workspace',
          error: true,
        });
      },
    });
  }

  saveName(): void {
    const d = this.detail();
    if (!d) return;
    const trimmed = this.name.trim();
    if (!trimmed) return;
    this.saving.set(true);
    this.message.set(null);
    this.workspaceService.renameWorkspace(d.slug, trimmed).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.detail.set(updated);
        this.name = updated.name;
        this.message.set({ text: 'Workspace renamed', error: false });
        setTimeout(() => this.message.set(null), 3000);
      },
      error: (err) => {
        this.saving.set(false);
        this.message.set({
          text: err?.error?.detail || 'Failed to rename workspace',
          error: true,
        });
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
