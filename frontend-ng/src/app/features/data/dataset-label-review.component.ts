import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { labelReviewSubmission, sameLabelReview, updateLabelCorrection, type LabelReviewPage, type LabelReviewSubmission } from './label-review.vm';

/** Edits the existing human gate's submission; never approves independently. */
@Component({
  selector: 'app-dataset-label-review', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="label-review" data-testid="dataset-label-review" [attr.aria-label]="i18n.t('data.labelReview.title')" [attr.aria-busy]="loading()">
      <h3>{{ i18n.t('data.labelReview.title') }}</h3>
      @if (error()) {
        <p role="alert">{{ i18n.t('data.labelReview.unavailable') }}</p>
        <button type="button" (click)="reload()" [disabled]="loading()">{{ i18n.t('common.retry') }}</button>
      }
      @if (loading()) { <p role="status">{{ i18n.t('data.labelReview.loading') }}</p> }
      @if (page(); as snapshot) {
        <p>{{ snapshot.dataset_name }} · v{{ snapshot.source_version }} · {{ i18n.t('data.labelReview.total', { count: snapshot.total }) }}</p>
        <p>{{ i18n.t('data.labelReview.instructions') }}</p>
        <div class="table-wrap"><table>
          <thead><tr><th>{{ i18n.t('data.labelReview.row') }}</th>@for (column of snapshot.text_columns; track column) { <th>{{ column }}</th> }<th>{{ i18n.t('data.labelReview.original') }}</th><th>{{ i18n.t('data.labelReview.corrected') }}</th></tr></thead>
          <tbody>@for (row of snapshot.rows; track row.row_id) {
            <tr [attr.data-row-id]="row.row_id"><th>{{ row.row_id + 1 }}</th>
              @for (column of snapshot.text_columns; track column) { <td class="text">{{ row.values[column] ?? '—' }}</td> }
              <td>{{ row.label }}</td><td><select [attr.aria-label]="i18n.t('data.labelReview.label_for', { row: row.row_id + 1 })" [value]="corrections()[row.row_id] ?? row.label" [disabled]="loading() || error() || disabled()" (change)="change(row.row_id, $any($event.target).value)">
                @for (label of snapshot.labels; track label) { <option [value]="label" [selected]="(corrections()[row.row_id] ?? row.label) === label">{{ label }}</option> }
              </select></td>
            </tr>
          }</tbody>
        </table></div>
        <div class="pager">
          <button type="button" data-testid="label-review-prev" [disabled]="snapshot.offset === 0 || loading() || error() || disabled()" (click)="loadPage(Math.max(0, snapshot.offset - 50))">{{ i18n.t('data.detail.preview.prev') }}</button>
          <span>{{ snapshot.offset + 1 }}–{{ snapshot.offset + snapshot.rows.length }} / {{ snapshot.total }}</span>
          <button type="button" data-testid="label-review-next" [disabled]="snapshot.offset + snapshot.rows.length >= snapshot.total || loading() || error() || disabled()" (click)="loadPage(snapshot.offset + snapshot.rows.length)">{{ i18n.t('data.detail.preview.next') }}</button>
        </div>
        <p role="status">{{ i18n.t('data.labelReview.changed', { count: changed() }) }}</p>
        <label class="ack"><input type="checkbox" data-testid="label-review-ack" [checked]="acknowledged()" [disabled]="loading() || error() || disabled()" (change)="acknowledged.set($any($event.target).checked)" />{{ i18n.t('data.labelReview.ack', { count: snapshot.total }) }}</label>
      }
    </section>
  `,
  styles: [`:host{display:block;min-width:0}.label-review{padding:14px;border:1px solid var(--ck-stroke-2);border-radius:6px;color:var(--ck-fg-1);background:var(--ck-bg-panel);font-size:12px;line-height:1.5}h3{font-size:14px;margin:0 0 10px}p{margin:8px 0;color:var(--ck-fg-3)}.table-wrap{max-height:340px;overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--ck-stroke-2);vertical-align:top}.text{min-width:130px;max-width:380px;white-space:pre-wrap;overflow-wrap:anywhere}select,button{color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);border:1px solid var(--ck-stroke-2);border-radius:4px;padding:6px}button:disabled{opacity:.45}.pager{display:flex;align-items:center;gap:12px;justify-content:space-between;margin:12px 0}.ack{display:flex;gap:10px;align-items:flex-start}.ack input{margin-top:4px}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:2px}`],
})
export class DatasetLabelReviewComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  readonly runId = input.required<string>();
  readonly decisionId = input.required<string>();
  readonly disabled = input(false);
  readonly submissionChange = output<LabelReviewSubmission | null>();
  readonly page = signal<LabelReviewPage | null>(null);
  readonly corrections = signal<Record<number, string>>({});
  readonly acknowledged = signal(false);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly changed = computed(() => Object.keys(this.corrections()).length);
  protected readonly Math = Math;
  private request: Subscription | null = null;
  private generation = 0;
  private readonly identity = computed(() => JSON.stringify([this.workspace.current()?.id, this.runId(), this.decisionId()]));

  constructor() {
    effect(() => { this.identity(); untracked(() => this.reload()); });
    effect(() => this.submissionChange.emit(this.loading() || this.error() || this.disabled()
      ? null : labelReviewSubmission(this.page(), this.corrections(), this.acknowledged())));
  }

  reload(): void {
    this.request?.unsubscribe();
    this.page.set(null); this.corrections.set({}); this.acknowledged.set(false);
    this.loadPage(0);
  }

  loadPage(offset: number): void {
    this.request?.unsubscribe();
    const runId = this.runId(), decisionId = this.decisionId();
    const generation = ++this.generation, identity = this.identity();
    const scope = this.workspace.captureRequestScope();
    this.loading.set(true); this.error.set(false);
    if (!runId || !decisionId) { this.loading.set(false); this.error.set(true); return; }
    this.request = this.api.getLabelReview(runId, decisionId, offset).pipe(takeUntilDestroyed(this.destroy)).subscribe({
      next: page => {
        if (generation !== this.generation || identity !== this.identity() || !this.workspace.isRequestScopeCurrent(scope)) return;
        const previous = this.page();
        if (page.decision_id !== decisionId || (previous && !sameLabelReview(previous, page))) {
          this.error.set(true); this.acknowledged.set(false); this.loading.set(false); return;
        }
        this.page.set(page); this.loading.set(false);
      },
      error: () => {
        if (generation !== this.generation || identity !== this.identity() || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false); this.error.set(true); this.acknowledged.set(false);
      },
    });
  }

  change(rowId: number, label: string): void {
    const page = this.page();
    if (!page || this.loading() || this.error() || this.disabled()) return;
    this.corrections.set(updateLabelCorrection(page, this.corrections(), rowId, label));
    this.acknowledged.set(false);
  }
}
