import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  NgZone,
  OnDestroy,
  ViewChild,
  ViewEncapsulation,
  inject,
  signal,
} from '@angular/core';
import { ToastrService } from 'ngx-toastr';
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

interface FlowTemplate {
  id: string;
  label: string;
  description: string;
  build: (add: (t: string, x: number, y: number) => number, connect: (a: number, b: number) => void) => void;
}

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, SectionHeaderComponent, StatusPulseComponent],
  styleUrls: ['./workflow-editor.styles.scss'],
  encapsulation: ViewEncapsulation.None,
  template: `
    <app-section-header
      breadcrumb="Build"
      title="Flow builder"
      icon="workflow"
      subtitle="Compose and preview a system's pipeline — retrieval, tools, guardrails, routing."
    >
      <div class="flex items-center gap-2">
        <app-status-pulse tone="accent" label="Draft" />
        <button
          type="button"
          (click)="resetCanvas()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        >
          <app-icon name="rotate-ccw" [size]="14" /> Reset
        </button>
        <button
          type="button"
          (click)="run()"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
        >
          <app-icon name="play" [size]="14" /> Simulate run
        </button>
      </div>
    </app-section-header>

    <div class="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4">
      <!-- Palette -->
      <aside class="t-card t-elevated rounded-md p-4 h-fit">
        <h3 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-3 flex items-center gap-1.5">
          <app-icon name="layers" [size]="12" class="text-brand-400" /> Nodes
        </h3>
        <p class="text-[11px] text-gray-500 mb-3 leading-relaxed">
          Drag a node onto the canvas or click to add it at the center.
        </p>
        <div class="space-y-2">
          @for (node of palette; track node.type) {
            <div
              draggable="true"
              (dragstart)="onDragStart($event, node)"
              (click)="addNodeAtCenter(node)"
              class="flex items-start gap-3 px-3 py-2.5 rounded border border-white/5 bg-black/20 hover:bg-white/5 hover:border-brand-500/30 transition text-left group cursor-grab active:cursor-grabbing"
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
            </div>
          }
        </div>

        <div class="mt-5 pt-4 border-t border-white/5">
          <h3 class="text-xs uppercase tracking-wider font-semibold text-gray-400 mb-2 flex items-center gap-1.5">
            <app-icon name="sparkles" [size]="12" class="text-brand-400" /> Templates
          </h3>
          <div class="space-y-1">
            @for (tpl of flowTemplates; track tpl.id) {
              <button
                type="button"
                (click)="loadTemplate(tpl)"
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

      <!-- Canvas -->
      <div
        class="t-card t-elevated rounded-md overflow-hidden relative"
        style="height: 640px"
      >
        <div class="absolute inset-x-0 top-0 z-10 px-4 py-2 flex items-center justify-between bg-black/30 backdrop-blur-sm border-b border-white/5">
          <div class="flex items-center gap-2 text-xs text-gray-400">
            <app-icon name="mouse-pointer-2" [size]="12" class="text-brand-400" />
            Drag nodes onto the grid · connect by dragging between ports · scroll to pan
          </div>
          <div class="flex items-center gap-1">
            <button (click)="zoom('in')" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Zoom in">
              <app-icon name="zoom-in" [size]="14" />
            </button>
            <button (click)="zoom('out')" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Zoom out">
              <app-icon name="zoom-out" [size]="14" />
            </button>
            <button (click)="zoomReset()" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Reset zoom">
              <app-icon name="maximize" [size]="14" />
            </button>
            <button (click)="clearAll()" class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-red-400 transition" title="Clear canvas">
              <app-icon name="trash-2" [size]="14" />
            </button>
          </div>
        </div>

        <div
          #drawflowContainer
          class="w-full h-full pt-10"
          (dragover)="onDragOver($event)"
          (drop)="onDrop($event)"
        ></div>

        @if (loading()) {
          <div class="absolute inset-0 flex flex-col items-center justify-center text-sm text-gray-400 bg-black/20 pointer-events-none">
            <app-icon name="loader-2" [size]="18" class="animate-spin text-brand-400 mb-2" />
            Initializing canvas…
          </div>
        }
        @if (error()) {
          <div class="absolute inset-0 flex items-center justify-center text-sm text-gray-400">
            <app-icon name="alert-triangle" [size]="16" class="mr-2 text-amber-400" />
            {{ error() }}
          </div>
        }
      </div>
    </div>
  `,
})
export class WorkflowEditorComponent implements AfterViewInit, OnDestroy {
  @ViewChild('drawflowContainer', { static: true }) container!: ElementRef<HTMLElement>;

  private readonly destroyRef = inject(DestroyRef);
  private readonly zone = inject(NgZone);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly toastr = inject(ToastrService);

  private editor: any = null;
  loading = signal(true);
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

