import { ChangeDetectionStrategy, Component, type OnInit, computed, inject, input, signal } from '@angular/core';
import type { Observable } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import type { ExperienceNode, RuntimeNodeContext } from '../model';
import { deadlineState, matrixOf, type ReviewSetView } from './review-model';
import { ReviewSetsApi, reviewErrorCode } from './review-sets.api';

type Phase = 'loading' | 'loaded' | 'error';

/**
 * Certified `review_matrix`: review sets of a namespace on two axes taken from
 * their group labels, with progress and deadline, and the administrator
 * actions every cell offers (move the deadline, close, export).
 */
@Component({
  selector: 'xp-rt-review-matrix',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  styleUrls: ['../runtime.scss', './review.scss'],
  template: `
    <section class="xp-rt-block xp-rv" [attr.aria-label]="title() || i18n.t('experience.review.matrix.title')">
      <h3>{{ title() || i18n.t('experience.review.matrix.title') }}</h3>
      <p class="xp-rv-live" aria-live="polite">{{ notice() }}</p>
      @switch (phase()) {
        @case ('loading') {
          <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('experience.review.sets.loading')" />
        }
        @case ('error') {
          <app-empty-state icon="alert-triangle" size="sm" [title]="i18n.t('experience.review.sets.error')" />
          <button type="button" class="xp-rt-btn" (click)="load()">{{ i18n.t('experience.review.retry') }}</button>
        }
        @default {
          @if (!sets().length) {
            <app-empty-state icon="inbox" size="sm" [title]="i18n.t('experience.review.sets.empty_title')" [description]="i18n.t('experience.review.sets.empty_body')" />
          } @else {
            <div class="xp-rt-table-scroll" role="region" tabindex="0" [attr.aria-label]="title() || i18n.t('experience.review.matrix.title')">
              <table class="xp-rt-table">
                <thead>
                  <tr>
                    <th scope="col">{{ rowLabel() }}</th>
                    @for (column of matrix().columns; track column) {
                      <th scope="col">{{ column || '—' }}</th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (row of matrix().rows; track row) {
                    <tr>
                      <th scope="row">{{ row }}</th>
                      @for (column of matrix().columns; track column) {
                        <td>
                          @for (s of matrix().cell(row, column); track s.id) {
                            <div class="xp-rv-cell">
                              <p>{{ i18n.t('experience.review.matrix.cell', { progress: percent(s) }) }}
                                @if (s.status === 'closed') { · {{ i18n.t('experience.review.set.closed') }} }
                              </p>
                              @if (deadline(s) !== 'none') {
                                <p [class]="'xp-rv-due-' + deadline(s)">{{ i18n.t('experience.review.deadline.' + deadline(s)) }}</p>
                              }
                              <div class="xp-rt-actions">
                                @if (s.status === 'open') {
                                  <button type="button" class="xp-rt-btn xp-rt-btn-ghost" [disabled]="busy()" (click)="extend(s)">
                                    {{ i18n.t('experience.review.matrix.extend', { days: extendDays() }) }}
                                  </button>
                                  <button type="button" class="xp-rt-btn xp-rt-btn-ghost" [disabled]="busy()" (click)="close(s)">
                                    {{ i18n.t('experience.review.matrix.close') }}
                                  </button>
                                }
                                <button type="button" class="xp-rt-btn xp-rt-btn-ghost" [disabled]="busy()" (click)="exportCsv(s)">
                                  {{ i18n.t('experience.review.matrix.export') }}
                                </button>
                              </div>
                            </div>
                          } @empty {
                            <span class="xp-rt-sub">—</span>
                          }
                        </td>
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        }
      }
    </section>
  `,
})
export class ReviewMatrixBlock implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ReviewSetsApi);
  private readonly workspace = inject(WorkspaceService);

  readonly node = input.required<ExperienceNode>();
  readonly context = input<RuntimeNodeContext | null>(null);

  readonly phase = signal<Phase>('loading');
  readonly sets = signal<ReviewSetView[]>([]);
  readonly busy = signal(false);
  readonly notice = signal('');

  readonly title = computed(() => this.prop('title'));
  readonly rowLabel = computed(() => this.prop('rowLabel') || 'group');
  readonly columnLabel = computed(() => this.prop('columnLabel'));
  readonly extendDays = computed(() => {
    const value = this.node().props?.['extendDays'];
    return typeof value === 'number' && value > 0 && value <= 60 ? Math.round(value) : 3;
  });
  readonly matrix = computed(() => matrixOf(this.sets(), this.rowLabel(), this.columnLabel()));

  ngOnInit(): void {
    this.load();
  }

  private prop(key: string): string {
    const value = this.node().props?.[key];
    return typeof value === 'string' ? value : '';
  }

  load(): void {
    const scope = this.workspace.captureRequestScope();
    this.phase.set('loading');
    this.api.sets(scope, this.prop('namespace') || undefined).subscribe({
      next: (rows) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.sets.set(rows);
        this.phase.set('loaded');
      },
      error: () => {
        if (this.workspace.isRequestScopeCurrent(scope)) this.phase.set('error');
      },
    });
  }

  percent(s: ReviewSetView): number {
    return s.item_count ? Math.round((s.decided_count / s.item_count) * 100) : 0;
  }

  deadline(s: ReviewSetView): 'overdue' | 'soon' | 'none' {
    return deadlineState(s.deadline_at);
  }

  private act(work: () => Observable<unknown>, done: string): void {
    const scope = this.workspace.captureRequestScope();
    this.busy.set(true);
    work().subscribe({
      next: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.busy.set(false);
        this.notice.set(done);
        this.load();
      },
      error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.busy.set(false);
        const code = reviewErrorCode(err);
        this.notice.set(this.i18n.t(
          (err as { status?: number })?.status === 403 || code === 'WORKSPACE_PERMISSION_DENIED'
            ? 'experience.review.matrix.forbidden'
            : 'experience.review.matrix.action_error',
        ));
      },
    });
  }

  extend(s: ReviewSetView): void {
    const scope = this.workspace.captureRequestScope();
    const base = s.deadline_at ? Date.parse(s.deadline_at.endsWith('Z') ? s.deadline_at : `${s.deadline_at}Z`) : Date.now();
    const next = new Date(Math.max(base, Date.now()) + this.extendDays() * 86_400_000).toISOString();
    this.act(() => this.api.moveDeadline(scope, s.id, next), this.i18n.t('experience.review.matrix.extended'));
  }

  close(s: ReviewSetView): void {
    const scope = this.workspace.captureRequestScope();
    this.act(() => this.api.close(scope, s.id), this.i18n.t('experience.review.matrix.closed'));
  }

  exportCsv(s: ReviewSetView): void {
    const scope = this.workspace.captureRequestScope();
    this.busy.set(true);
    this.api.exportCsv(scope, s.id).subscribe({
      next: (blob) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.busy.set(false);
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${s.group_key.replace(/[^A-Za-z0-9_.-]+/g, '-')}.csv`;
        link.click();
        URL.revokeObjectURL(url);
        this.notice.set(this.i18n.t('experience.review.matrix.exported'));
      },
      error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.busy.set(false);
        this.notice.set(this.i18n.t(
          (err as { status?: number })?.status === 403 ? 'experience.review.matrix.forbidden' : 'experience.review.matrix.action_error',
        ));
      },
    });
  }
}
