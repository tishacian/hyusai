import { ChangeDetectionStrategy, Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { laterResults, reviewRefusalKey, reviewStep } from './review-loop.vm';

interface ReviewRow {
  id: string;
  note: string;
  status: string;
  draft_hash?: string | null;
  correction_hash?: string | null;
  later_run_id?: string | null;
  later_status?: string;
  same_object?: boolean;
  ran_correction?: boolean | null;
  nodes?: Array<{ type: string; editable?: boolean }>;
  run_id: string;
}

@Component({
  selector: 'app-review-loop',
  standalone: true,
  imports: [FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (runs().length || review()) {
      <section class="review" [class.is-open]="open()" [attr.aria-label]="i18n.t('flow.review.title')">
        <div class="review__bar">
          <h2 class="review__eyebrow"><app-icon name="flag" [size]="12" />{{ i18n.t('flow.review.title') }}</h2>
          @if (review(); as row) {
            <span class="review__status" data-testid="review-status">
              {{ step() > 4 ? i18n.t('flow.review.done') : i18n.t('flow.review.step', { step: step(), label: stepLabel(step()) }) }}
            </span>
            <q class="review__quote">{{ row.note }}</q>
          } @else {
            <span class="review__status">{{ i18n.t('flow.review.intro') }}</span>
          }
          <button type="button" class="ck-btn ck-btn--sm ck-btn-quiet review__toggle" [attr.aria-expanded]="open()" (click)="open.set(!open())">
            {{ i18n.t(open() ? 'flow.review.close' : review() ? 'flow.review.continue' : 'flow.review.start') }}
          </button>
        </div>
        @if (open()) {
          <div class="review__body">
            <ol class="review__steps">
              @for (index of [1, 2, 3, 4]; track index) {
                <li [class.is-done]="step() > index" [class.is-current]="step() === index">
                  <span class="review__dot">{{ index }}</span>{{ stepLabel(index) }}
                </li>
              }
            </ol>
            @if (error()) {
              <p class="review__error" role="alert">{{ error() }}</p>
            }
            @if (!review()) {
              <label class="review__field">
                <span>{{ i18n.t('flow.review.note') }}</span>
                <textarea rows="2" maxlength="500" [placeholder]="i18n.t('flow.review.note_placeholder')" [ngModel]="note()" (ngModelChange)="note.set($event)"></textarea>
              </label>
              <div class="review__actions">
                <button type="button" class="ck-btn ck-btn--sm ck-btn-accent" (click)="save()" [disabled]="busy() || !note().trim()">{{ i18n.t('flow.review.save') }}</button>
                <span class="review__hint">{{ i18n.t('flow.review.save_hint') }}</span>
              </div>
            } @else if (review(); as row) {
              <div class="review__actions">
                @if (step() === 2) {
                  <button type="button" class="ck-btn ck-btn--sm ck-btn-accent" (click)="reread()" [disabled]="busy()">{{ i18n.t('flow.review.reread') }}</button>
                  <span class="review__hint">{{ i18n.t('flow.review.reread_hint') }}</span>
                } @else if (step() === 3) {
                  <button type="button" class="ck-btn ck-btn--sm ck-btn-accent" (click)="confirm()" [disabled]="busy()">{{ i18n.t('flow.review.confirm') }}</button>
                  <button type="button" class="ck-btn ck-btn--sm ck-btn-quiet" (click)="reread()" [disabled]="busy()">{{ i18n.t('flow.review.reread') }}</button>
                  @if (row.nodes?.length) {
                    <span class="review__hint">{{ i18n.t('flow.review.read', { blocks: blocks(row) }) }}</span>
                  }
                } @else if (step() === 4) {
                  @if (laterRuns().length) {
                    <label class="review__field review__field--inline">
                      <span>{{ i18n.t('flow.review.later_label') }}</span>
                      <select [ngModel]="laterId()" (ngModelChange)="laterId.set($event)">
                        @for (run of laterRuns(); track run.id) {
                          <option [value]="run.id">{{ run.status }}</option>
                        }
                      </select>
                    </label>
                    <button type="button" class="ck-btn ck-btn--sm ck-btn-accent" (click)="compare()" [disabled]="busy() || !laterId()">{{ i18n.t('flow.review.compare') }}</button>
                  } @else {
                    <span class="review__hint">{{ i18n.t('flow.review.need_later') }}</span>
                  }
                }
              </div>
              @if (row.same_object) {
                <p class="review__verdict" role="status" [class.is-ok]="row.ran_correction === true">
                  {{ i18n.t('flow.review.same') }} {{ i18n.t('flow.review.later', { status: row.later_status || '' }) }}
                  @if (row.ran_correction === true) {
                    {{ i18n.t('flow.review.ran_correction') }}
                  } @else if (row.ran_correction === false) {
                    {{ i18n.t('flow.review.other_draft') }}
                  }
                </p>
              }
            }
          </div>
        }
      </section>
    }
  `,
  styles: `
    :host { display: block; flex-shrink: 0; }
    .review {
      border: 1px solid var(--ck-stroke-2);
      border-radius: var(--ck-radius-md, 6px);
      background: var(--ck-bg-raised);
      color: var(--ck-fg-3);
      font-size: 12px;
    }
    .review__bar { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; padding: 6px 8px 6px 10px; min-width: 0; }
    .review__eyebrow { margin: 0; display: inline-flex; align-items: center; gap: 6px; color: var(--ck-fg-2); font: 600 10px/1.4 var(--ck-font-mono); letter-spacing: .08em; text-transform: uppercase; }
    .review__status { color: var(--ck-fg-2); }
    .review__quote { flex: 1; min-width: 120px; overflow: hidden; color: var(--ck-fg-3); white-space: nowrap; text-overflow: ellipsis; font-style: italic; }
    .review__toggle { margin-left: auto; }
    .review__body { display: grid; gap: 10px; padding: 10px 10px 12px; border-top: 1px solid var(--ck-stroke-2); }
    .review__steps { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 0; padding: 0; list-style: none; }
    .review__steps li { display: inline-flex; align-items: center; gap: 6px; color: var(--ck-fg-3); }
    .review__steps li.is-current { color: var(--ck-fg-1); font-weight: 600; }
    .review__steps li.is-done { color: var(--ck-status-ok-fg); }
    .review__dot { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border: 1px solid currentColor; border-radius: var(--ck-radius-sm); font: 600 10px/1 var(--ck-font-mono); }
    .review__field { display: grid; gap: 4px; max-width: 640px; color: var(--ck-fg-2); }
    .review__field--inline { display: inline-grid; grid-auto-flow: column; align-items: center; gap: 8px; }
    textarea, select { width: 100%; padding: 6px 8px; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-sm); background: var(--ck-bg-inset); color: var(--ck-fg-1); font: inherit; resize: vertical; }
    select { width: auto; min-width: 160px; height: 28px; padding: 0 8px; }
    textarea:focus-visible, select:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .review__actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
    .review__hint { color: var(--ck-fg-3); }
    .review__error { margin: 0; padding: 6px 8px; border: 1px solid var(--ck-status-neg-line); border-radius: var(--ck-radius-sm); background: var(--ck-status-neg-bg); color: var(--ck-status-neg-fg); }
    .review__verdict { margin: 0; padding: 6px 8px; border: 1px solid var(--ck-status-warn-line); border-radius: var(--ck-radius-sm); background: var(--ck-status-warn-bg); color: var(--ck-status-warn-fg); }
    .review__verdict.is-ok { border-color: var(--ck-status-ok-line); background: var(--ck-status-ok-bg); color: var(--ck-status-ok-fg); }
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
  protected readonly open = signal(false);
  /** 1 objection, 2 reread, 3 confirm, 4 compare, 5 closed. */
  protected readonly step = computed(() => reviewStep(this.review()));

  ngOnInit(): void {
    this.load();
  }

  protected laterRuns(): Array<{ id: string; status: string }> {
    return laterResults(this.runs(), this.review()?.run_id);
  }

  protected stepLabel(step: number): string {
    return this.i18n.t(`flow.review.steps.${step}`);
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
      error: (error: unknown) => this.fail(error),
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
      error: (error: unknown) => this.fail(error),
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
      error: (error: unknown) => this.fail(error),
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
        this.review.set({
          ...row,
          ...compared,
          same_object: compared.same_object === true,
          ran_correction: compared.ran_correction ?? null,
        });
        this.busy.set(false);
      },
      error: (error: unknown) => this.fail(error),
    });
  }

  private load(): void {
    this.canonical.automationReview(this.systemId()).subscribe({
      next: (state) => {
        this.runs.set(state.runs ?? []);
        this.review.set(state.review ? { ...state.review, run_id: state.review.run_id } : null);
        if (state.review?.note) this.note.set(state.review.note);
        const later = this.laterRuns()[0];
        if (later) this.laterId.set(later.id);
      },
      error: (error: unknown) => this.fail(error),
    });
  }

  private fail(error?: unknown): void {
    this.busy.set(false);
    const code = error instanceof HttpErrorResponse ? error.error?.detail?.code : '';
    this.error.set(this.i18n.t(reviewRefusalKey(code)));
  }
}
