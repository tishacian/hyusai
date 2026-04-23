import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import {
  CanonicalApiService,
  type EvaluationReviewQueueResponse,
  type ReviewQueueItem,
} from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  PageFrameComponent,
  TagComponent,
} from '@app/shared/cockpit';

/**
 * Steering · Review queue — Vague E / E1.
 *
 * Lists Decisions(kind=review_required) produced by the auto-eval
 * loop after a Run completes. Each row surfaces:
 *
 * - The observed breach (composite score, hallucination rate, or a
 *   dimension floor) with the threshold that was tripped, so the
 *   operator can judge severity at a glance.
 * - A run preview (query + first 400 chars of the response) to avoid
 *   a round-trip into `/runs/:id` for the triage pass.
 * - Three canonical actions: **Accept** (false positive, the reply
 *   was fine), **Reject** (response is indeed bad — logged for
 *   retraining / prompt tuning) and **Open run** (full reasoning
 *   trail). Accept/Reject reuse the existing Decision state machine
 *   via `POST /hypervisor/decisions/{id}/{accept|reject}`.
 *
 * Intentionally no custom re-run or override here: those belong in
 * the Run detail view; this page is about queue triage at scale.
 */
@Component({
  selector: 'app-steering-review-queue',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, PageFrameComponent, GlyphComponent, TagComponent],
  template: `
    <ck-page-frame
      eyebrow="Steering · Review queue"
      title="Evaluation review queue"
      description="Runs flagged by the auto-eval loop for manual review. Accept clears the decision (false positive); Reject keeps it for retraining signal."
    >
      <div class="flex flex-col gap-5">
        <!-- Filters -->
        <section class="ck-surface rounded-md" style="padding:12px 18px;">
          <div class="flex items-center gap-3 flex-wrap">
            <span
              class="ck-mono"
              style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);"
            >
              STATUS
            </span>
            <div
              class="flex items-center gap-1 ck-surface rounded"
              style="padding:3px; background:var(--ck-bg-inset);"
            >
              @for (opt of statusOptions; track opt.value) {
                <button
                  type="button"
                  (click)="setStatus(opt.value)"
                  class="ck-mono"
                  style="padding:5px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase;"
                  [style.background]="status() === opt.value ? 'var(--ck-bg-raised)' : 'transparent'"
                  [style.color]="status() === opt.value ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                >
                  {{ opt.label }}
                </button>
              }
            </div>
            <span class="ml-auto ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
              {{ items().length }} ITEMS
            </span>
            <button
              type="button"
              (click)="refresh()"
              class="ck-mono"
              style="padding:4px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset);"
              [disabled]="loading()"
            >
              {{ loading() ? 'LOADING…' : 'REFRESH' }}
            </button>
            <a
              routerLink="/presets/evaluation"
              class="ck-mono"
              style="padding:4px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset); text-decoration:none;"
            >
              THRESHOLDS
            </a>
          </div>
        </section>

        <!-- Queue -->
        <section class="ck-surface rounded-md" style="padding:0;">
          @if (loading() && !items().length) {
            <div
              class="ck-mono"
              style="font-size:11px; padding:48px; text-align:center; color:var(--ck-fg-4);"
            >
              LOADING QUEUE…
            </div>
          } @else if (!items().length) {
            <div
              class="ck-mono"
              style="font-size:11px; padding:48px; text-align:center; color:var(--ck-fg-4);"
            >
              @if (status() === 'proposed') {
                NO OPEN REVIEWS — EVAL LOOP IS CLEAN
              } @else {
                NO ITEMS AT STATUS "{{ status().toUpperCase() }}"
              }
            </div>
          } @else {
            <ul style="display:flex; flex-direction:column; gap:0;">
              @for (item of items(); track item.decision.id) {
                <li
                  style="padding:16px 22px; border-bottom:1px solid var(--ck-hair);"
                  [style.background]="
                    pendingId() === item.decision.id
                      ? 'var(--ck-bg-inset)'
                      : 'transparent'
                  "
                >
                  <div class="flex items-start gap-4">
                    <!-- Severity indicator -->
                    <div class="flex flex-col items-center gap-1" style="min-width:60px;">
                      <span
                        class="ck-mono ck-tnum"
                        style="font-size:18px; font-weight:500;"
                        [style.color]="compositeColor(compositeScore(item))"
                      >
                        {{ formatScore(compositeScore(item)) }}
                      </span>
                      <span
                        class="ck-mono"
                        style="font-size:8px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);"
                      >
                        COMPOSITE
                      </span>
                    </div>

                    <!-- Main content -->
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2 mb-1">
                        <ck-tag tone="warn" variant="soft">REVIEW</ck-tag>
                        <ck-tag [tone]="statusTone(item.decision.status)" variant="outline">
                          {{ item.decision.status.toUpperCase() }}
                        </ck-tag>
                        <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                          {{ formatTimestamp(item.decision.created_at) }}
                        </span>
                      </div>

                      <div class="text-sm text-white font-medium mb-2">
                        {{ item.decision.title }}
                      </div>

                      <!-- Breach reasons -->
                      @if (breachReasons(item).length) {
                        <div class="flex flex-wrap gap-2 mb-2">
                          @for (reason of breachReasons(item); track reason.metric) {
                            <span
                              class="ck-mono"
                              style="font-size:10px; padding:3px 8px; border-radius:3px; background:var(--ck-bg-inset); color:var(--ck-fg-2);"
                            >
                              {{ reason.metric }} ·
                              <span class="ck-tnum" style="color:var(--ck-signal-neg);">
                                {{ formatReason(reason) }}
                              </span>
                            </span>
                          }
                        </div>
                      }

                      <!-- Run preview -->
                      @if (runQuery(item)) {
                        <div
                          class="ck-mono"
                          style="font-size:11px; color:var(--ck-fg-3); line-height:1.5; margin-bottom:4px;"
                        >
                          <span style="color:var(--ck-fg-4);">Q·</span>
                          {{ truncate(runQuery(item), 180) }}
                        </div>
                      }
                      @if (runResponse(item)) {
                        <div
                          class="ck-mono"
                          style="font-size:11px; color:var(--ck-fg-2); line-height:1.5; white-space:pre-wrap;"
                        >
                          <span style="color:var(--ck-fg-4);">A·</span>
                          {{ truncate(runResponse(item), 400) }}
                        </div>
                      }

                      <!-- Suggestion -->
                      @if (suggestion(item)) {
                        <div
                          class="ck-mono"
                          style="font-size:11px; color:var(--ck-signal-cool); margin-top:8px; padding:6px 10px; background:var(--ck-bg-inset); border-radius:3px; border-left:2px solid var(--ck-signal-cool);"
                        >
                          <ck-glyph name="bolt" [size]="10" />
                          {{ suggestion(item) }}
                        </div>
                      }
                    </div>

                    <!-- Actions -->
                    <div class="flex flex-col gap-2" style="min-width:120px;">
                      @if (item.decision.status === 'proposed') {
                        <button
                          type="button"
                          (click)="accept(item)"
                          [disabled]="pendingId() === item.decision.id"
                          class="ck-mono"
                          style="padding:6px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; background:var(--ck-signal-pos); color:var(--ck-on-signal); font-weight:500;"
                          [style.opacity]="pendingId() === item.decision.id ? '0.5' : '1'"
                          title="Mark as false positive — the response was actually fine"
                        >
                          ACCEPT
                        </button>
                        <button
                          type="button"
                          (click)="reject(item)"
                          [disabled]="pendingId() === item.decision.id"
                          class="ck-mono"
                          style="padding:6px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-signal-neg); background:transparent;"
                          [style.opacity]="pendingId() === item.decision.id ? '0.5' : '1'"
                          title="Confirm the response is bad — kept for retraining signal"
                        >
                          REJECT
                        </button>
                      }
                      @if (item.run) {
                        <a
                          [routerLink]="['/runs', item.run.id]"
                          class="ck-mono"
                          style="padding:6px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-2); background:var(--ck-bg-inset); text-decoration:none; text-align:center;"
                        >
                          OPEN RUN
                        </a>
                      }
                    </div>
                  </div>
                </li>
              }
            </ul>
          }
        </section>
      </div>
    </ck-page-frame>
  `,
})
export class SteeringReviewQueueComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);

  readonly items = signal<ReviewQueueItem[]>([]);
  readonly loading = signal(false);
  readonly pendingId = signal<string | null>(null);
  readonly status = signal<'proposed' | 'accepted' | 'rejected' | 'all'>('proposed');

  protected readonly statusOptions = [
    { value: 'proposed' as const, label: 'OPEN' },
    { value: 'accepted' as const, label: 'ACCEPTED' },
    { value: 'rejected' as const, label: 'REJECTED' },
    { value: 'all' as const, label: 'ALL' },
  ];

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.canonical
      .getEvaluationReviewQueue({ status: this.status(), limit: 100 })
      .subscribe({
        next: (response: EvaluationReviewQueueResponse | null) => {
          this.items.set(response?.items ?? []);
          this.loading.set(false);
        },
        error: () => {
          this.items.set([]);
          this.loading.set(false);
        },
      });
  }

  setStatus(s: 'proposed' | 'accepted' | 'rejected' | 'all'): void {
    if (this.status() === s) return;
    this.status.set(s);
    this.refresh();
  }

  accept(item: ReviewQueueItem): void {
    if (this.pendingId()) return;
    this.pendingId.set(item.decision.id);
    this.canonical.acceptDecision(item.decision.id).subscribe({
      next: () => {
        this.pendingId.set(null);
        this.refresh();
      },
      error: () => this.pendingId.set(null),
    });
  }

  reject(item: ReviewQueueItem): void {
    if (this.pendingId()) return;
    this.pendingId.set(item.decision.id);
    this.canonical.rejectDecision(item.decision.id).subscribe({
      next: () => {
        this.pendingId.set(null);
        this.refresh();
      },
      error: () => this.pendingId.set(null),
    });
  }

  protected compositeScore(item: ReviewQueueItem): number | null {
    return item.run?.evaluation_scores?.composite_score ?? null;
  }

  protected breachReasons(item: ReviewQueueItem): Array<{
    metric: string;
    observed: number;
    threshold: number;
    direction: 'above' | 'below';
  }> {
    return item.run?.evaluation_scores?.reasons ?? [];
  }

  protected runQuery(item: ReviewQueueItem): string {
    const input = item.run?.input_ref;
    if (!input) return '';
    for (const key of ['query', 'question', 'prompt', 'input']) {
      const v = (input as Record<string, unknown>)[key];
      if (typeof v === 'string') return v;
    }
    return '';
  }

  protected runResponse(item: ReviewQueueItem): string {
    const output = item.run?.output_ref;
    if (!output) return '';
    for (const key of ['answer', 'response', 'output', 'text']) {
      const v = (output as Record<string, unknown>)[key];
      if (typeof v === 'string') return v;
    }
    return '';
  }

  protected suggestion(item: ReviewQueueItem): string {
    const rationale = item.decision.rationale as Record<string, unknown> | null;
    if (!rationale) return '';
    const s = rationale['suggestion'];
    return typeof s === 'string' ? s : '';
  }

  protected formatScore(v: number | null): string {
    if (v == null) return '—';
    return v.toFixed(0);
  }

  protected compositeColor(v: number | null): string {
    if (v == null) return 'var(--ck-fg-3)';
    if (v < 40) return 'var(--ck-signal-neg)';
    if (v < 60) return 'var(--ck-signal-warn)';
    return 'var(--ck-signal-pos)';
  }

  protected formatReason(reason: {
    metric: string;
    observed: number;
    threshold: number;
    direction: 'above' | 'below';
  }): string {
    const isRatio = reason.metric.includes('hallucination_rate');
    const fmt = (n: number) =>
      isRatio ? `${(n * 100).toFixed(0)}%` : n.toFixed(1);
    const comparator = reason.direction === 'above' ? '>' : '<';
    return `${fmt(reason.observed)} ${comparator} ${fmt(reason.threshold)}`;
  }

  protected truncate(s: string, n: number): string {
    if (!s) return '';
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  protected formatTimestamp(iso: string | null): string {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const now = new Date();
      const diff = now.getTime() - d.getTime();
      const mins = Math.round(diff / 60000);
      if (mins < 1) return 'just now';
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.round(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.round(hrs / 24);
      return `${days}d ago`;
    } catch {
      return iso;
    }
  }

  protected statusTone(
    status: string,
  ): 'pos' | 'warn' | 'cool' | 'neg' | 'neutral' {
    switch (status) {
      case 'accepted':
        return 'pos';
      case 'rejected':
        return 'neg';
      case 'applied':
        return 'cool';
      case 'proposed':
      default:
        return 'warn';
    }
  }
}
