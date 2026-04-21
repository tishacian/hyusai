import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  NgZone,
  OnDestroy,
  OnInit,
  ViewChild,
  ViewEncapsulation,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import {
  FlowSerializerService,
  type CanonicalFlow,
  type CanonicalFlowEdge,
  type CanonicalFlowNode,
  type DrawflowGraph,
} from '@app/core/flow-serializer.service';

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
  build: (
    add: (t: string, x: number, y: number) => number,
    connect: (a: number, b: number) => void,
  ) => void;
}

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, CkObjectHeaderComponent, StatusPulseComponent],
  styleUrls: ['./workflow-editor.styles.scss'],
  encapsulation: ViewEncapsulation.None,
  template: `
    <ck-object-header
      [eyebrow]="headerEyebrow()"
      [title]="headerTitle()"
      [subtitle]="headerSubtitle()"
      [kpis]="headerKpis()"
    >
      <app-status-pulse
        status
        [tone]="extended() ? 'warning' : 'accent'"
        [label]="extended() ? 'Extended' : 'Canonical'"
      />
      @if (systemId()) {
        <button
          actions
          type="button"
          (click)="backToBuilder()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          title="Back to the System detail view"
        >
          <app-icon name="arrow-left" [size]="14" /> Back to System
        </button>
      }
      @if (systemId()) {
        <button
          actions
          type="button"
          (click)="saveToSystem()"
          [disabled]="saving()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-xs font-medium ck-mono transition"
          style="letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:#020617;"
          [style.opacity]="saving() ? '0.4' : '1'"
        >
          <app-icon name="save" [size]="12" />
          {{ saving() ? 'Saving…' : 'Save to System' }}
        </button>
      }
      <button
        actions
        type="button"
        (click)="resetCanvas()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="rotate-ccw" [size]="14" /> Reset
      </button>
      <button
        actions
        type="button"
        (click)="run()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
      >
        <app-icon name="play" [size]="14" /> Simulate run
      </button>
    </ck-object-header>

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
export class WorkflowEditorComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('drawflowContainer', { static: true }) container!: ElementRef<HTMLElement>;

  private readonly destroyRef = inject(DestroyRef);
  private readonly zone = inject(NgZone);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly toastr = inject(ToastrService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly serializer = inject(FlowSerializerService);
  private readonly zoomCtx = inject(ZoomContextService);

  private editor: any = null;
  loading = signal(true);
  error = signal<string | null>(null);

  // Systemid-scoped state.
  readonly systemId = signal<string | null>(null);
  readonly system = signal<System | null>(null);
  readonly saving = signal(false);

  // Semantic projection of the current canvas.
  readonly nodeCount = signal(0);
  readonly edgeCount = signal(0);
  readonly source = signal<'form' | 'flow'>('flow');
  readonly extended = signal(false);

  readonly headerEyebrow = computed(() =>
    this.systemId() ? 'Systems · Flow' : 'Build · Flow · Scratchpad',
  );
  readonly headerTitle = computed(() => this.system()?.name ?? 'Flow builder');
  readonly headerSubtitle = computed(() => {
    if (this.systemId()) {
      return (
        this.system()?.objective ||
        "Edit this System's flow graph. Save overwrites the System's flow_definition."
      );
    }
    return "Compose and preview a system's pipeline — retrieval, tools, guardrails, routing.";
  });

  readonly headerKpis = computed<CkObjectKpi[]>(() => [
    { label: 'Nodes', value: String(this.nodeCount()), tone: 'cool' },
    { label: 'Edges', value: String(this.edgeCount()), tone: 'neutral' },
    { label: 'Source', value: this.source(), tone: this.source() === 'flow' ? 'violet' : 'neutral' },
    {
      label: 'Extended',
      value: this.extended() ? 'Yes' : 'No',
      tone: this.extended() ? 'warn' : 'neutral',
    },
  ]);

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

  ngOnInit(): void {
    const sid = this.route.snapshot.queryParamMap.get('systemId');
    this.systemId.set(sid);
    if (sid) {
      this.zoomCtx.setCurrentSystem(sid);
    } else {
      this.zoomCtx.setCurrentSystem(null);
    }
    this.zoomCtx.setCurrentRun(null);
  }

  async ngAfterViewInit(): Promise<void> {
    const el = this.container?.nativeElement;
    if (!el) {
      this.loading.set(false);
      this.error.set('Canvas element not found');
      return;
    }

    await this.zone.runOutsideAngular(async () => {
      try {
        const mod: any = await import('drawflow');
        const Drawflow = mod.default ?? mod;
        this.editor = new Drawflow(el);
        this.editor.reroute = true;
        this.editor.reroute_fix_curvature = true;
        this.editor.start();

        if (this.systemId()) {
          await this.hydrateFromSystem(this.systemId()!);
        } else {
          this.loadTemplate(this.flowTemplates[0]);
        }

        this.attachChangeListeners();
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

  /**
   * Subscribe to Drawflow's mutation events so the header KPIs stay in
   * sync with the canvas. All events are handled outside the Angular
   * zone — we only poke CD when we actually update a signal.
   */
  private attachChangeListeners(): void {
    if (!this.editor?.on) return;
    const refresh = () => {
      this.zone.run(() => this.refreshKpis());
    };
    try {
      this.editor.on('nodeCreated', refresh);
      this.editor.on('nodeRemoved', refresh);
      this.editor.on('nodeDataChanged', refresh);
      this.editor.on('connectionCreated', refresh);
      this.editor.on('connectionRemoved', refresh);
    } catch {
      // older drawflow builds silently ignore unknown events
    }
    this.refreshKpis();
  }

  private refreshKpis(): void {
    const graph = this.exportGraph();
    const flow = this.serializer.project(graph);
    this.nodeCount.set(flow.nodes.length);
    this.edgeCount.set(flow.edges.length);
    this.extended.set(!!flow.extended);
  }

  private async hydrateFromSystem(systemId: string): Promise<void> {
    const sys = await this.canonical
      .getSystem(systemId)
      .toPromise()
      .catch(() => null);
    if (!sys) {
      this.zone.run(() => {
        this.toastr.warning(
          'System not found — falling back to scratchpad',
          'Orchestration',
        );
        this.systemId.set(null);
      });
      this.loadTemplate(this.flowTemplates[0]);
      return;
    }
    this.zone.run(() => this.system.set(sys));

    const flow = (sys.flow_definition ?? {}) as unknown as CanonicalFlow;
    if (!Array.isArray(flow.nodes) || flow.nodes.length === 0) {
      this.zone.run(() =>
        this.toastr.info(
          'This System has no flow yet — starting from the RAG template.',
          'Orchestration',
        ),
      );
      this.loadTemplate(this.flowTemplates[0]);
      this.zone.run(() => this.source.set('form'));
      return;
    }
    this.importFlow(flow);
    this.zone.run(() => this.source.set(flow.source ?? 'form'));
  }

  /** Import a canonical flow into the current Drawflow instance. */
  private importFlow(flow: CanonicalFlow): void {
    if (!this.editor) return;
    try {
      this.editor.clearModuleSelected();
    } catch {
      // ignore
    }
    const graph = this.serializer.materialize(flow);
    try {
      this.editor.import(graph as any);
    } catch (err) {
      console.warn('drawflow.import failed, falling back to manual add', err);
      this.manualImport(flow);
    }
    this.refreshKpis();
  }

  /**
   * Fallback import path used when `drawflow.import` chokes on a graph.
   * We rebuild the canvas node by node using the same canonical ids,
   * matching the behaviour of `materialize` as closely as possible.
   */
  private manualImport(flow: CanonicalFlow): void {
    const idToNum = new Map<string, number>();
    for (const n of flow.nodes) {
      const type = String(n.type);
      const num = this.internalAdd(type, n.position?.x ?? 60, n.position?.y ?? 80, n);
      idToNum.set(n.id, num);
    }
    for (const e of flow.edges) {
      const from = idToNum.get(e.from);
      const to = idToNum.get(e.to);
      if (from && to) this.internalConnect(from, to);
    }
  }

  private exportGraph(): DrawflowGraph {
    try {
      return this.editor?.export?.() ?? { drawflow: { Home: { data: {} } } };
    } catch {
      return { drawflow: { Home: { data: {} } } };
    }
  }

  private paletteFor(type: string): PaletteItem {
    return this.palette.find((p) => p.type === type) ?? this.palette[0];
  }

  private nodeHtml(node: PaletteItem, override?: { label?: string; description?: string }): string {
    const label = override?.label ?? node.label;
    const body = override?.description ?? node.description;
    return `
      <div class="df-node">
        <div class="df-node-head"><span class="df-dot df-${node.tone}"></span>${label}</div>
        <div class="df-node-body">${body}</div>
      </div>`;
  }

  private internalAdd(
    type: string,
    x: number,
    y: number,
    canonical?: CanonicalFlowNode,
  ): number {
    if (!this.editor) return 0;
    const p = this.paletteFor(type);
    const inputs = type === 'input' ? 0 : 1;
    const outputs = type === 'output' ? 0 : type === 'router' ? 2 : 1;
    const data: Record<string, unknown> = {};
    if (canonical) {
      data['canonical_id'] = canonical.id;
      data['canonical_type'] = canonical.type;
      if (canonical.data) Object.assign(data, canonical.data);
    }
    const html = this.nodeHtml(p, { label: canonical?.label });
    const id = this.editor.addNode(type, inputs, outputs, x, y, type, data, html);
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
      this.zone.run(() => this.refreshKpis());
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
    const zoomLvl = this.editor.zoom ?? 1;
    const x = (ev.clientX - rect.left) / zoomLvl;
    const y = (ev.clientY - rect.top) / zoomLvl;
    this.zone.runOutsideAngular(() => {
      this.internalAdd(this.pendingDrop!.type, Math.max(20, x - 80), Math.max(20, y - 40));
      this.zone.run(() => this.refreshKpis());
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
    this.zone.run(() => {
      this.toastr.info(tpl.label, 'Template loaded');
      this.refreshKpis();
    });
  }

  resetCanvas(): void {
    if (!this.editor) return;
    this.zone.runOutsideAngular(() => {
      try {
        this.editor.clearModuleSelected();
      } catch {
        // ignore
      }
    });
    if (this.systemId()) {
      this.hydrateFromSystem(this.systemId()!);
    } else {
      this.loadTemplate(this.flowTemplates[0]);
    }
  }

  clearAll(): void {
    if (!this.editor) return;
    this.zone.runOutsideAngular(() => {
      try {
        this.editor.clearModuleSelected();
      } catch {
        // ignore
      }
      this.zone.run(() => this.refreshKpis());
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

  /**
   * Serialize the current canvas and PATCH it back onto the owning
   * System's `flow_definition`. Preserves `variant` and semantic
   * sidecars so downstream RAG consumers keep working.
   */
  saveToSystem(): void {
    const sid = this.systemId();
    if (!sid) return;
    const graph = this.exportGraph();
    const projected = this.serializer.project(graph);
    const existing = (this.system()?.flow_definition ?? {}) as unknown as CanonicalFlow;
    const merged: CanonicalFlow = this.serializer.annotateSidecars({
      ...existing,
      ...projected,
      variant: existing.variant,
      source: 'flow',
    });
    this.saving.set(true);
    this.canonical
      .updateSystem(sid, { flow_definition: merged as unknown as Record<string, unknown> })
      .subscribe({
      next: (res) => {
        this.saving.set(false);
        if (!res) {
          this.toastr.error('Could not save flow — backend rejected the update.', 'Save failed');
          return;
        }
        this.system.set(res);
        this.source.set('flow');
        this.extended.set(!!merged.extended);
        this.toastr.success(`Flow saved to "${res.name}".`, 'Saved');
      },
      error: () => {
        this.saving.set(false);
        this.toastr.error('Could not save flow — network error.', 'Save failed');
      },
    });
  }

  backToBuilder(): void {
    const sid = this.systemId();
    if (!sid) {
      this.router.navigateByUrl('/systems');
      return;
    }
    this.router.navigate(['/systems', sid], { queryParams: { facet: 'overview' } });
  }
}

// Keep TypeScript from complaining about unused imports used only for typing.
export type { CanonicalFlowEdge };
