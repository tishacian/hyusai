import {
  AfterViewInit,
  Component,
  DestroyRef,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

interface PaletteItem {
  type: string;
  icon: string;
  label: string;
  description: string;
  tone: 'brand' | 'violet' | 'emerald' | 'amber';
}

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  imports: [IconComponent, SectionHeaderComponent, StatusPulseComponent],
  template: `
    <app-section-header
      breadcrumb="Build"
      title="Orchestration"
      icon="workflow"
      subtitle="Compose multi-step agent flows with retrieval, tools and guardrails."
    >
      <div class="flex items-center gap-2">
        <app-status-pulse tone="accent" label="Draft" />
        <button
          type="button"
          (click)="run()"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
        >
          <app-icon name="play" [size]="14" /> Run
        </button>
      </div>
    </app-section-header>

    <div class="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4">
      <!-- Palette -->
      <aside class="t-card t-elevated rounded-md p-4 h-fit sticky top-0">
        <h3 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-3 flex items-center gap-1.5">
          <app-icon name="layers" [size]="12" class="text-brand-400" /> Nodes
        </h3>
        <div class="space-y-2">
          @for (node of palette; track node.type) {
            <button
              type="button"
              draggable="true"
              (dragstart)="onDragStart($event, node)"
              (click)="addNode(node)"
              class="w-full flex items-start gap-3 px-3 py-2.5 rounded border border-white/5 bg-black/20 hover:bg-white/5 hover:border-brand-500/30 transition text-left group"
            >
              <div
                class="w-8 h-8 rounded flex items-center justify-center shrink-0 ring-1"
                [class.bg-brand-500\\/15]="node.tone === 'brand'"
                [class.ring-brand-500\\/30]="node.tone === 'brand'"
                [class.text-brand-400]="node.tone === 'brand'"
                [class.bg-violet-500\\/15]="node.tone === 'violet'"
                [class.ring-violet-500\\/30]="node.tone === 'violet'"
                [class.text-violet-400]="node.tone === 'violet'"
                [class.bg-emerald-500\\/15]="node.tone === 'emerald'"
                [class.ring-emerald-500\\/30]="node.tone === 'emerald'"
                [class.text-emerald-400]="node.tone === 'emerald'"
                [class.bg-amber-500\\/15]="node.tone === 'amber'"
                [class.ring-amber-500\\/30]="node.tone === 'amber'"
                [class.text-amber-400]="node.tone === 'amber'"
              >
                <app-icon [name]="node.icon" [size]="14" />
              </div>
              <div class="min-w-0">
                <div class="text-sm font-medium text-white truncate">{{ node.label }}</div>
                <div class="text-[11px] text-gray-500 line-clamp-1">{{ node.description }}</div>
              </div>
            </button>
          }
        </div>

        <div class="mt-5 pt-4 border-t border-white/5">
          <h3 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-2 flex items-center gap-1.5">
            <app-icon name="sparkles" [size]="12" class="text-brand-400" /> Templates
          </h3>
          <button class="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-white/5 text-gray-300">
            RAG · Retrieve → Answer
          </button>
          <button class="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-white/5 text-gray-300">
            Router · Classify → Dispatch
          </button>
          <button class="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-white/5 text-gray-300">
            Critique loop · Draft → Review
          </button>
        </div>
      </aside>

      <!-- Canvas -->
      @defer (on viewport) {
        <div
          class="t-card t-elevated rounded-md overflow-hidden relative"
          style="height: 640px"
          (dragover)="$event.preventDefault()"
          (drop)="onDrop($event)"
        >
          <div class="absolute inset-x-0 top-0 z-10 px-4 py-2 flex items-center justify-between bg-black/30 backdrop-blur-sm border-b border-white/5">
            <div class="flex items-center gap-2 text-xs text-gray-400">
              <app-icon name="mouse-pointer-2" [size]="12" class="text-brand-400" />
              Drag nodes from the palette · click to connect
            </div>
            <div class="flex items-center gap-1">
              <button (click)="zoom('in')" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Zoom in">
                <app-icon name="zoom-in" [size]="14" />
              </button>
              <button (click)="zoom('out')" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Zoom out">
                <app-icon name="zoom-out" [size]="14" />
              </button>
              <button (click)="clearAll()" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-red-400 transition" title="Clear">
                <app-icon name="trash-2" [size]="14" />
              </button>
            </div>
          </div>
          <div #drawflowContainer class="w-full h-full pt-10"></div>

          @if (error()) {
            <div class="absolute inset-0 flex items-center justify-center text-sm text-gray-400">
              <app-icon name="alert-triangle" [size]="16" class="mr-2 text-amber-400" />
              {{ error() }}
            </div>
          }
        </div>
      } @placeholder {
        <div class="t-card t-elevated rounded-md h-96 flex items-center justify-center text-gray-400">
          <app-icon name="loader-2" [size]="18" class="animate-spin mr-2" />
          Loading canvas…
        </div>
      }
    </div>
  `,
})
export class WorkflowEditorComponent implements AfterViewInit {
  private readonly destroyRef = inject(DestroyRef);
  private readonly container = viewChild<ElementRef>('drawflowContainer');
  private editor: any;
  error = signal<string | null>(null);

