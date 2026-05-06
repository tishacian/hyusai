import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import type { Run } from '@app/core/canonical-api.service';
import type { TerminalEntry } from './workflow-editor.component';

@Component({
  selector: 'app-flow-terminal',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="df-terminal">
      <div class="df-terminal-head">
        <span class="ck-mono text-[9px] uppercase tracking-[0.14em] text-gray-400">Execution terminal</span>
        <div class="flex items-center gap-2">
          @if (entries.length > 0) {
            <span class="df-tag df-tag-cool">{{ entries.length }} LINES</span>
          }
          <button (click)="clear.emit()" class="text-[10px] text-gray-500 hover:text-gray-300 ck-mono" title="Clear log">
            CLEAR
          </button>
          <button (click)="collapse.emit()" class="df-tool-btn df-tool-btn--small" title="Collapse">
            <app-icon name="chevron-down" [size]="12" />
          </button>
        </div>
      </div>
      <div class="df-terminal-body ck-mono">
        @if (run?.status === 'hitl_pending' && run?.hitl) {
          <div class="df-hitl-card" role="alertdialog">
            <div class="df-hitl-head">
              <app-icon name="user-check" [size]="14" class="text-amber-300" />
              <span>Human approval required</span>
              <span class="df-tag df-tag-warn">PAUSED</span>
            </div>
            <div class="df-hitl-prompt">{{ run?.hitl?.prompt ?? 'An operator must approve this step to continue.' }}</div>
            @if (run?.hitl?.node_id) {
              <div class="df-hitl-meta">
                <span class="text-gray-500">Node</span>
                <span class="text-gray-300 ck-mono">{{ run?.hitl?.node_id }}</span>
              </div>
            }
            <div class="df-hitl-actions">
              <button
                type="button"
                (click)="resolveHitl.emit('reject')"
                [disabled]="hitlResolving"
                class="df-hitl-btn df-hitl-btn--reject"
              >
                <app-icon name="x" [size]="12" /> Reject
              </button>
              <button
                type="button"
                (click)="resolveHitl.emit('accept')"
                [disabled]="hitlResolving"
                class="df-hitl-btn df-hitl-btn--accept"
              >
                <app-icon name="check" [size]="12" /> Approve
              </button>
            </div>
          </div>
        }

        @if (run?.status === 'debug_pending' && run?.debug) {
          <div class="df-hitl-card" role="alertdialog" data-tone="debug">
            <div class="df-hitl-head">
              <app-icon name="bug" [size]="14" class="text-cyan-300" />
              <span>Debugger paused</span>
              <span class="df-tag df-tag-cool">{{ run?.debug?.debug_mode ?? 'step' }}</span>
            </div>
            <div class="df-hitl-prompt">
              Paused after
              <span class="ck-mono text-cyan-200">{{ run?.debug?.node_id ?? 'node' }}</span>
              — inspect context and advance.
            </div>
            <div class="df-debug-ctx">
              <div class="df-debug-ctx-label">Last output</div>
              <pre class="df-debug-ctx-body">{{ previewJson(run?.debug?.last_output) }}</pre>
              <div class="df-debug-ctx-label">Context snapshot</div>
              <pre class="df-debug-ctx-body">{{ previewJson(run?.debug?.ctx_snapshot) }}</pre>
            </div>
            <div class="df-hitl-actions">
              <button
                type="button"
                (click)="debugAction.emit('stop')"
                [disabled]="debugStepping"
                class="df-hitl-btn df-hitl-btn--reject"
              >
                <app-icon name="square" [size]="12" /> Stop
              </button>
              <button
                type="button"
                (click)="debugAction.emit('continue')"
                [disabled]="debugStepping"
                class="df-hitl-btn"
              >
                <app-icon name="chevrons-right" [size]="12" /> Continue
              </button>
              <button
                type="button"
                (click)="debugAction.emit('step')"
                [disabled]="debugStepping"
                class="df-hitl-btn df-hitl-btn--accept"
              >
                <app-icon name="chevron-right" [size]="12" /> Step
              </button>
            </div>
          </div>
        }

        @if (entries.length === 0 && run?.status !== 'hitl_pending' && run?.status !== 'debug_pending') {
          <div class="df-terminal-empty">
            <span class="text-gray-500">›</span>
            Execute a Run on this System to see live output. Click Simulate for a client-side dry run, or Execute to hit the backend.
          </div>
        }
        @for (entry of entries; track entry.id) {
          <div class="df-terminal-row">
            <span class="df-terminal-time">{{ entry.t }}</span>
            <span class="df-terminal-tag" [attr.data-tone]="entry.tone">[{{ entry.tag }}]</span>
            <span class="df-terminal-text">{{ entry.text }}</span>
          </div>
        }
      </div>
    </div>
  `,
})
export class FlowTerminalComponent {
  @Input() entries: TerminalEntry[] = [];
  @Input() run: Run | null = null;
  @Input() hitlResolving = false;
  @Input() debugStepping = false;

  @Output() clear = new EventEmitter<void>();
  @Output() collapse = new EventEmitter<void>();
  @Output() resolveHitl = new EventEmitter<'accept' | 'reject'>();
  @Output() debugAction = new EventEmitter<'step' | 'continue' | 'stop'>();

  previewJson(value: unknown): string {
    if (value == null) return '{}';
    try {
      return JSON.stringify(value, null, 2).slice(0, 2000);
    } catch {
      return String(value);
    }
  }
}
