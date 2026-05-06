import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';

@Component({
  selector: 'app-flow-canvas-toolbar',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="absolute inset-x-0 top-0 z-10 px-3 py-2 flex items-center justify-between bg-black/30 backdrop-blur-sm border-b border-white/5">
      <div class="flex items-center gap-3">
        <span class="ck-mono text-[9px] uppercase tracking-[0.14em] text-gray-400">Flow canvas</span>
        @if (nodeCount > 0) {
          <div class="flex items-center gap-1.5">
            @if (errorCount > 0) {
              <span class="df-tag df-tag-neg" title="Validation errors">
                <app-icon name="alert-triangle" [size]="10" />
                {{ errorCount }} ERR
              </span>
            }
            @if (warnCount > 0) {
              <span class="df-tag df-tag-warn" title="Validation warnings">
                {{ warnCount }} WARN
              </span>
            }
            @if (errorCount === 0 && warnCount === 0) {
              <span class="df-tag df-tag-pos">
                <app-icon name="check" [size]="10" />
                VALID
              </span>
            }
          </div>
        }
      </div>
      <div class="flex items-center gap-1">
        <button (click)="zoom.emit('in')" class="df-tool-btn" title="Zoom in">
          <app-icon name="zoom-in" [size]="14" />
        </button>
        <button (click)="zoom.emit('out')" class="df-tool-btn" title="Zoom out">
          <app-icon name="zoom-out" [size]="14" />
        </button>
        <button (click)="zoomReset.emit()" class="df-tool-btn" title="Reset zoom">
          <app-icon name="maximize" [size]="14" />
        </button>
        <button (click)="fit.emit()" class="df-tool-btn df-tool-toggle" title="Fit all nodes in view">
          <app-icon name="maximize" [size]="14" />
          <span>Fit</span>
        </button>
        <span class="w-px h-4 bg-white/10 mx-1"></span>
        <button (click)="autoLayout.emit()" class="df-tool-btn" title="Auto-layout nodes">
          <app-icon name="layout-grid" [size]="14" />
        </button>
        <span class="w-px h-4 bg-white/10 mx-1"></span>
        <button
          (click)="toggleTerminal.emit()"
          class="df-tool-btn df-tool-toggle"
          [class.active]="terminalOpen"
          [attr.aria-expanded]="terminalOpen"
          title="Toggle execution terminal"
        >
          <app-icon name="terminal" [size]="14" />
          <span>Terminal {{ terminalOpen ? 'ON' : 'OFF' }}</span>
        </button>
        <button
          (click)="toggleInspector.emit()"
          class="df-tool-btn df-tool-toggle"
          [class.active]="inspectorOpen"
          [attr.aria-expanded]="inspectorOpen"
          title="Toggle node inspector"
        >
          <app-icon name="sidebar" [size]="14" />
          <span>Inspector {{ inspectorOpen ? 'ON' : 'OFF' }}</span>
        </button>
        <button (click)="clearAll.emit()" class="df-tool-btn df-tool-btn--danger" title="Clear canvas">
          <app-icon name="trash-2" [size]="14" />
        </button>
      </div>
    </div>
  `,
})
export class FlowCanvasToolbarComponent {
  @Input() nodeCount = 0;
  @Input() errorCount = 0;
  @Input() warnCount = 0;
  @Input() terminalOpen = true;
  @Input() inspectorOpen = true;

  @Output() zoom = new EventEmitter<'in' | 'out'>();
  @Output() zoomReset = new EventEmitter<void>();
  @Output() fit = new EventEmitter<void>();
  @Output() autoLayout = new EventEmitter<void>();
  @Output() toggleTerminal = new EventEmitter<void>();
  @Output() toggleInspector = new EventEmitter<void>();
  @Output() clearAll = new EventEmitter<void>();
}