  readonly palette: PaletteItem[] = [
    { type: 'input', icon: 'message-circle', label: 'Input', description: 'User prompt / webhook', tone: 'brand' },
    { type: 'retrieve', icon: 'database', label: 'Retrieve', description: 'Vector search over knowledge', tone: 'violet' },
    { type: 'llm', icon: 'brain', label: 'LLM', description: 'Call a language model', tone: 'brand' },
    { type: 'tool', icon: 'wrench', label: 'Tool', description: 'Invoke a tool / API', tone: 'emerald' },
    { type: 'router', icon: 'git-branch', label: 'Router', description: 'Classify + dispatch', tone: 'violet' },
    { type: 'guardrail', icon: 'shield-check', label: 'Guardrail', description: 'Safety + policy filter', tone: 'amber' },
    { type: 'output', icon: 'arrow-up-right', label: 'Output', description: 'Return answer', tone: 'brand' },
  ];

  private pendingDrop: PaletteItem | null = null;

  async ngAfterViewInit(): Promise<void> {
    const el = this.container()?.nativeElement;
    if (!el) return;

    try {
      const Drawflow = (await import('drawflow')).default;
      this.editor = new Drawflow(el);
      this.editor.reroute = true;
      this.editor.start();
      this.seed();
    } catch {
      this.error.set('Workflow editor unavailable');
    }

    this.destroyRef.onDestroy(() => {
      this.editor?.clear?.();
    });
  }

  private seed(): void {
    if (!this.editor) return;
    this.editor.addNode(
      'input',
      0,
      1,
      80,
      120,
      'input',
      {},
      '<div class="df-node"><div class="df-node-head"><span class="df-dot df-brand"></span>Input</div><div class="df-node-body">User prompt</div></div>',
    );
    this.editor.addNode(
      'retrieve',
      1,
      1,
      320,
      60,
      'retrieve',
      {},
      '<div class="df-node"><div class="df-node-head"><span class="df-dot df-violet"></span>Retrieve</div><div class="df-node-body">Vector search</div></div>',
    );
    this.editor.addNode(
      'llm',
      1,
      1,
      560,
      120,
      'llm',
      {},
      '<div class="df-node"><div class="df-node-head"><span class="df-dot df-brand"></span>LLM</div><div class="df-node-body">GPT-4 · temperature 0.2</div></div>',
    );
    this.editor.addNode(
      'output',
      1,
      0,
      820,
      120,
      'output',
      {},
      '<div class="df-node"><div class="df-node-head"><span class="df-dot df-brand"></span>Output</div><div class="df-node-body">Answer</div></div>',
    );
    try {
      this.editor.addConnection(1, 2, 'output_1', 'input_1');
      this.editor.addConnection(2, 3, 'output_1', 'input_1');
      this.editor.addConnection(3, 4, 'output_1', 'input_1');
    } catch {
      // ignore
    }
  }

  onDragStart(ev: DragEvent, node: PaletteItem): void {
    this.pendingDrop = node;
    ev.dataTransfer?.setData('text/plain', node.type);
  }

  onDrop(ev: DragEvent): void {
    ev.preventDefault();
    if (!this.editor || !this.pendingDrop) return;
    const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    this.addNode(this.pendingDrop, ev.clientX - rect.left, ev.clientY - rect.top);
    this.pendingDrop = null;
  }

  addNode(node: PaletteItem, x = 200, y = 200): void {
    if (!this.editor) return;
    this.editor.addNode(
      node.type,
      1,
      1,
      x,
      y,
      node.type,
      {},
      `<div class="df-node"><div class="df-node-head"><span class="df-dot df-${node.tone}"></span>${node.label}</div><div class="df-node-body">${node.description}</div></div>`,
    );
  }

  zoom(dir: 'in' | 'out'): void {
    if (!this.editor) return;
    if (dir === 'in') this.editor.zoom_in();
    else this.editor.zoom_out();
  }

  clearAll(): void {
    this.editor?.clearModuleSelected?.();
  }

  run(): void {
    // Placeholder — would trigger workflow execution
  }
}
