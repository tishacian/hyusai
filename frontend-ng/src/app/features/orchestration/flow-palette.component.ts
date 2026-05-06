import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import type { FlowTemplate, PaletteItem } from './workflow-editor.component';

@Component({
  selector: 'app-flow-palette',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <aside class="t-card t-elevated rounded-md p-3 h-fit">
      <h3 class="text-[10px] uppercase tracking-[0.14em] font-semibold text-gray-400 mb-2 flex items-center gap-1.5 ck-mono">
        <app-icon name="layers" [size]="12" class="text-brand-400" /> Nodes
      </h3>
      <div class="space-y-1.5">
        @for (node of palette; track node.type) {
          <div
            draggable="true"
            (dragstart)="dragStart.emit({ event: $event, node })"
            (click)="addNode.emit(node)"
            class="df-palette-card group"
            [attr.data-tone]="node.tone"
            [title]="node.description"
          >
            <div class="df-palette-icon" [attr.data-tone]="node.tone">
              <app-icon [name]="node.icon" [size]="14" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="text-xs font-medium text-white truncate leading-tight">{{ node.label }}</div>
              <div class="text-[9px] text-gray-500 leading-tight ck-mono uppercase tracking-wider">{{ node.typeLabel ?? node.label }}</div>
            </div>
          </div>
        }
      </div>

      <div class="mt-4 pt-3 border-t border-white/5">
        <h3 class="text-[10px] uppercase tracking-[0.14em] font-semibold text-gray-400 mb-2 flex items-center gap-1.5 ck-mono">
          <app-icon name="sparkles" [size]="12" class="text-brand-400" /> Templates
        </h3>
        <div class="space-y-1">
          @for (tpl of templates; track tpl.id) {
            <button
              type="button"
              (click)="loadTemplate.emit(tpl)"
              class="w-full text-left px-2 py-1.5 rounded hover:bg-white/5 text-gray-300 transition"
              [title]="tpl.description"
            >
              <div class="text-xs font-medium text-white">{{ tpl.label }}</div>
              <div class="text-[10px] text-gray-500">{{ tpl.description }}</div>
            </button>
          }
        </div>
      </div>
    </aside>
  `,
})
export class FlowPaletteComponent {
  @Input({ required: true }) palette: PaletteItem[] = [];
  @Input({ required: true }) templates: FlowTemplate[] = [];
  @Output() addNode = new EventEmitter<PaletteItem>();
  @Output() loadTemplate = new EventEmitter<FlowTemplate>();
  @Output() dragStart = new EventEmitter<{ event: DragEvent; node: PaletteItem }>();
}
