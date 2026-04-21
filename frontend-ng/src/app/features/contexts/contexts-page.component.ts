/**
 * Contexts management page (Steering > Contexts).
 *
 * Minimal CRUD over the canonical `/contexts` endpoint: lists every
 * workspace context, lets the operator rename, add/remove refs, and delete.
 * Lives under `/steering/contexts` because Contexts are a steering lever of
 * the mental model — they decide *what state* a Run sees before the skills
 * fire. Kept intentionally thin: the builder is where fresh Contexts are
 * usually forged.
 */
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { CanonicalApiService, type Context } from '@app/core/canonical-api.service';

@Component({
  selector: 'app-contexts-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, IconComponent, SectionHeaderComponent, EmptyStateComponent],
  template: `
    <app-section-header
      breadcrumb="Steering"
      title="Contexts"
      icon="database"
      subtitle="Versioned bags of state attached to Systems. Each Run references a Context snapshot."
    >
      <a
        routerLink="/systems/new"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
      >
        <app-icon name="plus" [size]="14" /> New context (via Builder)
      </a>
    </app-section-header>

    @if (loading() && contexts().length === 0) {
      <div class="space-y-2">
        @for (_ of [0, 1, 2]; track $index) {
          <div class="t-card rounded-md p-5 animate-pulse">
            <div class="h-3 w-60 bg-white/5 rounded"></div>
          </div>
        }
      </div>
    } @else if (contexts().length === 0) {
      <app-empty-state
        icon="database"
        title="No contexts yet"
        description="Contexts are created from the System Builder (Context step). Open the builder to create one."
      >
        <a
          routerLink="/systems/new"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
        >
          <app-icon name="plus" [size]="14" /> Open System Builder
        </a>
      </app-empty-state>
    } @else {
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <!-- List column -->
        <aside class="lg:col-span-1 space-y-2">
          @for (c of contexts(); track c.id) {
            <button
              type="button"
              (click)="select(c)"
              class="w-full text-left t-card rounded-md px-4 py-3 transition"
              [class.ring-brand-500]="selectedId() === c.id"
              [class.ring-1]="selectedId() === c.id"
            >
              <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-medium text-white truncate">{{ c.name }}</span>
                <span class="ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-gray-400 ring-1 ring-white/10">
                  v{{ c.version ?? 1 }}
                </span>
              </div>
              <div class="text-[11px] text-gray-500 font-mono">
                {{ (c.data_refs?.length ?? 0) }} data · {{ (c.memory_refs?.length ?? 0) }} mem
              </div>
            </button>
          }
        </aside>

        <!-- Detail column -->
        <section class="lg:col-span-2">
          @if (!selected()) {
            <div class="t-card rounded-md p-8 text-center text-gray-400 text-sm">
              Select a context on the left to inspect / edit.
            </div>
          } @else {
            <div class="t-card t-elevated rounded-md p-5 space-y-4">
              <div class="flex items-center gap-2">
                <app-icon name="database" [size]="14" class="text-brand-400" />
                <input
                  class="flex-1 bg-transparent border-b border-white/10 focus:border-brand-400 text-sm font-medium text-white focus:outline-none px-1 py-0.5"
                  [(ngModel)]="draftName"
                />
                <span class="text-[10px] font-mono text-gray-500">id · {{ selected()!.id }}</span>
              </div>

              <div>
                <div class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">Data refs</div>
                <div class="space-y-1.5">
                  @for (ref of draftDataRefs(); track $index; let i = $index) {
                    <div class="flex items-center gap-2">
                      <input
                        class="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-brand-400"
                        [ngModel]="ref"
                        (ngModelChange)="setDataRef(i, $event)"
                      />
                      <button
                        type="button"
                        class="text-gray-500 hover:text-red-400 transition"
                        title="Remove"
                        (click)="removeDataRef(i)"
                      >
                        <app-icon name="x" [size]="14" />
                      </button>
                    </div>
                  }
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200"
                    (click)="addDataRef()"
                  >
                    <app-icon name="plus" [size]="12" /> Add ref
                  </button>
                </div>
              </div>

              <div class="flex items-center gap-2 pt-2 border-t border-white/5">
                <button
                  type="button"
                  [disabled]="saving()"
                  class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white transition"
                  (click)="save()"
                >
                  <app-icon [name]="saving() ? 'loader-2' : 'save'" [size]="12" [class.animate-spin]="saving()" />
                  {{ saving() ? 'Saving…' : 'Save changes' }}
                </button>
                <button
                  type="button"
                  [disabled]="saving()"
                  class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium bg-red-500/10 hover:bg-red-500/20 ring-1 ring-red-500/30 text-red-300 transition"
                  (click)="remove()"
                >
                  <app-icon name="trash-2" [size]="12" /> Delete
                </button>
              </div>
            </div>
          }
        </section>
      </div>
    }
  `,
})
export class ContextsPageComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);

  readonly contexts = signal<Context[]>([]);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed(() => this.contexts().find((c) => c.id === this.selectedId()) ?? null);

  draftName = '';
  private readonly draftRefs = signal<string[]>([]);
  readonly draftDataRefs = computed(() => this.draftRefs());

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.canonical.listContexts().subscribe({
      next: (list) => {
        this.contexts.set(list ?? []);
        this.loading.set(false);
        if (!this.selectedId() && list.length) this.select(list[0]);
      },
      error: () => {
        this.contexts.set([]);
        this.loading.set(false);
      },
    });
  }

  select(c: Context): void {
    this.selectedId.set(c.id);
    this.draftName = c.name ?? '';
    this.draftRefs.set([...(c.data_refs ?? [])]);
  }

  setDataRef(i: number, value: string): void {
    const refs = [...this.draftRefs()];
    refs[i] = value;
    this.draftRefs.set(refs);
  }

  addDataRef(): void {
    this.draftRefs.set([...this.draftRefs(), '']);
  }

  removeDataRef(i: number): void {
    const refs = [...this.draftRefs()];
    refs.splice(i, 1);
    this.draftRefs.set(refs);
  }

  save(): void {
    const ctx = this.selected();
    if (!ctx) return;
    this.saving.set(true);
    this.canonical
      .updateContext(ctx.id, {
        name: this.draftName.trim() || ctx.name,
        data_refs: this.draftRefs().filter((r) => r.trim()),
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          if (updated) {
            this.toast.success(`${updated.name} · v${updated.version}`, 'Context updated');
            this.refresh();
          } else {
            this.toast.error('Update failed', 'Context');
          }
        },
        error: () => {
          this.saving.set(false);
          this.toast.error('Update failed', 'Context');
        },
      });
  }

  remove(): void {
    const ctx = this.selected();
    if (!ctx) return;
    if (!confirm(`Delete context "${ctx.name}"? Systems referencing it will lose the pin.`)) return;
    this.saving.set(true);
    this.canonical.deleteContext(ctx.id).subscribe({
      next: (ok) => {
        this.saving.set(false);
        if (ok) {
          this.toast.success(`${ctx.name} deleted`, 'Context');
          this.selectedId.set(null);
          this.refresh();
        } else {
          this.toast.error('Delete failed', 'Context');
        }
      },
      error: () => {
        this.saving.set(false);
        this.toast.error('Delete failed', 'Context');
      },
    });
  }
}
