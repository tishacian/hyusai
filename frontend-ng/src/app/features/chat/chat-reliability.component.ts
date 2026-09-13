/**
 * The two surfaces that tell a non-technical user whether the assistant can
 * answer, and what to do when it cannot.
 *
 * Both are presentational: they take a state and emit intent. The panel owns
 * loading, retrying and navigation, so these can be reasoned about — and
 * tested — without the 8k-line chat component around them.
 *
 * `ChatReadinessBannerComponent` sits above the composer in Quick Ask. It is
 * deliberately quiet when everything works: one line, no card, no badge. It
 * only grows into an actionable block when the selected model needs setup or
 * is down.
 *
 * `ChatErrorCardComponent` replaces the old habit of appending `⚠ <message>`
 * to the answer buffer. A failed turn is not prose, it is a state with two
 * possible moves (retry, fix settings), and any partial answer that did arrive
 * stays visibly separate from it.
 */
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { failureCopyKey } from '@app/features/resources/model-plane.types';
import type { ChatStreamError, ModelReadiness } from '@app/features/resources/model-plane.types';

/**
 * Navigation remains an emitted intent so the parent can preserve the current
 * question and return location before opening model setup.
 */
@Component({
  selector: 'app-chat-readiness-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    @if (loading()) {
      <div class="rd-line" role="status" aria-live="polite">
        <app-icon name="loader-2" [size]="12" class="animate-spin rd-muted-icon" />
        <span class="rd-muted">{{ i18n.t('chat.readiness.checking') }}</span>
      </div>
    } @else if (readiness(); as state) {
      @if (state.status === 'ready') {
        <div class="rd-line" role="status" aria-live="polite">
          <app-icon name="check-circle" [size]="12" class="rd-ok-icon" />
          <span class="rd-ok">{{ i18n.t('chat.readiness.ready') }}</span>
          <span class="rd-muted rd-detail">{{ readyDetail() }}</span>
        </div>
      } @else {
        <div class="rd-card" [class.rd-card-setup]="state.status === 'needs_setup'" role="status" aria-live="polite">
          <app-icon name="alert-triangle" [size]="14" class="rd-warn-icon" />
          <div class="rd-copy">
            <span class="rd-title">{{ headline() }}</span>
            <span class="rd-message">{{ message() }}</span>
          </div>
          <div class="rd-actions">
            @if (state.status === 'unavailable') {
              <button type="button" class="rd-btn rd-btn-primary" (click)="retry.emit()">
                <app-icon name="refresh-cw" [size]="12" />
                {{ i18n.t('chat.readiness.retry') }}
              </button>
              <button type="button" class="rd-btn" (click)="configure.emit()">
                <app-icon name="settings" [size]="12" />
                {{ i18n.t('chat.readiness.settings') }}
              </button>
            } @else {
              <button type="button" class="rd-btn rd-btn-primary" (click)="configure.emit()">
                <app-icon name="settings" [size]="12" />
                {{ i18n.t('chat.readiness.configure') }}
              </button>
            }
          </div>
          <details class="rd-diagnostics">
            <summary>{{ i18n.t('chat.failure.technical_details') }}</summary>
            <span>{{ state.reason }} · {{ state.provider }} · {{ state.model }}</span>
          </details>
        </div>
      }
    }
  `,
  styles: [`
    :host { display: block; }
    .rd-line {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px 0;
      font-size: 11px;
      min-width: 0;
    }
    .rd-muted { color: var(--ck-fg-4); }
    .rd-muted-icon { color: var(--ck-fg-4); }
    .rd-ok { color: var(--ck-fg-3); font-weight: 600; }
    .rd-ok-icon { color: var(--ck-signal-pos, #34d399); }
    .rd-detail {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .rd-card {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      margin: 8px 14px 0;
      padding: 10px 12px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 10px;
      background: var(--ck-bg-inset, rgba(255, 255, 255, 0.03));
    }
    .rd-card-setup { border-color: var(--ck-stroke-1, var(--ck-stroke-2)); }
    .rd-warn-icon { color: var(--ck-signal-warn, #f59e0b); flex: 0 0 auto; margin-top: 1px; }
    .rd-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 auto; }
    .rd-title { color: var(--ck-fg-1); font-size: 12px; font-weight: 650; }
    .rd-message { color: var(--ck-fg-3); font-size: 11.5px; line-height: 1.45; }
    .rd-actions { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; flex-wrap: wrap; }
    .rd-diagnostics { width: 100%; color: var(--ck-fg-4); font: 10px/1.5 var(--ck-font-mono, ui-monospace, monospace); }
    .rd-diagnostics summary { cursor: pointer; }
    .rd-diagnostics span { display: block; margin-top: 4px; }
    .rd-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 8px;
      border: 1px solid var(--ck-stroke-2);
      background: transparent;
      color: var(--ck-fg-2);
      font-size: 11.5px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      transition: 120ms ease;
    }
    .rd-btn:hover { border-color: var(--ck-stroke-1, var(--ck-stroke-2)); color: var(--ck-fg-1); }
    .rd-btn-primary {
      border-color: transparent;
      background: var(--ck-signal-cool, #22d3ee);
      color: #04121a;
    }
    .rd-btn-primary:hover { background: var(--ck-signal-cool, #22d3ee); color: #04121a; filter: brightness(1.06); }
    @media (max-width: 640px) {
      .rd-card { flex-wrap: wrap; }
      .rd-actions { width: 100%; }
    }
  `],
})
export class ChatReadinessBannerComponent {
  readonly i18n = inject(I18nService);

  readonly readiness = input<ModelReadiness | null>(null);
  readonly loading = input(false);

  readonly retry = output<void>();
  readonly configure = output<void>();

  protected readonly headline = computed(() => {
    const status = this.readiness()?.status;
    return status === 'needs_setup'
      ? this.i18n.t('chat.readiness.needs_setup')
      : this.i18n.t('chat.readiness.unavailable');
  });

  /** Render local product copy from the stable reason code. */
  protected readonly message = computed(() => {
    const state = this.readiness();
    return this.i18n.t(failureCopyKey(state?.reason));
  });

  protected readonly readyDetail = computed(() => {
    const model = this.readiness()?.model?.trim();
    if (!model) return '';
    return this.i18n.t('chat.readiness.ready_detail', { model });
  });
}

@Component({
  selector: 'app-chat-error-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="ec-card" role="alert">
      <div class="ec-head">
        <app-icon name="alert-triangle" [size]="14" class="ec-icon" />
        <span class="ec-title">{{ i18n.t('chat.failure.title') }}</span>
      </div>
      <p class="ec-message">{{ message() }}</p>
      @if (partialAnswer()) {
        <div class="ec-partial">
          <span class="ec-partial-label">{{ i18n.t('chat.failure.partial_answer') }}</span>
          <span class="ec-partial-text">{{ partialAnswer() }}</span>
        </div>
      }
      <div class="ec-actions">
        @if (canRetry()) {
          <button type="button" class="ec-btn ec-btn-primary" (click)="retry.emit()">
            <app-icon name="refresh-cw" [size]="12" />
            {{ i18n.t('chat.failure.retry') }}
          </button>
        }
        @if (needsSetup()) {
          <button type="button" class="ec-btn" [class.ec-btn-primary]="!canRetry()" (click)="configure.emit()">
            <app-icon name="settings" [size]="12" />
            {{ i18n.t('chat.failure.settings') }}
          </button>
        }
      </div>
      <details class="ec-diagnostics">
        <summary>{{ i18n.t('chat.failure.technical_details') }}</summary>
        <span>{{ error()?.code || 'generation_failed' }}</span>
      </details>
    </div>
  `,
  styles: [`
    :host { display: block; }
    .ec-card {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-width: 85%;
      padding: 12px 14px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 14px;
      border-bottom-left-radius: 4px;
      background: var(--ck-bg-inset, rgba(255, 255, 255, 0.03));
    }
    .ec-head { display: flex; align-items: center; gap: 8px; }
    .ec-icon { color: var(--ck-signal-warn, #f59e0b); flex: 0 0 auto; }
    .ec-title { color: var(--ck-fg-1); font-size: 12.5px; font-weight: 650; }
    .ec-message { margin: 0; color: var(--ck-fg-3); font-size: 12.5px; line-height: 1.5; }
    .ec-partial {
      display: flex;
      flex-direction: column;
      gap: 3px;
      padding: 8px 10px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 8px;
      background: var(--ck-tint-faint, rgba(255, 255, 255, 0.02));
    }
    .ec-partial-label {
      color: var(--ck-fg-4);
      font-family: var(--ck-font-mono, ui-monospace, monospace);
      font-size: 9.5px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .ec-partial-text {
      color: var(--ck-fg-2);
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .ec-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .ec-diagnostics { color: var(--ck-fg-4); font: 10px/1.5 var(--ck-font-mono, ui-monospace, monospace); }
    .ec-diagnostics summary { cursor: pointer; }
    .ec-diagnostics span { display: block; margin-top: 4px; }
    .ec-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 8px;
      border: 1px solid var(--ck-stroke-2);
      background: transparent;
      color: var(--ck-fg-2);
      font-size: 11.5px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      transition: 120ms ease;
    }
    .ec-btn:hover { border-color: var(--ck-stroke-1, var(--ck-stroke-2)); color: var(--ck-fg-1); }
    .ec-btn-primary {
      border-color: transparent;
      background: var(--ck-signal-cool, #22d3ee);
      color: #04121a;
    }
    .ec-btn-primary:hover { filter: brightness(1.06); }
    @media (max-width: 640px) {
      .ec-card { max-width: 100%; }
    }
  `],
})
export class ChatErrorCardComponent {
  readonly i18n = inject(I18nService);

  /** The structured failure, or `null` for a transport/legacy error. */
  readonly error = input<ChatStreamError | null>(null);
  /** Whatever the model had already streamed, kept out of the error copy. */
  readonly partialAnswer = input<string>('');

  readonly retry = output<void>();
  readonly configure = output<void>();

  /** A legacy or transport error carries no classification — always retryable. */
  protected readonly canRetry = computed(() => this.error()?.retryable ?? true);
  protected readonly needsSetup = computed(() => this.error()?.needsSetup ?? false);

  protected readonly message = computed(() => {
    const failure = this.error();
    if (!failure) return this.i18n.t('chat.failure.generic');
    return this.i18n.t(failureCopyKey(failure.code));
  });
}
