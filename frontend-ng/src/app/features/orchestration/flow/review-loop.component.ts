import { ChangeDetectionStrategy, Component, inject, input, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';

interface ReviewRow {
  id: string;
  note: string;
  status: string;
  draft_hash?: string | null;
  correction_hash?: string | null;
  later_run_id?: string | null;
  later_status?: string;
  same_object?: boolean;
  nodes?: Array<{ type: string }>;
  run_id: string;
}

@Component({
  selector: 'app-review-loop',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="review" [attr.aria-label]="i18n.t('flow.review.title')">
      <h2>{{ i18n.t('flow.review.title') }}</h2>
      @if (error()) {
        <p role="alert">{{ error() }}</p>
      }
      @if (!runs().length) {
        <p>{{ i18n.t('flow.review.empty') }}</p>
      } @else {
        <label>
          {{ i18n.t('flow.review.note') }}
          <textarea rows="3" maxlength="500" [ngModel]="note()" (ngModelChange)="note.set($event)"></textarea>
        </label>
        <button type="button" (click)="save()" [disabled]="busy() || !note().trim()">{{ i18n.t('flow.review.save') }}</button>
      }
      @if (review(); as row) {
        <p>{{ row.note }}</p>
        <button type="button" (click)="reread()" [disabled]="busy()">{{ i18n.t('flow.review.reread') }}</button>
        @if (row.nodes?.length) {
          <p>{{ i18n.t('flow.review.read', { blocks: blocks(row) }) }}</p>
        }
        @if (row.draft_hash) {
          <button type="button" (click)="confirm()" [disabled]="busy()">{{ i18n.t('flow.review.confirm') }}</button>
        }
        @if (row.correction_hash) {
          @if (laterRuns().length) {
            <label>
              <select [ngModel]="laterId()" (ngModelChange)="laterId.set($event)">
                @for (run of laterRuns(); track run.id) {
                  <option [value]="run.id">{{ run.status }}</option>
                }
              </select>
            </label>
            <button type="button" (click)="compare()" [disabled]="busy() || !laterId()">{{ i18n.t('flow.review.compare') }}</button>
          } @else {
            <p>{{ i18n.t('flow.review.need_later') }}</p>
          }
        }
        @if (row.same_object) {
          <p role="status">{{ i18n.t('flow.review.same') }} {{ i18n.t('flow.review.later', { status: row.later_status || '' }) }}</p>
        }
      }
    </section>
  `,
  styles: `
    .review {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 12px;
      border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      border-radius: 12px;
      h2, p, label { margin: 0; }
      h2 { font-size: 1rem; }
      textarea, select, button { font: inherit; }
    }
  `,
})
export class ReviewLoopComponent implements OnInit {
  readonly systemId = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  protected readonly runs = signal<Array<{ id: string; status: string }>>([]);
  protected readonly review = signal<ReviewRow | null>(null);
  protected readonly note = signal('');
  protected readonly laterId = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  ngOnInit(): void {
    this.load();
  }

  protected laterRuns(): Array<{ id: string; status: string }> {
    const current = this.review()?.run_id;
    return this.runs().filter((run) => run.id !== current);
  }

  protected blocks(row: ReviewRow): string {
    return (row.nodes ?? []).map((node) => node.type).join(', ');
  }

  protected save(): void {
    const run = this.runs()[0];
    const note = this.note().trim();
    if (!run || !note || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.canonical.automationReserve(this.systemId(), run.id, note).subscribe({
      next: (row) => {
        this.review.set({ ...row, run_id: row.run_id });
        this.busy.set(false);
      },
      error: () => this.fail(),
    });
  }

  protected reread(): void {
    const row = this.review();
    if (!row || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.canonical.automationReread(this.systemId(), row.id).subscribe({
      next: (seen) => {
        this.review.set({ ...row, ...seen, same_object: false });
        this.busy.set(false);
      },
      error: () => this.fail(),
    });
  }

  protected confirm(): void {
    const row = this.review();
    if (!row?.draft_hash || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.canonical.automationConfirmReview(this.systemId(), row.id, row.draft_hash).subscribe({
      next: (confirmed) => {
        this.review.set({ ...row, ...confirmed });
        const later = this.laterRuns()[0];
        if (later) this.laterId.set(later.id);
        this.busy.set(false);
      },
      error: () => this.fail(),
    });
  }

  protected compare(): void {
    const row = this.review();
    const later = this.laterId();
    if (!row || !later || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.canonical.automationCompareReview(this.systemId(), row.id, later).subscribe({
      next: (compared) => {
        this.review.set({ ...row, ...compared, same_object: compared.same_object === true });
        this.busy.set(false);
      },
      error: () => this.fail(),
    });
  }

  private load(): void {
    this.canonical.automationReview(this.systemId()).subscribe({
      next: (state) => {
        this.runs.set(state.runs ?? []);
        this.review.set(state.review ? { ...state.review, run_id: state.review.run_id } : null);
        if (state.review?.note) this.note.set(state.review.note);
        const later = (state.runs ?? []).find((run) => run.id !== state.review?.run_id);
        if (later) this.laterId.set(later.id);
      },
      error: () => this.fail(),
    });
  }

  private fail(): void {
    this.busy.set(false);
    this.error.set(this.i18n.t('flow.review.error'));
  }
}
