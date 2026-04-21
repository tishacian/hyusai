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
  type FlowValidationIssue,
  type NodeKind,
} from '@app/core/flow-serializer.service';

/** Tone vocabulary — maps 1:1 to the mockup's `--signal-*` tokens. */
type NodeTone = 'brand' | 'violet' | 'emerald' | 'amber' | 'rose' | 'cyan';

interface PaletteItem {
  type: string;
  icon: string;
  label: string;
  description: string;
  tone: NodeTone;
  /** DAG kind this node represents. Defaults to 'task'. */
  kind?: NodeKind;
  /** Uppercase pill label shown on the node card. */
  typeLabel?: string;
}

/** Single timestamped entry in the Execution Terminal. */
interface TerminalEntry {
  t: string; // HH:MM:SS
  tag: string; // [System], [Skill], ...
  tone: NodeTone | 'pos' | 'neg' | 'warn' | 'info';
  text: string;
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

    <div class="grid grid-cols-1 gap-3 df-shell" [attr.data-inspector]="inspectorOpen() ? 'open' : 'closed'">
      <!-- Palette -->
      <aside class="t-card t-elevated rounded-md p-3 h-fit">
        <h3 class="text-[10px] uppercase tracking-[0.14em] font-semibold text-gray-400 mb-2 flex items-center gap-1.5 ck-mono">
          <app-icon name="layers" [size]="12" class="text-brand-400" /> Nodes
        </h3>
        <div class="space-y-1.5">
          @for (node of palette; track node.type) {
            <div
              draggable="true"
              (dragstart)="onDragStart($event, node)"
              (click)="addNodeAtCenter(node)"
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

      <!-- Canvas + Terminal column -->
      <div
        class="t-card t-elevated rounded-md overflow-hidden relative"
        style="height: 680px"
      >
        <!-- Canvas toolbar -->
        <div class="absolute inset-x-0 top-0 z-10 px-3 py-2 flex items-center justify-between bg-black/30 backdrop-blur-sm border-b border-white/5">
          <div class="flex items-center gap-3">
            <span class="ck-mono text-[9px] uppercase tracking-[0.14em] text-gray-400">Flow canvas</span>
            @if (nodeCount() > 0) {
              <div class="flex items-center gap-1.5">
                @if (errorCount() > 0) {
                  <span class="df-tag df-tag-neg" [title]="'Validation errors'">
                    <app-icon name="alert-triangle" [size]="10" />
                    {{ errorCount() }} ERR
                  </span>
                }
                @if (warnCount() > 0) {
                  <span class="df-tag df-tag-warn" [title]="'Validation warnings'">
                    {{ warnCount() }} WARN
                  </span>
                }
                @if (errorCount() === 0 && warnCount() === 0) {
                  <span class="df-tag df-tag-pos">
                    <app-icon name="check" [size]="10" />
                    VALID
                  </span>
                }
              </div>
            }
          </div>
          <div class="flex items-center gap-1">
            <button (click)="zoom('in')" class="df-tool-btn" title="Zoom in">
              <app-icon name="zoom-in" [size]="14" />
            </button>
            <button (click)="zoom('out')" class="df-tool-btn" title="Zoom out">
              <app-icon name="zoom-out" [size]="14" />
            </button>
            <button (click)="zoomReset()" class="df-tool-btn" title="Reset zoom">
              <app-icon name="maximize" [size]="14" />
            </button>
            <span class="w-px h-4 bg-white/10 mx-1"></span>
            <button (click)="toggleTerminal()" class="df-tool-btn" [class.active]="terminalOpen()" title="Toggle execution terminal">
              <app-icon name="terminal" [size]="14" />
            </button>
            <button (click)="toggleInspector()" class="df-tool-btn" [class.active]="inspectorOpen()" title="Toggle node inspector">
              <app-icon name="sidebar" [size]="14" />
            </button>
            <button (click)="clearAll()" class="df-tool-btn df-tool-btn--danger" title="Clear canvas">
              <app-icon name="trash-2" [size]="14" />
            </button>
          </div>
        </div>

        <!-- Drawflow host -->
        <div
          #drawflowContainer
          class="w-full h-full pt-10 df-host"
          (dragover)="onDragOver($event)"
          (drop)="onDrop($event)"
        ></div>

        <!-- Execution Terminal -->
        @if (terminalOpen()) {
          <div class="df-terminal">
            <div class="df-terminal-head">
              <span class="ck-mono text-[9px] uppercase tracking-[0.14em] text-gray-400">Execution terminal</span>
              <div class="flex items-center gap-2">
                @if (terminalLog().length > 0) {
                  <span class="df-tag df-tag-cool">{{ terminalLog().length }} LINES</span>
                }
                <button (click)="clearTerminal()" class="text-[10px] text-gray-500 hover:text-gray-300 ck-mono" title="Clear log">
                  CLEAR
                </button>
                <button (click)="toggleTerminal()" class="df-tool-btn df-tool-btn--small" title="Collapse">
                  <app-icon name="chevron-down" [size]="12" />
                </button>
              </div>
            </div>
            <div class="df-terminal-body ck-mono">
              @if (terminalLog().length === 0) {
                <div class="df-terminal-empty">
                  <span class="text-gray-500">›</span>
                  Execute a Run on this System to see live output. Click Simulate or Execute on backend.
                </div>
              }
              @for (entry of terminalLog(); track $index) {
                <div class="df-terminal-row">
                  <span class="df-terminal-time">{{ entry.t }}</span>
                  <span class="df-terminal-tag" [attr.data-tone]="entry.tone">[{{ entry.tag }}]</span>
                  <span class="df-terminal-text">{{ entry.text }}</span>
                </div>
              }
            </div>
          </div>
        }

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

      <!-- Node Inspector -->
      @if (inspectorOpen()) {
        <aside class="t-card t-elevated rounded-md overflow-hidden" style="height: 680px">
          <div class="df-inspector">
            <div class="df-inspector-head">
              <span class="ck-mono text-[10px] uppercase tracking-[0.14em] text-gray-400">Node inspector</span>
              @if (selectedNode()) {
                <span class="df-tag" [attr.data-tone]="toneForNode(selectedNode()!)">{{ kindLabel(selectedNode()!.kind) }}</span>
              }
            </div>

            @if (!selectedNode()) {
              <div class="df-inspector-empty">
                <app-icon name="mouse-pointer-2" [size]="20" class="text-gray-500 mb-3" />
                <div class="text-sm text-gray-400 font-medium mb-1">No node selected</div>
                <div class="text-[11px] text-gray-500 leading-relaxed max-w-[220px]">
                  Click a node on the canvas to inspect its contract, config, and live metrics.
                </div>
              </div>
            } @else {
              <div class="df-inspector-body">
                <!-- Title -->
                <div class="text-lg text-white font-light mb-1">{{ selectedNode()!.label || selectedNode()!.type }}</div>
                <div class="ck-mono text-[10px] text-gray-500">id: {{ selectedNode()!.id }}</div>

                <!-- I/O contract -->
                @if ((selectedNode()!.inputs?.length ?? 0) > 0 || (selectedNode()!.outputs?.length ?? 0) > 0) {
                  <div class="df-inspector-section">
                    <div class="df-inspector-label">Typed contract</div>
                    @if ((selectedNode()!.inputs?.length ?? 0) > 0) {
                      <div class="text-[10px] text-gray-500 mb-1 ck-mono">INPUTS</div>
                      <div class="space-y-1 mb-3">
                        @for (p of selectedNode()!.inputs; track p.name) {
                          <div class="df-port-row">
                            <span class="df-port-dot" data-dir="in"></span>
                            <span class="text-xs text-gray-200 ck-mono">{{ p.name }}</span>
                            <span class="df-port-schema">{{ p.schema }}</span>
                          </div>
                        }
                      </div>
                    }
                    @if ((selectedNode()!.outputs?.length ?? 0) > 0) {
                      <div class="text-[10px] text-gray-500 mb-1 ck-mono">OUTPUTS</div>
                      <div class="space-y-1">
                        @for (p of selectedNode()!.outputs; track p.name) {
                          <div class="df-port-row">
                            <span class="df-port-dot" data-dir="out"></span>
                            <span class="text-xs text-gray-200 ck-mono">{{ p.name }}</span>
                            <span class="df-port-schema">{{ p.schema }}</span>
                          </div>
                        }
                      </div>
                    }
                  </div>
                }

                <!-- Kind-specific config preview -->
                <div class="df-inspector-section">
                  <div class="df-inspector-label">Config · {{ kindLabel(selectedNode()!.kind) }}</div>
                  <div class="df-inspector-config ck-mono">
                    @if (configSummary(selectedNode()!).length === 0) {
                      <span class="text-gray-500">— no config —</span>
                    }
                    @for (row of configSummary(selectedNode()!); track row.key) {
                      <div class="df-config-row">
                        <span class="text-gray-400">{{ row.key }}</span>
                        <span class="text-gray-200">{{ row.value }}</span>
                      </div>
                    }
                  </div>
                </div>

                <!-- Local metrics placeholder -->
                <div class="df-inspector-section">
                  <div class="df-inspector-label">Local metrics · 24h</div>
                  <div class="grid grid-cols-2 gap-1.5">
                    <div class="df-metric">
                      <div class="df-metric-label">Runs</div>
                      <div class="df-metric-value">—</div>
                    </div>
                    <div class="df-metric">
                      <div class="df-metric-label">Success</div>
                      <div class="df-metric-value">—</div>
                    </div>
                    <div class="df-metric">
                      <div class="df-metric-label">Latency p95</div>
                      <div class="df-metric-value">—</div>
                    </div>
                    <div class="df-metric">
                      <div class="df-metric-label">Cost</div>
                      <div class="df-metric-value">—</div>
                    </div>
                  </div>
                  <div class="text-[10px] text-gray-600 mt-2">
                    Metrics are wired in C8.
                  </div>
                </div>
              </div>
            }
          </div>
        </aside>
      } @else {
        <aside class="t-card t-elevated rounded-md flex flex-col items-center py-3" style="height: 680px">
          <button (click)="toggleInspector()" class="df-tool-btn" title="Open inspector">
            <app-icon name="sidebar" [size]="14" />
          </button>
        </aside>
      }
    </div>

    <!-- Validation issues strip -->
    @if (issues().length > 0) {
      <div class="mt-3 t-card t-elevated rounded-md p-3">
        <div class="flex items-center gap-2 mb-2">
          <app-icon name="alert-triangle" [size]="14" class="text-amber-400" />
          <span class="text-xs font-medium text-white">Flow validation — {{ issues().length }} issue{{ issues().length > 1 ? 's' : '' }}</span>
        </div>
        <div class="space-y-1">
          @for (issue of issues(); track $index) {
            <div class="flex items-start gap-2 text-[11px]">
              <span class="df-tag" [attr.data-tone]="issue.level === 'error' ? 'neg' : 'warn'">{{ issue.level === 'error' ? 'ERR' : 'WARN' }}</span>
              <span class="text-gray-300">{{ issue.message }}</span>
              @if (issue.node_id) {
                <span class="ck-mono text-[10px] text-gray-500">· {{ issue.node_id }}</span>
              }
            </div>
          }
        </div>
      </div>
    }
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
  readonly issues = signal<FlowValidationIssue[]>([]);

  // Inspector / Terminal state.
  readonly selectedNodeId = signal<string | null>(null);
  readonly selectedNode = signal<CanonicalFlowNode | null>(null);
  readonly inspectorOpen = signal(true);
  readonly terminalOpen = signal(true);
  readonly terminalLog = signal<TerminalEntry[]>([]);
  readonly errorCount = computed(
    () => this.issues().filter((i) => i.level === 'error').length,
  );
  readonly warnCount = computed(
    () => this.issues().filter((i) => i.level === 'warn').length,
  );

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
    // ── Execution-kind DAG primitives (Vague C) ──
    { type: 'input', icon: 'zap', label: 'Trigger', description: 'Webhook / queue / schedule', tone: 'violet', kind: 'source', typeLabel: 'TRIGGER' },
    { type: 'llm', icon: 'brain', label: 'LLM', description: 'Call a language model', tone: 'cyan', kind: 'task', typeLabel: 'LLM' },
    { type: 'retrieve', icon: 'database', label: 'Retrieve', description: 'Vector search over knowledge', tone: 'violet', kind: 'task', typeLabel: 'SKILL' },
    { type: 'tool', icon: 'wrench', label: 'Tool', description: 'Invoke a tool / API', tone: 'emerald', kind: 'task', typeLabel: 'SKILL' },
    { type: 'router', icon: 'git-branch', label: 'Decision', description: 'Branch on condition', tone: 'violet', kind: 'decision', typeLabel: 'LOGIC' },
    { type: 'fork', icon: 'split', label: 'Fork', description: 'Run branches in parallel', tone: 'cyan', kind: 'fork', typeLabel: 'LOGIC' },
    { type: 'join', icon: 'merge', label: 'Join', description: 'Wait for branches', tone: 'cyan', kind: 'join', typeLabel: 'LOGIC' },
    { type: 'loop', icon: 'repeat', label: 'Loop', description: 'Iterate with budget', tone: 'amber', kind: 'loop', typeLabel: 'LOGIC' },
    { type: 'retry', icon: 'rotate-ccw', label: 'Retry', description: 'Retry on error', tone: 'amber', kind: 'retry', typeLabel: 'LOGIC' },
    { type: 'hitl', icon: 'user-check', label: 'HITL', description: 'Human-in-the-loop gate', tone: 'amber', kind: 'hitl', typeLabel: 'HITL' },
    { type: 'subflow', icon: 'layers', label: 'Subflow', description: 'Nested System run', tone: 'violet', kind: 'subflow', typeLabel: 'SUBFLOW' },
    { type: 'guardrail', icon: 'shield-check', label: 'Guardrail', description: 'Safety + policy filter', tone: 'rose', kind: 'task', typeLabel: 'GUARD' },
    { type: 'output', icon: 'arrow-up-right', label: 'Output', description: 'Return answer', tone: 'emerald', kind: 'sink', typeLabel: 'OUTPUT' },
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
    const onSelect = (id: number | string) => {
      this.zone.run(() => this.onNodeSelected(String(id)));
    };
    const onUnselect = () => {
      this.zone.run(() => {
        this.selectedNodeId.set(null);
        this.selectedNode.set(null);
      });
    };
    try {
      this.editor.on('nodeCreated', refresh);
      this.editor.on('nodeRemoved', refresh);
      this.editor.on('nodeDataChanged', refresh);
      this.editor.on('connectionCreated', refresh);
      this.editor.on('connectionRemoved', refresh);
      this.editor.on('nodeSelected', onSelect);
      this.editor.on('nodeUnselected', onUnselect);
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
    this.issues.set(this.serializer.validateFlow(flow));
  }

  /**
   * Look up the canonical node behind a Drawflow integer id and push
   * it into the inspector signal. The lookup tolerates string/number
   * id drift across Drawflow versions.
   */
  private onNodeSelected(rawId: string): void {
    const graph = this.exportGraph();
    const nodeData = graph?.drawflow?.Home?.data?.[rawId];
    if (!nodeData) {
      this.selectedNodeId.set(null);
      this.selectedNode.set(null);
      return;
    }
    const canonicalId =
      (nodeData.data?.['canonical_id'] as string) || `flow.${rawId}`;
    const type =
      (nodeData.data?.['canonical_type'] as string) || nodeData.name || 'custom';
    const kind = (nodeData.data?.['canonical_kind'] as NodeKind) || 'task';
    const { canonical_id: _ci, canonical_type: _ct, canonical_kind: _ck,
            canonical_config: _cc, canonical_inputs: _cin, canonical_outputs: _cout,
            ...rest } = nodeData.data ?? {};
    this.selectedNodeId.set(rawId);
    this.selectedNode.set({
      id: canonicalId,
      type,
      kind,
      label: this.extractLabelFromHtml(nodeData.html ?? ''),
      data: rest,
      config: (nodeData.data?.['canonical_config'] as Record<string, unknown>) ?? {},
      inputs: (nodeData.data?.['canonical_inputs'] as CanonicalFlowNode['inputs']) ?? [],
      outputs: (nodeData.data?.['canonical_outputs'] as CanonicalFlowNode['outputs']) ?? [],
      position: { x: nodeData.pos_x, y: nodeData.pos_y },
    });
  }

  private extractLabelFromHtml(html: string): string {
    const match = html.match(/class="df-title[^"]*"[^>]*>([^<]+)</);
    if (match?.[1]) return match[1].trim();
    const fallback = html.match(/>(.*?)</);
    return fallback?.[1]?.trim() ?? 'Node';
  }

  /** Push a line into the Execution Terminal. Capped at 200 entries. */
  pushTerminal(entry: Omit<TerminalEntry, 't'>): void {
    const t = new Date().toTimeString().slice(0, 8);
    this.terminalLog.update((log) => {
      const next = [...log, { t, ...entry }];
      return next.length > 200 ? next.slice(next.length - 200) : next;
    });
  }

  clearTerminal(): void {
    this.terminalLog.set([]);
  }

  toggleTerminal(): void {
    this.terminalOpen.update((v) => !v);
  }

  toggleInspector(): void {
    this.inspectorOpen.update((v) => !v);
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

  private nodeHtml(
    node: PaletteItem,
    override?: { label?: string; description?: string; kind?: NodeKind },
  ): string {
    const label = this.escape(override?.label ?? node.label);
    const body = this.escape(override?.description ?? node.description);
    const typeLabel = this.escape(node.typeLabel ?? node.label.toUpperCase());
    const kind = override?.kind ?? node.kind ?? 'task';
    return `
      <div class="df-node df-tone-${node.tone} df-kind-${kind}">
        <div class="df-node-bar"></div>
        <div class="df-node-head">
          <span class="df-node-icon"></span>
          <span class="df-node-pill">${typeLabel}</span>
        </div>
        <div class="df-node-title">${label}</div>
        <div class="df-node-body mono">${body}</div>
      </div>`;
  }

  private escape(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  private internalAdd(
    type: string,
    x: number,
    y: number,
    canonical?: CanonicalFlowNode,
  ): number {
    if (!this.editor) return 0;
    const p = this.paletteFor(type);
    const isSource = p.kind === 'source' || type === 'input';
    const isSink = p.kind === 'sink' || type === 'output';
    const inputs = isSource ? 0 : 1;
    const outputs = isSink ? 0 : p.kind === 'decision' || type === 'router' ? 2 : p.kind === 'fork' ? 3 : 1;
    const kind = canonical?.kind ?? p.kind ?? 'task';
    const data: Record<string, unknown> = {
      canonical_kind: kind,
      canonical_config: canonical?.config ?? {},
      canonical_inputs: canonical?.inputs ?? [],
      canonical_outputs: canonical?.outputs ?? [],
    };
    if (canonical) {
      data['canonical_id'] = canonical.id;
      data['canonical_type'] = canonical.type;
      if (canonical.data) Object.assign(data, canonical.data);
    }
    const html = this.nodeHtml(p, { label: canonical?.label, kind });
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

  // ---------- Inspector helpers ----------

  toneForNode(node: CanonicalFlowNode): NodeTone {
    const match = this.palette.find((p) => p.type === node.type);
    if (match) return match.tone;
    switch (node.kind) {
      case 'decision':
      case 'fork':
      case 'join':
      case 'subflow':
        return 'violet';
      case 'loop':
      case 'retry':
      case 'hitl':
        return 'amber';
      case 'source':
      case 'sink':
        return 'emerald';
      default:
        return 'cyan';
    }
  }

  kindLabel(kind: NodeKind | undefined): string {
    const k = kind ?? 'task';
    return k.toUpperCase();
  }

  /**
   * Flatten the node's kind-specific config into a printable `key: value`
   * list the inspector can render without hard-coding every shape.
   */
  configSummary(node: CanonicalFlowNode): { key: string; value: string }[] {
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    const out: { key: string; value: string }[] = [];
    for (const [key, raw] of Object.entries(cfg)) {
      if (raw === null || raw === undefined) continue;
      let value: string;
      if (Array.isArray(raw)) {
        value = `[${raw.length}]`;
      } else if (typeof raw === 'object') {
        value = '{…}';
      } else {
        value = String(raw);
      }
      if (value.length > 48) value = value.slice(0, 45) + '…';
      out.push({ key, value });
    }
    return out;
  }
}

// Keep TypeScript from complaining about unused imports used only for typing.
export type { CanonicalFlowEdge };
