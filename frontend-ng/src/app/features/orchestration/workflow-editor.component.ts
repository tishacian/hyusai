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
import { Subscription, switchMap, takeWhile, timer } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import {
  CanonicalApiService,
  type Run,
  type Skill,
  type System,
} from '@app/core/canonical-api.service';
import {
  RunStreamService,
  type RunStreamEvent,
} from '@app/core/run-stream.service';
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
  /**
   * Optional stream id used by token_delta events (Vague D / D2) to
   * append deltas to a single entry instead of flooding the terminal
   * with one line per chunk. Typically the invocation id.
   */
  streamId?: string;
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
          style="letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:var(--ck-on-signal);"
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
        (click)="simulate()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        title="Client-side dry-run — no LLM calls, no backend invocation"
      >
        <app-icon name="play" [size]="14" /> Simulate
      </button>
      @if (systemId()) {
        <button
          actions
          type="button"
          (click)="toggleDebugMode()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium ring-1 ring-white/10 text-gray-200 transition"
          [class.bg-amber-500]="debugMode() !== 'off'"
          [class.hover:bg-amber-600]="debugMode() !== 'off'"
          [class.text-black]="debugMode() !== 'off'"
          [class.bg-white/5]="debugMode() === 'off'"
          [class.hover:bg-white/10]="debugMode() === 'off'"
          [title]="'Debug mode: ' + debugMode() + ' — click to cycle off / step / breakpoints'"
        >
          <app-icon name="bug" [size]="14" /> Debug: {{ debugMode() }}
        </button>
      }
      @if (systemId()) {
        <button
          actions
          type="button"
          (click)="executeOnBackend()"
          [disabled]="executing()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
          [style.opacity]="executing() ? '0.55' : '1'"
          [title]="debugMode() === 'off' ? 'Run this flow on the backend — real skill invocations, real Outcome' : 'Run with the debugger attached — walker will pause on steps / breakpoints'"
        >
          @if (executing()) {
            <app-icon name="loader-2" [size]="14" class="animate-spin" /> Running…
          } @else {
            <app-icon name="rocket" [size]="14" /> Execute
          }
        </button>
      }
      @if (systemId() && canReplay()) {
        <button
          actions
          type="button"
          (click)="replayRun()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          title="Replay the last completed run's checkpoints at cinematic pace"
        >
          <app-icon name="history" [size]="14" /> Replay
        </button>
      }
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
            <button (click)="autoLayout()" class="df-tool-btn" title="Auto-layout nodes (topological)">
              <app-icon name="layout-grid" [size]="14" />
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
              @if (currentRun()?.status === 'hitl_pending' && currentRun()?.hitl) {
                <div class="df-hitl-card" role="alertdialog">
                  <div class="df-hitl-head">
                    <app-icon name="user-check" [size]="14" class="text-amber-300" />
                    <span>Human approval required</span>
                    <span class="df-tag df-tag-warn">PAUSED</span>
                  </div>
                  <div class="df-hitl-prompt">{{ currentRun()?.hitl?.prompt ?? 'An operator must approve this step to continue.' }}</div>
                  @if (currentRun()?.hitl?.node_id) {
                    <div class="df-hitl-meta">
                      <span class="text-gray-500">Node</span>
                      <span class="text-gray-300 ck-mono">{{ currentRun()?.hitl?.node_id }}</span>
                    </div>
                  }
                  <div class="df-hitl-actions">
                    <button
                      type="button"
                      (click)="resolveHitl('reject')"
                      [disabled]="hitlResolving()"
                      class="df-hitl-btn df-hitl-btn--reject"
                    >
                      <app-icon name="x" [size]="12" /> Reject
                    </button>
                    <button
                      type="button"
                      (click)="resolveHitl('accept')"
                      [disabled]="hitlResolving()"
                      class="df-hitl-btn df-hitl-btn--accept"
                    >
                      <app-icon name="check" [size]="12" /> Approve
                    </button>
                  </div>
                </div>
              }
              @if (currentRun()?.status === 'debug_pending' && currentRun()?.debug) {
                <div class="df-hitl-card" role="alertdialog" data-tone="debug">
                  <div class="df-hitl-head">
                    <app-icon name="bug" [size]="14" class="text-cyan-300" />
                    <span>Debugger paused</span>
                    <span class="df-tag df-tag-cool">{{ currentRun()?.debug?.debug_mode ?? 'step' }}</span>
                  </div>
                  <div class="df-hitl-prompt">
                    Paused after
                    <span class="ck-mono text-cyan-200">{{ currentRun()?.debug?.node_id ?? 'node' }}</span>
                    — inspect context and advance.
                  </div>
                  <div class="df-debug-ctx">
                    <div class="df-debug-ctx-label">Last output</div>
                    <pre class="df-debug-ctx-body">{{ previewJson(currentRun()?.debug?.last_output) }}</pre>
                    <div class="df-debug-ctx-label">Context snapshot</div>
                    <pre class="df-debug-ctx-body">{{ previewJson(currentRun()?.debug?.ctx_snapshot) }}</pre>
                  </div>
                  <div class="df-hitl-actions">
                    <button
                      type="button"
                      (click)="debugAction('stop')"
                      [disabled]="debugStepping()"
                      class="df-hitl-btn df-hitl-btn--reject"
                    >
                      <app-icon name="square" [size]="12" /> Stop
                    </button>
                    <button
                      type="button"
                      (click)="debugAction('continue')"
                      [disabled]="debugStepping()"
                      class="df-hitl-btn"
                    >
                      <app-icon name="chevrons-right" [size]="12" /> Continue
                    </button>
                    <button
                      type="button"
                      (click)="debugAction('step')"
                      [disabled]="debugStepping()"
                      class="df-hitl-btn df-hitl-btn--accept"
                    >
                      <app-icon name="chevron-right" [size]="12" /> Step
                    </button>
                  </div>
                </div>
              }
              @if (terminalLog().length === 0 && currentRun()?.status !== 'hitl_pending' && currentRun()?.status !== 'debug_pending') {
                <div class="df-terminal-empty">
                  <span class="text-gray-500">›</span>
                  Execute a Run on this System to see live output. Click Simulate for a client-side dry run, or Execute to hit the backend.
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

                <!-- Debugger breakpoint toggle — only visible when debug mode is active -->
                @if (debugMode() !== 'off') {
                  <div class="df-inspector-section">
                    <label class="df-breakpoint-row">
                      <input
                        type="checkbox"
                        [checked]="isBreakpoint(selectedNode()!.id)"
                        (change)="toggleBreakpoint(selectedNode()!.id)"
                      />
                      <span class="text-xs text-gray-200">Break on this node</span>
                      @if (isBreakpoint(selectedNode()!.id)) {
                        <span class="df-tag df-tag-warn">BREAK</span>
                      }
                    </label>
                    <div class="text-[10px] text-gray-500 mt-1">
                      Breakpoints are sent to the walker at Execute time.
                    </div>
                  </div>
                }

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

                <!-- Skill binder — only for task kind -->
                @if ((selectedNode()!.kind ?? 'task') === 'task') {
                  <div class="df-inspector-section">
                    <div class="df-inspector-label">Bound skill</div>
                    <select
                      class="df-skill-select ck-mono"
                      [value]="currentSkillId(selectedNode()!) ?? ''"
                      (change)="onSkillBinderChange($event)"
                      (focus)="ensureSkillsLoaded()"
                    >
                      <option value="">— Unbound —</option>
                      @for (s of skills(); track s.id) {
                        <option [value]="s.id">{{ s.slug }} · {{ s.name }}</option>
                      }
                    </select>
                    @if (skillsLoading()) {
                      <div class="text-[10px] text-gray-500 mt-1.5 ck-mono">Loading catalog…</div>
                    } @else if (skills().length === 0) {
                      <div class="text-[10px] text-gray-500 mt-1.5">Focus the dropdown to load the skill catalog.</div>
                    } @else {
                      <div class="text-[10px] text-gray-500 mt-1.5">{{ skills().length }} skills available.</div>
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
  private readonly runStream = inject(RunStreamService);
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

  // Backend execution state — non-null while a Run is in flight against the
  // live System. ``hitlResolving`` blocks double-clicks on the approve /
  // reject buttons while the /hitl POST is on the wire.
  readonly executing = signal(false);
  readonly currentRun = signal<Run | null>(null);
  readonly hitlResolving = signal(false);
  // Step debugger — ``debugMode`` cycles off/step/breakpoints. ``breakpoints``
  // is a Set kept as a plain state; we materialise it into a signal through
  // `breakpointsSig` for change detection on template reads.
  readonly debugMode = signal<'off' | 'step' | 'breakpoints'>('off');
  readonly breakpointsSig = signal<string[]>([]);
  readonly debugStepping = signal(false);
  readonly canReplay = computed(() => {
    const r = this.currentRun();
    return !!r && (r.checkpoints?.length ?? 0) > 0;
  });
  private pollSub: Subscription | null = null;
  private streamSub: Subscription | null = null;
  private replayTimer: ReturnType<typeof setTimeout> | null = null;
  private seenInvocationIds = new Set<string>();
  private seenCheckpoints = new Set<string>();
  private streamFellBackToPoll = false;
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
    {
      id: 'router',
      label: 'Router · Classify → Dispatch',
      description: 'Decision splits traffic between two tools',
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
      id: 'parallel',
      label: 'Fork / Join · Parallel research',
      description: 'Fan out to 3 LLMs, join results',
      build: (add, connect) => {
        const a = add('input', 60, 260);
        const f = add('fork', 280, 260);
        const l1 = add('llm', 520, 140);
        const l2 = add('llm', 520, 260);
        const l3 = add('llm', 520, 380);
        const j = add('join', 760, 260);
        const o = add('output', 980, 260);
        connect(a, f);
        connect(f, l1);
        connect(f, l2);
        connect(f, l3);
        connect(l1, j);
        connect(l2, j);
        connect(l3, j);
        connect(j, o);
      },
    },
    {
      id: 'retry-loop',
      label: 'Retry + Loop · Self-healing',
      description: 'Loop with retry policy and HITL fallback',
      build: (add, connect) => {
        const a = add('input', 60, 240);
        const l = add('loop', 280, 240);
        const r = add('retry', 520, 240);
        const t = add('llm', 760, 160);
        const h = add('hitl', 760, 340);
        const o = add('output', 1000, 240);
        connect(a, l);
        connect(l, r);
        connect(r, t);
        connect(r, h);
        connect(t, o);
        connect(h, o);
      },
    },
    {
      id: 'hitl-review',
      label: 'HITL gate · Compliance',
      description: 'LLM draft → human review → commit',
      build: (add, connect) => {
        const a = add('input', 60, 240);
        const c = add('llm', 290, 240);
        const h = add('hitl', 540, 240);
        const g = add('guardrail', 790, 240);
        const o = add('output', 1040, 240);
        connect(a, c);
        connect(c, h);
        connect(h, g);
        connect(g, o);
      },
    },
    {
      id: 'subflow',
      label: 'Subflow · Nested pipeline',
      description: 'Trigger → Subflow → Output',
      build: (add, connect) => {
        const a = add('input', 60, 220);
        const s = add('subflow', 290, 220);
        const g = add('guardrail', 540, 220);
        const o = add('output', 790, 220);
        connect(a, s);
        connect(s, g);
        connect(g, o);
      },
    },
    {
      id: 'research-agent',
      label: 'Research agent · Plan → Execute',
      description: 'Decision → Retrieve OR Tool → LLM synthesis',
      build: (add, connect) => {
        const a = add('input', 60, 240);
        const d = add('router', 290, 240);
        const r = add('retrieve', 540, 140);
        const t = add('tool', 540, 340);
        const s = add('llm', 790, 240);
        const o = add('output', 1040, 240);
        connect(a, d);
        connect(d, r);
        connect(d, t);
        connect(r, s);
        connect(t, s);
        connect(s, o);
      },
    },
  ];

  // Skill binder state — loaded lazily on first inspector open.
  readonly skills = signal<Skill[]>([]);
  readonly skillsLoading = signal(false);
  readonly boundSkillId = signal<string | null>(null);

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
    this.stopStream();
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

  /**
   * Append a token delta to an existing streaming entry, or create a
   * new one when the first delta for an invocation arrives. Keeps the
   * Execution Terminal from exploding when an LLM emits dozens of
   * chunks per second — only the tail line grows, character-by-character.
   */
  private appendStreamToken(
    streamId: string,
    delta: string,
    tag: string,
    tone: TerminalEntry['tone'],
  ): void {
    if (!delta) return;
    this.terminalLog.update((log) => {
      for (let i = log.length - 1; i >= 0; i--) {
        if (log[i].streamId === streamId) {
          const next = [...log];
          next[i] = { ...next[i], text: next[i].text + delta };
          return next;
        }
      }
      const t = new Date().toTimeString().slice(0, 8);
      const next = [...log, { t, tag, tone, text: delta, streamId }];
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

  /**
   * Client-side dry-run — stamps a few synthetic lines into the terminal
   * so designers can sketch flows without hitting the backend. Real
   * execution flows through :method:`executeOnBackend`.
   */
  simulate(): void {
    if (this.nodeCount() === 0) {
      this.toastr.warning('Add at least one node before simulating.', 'Simulate');
      return;
    }
    this.terminalOpen.set(true);
    this.pushTerminal({ tone: 'cyan', tag: 'SIM', text: 'Client-side simulation — no backend call.' });
    this.pushTerminal({ tone: 'info', tag: 'PLAN', text: `${this.nodeCount()} nodes · ${this.edgeCount()} edges` });
    this.pushTerminal({ tone: 'pos', tag: 'DONE', text: 'Simulation finished.' });
    this.toastr.success('Client-side dry-run — switch to Execute to run on the backend.', 'Simulated');
  }

  /**
   * Execute the current System on the backend and surface events in the
   * Execution Terminal via polling. The Run is persisted server-side so
   * the cockpit's /runs views reflect it immediately.
   *
   * Polling cadence: 1500ms. Stops once the Run reaches a terminal state
   * (``completed | failed | cancelled``) or ``hitl_pending`` — in which
   * case the HITL card becomes the next interaction surface.
   */
  executeOnBackend(): void {
    const sid = this.systemId();
    if (!sid) {
      this.toastr.info('Save this flow to a System first — /orchestration scratchpad cannot Execute.', 'Execute');
      return;
    }
    if (this.executing()) return;
    if (this.errorCount() > 0) {
      this.toastr.warning('Fix validation errors before running — the backend will reject an invalid DAG.', 'Execute');
      return;
    }
    this.stopStream();
    this.terminalOpen.set(true);
    this.seenInvocationIds.clear();
    this.seenCheckpoints.clear();
    this.streamFellBackToPoll = false;
    this.pushTerminal({ tone: 'cyan', tag: 'EXEC', text: 'Dispatching run to backend…' });
    this.executing.set(true);

    const mode = this.debugMode();
    const trigger$ =
      mode === 'off'
        ? this.canonical.triggerRun(sid, {})
        : this.canonical.triggerRunDebug(sid, {
            mode,
            breakpoints: this.breakpointsSig(),
          });
    if (mode !== 'off') {
      this.pushTerminal({
        tone: 'warn',
        tag: 'DEBUG',
        text: `Debugger attached · mode=${mode} · breakpoints=${this.breakpointsSig().length}`,
      });
    }

    trigger$.subscribe({
      next: (run) => {
        if (!run) {
          this.executing.set(false);
          this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'Backend rejected the trigger request.' });
          this.toastr.error('Could not trigger a run — check backend logs.', 'Execute failed');
          return;
        }
        this.currentRun.set(run);
        this.pushTerminal({
          tone: 'info',
          tag: 'RUN',
          text: `Run ${run.id.slice(0, 8)}… scheduled (status=${run.status}).`,
        });
        this.startStreaming(run.id);
      },
      error: () => {
        this.executing.set(false);
        this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'Network error while triggering run.' });
        this.toastr.error('Could not reach the backend.', 'Execute failed');
      },
    });
  }

  // ---------------------------------------------------------------------
  // Step debugger actions
  // ---------------------------------------------------------------------

  /** Cycle the debug mode through off → step → breakpoints → off.
   *  When switching to ``breakpoints`` with no flags set, we coach the
   *  operator towards the Node Inspector to mark one. */
  toggleDebugMode(): void {
    const m = this.debugMode();
    const next = m === 'off' ? 'step' : m === 'step' ? 'breakpoints' : 'off';
    this.debugMode.set(next);
    if (next === 'breakpoints' && this.breakpointsSig().length === 0) {
      this.toastr.info(
        'Mark breakpoints from the Node Inspector (checkbox at the top of a selected node).',
        'Debugger',
      );
    }
  }

  isBreakpoint(nodeId: string): boolean {
    return this.breakpointsSig().includes(nodeId);
  }

  /** Toggle a breakpoint on the given node. When the debugger is already
   *  running and paused on this node, the new set is pushed to the backend
   *  on the next Step / Continue. */
  toggleBreakpoint(nodeId: string): void {
    const set = new Set(this.breakpointsSig());
    if (set.has(nodeId)) set.delete(nodeId);
    else set.add(nodeId);
    this.breakpointsSig.set([...set]);
  }

  /** Send a debugger step / continue / stop to the backend; on a successful
   *  Step or Continue we reopen the SSE stream so resumed events land live.
   */
  debugAction(action: 'step' | 'continue' | 'stop'): void {
    const run = this.currentRun();
    if (!run || run.status !== 'debug_pending') return;
    if (this.debugStepping()) return;
    this.debugStepping.set(true);
    this.pushTerminal({
      tone: action === 'stop' ? 'neg' : 'cyan',
      tag: 'DEBUG',
      text: `Operator → ${action}${
        action === 'continue' && this.breakpointsSig().length
          ? ` (breakpoints=${this.breakpointsSig().length})`
          : ''
      }`,
    });
    this.canonical
      .stepRun(run.id, { action, breakpoints: this.breakpointsSig() })
      .subscribe({
        next: (updated) => {
          this.debugStepping.set(false);
          if (!updated) {
            this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'Debugger rejected by backend.' });
            return;
          }
          if (action === 'stop') {
            this.executing.set(false);
            this.canonical.getRun(run.id).subscribe((r) => {
              if (r) this.currentRun.set(r);
            });
            return;
          }
          // Reopen the live stream so the resumed walker's events land in
          // the terminal.
          this.executing.set(true);
          this.seenCheckpoints.clear();
          this.startStreaming(run.id);
        },
        error: () => {
          this.debugStepping.set(false);
          this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'Network error during debug action.' });
        },
      });
  }

  // ---------------------------------------------------------------------
  // Outcome replay — cinematic playback of a finished run's checkpoints
  // ---------------------------------------------------------------------

  /** Replay the current run's checkpoints as if they were arriving live.
   *  Useful for demos and for inspecting a run post-mortem without having
   *  to rerun the DAG. */
  replayRun(): void {
    if (this.replayTimer) {
      clearTimeout(this.replayTimer);
      this.replayTimer = null;
    }
    const run = this.currentRun();
    if (!run) return;
    const checkpoints = (run.checkpoints ?? []) as Array<
      Record<string, unknown> & { kind?: string }
    >;
    if (checkpoints.length === 0) {
      this.toastr.info('No checkpoints to replay on this run.', 'Replay');
      return;
    }
    this.terminalOpen.set(true);
    this.terminalLog.set([]);
    this.pushTerminal({
      tone: 'cyan',
      tag: 'REPLAY',
      text: `Replaying ${checkpoints.length} checkpoints from run ${run.id.slice(0, 8)}…`,
    });

    const stepDelayMs = 380;
    const playNext = (i: number) => {
      if (i >= checkpoints.length) {
        this.pushTerminal({ tone: 'pos', tag: 'REPLAY', text: 'Replay done.' });
        return;
      }
      const cp = checkpoints[i];
      this.emitStreamEvent(run.id, {
        event: String(cp['kind'] ?? 'event'),
        data: cp,
      });
      this.replayTimer = setTimeout(() => playNext(i + 1), stepDelayMs);
    };
    playNext(0);
  }

  /** Tiny JSON previewer for the debug card — caps depth + length so a
   *  rogue skill output can't blow up the panel. */
  previewJson(value: unknown): string {
    if (value === undefined || value === null) return '— no data —';
    try {
      const json = JSON.stringify(value, null, 2);
      return json.length > 1400 ? json.slice(0, 1400) + '\n… (truncated)' : json;
    } catch {
      return String(value);
    }
  }

  /** Accept or reject the HITL Decision pinned on the current run, then
   * restart polling so the resumed DAG's events flow back into the UI. */
  resolveHitl(action: 'accept' | 'reject'): void {
    const run = this.currentRun();
    if (!run || run.status !== 'hitl_pending' || !run.hitl) return;
    if (this.hitlResolving()) return;
    this.hitlResolving.set(true);
    this.pushTerminal({
      tone: action === 'accept' ? 'pos' : 'warn',
      tag: 'HITL',
      text: `Operator ${action === 'accept' ? 'approved' : 'rejected'} the pending step.`,
    });
        this.canonical.resolveRunHitl(run.id, { action }).subscribe({
      next: (updated) => {
        this.hitlResolving.set(false);
        if (!updated) {
          this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'HITL resolve rejected by backend.' });
          this.toastr.error('Backend rejected the HITL resolution.', 'HITL');
          return;
        }
        // Resume spawns a fresh execution phase — reopen a new SSE stream
        // so node_start / node_end events from the resumed walk land in
        // the terminal in real time.
        this.seenCheckpoints.clear();
        this.startStreaming(run.id);
      },
      error: () => {
        this.hitlResolving.set(false);
        this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'Network error during HITL resolve.' });
      },
    });
  }

  /**
   * Subscribe to the backend SSE stream for this Run. Each event fans out
   * to :method:`emitStreamEvent` which produces a terminal line and keeps
   * the ``currentRun`` signal in sync. On transport error we transparently
   * fall back to the legacy 1.5s polling loop so the UI never gets stuck.
   */
  private startStreaming(runId: string): void {
    this.stopStream();
    this.streamSub = this.runStream.streamRun(runId).subscribe({
      next: (event) => this.emitStreamEvent(runId, event),
      error: () => {
        // Transport died (proxy quirks, network blip, CORS). Degrade to
        // polling once; if that also fails we show a terminal error.
        if (!this.streamFellBackToPoll) {
          this.streamFellBackToPoll = true;
          this.pushTerminal({
            tone: 'warn',
            tag: 'STREAM',
            text: 'Live stream interrupted — falling back to polling.',
          });
          this.startPolling(runId);
        } else {
          this.executing.set(false);
          this.pushTerminal({
            tone: 'neg',
            tag: 'ERR',
            text: 'Lost connection to the backend (stream + poll).',
          });
        }
      },
      complete: () => {
        // Stream ended cleanly; one final fetch to refresh outcome +
        // HITL payload in the inspector before releasing the UI.
        this.canonical.getRun(runId).subscribe((r) => {
          if (r) {
            const prev = this.currentRun();
            this.currentRun.set(r);
            this.emitDeltaEvents(prev, r);
          }
          this.executing.set(false);
        });
      },
    });
  }

  private stopStream(): void {
    if (this.streamSub) {
      this.streamSub.unsubscribe();
      this.streamSub = null;
    }
    if (this.replayTimer) {
      clearTimeout(this.replayTimer);
      this.replayTimer = null;
    }
    this.stopPolling();
  }

  /**
   * Map one SSE event to a terminal entry and a minimal state update.
   * Dedupes by checkpoint timestamp so the replay-then-live phase
   * doesn't double-log the first few events.
   */
  private emitStreamEvent(runId: string, event: RunStreamEvent): void {
    const data = event.data as {
      t?: string;
      kind?: string;
      node_id?: string;
      node_kind?: string;
      label?: string;
      status?: string;
      skill_slug?: string;
      latency_ms?: number;
      cost?: number;
      error?: string;
      chosen_branch?: string;
      reason?: string;
      outcome?: Run['outcome'];
      checkpoints_emitted?: number;
      invocation_id?: string;
      text?: string;
      seq?: number;
    };
    const ts = data.t;
    if (typeof ts === 'string') {
      const key = `${event.event}:${ts}:${data.node_id ?? ''}`;
      if (this.seenCheckpoints.has(key)) return;
      this.seenCheckpoints.add(key);
    }

    switch (event.event) {
      case 'run_start':
        this.pushTerminal({ tone: 'info', tag: 'START', text: 'Walker booted — executing DAG.' });
        break;
      case 'node_start': {
        const label = data.label ?? data.node_id ?? 'node';
        const tag = (data.node_kind ?? 'NODE').toUpperCase();
        this.pushTerminal({
          tone: 'info',
          tag,
          text: `▶ ${label}${data.skill_slug ? ` · ${data.skill_slug}` : ''}`,
        });
        break;
      }
      case 'node_end': {
        const label = data.label ?? data.node_id ?? 'node';
        const tag = (data.node_kind ?? 'NODE').toUpperCase();
        const status = data.status;
        const latency = data.latency_ms != null ? ` · ${Math.round(data.latency_ms)}ms` : '';
        const branch = data.chosen_branch ? ` · branch=${data.chosen_branch}` : '';
        const tone: TerminalEntry['tone'] =
          status === 'failed' ? 'neg' : status === 'completed' ? 'pos' : 'info';
        this.pushTerminal({
          tone,
          tag,
          text: `◼ ${label}${status ? ` · ${status}` : ''}${latency}${branch}${
            data.error ? ` · ${data.error.slice(0, 80)}` : ''
          }`,
        });
        break;
      }
      case 'hitl_pause':
        this.pushTerminal({
          tone: 'warn',
          tag: 'HITL',
          text: `⏸ Paused on ${data.label ?? data.node_id ?? 'hitl gate'} — awaiting operator.`,
        });
        // Fetch the full run to populate the HITL card; the stream has
        // closed, so polling/stream restart isn't needed until the
        // operator hits Approve / Reject.
        this.canonical.getRun(runId).subscribe((r) => {
          if (r) this.currentRun.set(r);
          this.executing.set(false);
        });
        break;
      case 'hitl_resume':
        this.pushTerminal({
          tone: 'info',
          tag: 'HITL',
          text: `▶ Resumed from ${data.node_id ?? 'gate'}.`,
        });
        break;
      case 'debug_pause':
        this.pushTerminal({
          tone: 'warn',
          tag: 'DEBUG',
          text: `⏸ Paused after ${data.node_id ?? 'node'} — open Inspector to continue.`,
        });
        // Close the stream and refresh the run so the Debugger card fills in
        // with ctx_snapshot / last_output.
        this.canonical.getRun(runId).subscribe((r) => {
          if (r) this.currentRun.set(r);
          this.executing.set(false);
        });
        break;
      case 'debug_resume':
        this.pushTerminal({
          tone: 'cyan',
          tag: 'DEBUG',
          text: `▶ Resumed from ${data.node_id ?? 'node'} · action=${(data as { action?: string }).action ?? '—'}`,
        });
        break;
      case 'run_end':
        this.pushTerminal({
          tone: data.status === 'completed' ? 'pos' : 'neg',
          tag: 'END',
          text: `Run finished · status=${data.status ?? 'unknown'}`,
        });
        break;
      case 'snapshot':
        // Update the local state shape so the inspector's outcome tile
        // and status pulse reflect the server without a second request.
        if (data.status || data.outcome) {
          const prev = this.currentRun();
          if (prev) {
            this.currentRun.set({ ...prev, status: (data.status as Run['status']) ?? prev.status, outcome: data.outcome ?? prev.outcome });
          }
        }
        break;
      case 'token_delta': {
        // Live LLM chunks (Vague D / D2). Group by invocation id so
        // each streaming node owns exactly one terminal line that
        // grows in place instead of flooding the log.
        const streamId = data.invocation_id ?? data.node_id ?? runId;
        this.appendStreamToken(streamId, data.text ?? '', 'LLM', 'cyan');
        break;
      }
      case 'close':
        // Noop — stream will `complete()` right after this frame.
        break;
      case 'error':
        this.pushTerminal({ tone: 'neg', tag: 'ERR', text: data.reason ?? 'Stream error.' });
        break;
      default:
        // Unknown event — log raw for debug visibility.
        this.pushTerminal({ tone: 'info', tag: event.event.toUpperCase().slice(0, 10), text: JSON.stringify(data).slice(0, 120) });
    }
  }

  private startPolling(runId: string): void {
    this.stopPolling();
    this.pollSub = timer(0, 1500)
      .pipe(
        switchMap(() => this.canonical.getRun(runId)),
        takeWhile(
          (r) => !!r && !this.isTerminalRunState(r.status) && !this.isPausedState(r.status),
          true,
        ),
      )
      .subscribe({
        next: (r) => {
          if (!r) return;
          const prev = this.currentRun();
          this.currentRun.set(r);
          this.emitDeltaEvents(prev, r);
          if (this.isTerminalRunState(r.status) || this.isPausedState(r.status)) {
            this.executing.set(false);
            this.stopPolling();
          }
        },
        error: () => {
          this.executing.set(false);
          this.stopPolling();
          this.pushTerminal({ tone: 'neg', tag: 'ERR', text: 'Lost connection while polling run.' });
        },
      });
  }

  private stopPolling(): void {
    if (this.pollSub) {
      this.pollSub.unsubscribe();
      this.pollSub = null;
    }
  }

  private isTerminalRunState(
    status: Run['status'] | undefined,
  ): boolean {
    return status === 'completed' || status === 'failed' || status === 'cancelled';
  }

  /** Shared predicate for the polling loop so both hitl_pending and
   *  debug_pending correctly short-circuit out of the tick. */
  private isPausedState(status: Run['status'] | undefined): boolean {
    return status === 'hitl_pending' || status === 'debug_pending';
  }

  /** Emit terminal lines for each new SkillInvocation delta and any
   * status transition. Keeps the terminal conversational without
   * hammering it when the polling tick brings back the same snapshot.
   */
  private emitDeltaEvents(prev: Run | null, next: Run): void {
    if (!prev || prev.status !== next.status) {
      this.pushTerminal({
        tone: this.toneForStatus(next.status),
        tag: 'STATUS',
        text: `Run ${next.id.slice(0, 8)} → ${next.status}`,
      });
    }
    const invocations = next.skill_invocations ?? [];
    for (const inv of invocations) {
      if (!inv.id || this.seenInvocationIds.has(inv.id)) continue;
      if (inv.status === 'running') continue;
      this.seenInvocationIds.add(inv.id);
      this.pushTerminal({
        tone:
          inv.status === 'completed'
            ? 'pos'
            : inv.status === 'failed'
              ? 'neg'
              : 'warn',
        tag: inv.skill_slug?.slice(0, 14).toUpperCase() ?? 'SKILL',
        text: `${inv.status} · ${Math.round(inv.latency_ms ?? 0)}ms${
          inv.error ? ' · ' + inv.error.slice(0, 80) : ''
        }`,
      });
    }
    if (this.isTerminalRunState(next.status) && next.outcome) {
      const o = next.outcome;
      this.pushTerminal({
        tone: next.status === 'completed' ? 'pos' : 'neg',
        tag: 'OUTCOME',
        text: `decision=${o.decision ?? '—'} · confidence=${
          o.confidence != null ? o.confidence.toFixed(2) : '—'
        } · cost=${o.cost_internal != null ? o.cost_internal.toFixed(4) : '—'}`,
      });
    }
  }

  private toneForStatus(status: Run['status']): TerminalEntry['tone'] {
    switch (status) {
      case 'completed':
        return 'pos';
      case 'failed':
      case 'cancelled':
        return 'neg';
      case 'hitl_pending':
        return 'warn';
      case 'running':
        return 'cyan';
      default:
        return 'info';
    }
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

  // ---------- Skills binder ----------

  /** Load the skill catalog once. Called when the inspector first shows
   *  a task node that has no skill bound. Idempotent. */
  ensureSkillsLoaded(): void {
    if (this.skills().length > 0 || this.skillsLoading()) return;
    this.skillsLoading.set(true);
    this.canonical.listSkills().subscribe({
      next: (rows) => {
        this.skills.set(rows ?? []);
        this.skillsLoading.set(false);
      },
      error: () => {
        this.skillsLoading.set(false);
        this.toastr.warning('Could not load skill catalog — binder offline.', 'Inspector');
      },
    });
  }

  /**
   * Bind / unbind a Skill on the currently selected task node. Writes
   * `canonical_config.skill_id` + `skill_slug` on the Drawflow node
   * data so the next project() picks it up and serializes it.
   */
  bindSkill(skillId: string | null): void {
    const rawId = this.selectedNodeId();
    const node = this.selectedNode();
    if (!rawId || !node || !this.editor) return;
    const nodeData = this.exportGraph()?.drawflow?.Home?.data?.[rawId];
    if (!nodeData) return;
    const skill = this.skills().find((s) => s.id === skillId) ?? null;
    const nextConfig: Record<string, unknown> = {
      ...((nodeData.data?.['canonical_config'] as Record<string, unknown>) ?? {}),
      skill_id: skill?.id ?? null,
      skill_slug: skill?.slug ?? null,
    };
    const nextData = {
      ...(nodeData.data ?? {}),
      canonical_config: nextConfig,
    };
    try {
      this.editor.updateNodeDataFromId(rawId, nextData);
    } catch {
      return;
    }
    this.boundSkillId.set(skill?.id ?? null);
    this.selectedNode.set({
      ...node,
      config: nextConfig as CanonicalFlowNode['config'],
    });
    this.refreshKpis();
    if (skill) {
      this.toastr.success(`Bound "${skill.name}" (${skill.slug})`, 'Skill');
    } else {
      this.toastr.info('Skill unbound', 'Skill');
    }
  }

  onSkillBinderChange(ev: Event): void {
    const value = (ev.target as HTMLSelectElement | null)?.value ?? '';
    this.bindSkill(value || null);
  }

  // ---------- Auto-layout (topological layered) ----------

  /**
   * Reposition every node using a simple layered topological layout.
   * Pure JavaScript — no dagre dependency. Good enough for <100 nodes.
   */
  autoLayout(): void {
    if (!this.editor) return;
    const graph = this.exportGraph();
    const flow = this.serializer.project(graph);
    const order = this.serializer.topoSort(flow);
    if (!order) {
      this.toastr.warning('Auto-layout refused — flow has a cycle.', 'Layout');
      return;
    }

    // Assign each node to a layer = 1 + max(layer of predecessors).
    const layer = new Map<string, number>();
    flow.nodes.forEach((n) => layer.set(n.id, 0));
    const preds = new Map<string, string[]>();
    flow.nodes.forEach((n) => preds.set(n.id, []));
    flow.edges.forEach((e) => {
      if (preds.has(e.to)) preds.get(e.to)!.push(e.from);
    });
    for (const id of order) {
      const ps = preds.get(id) ?? [];
      const d = ps.length === 0 ? 0 : Math.max(...ps.map((p) => (layer.get(p) ?? 0) + 1));
      layer.set(id, d);
    }

    // Group by layer and spread vertically within each layer.
    const byLayer = new Map<number, string[]>();
    layer.forEach((l, id) => {
      if (!byLayer.has(l)) byLayer.set(l, []);
      byLayer.get(l)!.push(id);
    });

    const COL_W = 260;
    const ROW_H = 140;
    const START_X = 60;
    const START_Y = 80;

    // Find drawflow numeric id per canonical id.
    const canonicalToNum = new Map<string, string>();
    for (const [key, node] of Object.entries(graph.drawflow?.Home?.data ?? {})) {
      const cid = (node.data?.['canonical_id'] as string) || `flow.${key}`;
      canonicalToNum.set(cid, key);
    }

    let moved = 0;
    byLayer.forEach((ids, l) => {
      ids.forEach((id, row) => {
        const num = canonicalToNum.get(id);
        if (!num) return;
        const x = START_X + l * COL_W;
        const y = START_Y + row * ROW_H;
        try {
          const dn = graph.drawflow?.Home?.data?.[num];
          if (dn) {
            dn.pos_x = x;
            dn.pos_y = y;
          }
          const el = document.getElementById(`node-${num}`);
          if (el) {
            (el as HTMLElement).style.left = `${x}px`;
            (el as HTMLElement).style.top = `${y}px`;
          }
          moved += 1;
        } catch {
          // continue
        }
      });
    });

    try {
      // Redraw connections after moving nodes.
      this.editor.updateConnectionNodes?.('node-*');
    } catch {
      // noop
    }
    this.toastr.success(`${moved} nodes rearranged.`, 'Auto-layout');
    this.refreshKpis();
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

  /** Currently bound skill id on a node's config, if any. */
  currentSkillId(node: CanonicalFlowNode): string | null {
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    const id = cfg['skill_id'];
    return typeof id === 'string' && id.length > 0 ? id : null;
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