  readonly flowTemplates: FlowTemplate[] = [
    {
      id: 'rag',
      label: 'RAG · Retrieve → Answer',
      description: 'Input → Retrieve → LLM → Output',
      build: (add, connect) => {
        const a = add('input', 60, 220);
        const b = add('retrieve', 290, 220);
        const c = add('llm', 540, 220);
        const d = add('output', 790, 220);
        connect(a, b);
        connect(b, c);
        connect(c, d);
      },
    },
    {
      id: 'router',
      label: 'Router · Classify → Dispatch',
      description: 'Split traffic between two tools',
      build: (add, connect) => {
        const a = add('input', 60, 240);
        const r = add('router', 300, 240);
        const t1 = add('tool', 560, 130);
        const t2 = add('tool', 560, 340);
        const o = add('output', 820, 240);
        connect(a, r);
        connect(r, t1);
        connect(r, t2);
        connect(t1, o);
        connect(t2, o);
      },
    },
    {
      id: 'safe',
      label: 'Guarded LLM · Safety first',
      description: 'Input → Guardrail → LLM → Output',
      build: (add, connect) => {
        const a = add('input', 60, 220);
        const g = add('guardrail', 290, 220);
        const c = add('llm', 540, 220);
        const d = add('output', 790, 220);
        connect(a, g);
        connect(g, c);
        connect(c, d);
      },
    },
  ];

  private pendingDrop: PaletteItem | null = null;
  private ids = 0;

  async ngAfterViewInit(): Promise<void> {
    const el = this.container?.nativeElement;
    if (!el) {
      this.loading.set(false);
      this.error.set('Canvas element not found');
      return;
    }

    // Drawflow mutates the DOM heavily & relies on timers; keep it outside Angular.
    await this.zone.runOutsideAngular(async () => {
      try {
        const mod: any = await import('drawflow');
        const Drawflow = mod.default ?? mod;
        this.editor = new Drawflow(el);
        this.editor.reroute = true;
        this.editor.reroute_fix_curvature = true;
        this.editor.start();
        this.loadTemplate(this.flowTemplates[0]);
      } catch (err) {
        console.error('Drawflow init failed', err);
        this.zone.run(() => this.error.set('Workflow editor unavailable'));
      } finally {
        this.zone.run(() => {
          this.loading.set(false);
          this.cdr.markForCheck();
        });
      }
    });
  }

  ngOnDestroy(): void {
    try {
      this.editor?.clear?.();
    } catch {
      // ignore
    }
  }

  private paletteFor(type: string): PaletteItem {
    return this.palette.find((p) => p.type === type) ?? this.palette[0];
  }

  private nodeHtml(node: PaletteItem): string {
    return `
      <div class="df-node">
        <div class="df-node-head"><span class="df-dot df-${node.tone}"></span>${node.label}</div>
        <div class="df-node-body">${node.description}</div>
      </div>`;
  }

  private internalAdd(type: string, x: number, y: number): number {
    if (!this.editor) return 0;
    const p = this.paletteFor(type);
    const inputs = type === 'input' ? 0 : 1;
    const outputs = type === 'output' ? 0 : type === 'router' ? 2 : 1;
    const id = this.editor.addNode(type, inputs, outputs, x, y, type, {}, this.nodeHtml(p));
    this.ids = Math.max(this.ids, id);
    return id;
  }

  private internalConnect(a: number, b: number, outPort = 'output_1', inPort = 'input_1'): void {
    if (!this.editor) return;
    try {
      this.editor.addConnection(a, b, outPort, inPort);
    } catch {
      // ignore invalid connections
    }
  }

  addNodeAtCenter(node: PaletteItem): void {
    if (!this.editor) return;
    this.zone.runOutsideAngular(() => {
      const rect = this.container.nativeElement.getBoundingClientRect();
      const x = rect.width / 2 - 80;
      const y = rect.height / 2 - 40;
      this.internalAdd(node.type, x, y);
    });
  }

  onDragStart(ev: DragEvent, node: PaletteItem): void {
    this.pendingDrop = node;
    ev.dataTransfer?.setData('text/plain', node.type);
  }

  onDragOver(ev: DragEvent): void {
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
  }

  onDrop(ev: DragEvent): void {
    ev.preventDefault();
    if (!this.editor || !this.pendingDrop) return;
    const rect = this.container.nativeElement.getBoundingClientRect();
    const zoom = this.editor.zoom ?? 1;
    const x = (ev.clientX - rect.left) / zoom;
    const y = (ev.clientY - rect.top) / zoom;
    this.zone.runOutsideAngular(() => {
      this.internalAdd(this.pendingDrop!.type, Math.max(20, x - 80), Math.max(20, y - 40));
    });
    this.pendingDrop = null;
  }

  loadTemplate(tpl: FlowTemplate): void {
    if (!this.editor) return;
    this.zone.runOutsideAngular(() => {
      try {
        this.editor.clearModuleSelected();
      } catch {
        // ignore
      }
      tpl.build(
        (t, x, y) => this.internalAdd(t, x, y),
        (a, b) => this.internalConnect(a, b),
      );
    });
    this.zone.run(() => this.toastr.info(tpl.label, 'Template loaded'));
  }

  resetCanvas(): void {
    if (!this.editor) return;
    this.zone.runOutsideAngular(() => {
      try {
        this.editor.clearModuleSelected();
      } catch {
        // ignore
      }
      this.loadTemplate(this.flowTemplates[0]);
    });
  }

  clearAll(): void {
    if (!this.editor) return;
    this.zone.runOutsideAngular(() => {
      try {
        this.editor.clearModuleSelected();
      } catch {
        // ignore
      }
    });
  }

  zoom(dir: 'in' | 'out'): void {
    if (!this.editor) return;
    if (dir === 'in') this.editor.zoom_in();
    else this.editor.zoom_out();
  }

  zoomReset(): void {
    if (!this.editor) return;
    this.editor.zoom_reset();
  }

  run(): void {
    this.toastr.success('Runs are simulated in the demo — connect a backend to execute flows.', 'Flow simulated');
  }
}
