import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
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
          <app-icon name="waves" [size]="13" class="text-brand-300" />
          Voice runtime
          <span
            class="control-info-dot"
            title="Select the voice runtime used for speech-to-text and voice session events."
          >
            <app-icon name="info" [size]="10" />
          </span>
        </span>
        <div class="voice-select-wrap" [title]="selectedRuntimeDescription">
          <select
            class="voice-select"
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
          title="Record one audio segment, then transcribe through the batch voice endpoint."
        >
          Batch
        </button>
        <button
          type="button"
          class="voice-transport-button"
          [class.voice-transport-active]="transport === 'backend_ws'"
          [disabled]="!canUseSession"
          (click)="transportChange.emit('backend_ws')"
          [title]="sessionButtonTitle"
        >
          Session loop
        </button>
        <button
          type="button"
          class="voice-transport-button"
          disabled
          [title]="realtimeBlockedHint || 'Realtime voice uses WebRTC and is enabled only when the workspace/provider lane is ready.'"
        >
          Realtime
        </button>
      </div>

      @if (transport === 'backend_ws') {
        <div class="voice-loop-actions" title="Start or pause a hands-free Agentium voice session. The microphone rearms after the spoken answer.">
          @if (!conversationActive) {
            <button
              type="button"
              class="voice-loop-button voice-loop-start"
              [disabled]="!canUseSession || streaming || transcribing"
              (click)="startConversation.emit()"
            >
              <app-icon name="play" [size]="12" />
              Start conversation
            </button>
          } @else {
            <button
              type="button"
              class="voice-loop-button"
              [disabled]="transcribing"
              (click)="conversationPaused ? resumeConversation.emit() : pauseConversation.emit()"
            >
              <app-icon [name]="conversationPaused ? 'play' : 'pause'" [size]="12" />
              {{ conversationPaused ? 'Resume' : 'Pause' }}
            </button>
            <button
              type="button"
              class="voice-loop-button voice-loop-stop"
              (click)="stopConversation.emit()"
            >
              <app-icon name="square" [size]="12" />
              Stop
            </button>
          }
        </div>
      }

      @if (realtimeBlockedHint) {
        <span class="voice-warning-pill" [title]="realtimeBlockedHint">
          <app-icon name="radio" [size]="12" />
          WebRTC required
        </span>
      }

      <span class="tandem-oracle-pill" [title]="tandemOracleHint">
        <app-icon name="activity" [size]="12" />
        Tandem oracle
        <span
          class="control-info-dot"
          title="Fast voice loop plus background Knowledge oracle. It can update context while the conversation continues."
        >
          <app-icon name="info" [size]="10" />
        </span>
      </span>

      <label
        class="voice-checkbox"
        title="When enabled, the final voice transcript replaces the current draft and is sent as one chat turn."
      >
        <input
          type="checkbox"
          class="accent-brand-500"
          [ngModel]="autoSend"
          (ngModelChange)="autoSendChange.emit($event)"
          [disabled]="!canTranscribe"
        />
        Auto-send final transcript
      </label>

      @if (transport === 'backend_ws') {
        <label
          class="voice-checkbox"
          title="When enabled, Agentium ends the current voice turn after speech followed by a short silence."
        >
          <input
            type="checkbox"
            class="accent-brand-500"
            [ngModel]="autoEndpoint"
            (ngModelChange)="autoEndpointChange.emit($event)"
            [disabled]="!canUseSession"
          />
          Auto endpoint
        </label>
      }

      <span [class]="statusClass">{{ statusLabel }}</span>
      <span class="text-gray-600">·</span>
      <span class="truncate max-w-[36rem]" [title]="runtimeDetail">{{ runtimeDetail }}</span>
      @if (partial) {
        <span class="text-brand-200 truncate max-w-xs">“{{ partial }}”</span>
      }
    </div>

    @if (transport === 'backend_ws') {
      <div class="voice-oracle-panel" [title]="oraclePanelHint">
        <div class="voice-oracle-copy">
          <span class="voice-oracle-kicker">Agentium voice session</span>
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
      font: 700 10px/1.2 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.12em;
      text-transform: uppercase;
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
  `],
})
export class VoiceControlsComponent {
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
}
