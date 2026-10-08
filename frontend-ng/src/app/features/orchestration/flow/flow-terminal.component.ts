/**
 * `<app-flow-terminal>` — the execution terminal (presentational only).
 *
 * Restored from the deleted `flow-terminal.component.ts`, re-skinned to the
 * `--ck-*` token system and split clean from any orchestration: it renders the
 * live run log, the human-approval card (`hitl_pending` → Accept / Reject) and
 * the debugger-paused card (`debug_pending` → Stop / Continue / Step, with a
 * last-output + context-snapshot preview). All state arrives as inputs from
 * `FlowRunService`; all user intents leave as outputs. It performs no graph or
 * run logic of its own, so it can never grow into a god-component.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  input,
  output,
  viewChild,
  signal,
  computed,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { inject } from '@angular/core';
import type {
  RunDebugPayload,
  RunHitlPayload,
  LabelReviewSubmission,
} from '@app/core/canonical-api.service';
import { DatasetLabelReviewComponent } from '@app/features/data/dataset-label-review.component';
import type { DebugMode, RunLogEntry, RunUiStatus } from './flow-run.types';

@Component({
  selector: 'app-flow-terminal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, DatasetLabelReviewComponent],
  styleUrl: './flow-terminal.component.scss',
  template: `
    <section class="ck-term" [attr.aria-label]="i18n.t('flow.terminal.aria')">
      <header class="ck-term__head">
        <span class="ck-term__eyebrow">
          <app-icon name="terminal" [size]="12" />
          {{ i18n.t('flow.terminal.title') }}
        </span>
        <span class="ck-term__status" [attr.data-status]="status()">{{ statusLabel() }}</span>
        <span class="ck-term__spacer"></span>
        @if (entries().length > 0) {
          <span class="ck-term__count">{{
            i18n.t('flow.terminal.lines', { count: entries().length })
          }}</span>
        }
        <button
          type="button"
          class="ck-term__tool"
          (click)="clear.emit()"
          [title]="i18n.t('flow.terminal.clear')"
          [attr.aria-label]="i18n.t('flow.terminal.clear')"
        >
          {{ i18n.t('flow.terminal.clear') }}
        </button>
        <button
          type="button"
          class="ck-term__tool ck-term__tool--icon"
          (click)="close.emit()"
          [title]="i18n.t('flow.terminal.collapse')"
          [attr.aria-label]="i18n.t('flow.terminal.collapse')"
        >
          <app-icon name="chevron-down" [size]="14" />
        </button>
      </header>

      <div class="ck-term__body" #body>
        @if (hitl(); as h) {
          <div
            class="ck-term__card"
            data-tone="approval"
            role="alertdialog"
            [attr.aria-label]="i18n.t('flow.terminal.approval.title')"
          >
            <div class="ck-term__card-head">
              <app-icon name="user-check" [size]="14" />
              <span>{{ i18n.t('flow.terminal.approval.title') }}</span>
              <span class="ck-term__pill" data-tone="warn">{{
                i18n.t('flow.terminal.approval.paused')
              }}</span>
            </div>
            <p class="ck-term__card-prompt">
              {{ h.prompt || i18n.t('flow.terminal.approval.prompt') }}
            </p>
            @if (h.node_id) {
              <div class="ck-term__card-meta">
                <span>{{ i18n.t('flow.terminal.approval.node') }}</span><code>{{ h.node_id }}</code>
              </div>
            }
            @if (h.expires_at || (h.inbox_count ?? 0) > 0 || h.memory) {
              <div class="ck-term__card-meta" data-tone="gate-ttl">
                @if (h.seconds_remaining != null) {
                  <span>{{ i18n.t('flow.terminal.approval.ttl') }}</span>
                  <code>{{ formatRemaining(h.seconds_remaining) }}</code>
                  @if (h.expiry_action) {
                    <span class="ck-term__pill" data-tone="warn">{{ h.expiry_action }}</span>
                  }
                }
                @if ((h.inbox_count ?? 0) > 0) {
                  <span>{{ i18n.t('flow.terminal.approval.buffered') }}</span>
                  <code>{{ h.inbox_count }} txn{{ h.inbox_count === 1 ? '' : 's' }}</code>
                }
                @if (h.memory; as mem) {
                  @if (mem.event_count) {
                    <span>{{ i18n.t('flow.terminal.approval.memory') }}</span>
                    <code>v{{ mem.version ?? 1 }} · {{ mem.event_count }} evt</code>
                  }
                }
              </div>
            }
            @if (h.prompt_kind === 'review_dataset_labels') {
              <app-dataset-label-review [runId]="runId()" [decisionId]="h.decision_id ?? ''" [disabled]="hitlResolving()" (submissionChange)="labelReview.set($event)" />
            }
            <div class="ck-term__actions">
              <button
                type="button"
                class="ck-term__btn ck-term__btn--reject"
                [disabled]="hitlResolving()"
                (click)="resolve('reject')"
              >
                <app-icon name="x" [size]="12" /> {{ i18n.t('flow.terminal.approval.reject') }}
              </button>
              <button
                type="button"
                class="ck-term__btn ck-term__btn--accept"
                [disabled]="hitlResolving() || (h.prompt_kind === 'review_dataset_labels' && !labelReview())"
                (click)="resolve('accept')"
              >
                <app-icon name="check" [size]="12" /> {{ i18n.t('flow.terminal.approval.accept') }}
              </button>
            </div>
          </div>
        }

        @if (debug(); as d) {
          <div
            class="ck-term__card"
            data-tone="debug"
            role="alertdialog"
            [attr.aria-label]="i18n.t('flow.terminal.debug.title')"
          >
            <div class="ck-term__card-head">
              <app-icon name="bug" [size]="14" />
              <span>{{ i18n.t('flow.terminal.debug.title') }}</span>
              <span class="ck-term__pill" data-tone="cool">{{ d.debug_mode || 'step' }}</span>
            </div>
            <p class="ck-term__card-prompt">
              {{ i18n.t('flow.terminal.debug.prompt') }}
              <code>{{ d.node_id || 'node' }}</code>
              {{ i18n.t('flow.terminal.debug.prompt.tail') }}
            </p>
            <div class="ck-term__snap">
              <span class="ck-term__snap-label">{{
                i18n.t('flow.terminal.debug.last_output')
              }}</span>
              <pre class="ck-term__snap-body">{{ previewJson(d.last_output) }}</pre>
              <span class="ck-term__snap-label">{{
                i18n.t('flow.terminal.debug.context')
              }}</span>
              <pre class="ck-term__snap-body">{{ previewJson(d.ctx_snapshot) }}</pre>
            </div>
            <div class="ck-term__actions">
              <button
                type="button"
                class="ck-term__btn ck-term__btn--reject"
                [disabled]="debugStepping()"
                (click)="debugAction.emit('stop')"
              >
                <app-icon name="square" [size]="12" /> {{ i18n.t('flow.terminal.debug.stop') }}
              </button>
              <button
                type="button"
                class="ck-term__btn"
                [disabled]="debugStepping()"
                (click)="debugAction.emit('continue')"
              >
                <app-icon name="play" [size]="12" /> {{ i18n.t('flow.terminal.debug.continue') }}
              </button>
              <button
                type="button"
                class="ck-term__btn ck-term__btn--accept"
                [disabled]="debugStepping()"
                (click)="debugAction.emit('step')"
              >
                <app-icon name="chevron-right" [size]="12" /> {{ i18n.t('flow.terminal.debug.step') }}
              </button>
            </div>
          </div>
        }

        @if (entries().length === 0 && !hitl() && !debug()) {
          <div class="ck-term__empty">
            <span class="ck-term__caret">›</span>
            {{ i18n.t('flow.terminal.empty') }}
          </div>
        }

        @for (entry of entries(); track entry.id) {
          <div class="ck-term__row">
            <span class="ck-term__time">{{ entry.t }}</span>
            <span class="ck-term__tag" [attr.data-tone]="entry.tone">[{{ entry.tag }}]</span>
            <span class="ck-term__text">{{ entry.text }}</span>
          </div>
        }
      </div>
    </section>
  `,
})
export class FlowTerminalComponent {
  readonly i18n = inject(I18nService);

  readonly entries = input<RunLogEntry[]>([]);
  readonly status = input<RunUiStatus>('idle');
  readonly hitl = input<RunHitlPayload | null>(null);
  readonly runId = input('');
  readonly labelReview = signal<LabelReviewSubmission | null>(null);
  private readonly gateKey = computed(() => JSON.stringify([this.runId(), this.hitl()?.decision_id]));
  readonly debug = input<RunDebugPayload | null>(null);
  readonly hitlResolving = input(false);
  readonly debugStepping = input(false);
  readonly debugModeLabel = input<DebugMode>('off');

  readonly resolveHitl = output<{ action: 'accept' | 'reject'; label_review?: LabelReviewSubmission }>();
  readonly debugAction = output<'step' | 'continue' | 'stop'>();
  readonly clear = output<void>();
  readonly close = output<void>();

  private readonly body = viewChild<ElementRef<HTMLDivElement>>('body');

  constructor() {
    effect(() => { this.gateKey(); this.labelReview.set(null); });
    // Keep the newest line in view as the log grows.
    effect(() => {
      this.entries();
      const el = this.body()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
  }

  protected resolve(action: 'accept' | 'reject'): void {
    if (this.hitlResolving()) return;
    const label_review = this.labelReview();
    if (action === 'accept' && this.hitl()?.prompt_kind === 'review_dataset_labels') {
      if (!label_review) return;
      this.resolveHitl.emit({ action, label_review });
    } else this.resolveHitl.emit({ action });
  }

  protected statusLabel(): string {
    return this.i18n.t(`flow.terminal.status.${this.status()}`);
  }

  protected previewJson(value: unknown): string {
    if (value === undefined || value === null) return this.i18n.t('flow.terminal.no_data');
    try {
      const json = JSON.stringify(value, null, 2);
      return json.length > 1400 ? json.slice(0, 1400) + '\n… (truncated)' : json;
    } catch {
      return String(value);
    }
  }

  /** Compact remaining-time label for gate TTL (e.g. ``2d 4h``, ``45m``). */
  protected formatRemaining(seconds: number | null | undefined): string {
    if (seconds == null || !Number.isFinite(seconds)) return '—';
    const s = Math.max(0, Math.floor(seconds));
    if (s < 60) return `${s}s`;
    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    const mins = Math.floor((s % 3600) / 60);
    if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
    if (hours > 0) return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
    return `${mins}m`;
  }
}
