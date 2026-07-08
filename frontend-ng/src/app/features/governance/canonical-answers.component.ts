import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import {
  CanonicalApiService,
  type CanonicalAnswerRow,
} from '@app/core/canonical-api.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

@Component({
  selector: 'app-canonical-answers',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, EmptyStateComponent, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Govern"
      title="Canonical answers"
      icon="shield-check"
      subtitle="Deterministic answers promoted from evaluation feedback. These bypass the LLM when the same question is asked again."
    >
      <button
        type="button"
        (click)="reload()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
      </button>
    </app-section-header>

    <section class="ck-surface rounded-md overflow-hidden">
      @if (loading()) {
        <div class="p-6 text-sm text-gray-400">Loading canonical answers…</div>
      } @else if (!items().length) {
        <app-empty-state
          icon="shield-check"
          title="No canonical answer yet"
          description="Corrected evaluation feedback can be promoted into deterministic answers."
        />
      } @else {
        <ul class="divide-y divide-white/5">
          @for (item of items(); track item.id) {
            <li class="p-5 flex gap-4 items-start">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap mb-2">
                  <span class="text-[10px] uppercase tracking-wider font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/30">
                    {{ item.hit_count }} hit{{ item.hit_count === 1 ? '' : 's' }}
                  </span>
                  <span class="text-[11px] text-gray-500 font-mono">
                    threshold {{ item.similarity_threshold }}
                  </span>
                  @if (item.updated_at) {
                    <span class="text-[11px] text-gray-500">
                      Updated {{ item.updated_at | date: 'MMM d, HH:mm' }}
                    </span>
                  }
                </div>
                <div class="text-sm font-semibold text-white mb-1">{{ item.question }}</div>
                <p class="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{{ item.answer }}</p>
                <div class="text-[11px] text-gray-500 font-mono mt-3 flex flex-wrap gap-3">
                  @if (item.source_run_id) {
                    <span>run {{ short(item.source_run_id) }}</span>
                  }
                  @if (item.source_decision_id) {
                    <span>decision {{ short(item.source_decision_id) }}</span>
                  }
                  @if (item.source_feedback_id) {
                    <span>feedback {{ short(item.source_feedback_id) }}</span>
                  }
                  <span>by {{ item.created_by || 'system' }}</span>
                </div>
              </div>
              <button
                type="button"
                (click)="delete(item)"
                [disabled]="deletingId() === item.id"
                class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium bg-white/5 hover:bg-red-500/15 ring-1 ring-white/10 hover:ring-red-500/40 text-gray-300 hover:text-red-200 transition disabled:opacity-50"
              >
                <app-icon name="trash-2" [size]="12" />
                {{ deletingId() === item.id ? 'Deleting…' : 'Delete' }}
              </button>
            </li>
          }
        </ul>
      }
    </section>
  `,
})
export class CanonicalAnswersComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);

  readonly loading = signal(false);
  readonly items = signal<CanonicalAnswerRow[]>([]);
  readonly deletingId = signal<string | null>(null);
  readonly total = computed(() => this.items().length);

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.canonical.listCanonicalAnswers({ limit: 200 }).subscribe({
      next: (res) => {
        this.items.set(res?.items ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.items.set([]);
        this.loading.set(false);
      },
    });
  }

  delete(item: CanonicalAnswerRow): void {
    if (!confirm(`Delete canonical answer for: ${item.question}?`)) return;
    this.deletingId.set(item.id);
    this.canonical.deleteCanonicalAnswer(item.id).subscribe({
      next: () => {
        this.deletingId.set(null);
        this.items.update((rows) => rows.filter((row) => row.id !== item.id));
      },
      error: () => this.deletingId.set(null),
    });
  }

  short(id: string): string {
    return id.slice(0, 8);
  }
}
