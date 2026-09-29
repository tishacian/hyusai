import { Component, EventEmitter, Input, Output, inject } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { FormsModule } from '@angular/forms';
import { VoiceCaptureMode } from '@app/core/voice-capture-config';
import { IconComponent } from '@app/shared/ui/icon.component';

export type SharedVoiceTransportChoice = 'batch_http' | 'backend_ws';

export interface SharedVoiceRuntimeOption {
  slug: string;
  label: string;
  disabled?: boolean;
}

export interface SharedVoiceOracleStep {
  stage: string;
  label: string;
  icon: string;
  detail: string;
  state: 'active' | 'done' | 'pending' | 'error';
}

@Component({
  selector: 'app-voice-controls',
  standalone: true,
  imports: [FormsModule, IconComponent],
  template: `
    <div class="voice-control-bar">
      <div class="voice-control-group">
        <span class="voice-control-label">
          <app-icon name="waves" [size]="13" class="text-cyan-300" />
          {{ i18n.t('chat.voice.controls.runtime') }}
          <span
            class="control-info-dot"
            [title]="i18n.t('chat.voice.controls.runtime_hint')"
          >
            <app-icon name="info" [size]="10" />
          </span>
        </span>
        <div class="voice-select-wrap" [title]="selectedRuntimeDescription">
          <select
            class="voice-select"
            [attr.aria-label]="i18n.t('chat.voice.controls.runtime')"
            [ngModel]="provider"
            (ngModelChange)="providerChange.emit($event)"
          >
            @for (runtime of runtimeOptions; track runtime.slug) {
              <option [value]="runtime.slug" [disabled]="runtime.disabled">
                {{ runtime.label }}
              </option>
            }
          </select>
          <app-icon name="chevron-down" [size]="12" class="voice-select-chevron" />
        </div>
      </div>

      <div class="voice-transport-toggle" [title]="transportHint">
        <button
          type="button"
          class="voice-transport-button"
          [class.voice-transport-active]="transport === 'batch_http'"
          (click)="transportChange.emit('batch_http')"
          [attr.aria-pressed]="transport === 'batch_http'"
          [title]="i18n.t('chat.voice.controls.batch_hint')"
        >
          {{ i18n.t('chat.voice.controls.batch') }}
        </button>
        <button
          type="button"
          class="voice-transport-button"
          [class.voice-transport-active]="transport === 'backend_ws'"
          [disabled]="!canUseSession"
          (click)="transportChange.emit('backend_ws')"
          [attr.aria-pressed]="transport === 'backend_ws'"
          [title]="sessionButtonTitle"
        >
          {{ i18n.t('chat.voice.controls.conversation') }}
        </button>
        <button
          type="button"
          class="voice-transport-button"
          disabled
          [title]="realtimeBlockedHint || i18n.t('chat.voice.controls.realtime_hint')"
        >
          {{ i18n.t('chat.voice.controls.realtime') }}
        </button>
      </div>

      <div class="voice-control-group">
        <span class="voice-control-label">
          <app-icon name="shield-check" [size]="13" class="text-emerald-300" />
          {{ i18n.t('chat.voice.controls.capture') }}
        </span>
        <div class="voice-select-wrap voice-capture-select-wrap" [title]="captureModeHint">
          <select
            class="voice-select"
            [attr.aria-label]="i18n.t('chat.voice.controls.capture')"
            [ngModel]="captureMode"
            (ngModelChange)="captureModeChange.emit($event)"
          >
            <option value="normal">{{ i18n.t('chat.voice.controls.capture_normal') }}</option>
            <option value="robust">{{ i18n.t('chat.voice.controls.capture_robust') }}</option>
            <option value="manual_safe">{{ i18n.t('chat.voice.controls.capture_manual') }}</option>
          </select>
          <app-icon name="chevron-down" [size]="12" class="voice-select-chevron" />
        </div>
      </div>

      @if (transport === 'backend_ws') {
        <div class="voice-loop-actions" [title]="i18n.t('chat.voice.controls.loop_hint')">
          @if (!conversationActive) {
            <button
              type="button"
              class="voice-loop-button voice-loop-start"
              [disabled]="!canUseSession || streaming || transcribing"
              (click)="startConversation.emit()"
            >
              <app-icon name="play" [size]="12" />
              {{ i18n.t('chat.voice.controls.start') }}
            </button>
          } @else {
            <button
              type="button"
              class="voice-loop-button"
              [disabled]="transcribing"
              (click)="conversationPaused ? resumeConversation.emit() : pauseConversation.emit()"
            >
              <app-icon [name]="conversationPaused ? 'play' : 'pause'" [size]="12" />
              {{ i18n.t(conversationPaused ? 'chat.voice.controls.resume' : 'chat.voice.controls.pause') }}
            </button>
            <button
              type="button"
              class="voice-loop-button voice-loop-stop"
              (click)="stopConversation.emit()"
            >
              <app-icon name="square" [size]="12" />
              {{ i18n.t('chat.voice.controls.stop') }}
            </button>
          }
        </div>
      }

      @if (realtimeBlockedHint) {
        <span class="voice-warning-pill" [title]="realtimeBlockedHint">
          <app-icon name="radio" [size]="12" />
          {{ i18n.t('chat.voice.controls.webrtc_required') }}
        </span>
      }

      <span class="tandem-oracle-pill" [title]="tandemOracleHint">
        <app-icon name="activity" [size]="12" />
        {{ i18n.t('chat.voice.controls.live_context') }}
        <span
          class="control-info-dot"
          [title]="i18n.t('chat.voice.controls.live_context_hint')"
        >
          <app-icon name="info" [size]="10" />
        </span>
      </span>

      <label
        class="voice-checkbox"
        [title]="i18n.t('chat.voice.controls.auto_send_hint')"
      >
        <input
          type="checkbox"
          class="accent-cyan-500"
          [ngModel]="autoSend"
          (ngModelChange)="autoSendChange.emit($event)"
          [disabled]="!canTranscribe"
        />
        {{ i18n.t('chat.voice.controls.auto_send') }}
      </label>

      @if (transport === 'backend_ws') {
        <label
          class="voice-checkbox"
          [title]="i18n.t('chat.voice.controls.auto_endpoint_hint')"
        >
          <input
            type="checkbox"
            class="accent-cyan-500"
            [ngModel]="autoEndpoint"
            (ngModelChange)="autoEndpointChange.emit($event)"
            [disabled]="!canUseSession"
          />
          {{ i18n.t('chat.voice.controls.auto_endpoint') }}
        </label>
      }

      <span [class]="statusClass">{{ statusLabel }}</span>
      <span class="text-gray-600">·</span>
      <span class="truncate max-w-[36rem]" [title]="runtimeDetail">{{ runtimeDetail }}</span>
      @if (partial) {
        <span class="text-cyan-200 truncate max-w-xs">“{{ partial }}”</span>
      }
    </div>

    @if (transport === 'backend_ws') {
      <div class="voice-oracle-panel" [title]="oraclePanelHint">
        <div class="voice-oracle-copy">
          <span class="voice-oracle-kicker">{{ i18n.t('chat.voice.controls.session') }}</span>
          <span class="voice-oracle-message">{{ oracleMessage }}</span>
        </div>
        <div class="voice-oracle-steps">
          @for (step of oracleTimeline; track step.stage) {
            <span
              class="voice-oracle-step"
              [class.voice-oracle-step-active]="step.state === 'active'"
              [class.voice-oracle-step-done]="step.state === 'done'"
              [class.voice-oracle-step-error]="step.state === 'error'"
              [title]="step.detail"
            >
              <app-icon [name]="step.icon" [size]="11" />
              {{ step.label }}
            </span>
          }
        </div>
      </div>
    }
  `,
  styles: [`
    .control-info-dot {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      border-radius: 999px;
      color: rgba(177, 190, 210, 0.78);
      background: rgba(255, 255, 255, 0.055);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
      cursor: help;
    }
    .control-info-dot:hover {
      color: rgb(219, 249, 255);
      background: rgba(34, 211, 238, 0.13);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.25);
    }
    .voice-control-bar {
      display: flex;
      align-items: center;
      gap: 9px;
      flex-wrap: wrap;
      padding: 10px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(0, 0, 0, 0.15);
      color: rgba(177, 190, 210, 0.82);
      font-size: 11px;
    }
    .voice-control-group,
    .voice-control-label,
    .tandem-oracle-pill,
    .voice-warning-pill,
    .voice-checkbox {
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }
    .voice-control-label {
      color: rgba(232, 239, 250, 0.86);
      font-weight: 700;
    }
    .tandem-oracle-pill {
      min-height: 30px;
      padding: 5px 9px;
      border-radius: 12px;
      background: rgba(34, 211, 238, 0.10);
      color: rgb(207, 250, 254);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.20);
    }
    .voice-warning-pill {
      min-height: 30px;
      padding: 5px 9px;
      border-radius: 12px;
      background: rgba(245, 158, 11, 0.10);
      color: rgb(253, 230, 138);
      box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.22);
      font-weight: 750;
    }
    .voice-select-wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
      min-width: 176px;
      max-width: 260px;
    }
    .voice-capture-select-wrap {
      min-width: 120px;
    }
    .voice-select {
      width: 100%;
      -webkit-appearance: none;
      appearance: none;
      border: 0;
      outline: 0;
      border-radius: 8px;
      background: rgba(2, 8, 18, 0.38);
      color: rgba(245, 248, 252, 0.92);
      padding: 4px 24px 4px 9px;
      font: 600 11px/1.2 var(--ck-font-sans, ui-sans-serif, system-ui);
      color-scheme: dark;
    }
    .voice-select:focus {
      box-shadow: 0 0 0 1px rgba(103, 213, 246, 0.42);
      background: rgba(6, 13, 25, 0.76);
    }
    .voice-select-chevron {
      position: absolute;
      right: 7px;
      color: rgba(177, 190, 210, 0.72);
      pointer-events: none;
    }
    .voice-transport-toggle {
      display: inline-flex;
      overflow: hidden;
      border-radius: 12px;
      border: 1px solid rgba(148, 197, 229, 0.14);
      background: rgba(255, 255, 255, 0.035);
    }
    .voice-transport-button {
      padding: 6px 11px;
      color: rgba(177, 190, 210, 0.78);
      font-weight: 700;
      transition: 140ms ease;
    }
    .voice-transport-button:hover:not(:disabled) {
      color: rgba(245, 248, 252, 0.94);
      background: rgba(255, 255, 255, 0.06);
    }
    .voice-transport-button:disabled {
      opacity: 0.42;
      cursor: not-allowed;
    }
    .voice-transport-active {
      color: rgb(207, 250, 254);
      background: rgba(34, 211, 238, 0.14);
    }
    .voice-loop-actions {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px;
      border-radius: 12px;
      border: 1px solid rgba(148, 197, 229, 0.14);
      background: rgba(255, 255, 255, 0.035);
    }
    .voice-loop-button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      border-radius: 9px;
      padding: 5px 9px;
      color: rgba(232, 239, 250, 0.86);
      font-weight: 750;
      transition: 140ms ease;
    }
    .voice-loop-button:hover:not(:disabled) {
      background: rgba(255, 255, 255, 0.07);
      color: rgb(245, 248, 252);
    }
    .voice-loop-button:disabled {
      opacity: 0.48;
      cursor: not-allowed;
    }
    .voice-loop-start {
      background: rgba(16, 185, 129, 0.12);
      color: rgb(187, 247, 208);
      box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.20);
    }
    .voice-loop-stop {
      background: rgba(239, 68, 68, 0.10);
      color: rgb(254, 202, 202);
      box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.18);
    }
    .voice-checkbox {
      color: rgba(177, 190, 210, 0.84);
    }
    .voice-oracle-panel {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      background:
        linear-gradient(90deg, rgba(34, 211, 238, 0.055), transparent 42%),
        rgba(3, 8, 16, 0.30);
      color: rgba(177, 190, 210, 0.84);
      font-size: 11px;
    }
    .voice-oracle-copy {
      display: flex;
      align-items: baseline;
      gap: 9px;
      min-width: 0;
    }
    .voice-oracle-kicker {
      color: rgb(103, 213, 246);
      font-size: 12px;
      font-weight: 600;
      line-height: 1.2;
      white-space: nowrap;
    }
    .voice-oracle-message {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: rgba(232, 239, 250, 0.82);
    }
    .voice-oracle-steps {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .voice-oracle-step {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 24px;
      padding: 3px 7px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.035);
      color: rgba(177, 190, 210, 0.70);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
      white-space: nowrap;
    }
    .voice-oracle-step-active {
      background: rgba(34, 211, 238, 0.12);
      color: rgb(207, 250, 254);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.24);
    }
    .voice-oracle-step-done {
      background: rgba(16, 185, 129, 0.10);
      color: rgb(187, 247, 208);
      box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.18);
    }
    .voice-oracle-step-error {
      background: rgba(239, 68, 68, 0.10);
      color: rgb(254, 202, 202);
      box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.20);
    }
    @media (max-width: 900px) {
      .voice-oracle-panel {
        align-items: flex-start;
        flex-direction: column;
      }
      .voice-oracle-steps {
        justify-content: flex-start;
      }
    }

    /* ------------------------------------------------------------------
       Light theme. Everything above was authored dark-only: near-white
       text on translucent black slabs. On paper that is a grey smear with
       invisible labels.

       This has to live here, not in the host. chat-panel does carry
       host-context light rules for .voice-control-bar, but view
       encapsulation stamps them with chat-panel's own attribute, so they
       never match anything inside this component — they were dead the day
       they were written.

       The accent tints (cyan, emerald, amber at ~10 % alpha) hold up on
       both surfaces and stay as they are; only the neutral foregrounds
       and the black slabs need a counterpart.
       ------------------------------------------------------------------ */
    :host-context([data-theme="light"]) .voice-control-bar,
    :host-context([data-theme="light"]) .voice-oracle-panel {
      background: var(--ck-tint-faint);
      border-bottom-color: var(--ck-stroke-2);
      color: var(--ck-fg-3);
    }
    :host-context([data-theme="light"]) .voice-control-label,
    :host-context([data-theme="light"]) .voice-loop-button,
    :host-context([data-theme="light"]) .voice-oracle-message {
      color: var(--ck-fg-2);
    }
    :host-context([data-theme="light"]) .voice-checkbox,
    :host-context([data-theme="light"]) .voice-transport-button,
    :host-context([data-theme="light"]) .voice-select-chevron,
    :host-context([data-theme="light"]) .voice-oracle-step,
    :host-context([data-theme="light"]) .control-info-dot {
      color: var(--ck-fg-3);
    }
    :host-context([data-theme="light"]) .control-info-dot,
    :host-context([data-theme="light"]) .voice-transport-toggle,
    :host-context([data-theme="light"]) .voice-loop-actions,
    :host-context([data-theme="light"]) .voice-oracle-step {
      background: var(--ck-tint-soft);
      border-color: var(--ck-stroke-2);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-2);
    }
    :host-context([data-theme="light"]) .voice-select {
      background: var(--ck-bg-panel-hi);
      color: var(--ck-fg-1);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-2);
      color-scheme: light;
    }
    :host-context([data-theme="light"]) .voice-select:focus {
      background: var(--ck-bg-panel-hi);
      box-shadow: 0 0 0 1px var(--ck-stroke-hot);
    }
    :host-context([data-theme="light"]) .voice-transport-button:hover:not(:disabled),
    :host-context([data-theme="light"]) .voice-loop-button:hover:not(:disabled) {
      background: var(--ck-tint-soft);
      color: var(--ck-fg-1);
    }
    /* The saturated states keep their meaning, on the light signal tones. */
    /* The selected transport reads in body ink: the info tone on its own
       wash fell under 4.5:1 at 11 px (axe, light theme). */
    :host-context([data-theme="light"]) .voice-transport-active {
      color: var(--ck-fg-1);
      background: var(--ck-status-info-bg);
      box-shadow: inset 0 0 0 1px var(--ck-status-info-line);
    }
    :host-context([data-theme="light"]) .tandem-oracle-pill,
    :host-context([data-theme="light"]) .voice-oracle-step-active {
      color: var(--ck-status-info-fg);
      background: var(--ck-status-info-bg);
      box-shadow: inset 0 0 0 1px var(--ck-status-info-line);
    }
    :host-context([data-theme="light"]) .voice-warning-pill {
      color: var(--ck-status-warn-fg);
      background: var(--ck-status-warn-bg);
      box-shadow: inset 0 0 0 1px var(--ck-status-warn-line);
    }
    :host-context([data-theme="light"]) .voice-loop-start,
    :host-context([data-theme="light"]) .voice-oracle-step-done {
      color: var(--ck-status-ok-fg);
      background: var(--ck-status-ok-bg);
      box-shadow: inset 0 0 0 1px var(--ck-status-ok-line);
    }
    :host-context([data-theme="light"]) .voice-loop-stop,
    :host-context([data-theme="light"]) .voice-oracle-step-error {
      color: var(--ck-status-neg-fg);
      background: var(--ck-status-neg-bg);
      box-shadow: inset 0 0 0 1px var(--ck-status-neg-line);
    }
    :host-context([data-theme="light"]) .voice-oracle-kicker {
      color: var(--ck-status-info-fg);
    }
  `],
})
export class VoiceControlsComponent {
  /** Every label and hint comes from `chat.voice.controls.*` (FR + EN). */
  protected readonly i18n = inject(I18nService);
  @Input() runtimeOptions: SharedVoiceRuntimeOption[] = [];
  @Input() provider = 'cascade_openai';
  @Input() selectedRuntimeDescription = '';
  @Input() transport: SharedVoiceTransportChoice = 'batch_http';
  @Input() transportHint = '';
  @Input() sessionButtonTitle = '';
  @Input() realtimeBlockedHint: string | null = null;
  @Input() canUseSession = false;
  @Input() canTranscribe = false;
  @Input() streaming = false;
  @Input() transcribing = false;
  @Input() conversationActive = false;
  @Input() conversationPaused = false;
  @Input() tandemOracleHint = '';
  @Input() autoSend = false;
  @Input() autoEndpoint = true;
  @Input() captureMode: VoiceCaptureMode = 'normal';
  @Input() captureModeHint = '';
  @Input() statusClass = '';
  @Input() statusLabel = '';
  @Input() runtimeDetail = '';
  @Input() partial = '';
  @Input() oraclePanelHint = '';
  @Input() oracleMessage = '';
  @Input() oracleTimeline: SharedVoiceOracleStep[] = [];

  @Output() providerChange = new EventEmitter<string>();
  @Output() transportChange = new EventEmitter<SharedVoiceTransportChoice>();
  @Output() startConversation = new EventEmitter<void>();
  @Output() pauseConversation = new EventEmitter<void>();
  @Output() resumeConversation = new EventEmitter<void>();
  @Output() stopConversation = new EventEmitter<void>();
  @Output() autoSendChange = new EventEmitter<boolean>();
  @Output() autoEndpointChange = new EventEmitter<boolean>();
  @Output() captureModeChange = new EventEmitter<VoiceCaptureMode>();
}
