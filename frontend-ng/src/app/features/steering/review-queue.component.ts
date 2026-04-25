import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs/operators';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type EvaluationReviewQueueResponse,
  type ReviewQueueItem,
  type RunReplayResult,
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
                  [id]="'decision-' + item.decision.id"
                  style="padding:16px 22px; border-bottom:1px solid var(--ck-hair); transition:background 400ms ease;"
                  [style.background]="
                    focusedDecisionId() === item.decision.id
                      ? 'var(--ck-bg-focus, rgba(253, 190, 0, 0.08))'
                      : pendingId() === item.decision.id
                        ? 'var(--ck-bg-inset)'
                        : 'transparent'
                  "
                  [style.box-shadow]="
                    focusedDecisionId() === item.decision.id
                      ? 'inset 2px 0 0 var(--ck-signal-warn, #fdbe00)'
                      : 'none'
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
                        <button
                          type="button"
                          (click)="openReplayModal(item)"
                          [disabled]="pendingId() === item.decision.id"
                          class="ck-mono"
                          style="padding:6px 10px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; border:1px solid var(--ck-signal-cool); color:var(--ck-signal-cool); background:transparent;"
                          [style.opacity]="pendingId() === item.decision.id ? '0.5' : '1'"
                          title="Re-run this query with operator overrides — see if a tweaked prompt or RAG mode produces a better answer"
                        >
                          RE-RUN
                        </button>
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

      <!-- E1.5.2 — Replay-with-override modal -->
      @if (replayModalItem(); as replayItem) {
        <div
          class="rq-modal-backdrop"
          (click)="closeReplayModal()"
          style="position:fixed; inset:0; background:rgba(8,10,14,0.6); z-index:50; display:flex; align-items:center; justify-content:center;"
        >
          <div
            class="ck-surface rq-modal"
            (click)="$event.stopPropagation()"
            style="width:min(640px,92vw); max-height:90vh; overflow:auto; padding:18px 20px; border-radius:6px;"
          >
            <div class="flex items-center justify-between" style="margin-bottom:12px;">
              <div>
                <div
                  class="ck-mono"
                  style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);"
                >
                  REPLAY WITH OVERRIDE
                </div>
                <div style="font-size:14px; color:var(--ck-fg-1); margin-top:2px;">
                  Try a tweaked prompt, RAG mode, or model on the same question.
                </div>
              </div>
              <button
                type="button"
                (click)="closeReplayModal()"
                class="ck-icon-btn"
                style="border:1px solid var(--ck-stroke-soft); padding:4px 8px; background:transparent; color:var(--ck-fg-3); border-radius:3px;"
                title="Close"
              >
                ✕
              </button>
            </div>

            <div style="display:flex; flex-direction:column; gap:12px;">
              <label class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);">
                QUESTION
              </label>
              <textarea
                [ngModel]="replayQuery()"
                (ngModelChange)="replayQuery.set($event)"
                rows="3"
                class="ck-mono"
                style="width:100%; padding:8px 10px; background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-soft); border-radius:3px; font-size:12px;"
                placeholder="Edit the question to retry"
              ></textarea>

              <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                <div>
                  <label class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);">
                    RAG MODE
                  </label>
                  <select
                    [ngModel]="replayMode()"
                    (ngModelChange)="replayMode.set($event)"
                    class="ck-mono"
                    style="width:100%; padding:8px 10px; background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-soft); border-radius:3px; font-size:12px; margin-top:4px;"
                  >
                    <option value="">— keep parent —</option>
                    <option value="auto">auto</option>
                    <option value="naive">naive</option>
                    <option value="hybrid">hybrid</option>
                    <option value="hah">hah</option>
                    <option value="chah">chah</option>
                  </select>
                </div>
                <div>
                  <label class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);">
                    MODEL
                  </label>
                  <input
                    [ngModel]="replayModel()"
                    (ngModelChange)="replayModel.set($event)"
                    type="text"
                    placeholder="gpt-4.1, deepseek-r1, …"
                    class="ck-mono"
                    style="width:100%; padding:8px 10px; background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-soft); border-radius:3px; font-size:12px; margin-top:4px;"
                  />
                </div>
              </div>

              @if (replayResult(); as r) {
                <div
                  class="ck-mono"
                  style="margin-top:8px; padding:10px 12px; background:var(--ck-bg-inset); border-radius:3px; border-left:2px solid var(--ck-signal-cool); font-size:11px; color:var(--ck-fg-2); line-height:1.6;"
                >
                  <div style="color:var(--ck-signal-cool);">REPLAY · {{ statusLabel(r.status) }}</div>
                  <div>NEW RUN · <a [routerLink]="['/runs', r.run_id]" style="color:var(--ck-fg-1); text-decoration:underline;">{{ r.run_id.slice(0, 8) }}</a> · {{ r.duration_ms }}ms</div>
                  @if (r.response_preview) {
                    <div style="margin-top:6px; color:var(--ck-fg-2); white-space:pre-wrap;">{{ truncate(r.response_preview, 400) }}</div>
                  }
                  @if (r.eval_pending) {
                    <div style="margin-top:6px; color:var(--ck-fg-4);">Eval pending — open the run to see the score delta.</div>
                  }
                </div>
              }

              <div class="flex items-center gap-3" style="margin-top:6px;">
                <button
                  type="button"
                  (click)="confirmReplay(replayItem)"
                  [disabled]="replayPending() || !replayQuery().trim()"
                  class="ck-mono"
                  style="padding:8px 14px; border-radius:3px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-cool); color:var(--ck-on-signal); font-weight:500; flex:0 0 auto;"
                  [style.opacity]="(replayPending() || !replayQuery().trim()) ? '0.5' : '1'"
                >
                  {{ replayPending() ? 'RUNNING…' : 'RUN' }}
                </button>
                <button
                  type="button"
                  (click)="closeReplayModal()"
                  [disabled]="replayPending()"
                  class="ck-mono"
                  style="padding:8px 14px; border-radius:3px; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-3); background:transparent;"
                >
                  CLOSE
                </button>
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-left:auto;">
                  parent · {{ replayItem.run?.id?.slice(0, 8) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      }
    </ck-page-frame>
  `,
})
export class SteeringReviewQueueComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastrService);

  readonly items = signal<ReviewQueueItem[]>([]);
  readonly loading = signal(false);
  readonly pendingId = signal<string | null>(null);
  readonly status = signal<'proposed' | 'accepted' | 'rejected' | 'all'>('proposed');

  // E1.5.2 — replay-with-override modal state. Kept in the component
  // (not a separate service) because the modal is tightly coupled to
  // the queue row that opened it and lives inside the same template.
  readonly replayModalItem = signal<ReviewQueueItem | null>(null);
  readonly replayQuery = signal<string>('');
  readonly replayMode = signal<string>('');
  readonly replayModel = signal<string>('');
  readonly replayPending = signal(false);
  readonly replayResult = signal<RunReplayResult | null>(null);
  /**
   * Decision id the user deeplinked in via the chat auto-QA toast
   * (``?decision=<id>``). When it matches an item in the current
   * queue, the row is highlighted + scrolled into view. Cleared on
   * filter change so the highlight doesn't stick around.
   */
  readonly focusedDecisionId = signal<string | null>(null);

  protected readonly statusOptions = [
    { value: 'proposed' as const, label: 'OPEN' },
    { value: 'accepted' as const, label: 'ACCEPTED' },
    { value: 'rejected' as const, label: 'REJECTED' },
    { value: 'all' as const, label: 'ALL' },
  ];

  constructor() {
    // Pick up ?decision=<id> deeplinks coming from the chat auto-QA
    // toast so the reviewer lands directly on the breached row.
    this.route.queryParamMap
      .pipe(
        map((p) => p.get('decision')),
        takeUntilDestroyed(),
      )
      .subscribe((id) => this.focusedDecisionId.set(id));

    // When either the focus id changes or the queue items load,
    // scroll the matching row into view (if any). We run this in
    // an effect so it re-fires on both signals + plays nicely with
    // OnPush change detection.
    effect(() => {
      const focus = this.focusedDecisionId();
      const list = this.items();
      if (!focus || !list.length) return;
      if (!list.some((i) => i.decision.id === focus)) return;
      queueMicrotask(() => {
        const el = document.getElementById(`decision-${focus}`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }

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
    // Drop the deeplink highlight — the user explicitly moved away
    // from the filter the toast sent them to.
    this.focusedDecisionId.set(null);
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

  // ---- Replay-with-override ----

  openReplayModal(item: ReviewQueueItem): void {
    this.replayModalItem.set(item);
    this.replayQuery.set(this.runQuery(item));
    this.replayMode.set('');
    this.replayModel.set('');
    this.replayResult.set(null);
  }

  closeReplayModal(): void {
    if (this.replayPending()) return;
    this.replayModalItem.set(null);
    this.replayResult.set(null);
  }

  confirmReplay(item: ReviewQueueItem): void {
    if (this.replayPending() || !item.run) return;
    const overrides: Record<string, unknown> = {};
    const q = this.replayQuery().trim();
    if (q && q !== this.runQuery(item)) {
      overrides['query'] = q;
    } else if (q) {
      overrides['query'] = q;
    }
    const mode = this.replayMode();
    if (mode) overrides['rag_pipeline_mode'] = mode;
    const model = this.replayModel().trim();
    if (model) overrides['model'] = model;

    this.replayPending.set(true);
    this.canonical
      .replayRun(item.run.id, {
        overrides,
        source_decision_id: item.decision.id,
      })
      .subscribe({
        next: (res) => {
          this.replayPending.set(false);
          if (!res) {
            this.toast.error(
              'Replay failed — see backend logs.',
              'Replay error',
              { timeOut: 6000 },
            );
            return;
          }
          this.replayResult.set(res);
          if (res.status === 'failed') {
            this.toast.warning(
              'Replay completed with failure — open the run to inspect.',
              'Replay failed',
              { timeOut: 6000 },
            );
          } else {
            this.toast.success(
              `Replay run ${res.run_id.slice(0, 8)} created — eval pending.`,
              'Replay started',
              { timeOut: 5000 },
            );
          }
        },
        error: () => {
          this.replayPending.set(false);
          this.toast.error('Replay request failed.', 'Replay error', {
            timeOut: 6000,
          });
        },
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

  protected statusLabel(s: string | null | undefined): string {
    return (s ?? '').toUpperCase();
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
