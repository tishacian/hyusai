import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import {
  CanonicalApiService,
  type CanonicalAnswerRow,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
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
      [breadcrumb]="i18n.t('governance.breadcrumb')"
      [title]="i18n.t('governance.canonical.title')"
      icon="shield-check"
      [subtitle]="i18n.t('governance.canonical.subtitle')"
    >
      <button
        type="button"
        (click)="reload()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('common.refresh') }}
      </button>
    </app-section-header>

    <section class="ck-surface rounded-md overflow-hidden">
      @if (loading()) {
        <div class="p-6 text-sm text-gray-400">{{ i18n.t('governance.canonical.loading') }}</div>
      } @else if (!items().length) {
        <app-empty-state
          icon="shield-check"
          [title]="i18n.t('governance.canonical.empty.title')"
          [description]="i18n.t('governance.canonical.empty.description')"
        />
      } @else {
        <ul class="divide-y divide-white/5">
          @for (item of items(); track item.id) {
            <li class="p-5 flex gap-4 items-start">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap mb-2">
                  <span class="text-[10px] uppercase tracking-wider font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/30">
                    {{ item.hit_count === 1 ? i18n.t('governance.canonical.hits.one') : i18n.t('governance.canonical.hits.many', { count: item.hit_count }) }}
                  </span>
                  <span class="text-[11px] text-gray-500 font-mono">
                    {{ i18n.t('governance.canonical.threshold', { value: item.similarity_threshold }) }}
                  </span>
                  @if (item.updated_at) {
                    <span class="text-[11px] text-gray-500">
                      {{ i18n.t('governance.canonical.updated') }} {{ item.updated_at | date: 'MMM d, HH:mm' }}
                    </span>
                  }
                </div>
                <div class="text-sm font-semibold text-white mb-1">{{ item.question }}</div>
                <p class="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{{ item.answer }}</p>
                <div class="text-[11px] text-gray-500 font-mono mt-3 flex flex-wrap gap-3">
                  @if (item.source_run_id) {
                    <span>{{ i18n.t('governance.canonical.source.run', { id: short(item.source_run_id) }) }}</span>
                  }
                  @if (item.source_decision_id) {
                    <span>{{ i18n.t('governance.canonical.source.decision', { id: short(item.source_decision_id) }) }}</span>
                  }
                  @if (item.source_feedback_id) {
                    <span>{{ i18n.t('governance.canonical.source.feedback', { id: short(item.source_feedback_id) }) }}</span>
                  }
                  <span>{{ i18n.t('governance.canonical.by', { name: item.created_by || i18n.t('governance.canonical.system') }) }}</span>
                </div>
              </div>
              <button
                type="button"
                (click)="delete(item)"
                [disabled]="deletingId() === item.id"
                class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium bg-white/5 hover:bg-red-500/15 ring-1 ring-white/10 hover:ring-red-500/40 text-gray-300 hover:text-red-200 transition disabled:opacity-50"
              >
                <app-icon name="trash-2" [size]="12" />
                {{ deletingId() === item.id ? i18n.t('governance.canonical.deleting') : i18n.t('common.delete') }}
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
  readonly i18n = inject(I18nService);

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
    if (!confirm(this.i18n.t('governance.canonical.confirm_delete', { question: item.question }))) return;
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
