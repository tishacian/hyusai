/**
 * `<app-flow-terminal>` — the execution terminal (presentational only).
 *
 * Restored from the deleted `flow-terminal.component.ts`, re-skinned to the
 * `--ck-*` token system and split clean from any orchestration: it renders the
 * live run log, the HITL approval card (`hitl_pending` → Accept / Reject) and
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
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import type {
  RunDebugPayload,
  RunHitlPayload,
} from '@app/core/canonical-api.service';
import type { DebugMode, RunLogEntry, RunUiStatus } from './flow-run.types';

@Component({
  selector: 'app-flow-terminal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  styleUrl: './flow-terminal.component.scss',
  template: `
    <section class="ck-term" aria-label="Execution terminal">
      <header class="ck-term__head">
        <span class="ck-term__eyebrow">
          <app-icon name="terminal" [size]="12" />
          Execution terminal
        </span>
        <span class="ck-term__status" [attr.data-status]="status()">{{ statusLabel() }}</span>
        <span class="ck-term__spacer"></span>
        @if (entries().length > 0) {
          <span class="ck-term__count">{{ entries().length }} lines</span>
        }
        <button
          type="button"
          class="ck-term__tool"
          (click)="clear.emit()"
          title="Clear log"
          aria-label="Clear log"
        >
          Clear
        </button>
        <button
          type="button"
          class="ck-term__tool ck-term__tool--icon"
          (click)="close.emit()"
          title="Collapse terminal"
          aria-label="Collapse terminal"
        >
          <app-icon name="chevron-down" [size]="14" />
        </button>
      </header>

      <div class="ck-term__body" #body>
        @if (hitl(); as h) {
          <div class="ck-term__card" data-tone="hitl" role="alertdialog" aria-label="Human approval required">
            <div class="ck-term__card-head">
              <app-icon name="user-check" [size]="14" />
              <span>Human approval required</span>
              <span class="ck-term__pill" data-tone="warn">PAUSED</span>
            </div>
            <p class="ck-term__card-prompt">
              {{ h.prompt || 'An operator must approve this step to continue.' }}
            </p>
            @if (h.node_id) {
              <div class="ck-term__card-meta">
                <span>Node</span><code>{{ h.node_id }}</code>
              </div>
            }
            @if (h.expires_at || (h.inbox_count ?? 0) > 0 || h.memory) {
              <div class="ck-term__card-meta" data-tone="gate-ttl">
                @if (h.seconds_remaining != null) {
                  <span>TTL</span>
                  <code>{{ formatRemaining(h.seconds_remaining) }}</code>
                  @if (h.expiry_action) {
                    <span class="ck-term__pill" data-tone="warn">{{ h.expiry_action }}</span>
                  }
                }
                @if ((h.inbox_count ?? 0) > 0) {
                  <span>Buffered</span>
                  <code>{{ h.inbox_count }} txn{{ h.inbox_count === 1 ? '' : 's' }}</code>
                }
                @if (h.memory; as mem) {
                  @if (mem.event_count) {
                    <span>Memory</span>
                    <code>v{{ mem.version ?? 1 }} · {{ mem.event_count }} evt</code>
                  }
                }
              </div>
            }
            <div class="ck-term__actions">
              <button
                type="button"
                class="ck-term__btn ck-term__btn--reject"
                [disabled]="hitlResolving()"
                (click)="resolveHitl.emit('reject')"
              >
                <app-icon name="x" [size]="12" /> Reject
              </button>
              <button
                type="button"
                class="ck-term__btn ck-term__btn--accept"
                [disabled]="hitlResolving()"
                (click)="resolveHitl.emit('accept')"
              >
                <app-icon name="check" [size]="12" /> Approve
              </button>
            </div>
          </div>
        }

        @if (debug(); as d) {
          <div class="ck-term__card" data-tone="debug" role="alertdialog" aria-label="Debugger paused">
            <div class="ck-term__card-head">
              <app-icon name="bug" [size]="14" />
              <span>Debugger paused</span>
              <span class="ck-term__pill" data-tone="cool">{{ d.debug_mode || 'step' }}</span>
            </div>
            <p class="ck-term__card-prompt">
              Paused after <code>{{ d.node_id || 'node' }}</code> — inspect context and advance.
            </p>
            <div class="ck-term__snap">
              <span class="ck-term__snap-label">Last output</span>
              <pre class="ck-term__snap-body">{{ previewJson(d.last_output) }}</pre>
              <span class="ck-term__snap-label">Context snapshot</span>
              <pre class="ck-term__snap-body">{{ previewJson(d.ctx_snapshot) }}</pre>
            </div>
            <div class="ck-term__actions">
              <button
                type="button"
                class="ck-term__btn ck-term__btn--reject"
                [disabled]="debugStepping()"
                (click)="debugAction.emit('stop')"
              >
                <app-icon name="square" [size]="12" /> Stop
              </button>
              <button
                type="button"
                class="ck-term__btn"
                [disabled]="debugStepping()"
                (click)="debugAction.emit('continue')"
              >
                <app-icon name="play" [size]="12" /> Continue
              </button>
              <button
                type="button"
                class="ck-term__btn ck-term__btn--accept"
                [disabled]="debugStepping()"
                (click)="debugAction.emit('step')"
              >
                <app-icon name="chevron-right" [size]="12" /> Step
              </button>
            </div>
          </div>
        }

        @if (entries().length === 0 && !hitl() && !debug()) {
          <div class="ck-term__empty">
            <span class="ck-term__caret">›</span>
            Simulate for a client-side dry run, or Execute to run on the backend and stream live output here.
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
  readonly entries = input<RunLogEntry[]>([]);
  readonly status = input<RunUiStatus>('idle');
  readonly hitl = input<RunHitlPayload | null>(null);
  readonly debug = input<RunDebugPayload | null>(null);
  readonly hitlResolving = input(false);
  readonly debugStepping = input(false);
  readonly debugModeLabel = input<DebugMode>('off');

  readonly resolveHitl = output<'accept' | 'reject'>();
  readonly debugAction = output<'step' | 'continue' | 'stop'>();
  readonly clear = output<void>();
  readonly close = output<void>();

  private readonly body = viewChild<ElementRef<HTMLDivElement>>('body');

  constructor() {
    // Keep the newest line in view as the log grows.
    effect(() => {
      this.entries();
      const el = this.body()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
  }

  protected statusLabel(): string {
    switch (this.status()) {
      case 'running':
        return 'Running';
      case 'paused':
        return 'Paused';
      case 'done':
        return 'Done';
      case 'error':
        return 'Error';
      default:
        return 'Idle';
    }
  }

  protected previewJson(value: unknown): string {
    if (value === undefined || value === null) return '— no data —';
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
