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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
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
  type SystemExportEnvelope,
  type SystemImportReport,
  type SystemVersionFull,
  type SystemVersionSummary,
  type System,
  type FlowManifestUnit,
  type FlowRuntimeManifest,
} from '@app/core/canonical-api.service';
import {
  RunStreamService,
  type RunStreamEvent,
} from '@app/core/run-stream.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { FlowCanvasToolbarComponent } from './flow-canvas-toolbar.component';
import { FlowPaletteComponent } from './flow-palette.component';
import { FlowSelectComponent, type FlowSelectOption } from './flow-select.component';
import { FlowTerminalComponent } from './flow-terminal.component';
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
type ConfigSheetTab = 'overview' | 'config' | 'prompts' | 'runtime';

interface PromptBlock {
  key: string;
  title: string;
  body: string;
  source: 'node' | 'flow';
  path: string;
  editable: boolean;
}

export interface PaletteItem {
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
export interface TerminalEntry {
  id: string;
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

export interface FlowTemplate {
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
  imports: [
    IconComponent,
    CkObjectHeaderComponent,
    StatusPulseComponent,
    RouterLink,
    FlowCanvasToolbarComponent,
    FlowPaletteComponent,
    FlowSelectComponent,
    FlowTerminalComponent,
  ],
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
      @if (systemId()) {
        <button
          actions
          type="button"
          (click)="openVersionsPanel()"
          [class.bg-white/5]="!versionsPanelOpen()"
          [class.bg-brand-500/20]="versionsPanelOpen()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          title="Browse version history — roll back to any prior snapshot."
        >
          <app-icon name="history" [size]="14" /> Versions
        </button>
      }
      @if (systemId()) {
        <button
          actions
          type="button"
          (click)="exportCurrentSystem()"
          [disabled]="exporting()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          title="Download this system as a portable JSON envelope (no DB IDs, skills referenced by slug)."
        >
          <app-icon name="download" [size]="14" /> Export
        </button>
      }
      <button
        actions
        type="button"
        (click)="openImportModal()"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
        title="Import a chain from a JSON envelope. Skills are rebound by slug against the current workspace."
      >
        <app-icon name="upload" [size]="14" /> Import
      </button>
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

    <section class="t-card rounded-md px-4 py-3 mb-3 flex items-center gap-2 text-xs text-gray-300">
      <span class="ck-mono text-[10px] uppercase tracking-[0.14em] text-gray-500">You are here</span>
      <span class="text-gray-600">/</span>
      <a routerLink="/systems" class="hover:text-white">Systems</a>
      @if (system(); as sys) {
        <span class="text-gray-600">/</span>
        <a [routerLink]="['/systems', sys.id]" class="text-brand-200 hover:text-brand-100">{{ sys.name }}</a>
        <span class="text-gray-600">/</span>
        <span class="text-white">Flow builder</span>
        @if (sys.context_id) {
          <span class="text-gray-600">/</span>
          <span title="Context in scope">Context linked</span>
        }
      } @else {
        <span class="text-gray-600">/</span>
        <span class="text-white">Scratchpad flow</span>
      }
    </section>

    @if (flowManifest(); as manifest) {
      <section class="df-runtime-manifest t-card t-elevated rounded-md px-4 py-3 mb-3">
        <div class="df-runtime-manifest__head">
          <div>
            <div class="ck-mono text-[10px] uppercase tracking-[0.14em] text-brand-300">Runtime manifest</div>
            <div class="text-sm font-medium text-white mt-1">
              {{ manifest.runtime_mode === 'chat_runtime' ? 'Workspace chat' : 'Run engine DAG' }}
              @if (manifest.live_surface) {
                <span class="ck-mono text-[11px] text-gray-500">· {{ manifest.live_surface }}</span>
              }
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="df-tag" [attr.data-tone]="manifest.operational_sync ? 'pos' : 'cool'">
              {{ manifest.operational_sync ? 'LIVE SYNC' : 'DAG RUNTIME' }}
            </span>
            @if (flowManifestLoading()) {
              <span class="df-tag df-tag-cool"><app-icon name="loader-2" [size]="10" class="animate-spin" /> REFRESH</span>
            }
          </div>
        </div>

        <div class="df-runtime-grid">
          <div class="df-runtime-card">
            <span class="df-runtime-card__label">Units</span>
            <strong>{{ manifest.summary?.operational_units ?? 0 }}/{{ manifest.summary?.nodes ?? 0 }}</strong>
            <span>{{ manifest.summary?.editable_parameters ?? 0 }} params</span>
          </div>
          <div class="df-runtime-card">
            <span class="df-runtime-card__label">Source</span>
            <strong>{{ manifest.source || 'flow' }}</strong>
            <span>{{ manifest.schema_version ? 'schema v' + manifest.schema_version : 'schema —' }}</span>
          </div>
          <div class="df-runtime-card df-runtime-card--wide">
            <span class="df-runtime-card__label">Effective config</span>
            @if (manifestEffectiveRows().length === 0) {
              <span class="text-gray-500">No flow overrides</span>
            } @else {
              <div class="df-runtime-kv">
                @for (row of manifestEffectiveRows(); track row.key) {
                  <span>{{ row.key }}</span>
                  <strong>{{ row.value }}</strong>
                }
              </div>
            }
          </div>
        </div>

        @if (manifestUnitsPreview().length > 0) {
          <div class="df-runtime-units">
            @for (unit of manifestUnitsPreview(); track unit.id) {
              <button
                type="button"
                class="df-runtime-unit"
                [attr.data-active]="unit.operational ? 'true' : 'false'"
                [title]="unit.runtime_ref || unit.skill_slug || unit.description || unit.id"
                (mousedown)="selectManifestUnit(unit)"
                (click)="selectManifestUnit(unit)"
              >
                <span>{{ unit.label }}</span>
                <small>{{ unit.skill_slug || unit.unit_type || unit.kind }}</small>
              </button>
            }
          </div>
        }
      </section>
    }

    <div class="grid grid-cols-1 gap-3 df-shell" [attr.data-inspector]="inspectorOpen() ? 'open' : 'closed'">
      <app-flow-palette
        [palette]="palette"
        [templates]="flowTemplates"
        (addNode)="addNodeAtCenter($event)"
        (loadTemplate)="loadTemplate($event)"
        (dragStart)="onPaletteDragStart($event)"
      />

      <!-- Canvas + Terminal column -->
      <div
        class="t-card t-elevated rounded-md overflow-hidden relative df-canvas-card"
      >
        <app-flow-canvas-toolbar
          [nodeCount]="nodeCount()"
          [errorCount]="errorCount()"
          [warnCount]="warnCount()"
          [terminalOpen]="terminalOpen()"
          [inspectorOpen]="inspectorOpen()"
          (zoom)="zoom($event)"
          (zoomReset)="zoomReset()"
          (fit)="fitCanvas()"
          (autoLayout)="autoLayout()"
          (toggleTerminal)="toggleTerminal()"
          (toggleInspector)="toggleInspector()"
          (clearAll)="clearAll()"
        />

        <!-- Drawflow host -->
        <div
          #drawflowContainer
          class="w-full h-full pt-10 df-host"
          (dragover)="onDragOver($event)"
          (drop)="onDrop($event)"
        ></div>

        <!-- Execution Terminal -->
        @if (terminalOpen()) {
          <app-flow-terminal
            [entries]="terminalLog()"
            [run]="currentRun()"
            [hitlResolving]="hitlResolving()"
            [debugStepping]="debugStepping()"
            (clear)="clearTerminal()"
            (collapse)="toggleTerminal()"
            (resolveHitl)="resolveHitl($event)"
            (debugAction)="debugAction($event)"
          />
        }

        @if (loading()) {
          <div class="absolute inset-0 flex flex-col items-center justify-center text-sm text-gray-400 bg-black/20 pointer-events-none">
            <app-icon name="loader-2" [size]="18" class="animate-spin text-brand-400 mb-2" />
            {{ loadPhase() }}
            @if (perfSummary()) {
              <div class="mt-1 text-[10px] text-gray-500 ck-mono">{{ perfSummary() }}</div>
            }
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
        <aside class="t-card t-elevated rounded-md overflow-hidden df-inspector-card">
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
                  Select a node to inspect its skill contract and configuration. Use Fit if the graph is off-screen.
                </div>
              </div>
            } @else {
              <div class="df-inspector-body">
                <!-- Title (editable label — Vague E / E3.3) -->
                <input
                  type="text"
                  class="df-inspector-title"
                  [value]="selectedNode()!.label || selectedNode()!.type"
                  (change)="onNodeLabelChange($event)"
                  [placeholder]="selectedNode()!.type"
                  maxlength="120"
                  title="Rename this node"
                />
                <div class="ck-mono text-[10px] text-gray-500 mt-1">id: {{ selectedNode()!.id }}</div>

                <div class="df-inspector-actions">
                  <button type="button" class="df-primary-soft-btn" (click)="openConfigSheet('config')">
                    <app-icon name="settings-2" [size]="13" /> Configure
                  </button>
                  <button type="button" class="df-ghost-btn" (click)="openConfigSheet('prompts')">
                    <app-icon name="file-text" [size]="12" /> Instructions {{ promptBlocks().length }}
                  </button>
                </div>

                @if (selectedManifestUnit(); as unit) {
                  <div class="df-inspector-section">
                    <div class="df-inspector-label">Runtime unit</div>
                    <div class="df-runtime-unit-card">
                      <div class="df-runtime-unit-card__head">
                        <div>
                          <strong>{{ unit.label }}</strong>
                          <span>{{ unit.description || unit.id }}</span>
                        </div>
                        <span class="df-tag" [attr.data-tone]="unit.operational ? 'pos' : 'info'">
                          {{ unit.operational ? 'OPERATIONAL' : 'MANIFEST' }}
                        </span>
                      </div>
                      @if (selectedManifestRows().length > 0) {
                        <div class="df-inspector-config ck-mono">
                          @for (row of selectedManifestRows(); track row.key) {
                            <div class="df-config-row">
                              <span class="text-gray-400">{{ row.key }}</span>
                              <span class="text-gray-200">{{ row.value }}</span>
                            </div>
                          }
                        </div>
                      }
                      @if (selectedManifestFieldRows().length > 0) {
                        <div class="df-runtime-fields">
                          @for (field of selectedManifestFieldRows(); track field.key) {
                            <div class="df-runtime-field">
                              <div>
                                <span>{{ field.key }}</span>
                                <small>{{ field.source }}</small>
                              </div>
                              <strong>{{ field.value }}</strong>
                            </div>
                          }
                        </div>
                      }
                    </div>
                  </div>
                }

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
                  <div class="df-inspector-section df-inspector-section--editor">
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
                    @if (!currentSkillId(selectedNode()!)) {
                      <div class="mt-2 rounded bg-amber-500/10 border border-amber-400/20 px-2 py-1.5 text-[10px] text-amber-100 leading-relaxed">
                        This task is not bound to a Skill yet. Bind one to unlock typed parameters and execution semantics.
                      </div>
                    }
                  </div>
                }

                <!-- Kind-specific config editor (Vague E / E3.3) -->
                <div class="df-inspector-section df-inspector-section--editor">
                  <div class="df-inspector-label">Config · {{ kindLabel(selectedNode()!.kind) }}</div>

                  @switch (selectedNode()!.kind ?? 'task') {
                    <!-- DECISION: branch label + condition rows, drop / add -->
                    @case ('decision') {
                      <div class="df-kind-editor">
                        <div class="df-field-hint">Each branch emits a <span class="ck-mono text-brand-300">branch</span> edge whose label is routed by the condition.</div>
                        @for (b of decisionBranches(); track $index) {
                          <div class="df-branch-row">
                            <input
                              type="text"
                              class="df-input df-input--mono"
                              [value]="b.label"
                              (change)="patchDecisionBranch($index, 'label', $event)"
                              placeholder="branch label"
                              maxlength="64"
                            />
                            <input
                              type="text"
                              class="df-input"
                              [value]="b.condition"
                              (change)="patchDecisionBranch($index, 'condition', $event)"
                              placeholder="context.score > 0.5"
                              maxlength="240"
                            />
                            <button
                              type="button"
                              class="df-icon-btn"
                              (click)="removeDecisionBranch($index)"
                              [disabled]="decisionBranches().length <= 2"
                              title="Remove branch (minimum 2)"
                            >
                              <app-icon name="x" [size]="11" />
                            </button>
                          </div>
                        }
                        <button
                          type="button"
                          class="df-ghost-btn"
                          (click)="addDecisionBranch()"
                          [disabled]="decisionBranches().length >= 8"
                        >
                          <app-icon name="plus" [size]="11" /> Add branch
                        </button>
                        <label class="df-field-label">Default branch (optional)</label>
                        <select
                          class="df-input"
                          [value]="decisionDefault() ?? ''"
                          (change)="onDecisionDefaultChange($event)"
                        >
                          <option value="">— none —</option>
                          @for (b of decisionBranches(); track $index) {
                            <option [value]="b.label">{{ b.label }}</option>
                          }
                        </select>
                      </div>
                    }

                    <!-- FORK: free-form branch name list -->
                    @case ('fork') {
                      <div class="df-kind-editor">
                        <div class="df-field-hint">Each label names one parallel branch. Order matters only for display.</div>
                        @for (name of forkBranches(); track $index) {
                          <div class="df-branch-row">
                            <input
                              type="text"
                              class="df-input df-input--mono"
                              [value]="name"
                              (change)="patchForkBranch($index, $event)"
                              placeholder="branch-name"
                              maxlength="48"
                            />
                            <button
                              type="button"
                              class="df-icon-btn"
                              (click)="removeForkBranch($index)"
                              [disabled]="forkBranches().length <= 2"
                              title="Remove branch (minimum 2)"
                            >
                              <app-icon name="x" [size]="11" />
                            </button>
                          </div>
                        }
                        <button
                          type="button"
                          class="df-ghost-btn"
                          (click)="addForkBranch()"
                          [disabled]="forkBranches().length >= 8"
                        >
                          <app-icon name="plus" [size]="11" /> Add branch
                        </button>
                      </div>
                    }

                    <!-- JOIN: strategy picker -->
                    @case ('join') {
                      <div class="df-kind-editor">
                        <label class="df-field-label">Wait strategy</label>
                        <select
                          class="df-input"
                          [value]="joinStrategy()"
                          (change)="onJoinStrategyChange($event)"
                        >
                          <option value="all">all — block until every inbound branch completes</option>
                          <option value="any">any — continue as soon as one branch completes</option>
                          <option value="race">race — first branch wins, others get cancelled</option>
                        </select>
                      </div>
                    }

                    <!-- LOOP: iterator expression + budget + break condition -->
                    @case ('loop') {
                      <div class="df-kind-editor">
                        <label class="df-field-label">Iterator (context expression)</label>
                        <input
                          type="text"
                          class="df-input df-input--mono"
                          [value]="loopIterator()"
                          (change)="patchLoopField('iterator', $event)"
                          placeholder="context.chunks"
                          maxlength="240"
                        />
                        <label class="df-field-label">Max iterations (budget)</label>
                        <input
                          type="number"
                          class="df-input"
                          min="1"
                          max="1000"
                          [value]="loopMaxIterations()"
                          (change)="patchLoopField('max_iterations', $event)"
                        />
                        <label class="df-field-label">Break when (optional)</label>
                        <input
                          type="text"
                          class="df-input df-input--mono"
                          [value]="loopBreakOn()"
                          (change)="patchLoopField('break_on', $event)"
                          placeholder="context.done === true"
                          maxlength="240"
                        />
                      </div>
                    }

                    <!-- RETRY: attempts + backoff + on_errors filter -->
                    @case ('retry') {
                      <div class="df-kind-editor">
                        <label class="df-field-label">Max attempts</label>
                        <input
                          type="number"
                          class="df-input"
                          min="1"
                          max="20"
                          [value]="retryMaxAttempts()"
                          (change)="patchRetryField('max_attempts', $event)"
                        />
                        <label class="df-field-label">Backoff (ms)</label>
                        <input
                          type="number"
                          class="df-input"
                          min="0"
                          max="60000"
                          step="100"
                          [value]="retryBackoffMs()"
                          (change)="patchRetryField('backoff_ms', $event)"
                        />
                        <label class="df-field-label">Only retry on (optional, CSV)</label>
                        <input
                          type="text"
                          class="df-input df-input--mono"
                          [value]="retryOnErrors()"
                          (change)="patchRetryField('on_errors', $event)"
                          placeholder="TimeoutError, RateLimitError"
                          maxlength="240"
                        />
                      </div>
                    }

                    <!-- HITL: prompt + timeout + approvers roles -->
                    @case ('hitl') {
                      <div class="df-kind-editor">
                        <label class="df-field-label">Prompt to the operator</label>
                        <textarea
                          class="df-input df-textarea"
                          [value]="hitlPrompt()"
                          (change)="patchHitlField('prompt', $event)"
                          placeholder="Approve the draft before it's sent to the client."
                          rows="3"
                          maxlength="2000"
                        ></textarea>
                        <label class="df-field-label">Timeout (ms, optional)</label>
                        <input
                          type="number"
                          class="df-input"
                          min="0"
                          step="1000"
                          [value]="hitlTimeoutMs()"
                          (change)="patchHitlField('timeout_ms', $event)"
                          placeholder="0 = wait forever"
                        />
                        <label class="df-field-label">Approver roles (CSV, optional)</label>
                        <input
                          type="text"
                          class="df-input df-input--mono"
                          [value]="hitlApprovers()"
                          (change)="patchHitlField('approvers', $event)"
                          placeholder="reviewer, compliance"
                          maxlength="240"
                        />
                      </div>
                    }

                    <!-- SUBFLOW: pick another System + simple input map -->
                    @case ('subflow') {
                      <div class="df-kind-editor">
                        <label class="df-field-label">Target system</label>
                        <select
                          class="df-input ck-mono"
                          [value]="subflowSystemId() ?? ''"
                          (change)="onSubflowSystemChange($event)"
                          (focus)="ensureOtherSystemsLoaded()"
                        >
                          <option value="">— unset —</option>
                          @for (s of otherSystems(); track s.id) {
                            <option [value]="s.id">{{ s.name }}</option>
                          }
                        </select>
                        @if (otherSystemsLoading()) {
                          <div class="text-[10px] text-gray-500 mt-1 ck-mono">Loading systems…</div>
                        } @else if (otherSystems().length === 0) {
                          <div class="text-[10px] text-gray-500 mt-1">Focus the picker to load the catalog.</div>
                        }
                        <label class="df-field-label">Input map (one <span class="ck-mono">key = expr</span> per line)</label>
                        <textarea
                          class="df-input df-textarea ck-mono"
                          [value]="subflowInputMap()"
                          (change)="onSubflowInputMapChange($event)"
                          placeholder="query = context.query&#10;lang = context.lang"
                          rows="3"
                        ></textarea>
                      </div>
                    }

                    <!-- Default case — task / source / sink / untyped -->
                    @default {
                      <div class="df-kind-editor">
                        @if ((selectedNode()!.kind ?? 'task') === 'task') {
                          <!-- Task input params (rendered from Skill.input_schema) -->
                          @if (taskParamFields().length > 0) {
                            <label class="df-field-label">Skill parameters</label>
                            @for (field of taskParamFields(); track field.key) {
                              <div class="df-param-row">
                                <label class="df-param-label" [title]="field.description ?? ''">
                                  {{ field.key }}
                                  @if (field.required) { <span class="text-rose-400">*</span> }
                                  <span class="ck-mono text-[9px] text-gray-500 ml-1">{{ field.type }}</span>
                                </label>
                                @switch (field.type) {
                                  @case ('boolean') {
                                    <input
                                      type="checkbox"
                                      class="df-checkbox"
                                      [checked]="$any(field.value) === true"
                                      (change)="onTaskParamChange(field.key, $event, field.type)"
                                    />
                                  }
                                  @case ('object') {
                                    <textarea
                                      class="df-input df-textarea ck-mono"
                                      [value]="jsonParamValue(field.value)"
                                      (change)="onTaskParamJsonChange(field.key, $event)"
                                      [placeholder]="field.description ?? '{ }'"
                                      rows="4"
                                    ></textarea>
                                  }
                                  @case ('array') {
                                    <textarea
                                      class="df-input df-textarea ck-mono"
                                      [value]="jsonParamValue(field.value)"
                                      (change)="onTaskParamJsonChange(field.key, $event)"
                                      [placeholder]="field.description ?? '[ ]'"
                                      rows="4"
                                    ></textarea>
                                  }
                                  @case ('number') {
                                    <input
                                      type="number"
                                      class="df-input"
                                      [value]="field.value ?? ''"
                                      (change)="onTaskParamChange(field.key, $event, field.type)"
                                    />
                                  }
                                  @case ('integer') {
                                    <input
                                      type="number"
                                      class="df-input"
                                      step="1"
                                      [value]="field.value ?? ''"
                                      (change)="onTaskParamChange(field.key, $event, field.type)"
                                    />
                                  }
                                  @default {
                                    @if ((field.enum ?? []).length > 0) {
                                      <select
                                        class="df-input"
                                        [value]="field.value ?? ''"
                                        (change)="onTaskParamChange(field.key, $event, field.type)"
                                      >
                                        <option value="">—</option>
                                        @for (opt of field.enum ?? []; track opt) {
                                          <option [value]="opt">{{ opt }}</option>
                                        }
                                      </select>
                                    } @else {
                                      <input
                                        type="text"
                                        class="df-input"
                                        [value]="field.value ?? ''"
                                        (change)="onTaskParamChange(field.key, $event, field.type)"
                                        [placeholder]="field.description ?? ''"
                                      />
                                    }
                                  }
                                }
                              </div>
                            }
                          } @else if (currentSkillId(selectedNode()!)) {
                            <div class="text-[10px] text-gray-500">Bound skill exposes no input schema.</div>
                          }

                          <!-- inputs_map / outputs_map (advanced, always editable) -->
                          <label class="df-field-label">Inputs map (<span class="ck-mono">key = expr</span>)</label>
                          <textarea
                            class="df-input df-textarea ck-mono"
                            [value]="taskInputsMap()"
                            (change)="onTaskInputsMapChange($event)"
                            placeholder="query = context.query"
                            rows="2"
                          ></textarea>
                          <label class="df-field-label">Outputs map (<span class="ck-mono">port = ctx_key</span>)</label>
                          <textarea
                            class="df-input df-textarea ck-mono"
                            [value]="taskOutputsMap()"
                            (change)="onTaskOutputsMapChange($event)"
                            placeholder="answer = context.answer"
                            rows="2"
                          ></textarea>
                        } @else {
                          @if (configSummary(selectedNode()!).length === 0) {
                            <div class="text-[11px] text-gray-500">— no config —</div>
                          } @else {
                            <div class="df-inspector-config ck-mono">
                              @for (row of configSummary(selectedNode()!); track row.key) {
                                <div class="df-config-row">
                                  <span class="text-gray-400">{{ row.key }}</span>
                                  <span class="text-gray-200">{{ row.value }}</span>
                                </div>
                              }
                            </div>
                          }
                        }
                      </div>
                    }
                  }
                </div>

                <div class="df-inspector-section">
                  <div class="df-inspector-label">Runtime metrics</div>
                  <div class="rounded bg-black/20 border border-white/10 px-3 py-2 text-[11px] text-gray-400 leading-relaxed">
                    Metrics appear after this System executes a Run. Until then, this inspector focuses on contract, binding and config.
                  </div>
                </div>

                @if (runtimeEvidenceRows().length > 0) {
                  <div class="df-inspector-section">
                    <div class="df-inspector-label">Runtime evidence</div>
                    <div class="df-inspector-config ck-mono">
                      @for (row of runtimeEvidenceRows(); track row.key) {
                        <div class="df-config-row">
                          <span class="text-gray-400">{{ row.key }}</span>
                          <span class="text-gray-200">{{ row.value }}</span>
                        </div>
                      }
                    </div>
                  </div>
                }

                @if (promptBlocks().length > 0) {
                  <div class="df-inspector-section df-inspector-section--editor">
                    <div class="df-inspector-label">Prompts & instructions</div>
                    <div class="space-y-2">
                      @for (block of promptBlocks(); track block.key) {
                        <div class="df-prompt-block">
                          <div class="df-prompt-block__title">{{ block.title }}</div>
                          <pre class="df-prompt-block__body">{{ block.body }}</pre>
                        </div>
                      }
                    </div>
                  </div>
                }
              </div>
            }
          </div>
        </aside>
      } @else {
        <aside class="t-card t-elevated rounded-md flex flex-col items-center py-3 df-inspector-collapsed">
          <button (click)="toggleInspector()" class="df-tool-btn df-tool-toggle df-tool-toggle--vertical" title="Open inspector">
            <app-icon name="sidebar" [size]="14" />
            <span>Inspector</span>
          </button>
        </aside>
      }
    </div>

    @if (configSheetOpen() && selectedNode()) {
      <div class="df-config-sheet-backdrop" (click)="closeConfigSheet()" aria-hidden="true"></div>
      <aside class="df-config-sheet t-card t-elevated" role="dialog" aria-label="Node configuration">
        <div class="df-config-sheet__head">
          <div>
            <div class="ck-mono text-[10px] uppercase tracking-[0.14em] text-brand-300">Node configuration</div>
            <h2>{{ selectedNode()!.label || selectedNode()!.type }}</h2>
            <span class="ck-mono">{{ selectedNode()!.id }}</span>
          </div>
          <button type="button" class="df-tool-btn" (click)="closeConfigSheet()" title="Close">
            <app-icon name="x" [size]="16" />
          </button>
        </div>

        <div class="df-config-tabs">
          @for (tab of ['overview', 'config', 'prompts', 'runtime']; track tab) {
            <button
              type="button"
              [attr.data-active]="configSheetTab() === tab ? 'true' : 'false'"
              (click)="setConfigSheetTab($any(tab))"
            >
              {{ tab }}
            </button>
          }
        </div>

        <div class="df-config-sheet__body">
          @switch (configSheetTab()) {
            @case ('overview') {
              <section class="df-sheet-section">
                <div class="df-sheet-label">Identity</div>
                <input
                  type="text"
                  class="df-input df-input--large"
                  [value]="selectedNode()!.label || selectedNode()!.type"
                  (change)="onNodeLabelChange($event)"
                  maxlength="120"
                />
                <div class="df-sheet-grid mt-3">
                  <div class="df-sheet-card">
                    <span>Kind</span>
                    <strong>{{ kindLabel(selectedNode()!.kind) }}</strong>
                  </div>
                  <div class="df-sheet-card">
                    <span>Type</span>
                    <strong>{{ selectedNode()!.type }}</strong>
                  </div>
                  <div class="df-sheet-card">
                    <span>Instructions</span>
                    <strong>{{ promptBlocks().length }}</strong>
                  </div>
                </div>
              </section>

              @if ((selectedNode()!.inputs?.length ?? 0) > 0 || (selectedNode()!.outputs?.length ?? 0) > 0) {
                <section class="df-sheet-section">
                  <div class="df-sheet-label">Typed contract</div>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <div class="text-[10px] text-gray-500 mb-1 ck-mono">INPUTS</div>
                      @for (p of selectedNode()!.inputs; track p.name) {
                        <div class="df-port-row mb-1">
                          <span class="df-port-dot" data-dir="in"></span>
                          <span class="text-xs text-gray-200 ck-mono">{{ p.name }}</span>
                          <span class="df-port-schema">{{ p.schema }}</span>
                        </div>
                      }
                    </div>
                    <div>
                      <div class="text-[10px] text-gray-500 mb-1 ck-mono">OUTPUTS</div>
                      @for (p of selectedNode()!.outputs; track p.name) {
                        <div class="df-port-row mb-1">
                          <span class="df-port-dot" data-dir="out"></span>
                          <span class="text-xs text-gray-200 ck-mono">{{ p.name }}</span>
                          <span class="df-port-schema">{{ p.schema }}</span>
                        </div>
                      }
                    </div>
                  </div>
                </section>
              }
            }

            @case ('config') {
              <section class="df-sheet-section">
                <div class="df-sheet-label">Config · {{ kindLabel(selectedNode()!.kind) }}</div>
                @switch (selectedNode()!.kind ?? 'task') {
                  @case ('decision') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <div class="df-field-hint">Each branch emits a branch edge whose label is routed by the condition.</div>
                      @for (b of decisionBranches(); track $index) {
                        <div class="df-branch-row">
                          <input type="text" class="df-input df-input--mono" [value]="b.label" (change)="patchDecisionBranch($index, 'label', $event)" placeholder="branch label" maxlength="64" />
                          <input type="text" class="df-input" [value]="b.condition" (change)="patchDecisionBranch($index, 'condition', $event)" placeholder="context.score > 0.5" maxlength="240" />
                          <button type="button" class="df-icon-btn" (click)="removeDecisionBranch($index)" [disabled]="decisionBranches().length <= 2" title="Remove branch">
                            <app-icon name="x" [size]="11" />
                          </button>
                        </div>
                      }
                      <button type="button" class="df-ghost-btn" (click)="addDecisionBranch()" [disabled]="decisionBranches().length >= 8">
                        <app-icon name="plus" [size]="11" /> Add branch
                      </button>
                      <label class="df-field-label">Default branch</label>
                      <app-flow-select
                        [value]="decisionDefault()"
                        [options]="decisionDefaultOptions()"
                        [allowEmpty]="true"
                        emptyLabel="No default branch"
                        placeholder="Choose default branch"
                        (valueChange)="setDecisionDefault($event)"
                      />
                    </div>
                  }

                  @case ('fork') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <div class="df-field-hint">Each label names one parallel branch.</div>
                      @for (name of forkBranches(); track $index) {
                        <div class="df-branch-row df-branch-row--two">
                          <input type="text" class="df-input df-input--mono" [value]="name" (change)="patchForkBranch($index, $event)" placeholder="branch-name" maxlength="48" />
                          <button type="button" class="df-icon-btn" (click)="removeForkBranch($index)" [disabled]="forkBranches().length <= 2" title="Remove branch">
                            <app-icon name="x" [size]="11" />
                          </button>
                        </div>
                      }
                      <button type="button" class="df-ghost-btn" (click)="addForkBranch()" [disabled]="forkBranches().length >= 8">
                        <app-icon name="plus" [size]="11" /> Add branch
                      </button>
                    </div>
                  }

                  @case ('join') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <label class="df-field-label">Wait strategy</label>
                      <app-flow-select
                        [value]="joinStrategy()"
                        [options]="joinStrategyOptions"
                        placeholder="Join strategy"
                        (valueChange)="setJoinStrategy($event)"
                      />
                    </div>
                  }

                  @case ('loop') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <label class="df-field-label">Iterator</label>
                      <input type="text" class="df-input df-input--mono" [value]="loopIterator()" (change)="patchLoopField('iterator', $event)" placeholder="context.chunks" maxlength="240" />
                      <label class="df-field-label">Max iterations</label>
                      <input type="number" class="df-input" min="1" max="1000" [value]="loopMaxIterations()" (change)="patchLoopField('max_iterations', $event)" />
                      <label class="df-field-label">Break when</label>
                      <input type="text" class="df-input df-input--mono" [value]="loopBreakOn()" (change)="patchLoopField('break_on', $event)" placeholder="context.done === true" maxlength="240" />
                    </div>
                  }

                  @case ('retry') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <label class="df-field-label">Max attempts</label>
                      <input type="number" class="df-input" min="1" max="20" [value]="retryMaxAttempts()" (change)="patchRetryField('max_attempts', $event)" />
                      <label class="df-field-label">Backoff (ms)</label>
                      <input type="number" class="df-input" min="0" max="60000" step="100" [value]="retryBackoffMs()" (change)="patchRetryField('backoff_ms', $event)" />
                      <label class="df-field-label">Retry on errors</label>
                      <input type="text" class="df-input df-input--mono" [value]="retryOnErrors()" (change)="patchRetryField('on_errors', $event)" placeholder="TimeoutError, RateLimitError" maxlength="240" />
                    </div>
                  }

                  @case ('hitl') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <label class="df-field-label">Prompt to operator</label>
                      <textarea class="df-input df-textarea" [value]="hitlPrompt()" (change)="patchHitlField('prompt', $event)" rows="6" maxlength="2000"></textarea>
                      <label class="df-field-label">Timeout (ms)</label>
                      <input type="number" class="df-input" min="0" step="1000" [value]="hitlTimeoutMs()" (change)="patchHitlField('timeout_ms', $event)" />
                      <label class="df-field-label">Approver roles</label>
                      <input type="text" class="df-input df-input--mono" [value]="hitlApprovers()" (change)="patchHitlField('approvers', $event)" placeholder="reviewer, compliance" maxlength="240" />
                    </div>
                  }

                  @case ('subflow') {
                    <div class="df-kind-editor df-kind-editor--wide">
                      <label class="df-field-label">Target system</label>
                      <app-flow-select
                        [value]="subflowSystemId()"
                        [options]="subflowSystemOptions()"
                        [loading]="otherSystemsLoading()"
                        [allowEmpty]="true"
                        [searchable]="true"
                        emptyLabel="Unset"
                        placeholder="Select system"
                        (opened)="ensureOtherSystemsLoaded()"
                        (valueChange)="setSubflowSystem($event)"
                      />
                      <label class="df-field-label">Input map</label>
                      <textarea class="df-input df-textarea ck-mono" [value]="subflowInputMap()" (change)="onSubflowInputMapChange($event)" rows="5" placeholder="query = context.query&#10;lang = context.lang"></textarea>
                    </div>
                  }

                  @default {
                    <div class="df-kind-editor df-kind-editor--wide">
                      @if ((selectedNode()!.kind ?? 'task') === 'task') {
                        <label class="df-field-label">Bound skill</label>
                        <app-flow-select
                          [value]="currentSkillId(selectedNode()!)"
                          [options]="skillSelectOptions()"
                          [loading]="skillsLoading()"
                          [allowEmpty]="true"
                          [searchable]="true"
                          emptyLabel="Unbound"
                          placeholder="Bind skill"
                          (opened)="ensureSkillsLoaded()"
                          (valueChange)="onSkillSelect($event)"
                        />
                        @if (taskParamFields().length > 0) {
                          <label class="df-field-label">Skill parameters</label>
                          @for (field of taskParamFields(); track field.key) {
                            <div class="df-param-row df-param-row--wide">
                              <label class="df-param-label" [title]="field.description ?? ''">
                                {{ field.key }}
                                @if (field.required) { <span class="text-rose-400">*</span> }
                                <span class="ck-mono text-[9px] text-gray-500 ml-1">{{ field.type }}</span>
                              </label>
                              @switch (field.type) {
                                @case ('boolean') {
                                  <input type="checkbox" class="df-checkbox" [checked]="$any(field.value) === true" (change)="onTaskParamChange(field.key, $event, field.type)" />
                                }
                                @case ('object') {
                                  <textarea class="df-input df-textarea ck-mono" [value]="jsonParamValue(field.value)" (change)="onTaskParamJsonChange(field.key, $event)" [placeholder]="field.description ?? '{ }'" rows="5"></textarea>
                                }
                                @case ('array') {
                                  <textarea class="df-input df-textarea ck-mono" [value]="jsonParamValue(field.value)" (change)="onTaskParamJsonChange(field.key, $event)" [placeholder]="field.description ?? '[ ]'" rows="5"></textarea>
                                }
                                @case ('number') {
                                  <input type="number" class="df-input" [value]="field.value ?? ''" (change)="onTaskParamChange(field.key, $event, field.type)" />
                                }
                                @case ('integer') {
                                  <input type="number" class="df-input" step="1" [value]="field.value ?? ''" (change)="onTaskParamChange(field.key, $event, field.type)" />
                                }
                                @default {
                                  @if ((field.enum ?? []).length > 0) {
                                    <app-flow-select
                                      [value]="$any(field.value) ?? null"
                                      [options]="enumOptions(field)"
                                      [allowEmpty]="true"
                                      emptyLabel="Unset"
                                      placeholder="Choose value"
                                      (valueChange)="setTaskParamValue(field.key, $event, field.type)"
                                    />
                                  } @else {
                                    <input type="text" class="df-input" [value]="field.value ?? ''" (change)="onTaskParamChange(field.key, $event, field.type)" [placeholder]="field.description ?? ''" />
                                  }
                                }
                              }
                            </div>
                          }
                        }
                        <label class="df-field-label">Inputs map</label>
                        <textarea class="df-input df-textarea ck-mono" [value]="taskInputsMap()" (change)="onTaskInputsMapChange($event)" placeholder="query = context.query" rows="4"></textarea>
                        <label class="df-field-label">Outputs map</label>
                        <textarea class="df-input df-textarea ck-mono" [value]="taskOutputsMap()" (change)="onTaskOutputsMapChange($event)" placeholder="answer = context.answer" rows="4"></textarea>
                      } @else if (configSummary(selectedNode()!).length === 0) {
                        <div class="text-[11px] text-gray-500">No config for this node.</div>
                      } @else {
                        <div class="df-inspector-config ck-mono">
                          @for (row of configSummary(selectedNode()!); track row.key) {
                            <div class="df-config-row">
                              <span class="text-gray-400">{{ row.key }}</span>
                              <span class="text-gray-200">{{ row.value }}</span>
                            </div>
                          }
                        </div>
                      }
                    </div>
                  }
                }
              </section>
            }

            @case ('prompts') {
              <section class="df-sheet-section">
                <div class="df-sheet-label">Prompts & instructions</div>
                @if (promptBlocks().length === 0) {
                  <div class="df-sheet-empty">No prompt or runtime instruction exposed for this node.</div>
                } @else {
                  <div class="df-prompt-list">
                    @for (block of promptBlocks(); track block.key) {
                      <article class="df-prompt-block df-prompt-block--sheet" [attr.data-expanded]="expandedPromptKey() === block.key ? 'true' : 'false'">
                        <div class="df-prompt-block__title">
                          <span>{{ block.title }}</span>
                          <small>{{ block.source }} · {{ block.path }}</small>
                          <div class="df-prompt-actions">
                            <button type="button" class="df-tool-btn df-tool-btn--small" (click)="copyPrompt(block)" title="Copy instruction">
                              <app-icon name="copy" [size]="12" />
                            </button>
                            <button type="button" class="df-tool-btn df-tool-btn--small" (click)="togglePromptExpanded(block)" title="Expand instruction">
                              <app-icon name="maximize" [size]="12" />
                            </button>
                            @if (block.editable) {
                              <button type="button" class="df-tool-btn df-tool-btn--small" (click)="beginPromptEdit(block)" title="Edit prompt instruction">
                                <app-icon name="pencil" [size]="12" />
                              </button>
                            }
                          </div>
                        </div>
                        @if (promptEditKey() === block.key) {
                          <textarea class="df-input df-prompt-editor ck-mono" [value]="promptDraft()" (input)="onPromptDraftChange($event)" rows="12"></textarea>
                          <div class="df-prompt-edit-actions">
                            <button type="button" class="df-ghost-btn" (click)="cancelPromptEdit()">Cancel</button>
                            <button type="button" class="df-primary-soft-btn" (click)="savePromptEdit(block)">
                              <app-icon name="save" [size]="12" /> Apply locally
                            </button>
                          </div>
                        } @else {
                          <pre class="df-prompt-block__body">{{ block.body }}</pre>
                        }
                      </article>
                    }
                  </div>
                }
              </section>
            }

            @case ('runtime') {
              <section class="df-sheet-section">
                <div class="df-sheet-label">Runtime unit</div>
                @if (selectedManifestUnit(); as unit) {
                  <div class="df-runtime-unit-card">
                    <div class="df-runtime-unit-card__head">
                      <div>
                        <strong>{{ unit.label }}</strong>
                        <span>{{ unit.description || unit.id }}</span>
                      </div>
                      <span class="df-tag" [attr.data-tone]="unit.operational ? 'pos' : 'info'">
                        {{ unit.operational ? 'OPERATIONAL' : 'MANIFEST' }}
                      </span>
                    </div>
                    @if (selectedManifestRows().length > 0) {
                      <div class="df-inspector-config ck-mono">
                        @for (row of selectedManifestRows(); track row.key) {
                          <div class="df-config-row">
                            <span class="text-gray-400">{{ row.key }}</span>
                            <span class="text-gray-200">{{ row.value }}</span>
                          </div>
                        }
                      </div>
                    }
                  </div>
                } @else {
                  <div class="df-sheet-empty">No runtime manifest unit matched this node.</div>
                }
              </section>

              @if (runtimeEvidenceRows().length > 0) {
                <section class="df-sheet-section">
                  <div class="df-sheet-label">Runtime evidence</div>
                  <div class="df-inspector-config ck-mono">
                    @for (row of runtimeEvidenceRows(); track row.key) {
                      <div class="df-config-row">
                        <span class="text-gray-400">{{ row.key }}</span>
                        <span class="text-gray-200">{{ row.value }}</span>
                      </div>
                    }
                  </div>
                </section>
              }
            }
          }
        </div>
      </aside>
    }

    <!-- Validation issues strip -->
    @if (allIssues().length > 0) {
      <div class="mt-3 t-card t-elevated rounded-md p-3">
        <div class="flex items-center gap-2 mb-2">
          <app-icon name="alert-triangle" [size]="14" class="text-amber-400" />
          <span class="text-xs font-medium text-white">Flow validation — {{ allIssues().length }} issue{{ allIssues().length > 1 ? 's' : '' }}</span>
          @if (serverIssues().length > 0) {
            <span class="df-tag df-tag-neg">SERVER REJECTED</span>
          }
        </div>
        <div class="space-y-1">
          @for (issue of issues(); track $index) {
            <div class="flex items-start gap-2 text-[11px]">
              <span class="df-tag" [attr.data-tone]="issue.level === 'error' ? 'neg' : 'warn'">{{ issue.level === 'error' ? 'ERR' : 'WARN' }}</span>
              <span class="ck-mono text-[9px] text-gray-500 uppercase tracking-wider">client</span>
              <span class="text-gray-300">{{ issue.message }}</span>
              @if (issue.node_id) {
                <span class="ck-mono text-[10px] text-gray-500">· {{ issue.node_id }}</span>
              }
            </div>
          }
          @for (issue of serverIssues(); track $index) {
            <div class="flex items-start gap-2 text-[11px]">
              <span class="df-tag" [attr.data-tone]="issue.level === 'error' ? 'neg' : 'warn'">{{ issue.level === 'error' ? 'ERR' : 'WARN' }}</span>
              <span class="ck-mono text-[9px] text-brand-300 uppercase tracking-wider">server</span>
              <span class="text-gray-300">{{ issue.message }}</span>
              @if (issue.node_id) {
                <span class="ck-mono text-[10px] text-gray-500">· {{ issue.node_id }}</span>
              }
            </div>
          }
        </div>
      </div>
    }

    <!-- Versions panel (Vague E / E3.2) -->
    @if (versionsPanelOpen()) {
      <div
        class="df-versions-backdrop"
        (click)="closeVersionsPanel()"
        aria-hidden="true"
      ></div>
      <aside
        class="df-versions-panel t-card t-elevated"
        role="dialog"
        aria-label="Flow versions"
      >
        <header class="df-versions-head">
          <div class="flex items-center gap-2">
            <app-icon name="history" [size]="14" class="text-brand-400" />
            <span class="text-xs font-medium text-white">Flow history</span>
            <span class="df-tag df-tag-cool">{{ versionsTotal() }}</span>
          </div>
          <div class="flex items-center gap-1">
            <button
              type="button"
              class="df-tool-btn df-tool-btn--small"
              (click)="refreshVersions()"
              [disabled]="versionsLoading()"
              title="Refresh"
            >
              <app-icon name="refresh-cw" [size]="12" />
            </button>
            <button
              type="button"
              class="df-tool-btn df-tool-btn--small"
              (click)="closeVersionsPanel()"
              title="Close"
            >
              <app-icon name="x" [size]="12" />
            </button>
          </div>
        </header>
        <div class="df-versions-body">
          @if (versionsLoading() && versions().length === 0) {
            <div class="text-[11px] text-gray-500 ck-mono p-3">Loading…</div>
          } @else if (versions().length === 0) {
            <div class="text-[11px] text-gray-500 ck-mono p-3">
              No history yet. The first save on this System will seed v1.
            </div>
          } @else {
            @for (v of versions(); track v.id) {
              <div class="df-version-row" [attr.data-current]="$index === 0 ? 'true' : 'false'">
                <div class="df-version-row__head">
                  <span class="df-version-num">v{{ v.version_number }}</span>
                  @if ($index === 0) {
                    <span class="df-tag df-tag-pos">CURRENT</span>
                  }
                  @if (v.rolled_back_from_id) {
                    <span class="df-tag df-tag-warn">ROLLBACK</span>
                  }
                  <span class="ck-mono text-[9px] text-gray-500">{{ formatVersionTimestamp(v.created_at) }}</span>
                </div>
                <div class="df-version-row__meta">
                  <span class="ck-mono text-[10px] text-gray-400">{{ v.created_by }}</span>
                  <span class="df-version-dot"></span>
                  <span class="ck-mono text-[10px] text-gray-500">{{ v.node_count }}n · {{ v.edge_count }}e</span>
                  @if (versionDiffLabel(v); as d) {
                    <span class="df-version-dot"></span>
                    <span class="ck-mono text-[10px] text-brand-300">{{ d }}</span>
                  }
                </div>
                @if (v.message) {
                  <div class="df-version-row__msg">{{ v.message }}</div>
                }
                <div class="df-version-row__actions">
                  <button
                    type="button"
                    class="df-version-btn"
                    (click)="beginRollback(v)"
                    [disabled]="$index === 0 || rollbackPending()"
                    [title]="$index === 0 ? 'Already current' : 'Roll back to this version'"
                  >
                    <app-icon name="rotate-ccw" [size]="11" /> Roll back
                  </button>
                </div>
              </div>
            }
          }
        </div>
      </aside>
    }

    @if (rollbackTarget(); as tgt) {
      <div class="df-modal-backdrop" (click)="cancelRollback()" aria-hidden="true"></div>
      <div class="df-modal t-card t-elevated" role="dialog" aria-label="Confirm rollback">
        <header class="df-modal-head">
          <app-icon name="rotate-ccw" [size]="14" class="text-amber-300" />
          <span class="text-xs font-medium text-white">Roll back to v{{ tgt.version_number }}</span>
        </header>
        <div class="df-modal-body">
          <p class="text-[12px] text-gray-300 leading-snug">
            This will create a new version on top of history whose graph is an exact copy of
            <span class="ck-mono text-brand-300">v{{ tgt.version_number }}</span>.
            The current canvas will be replaced. Nothing is deleted — history is append-only.
          </p>
          <label class="df-modal-label" for="rollback-msg">Message (optional)</label>
          <input
            id="rollback-msg"
            type="text"
            class="df-modal-input"
            [value]="rollbackMessage()"
            (input)="onRollbackMessageChange($event)"
            [placeholder]="'rollback to v' + tgt.version_number"
            maxlength="280"
          />
        </div>
        <footer class="df-modal-actions">
          <button
            type="button"
            class="df-modal-btn df-modal-btn--ghost"
            (click)="cancelRollback()"
            [disabled]="rollbackPending()"
          >Cancel</button>
          <button
            type="button"
            class="df-modal-btn df-modal-btn--primary"
            (click)="confirmRollback()"
            [disabled]="rollbackPending()"
          >
            @if (rollbackPending()) {
              <app-icon name="loader-2" [size]="12" class="animate-spin" /> Rolling back…
            } @else {
              <app-icon name="rotate-ccw" [size]="12" /> Confirm rollback
            }
          </button>
        </footer>
      </div>
    }

    <!-- Import modal (Vague E / E3.4) -->
    @if (importModalOpen()) {
      <div class="df-modal-backdrop" (click)="closeImportModal()" aria-hidden="true"></div>
      <div class="df-modal df-modal--wide t-card t-elevated" role="dialog" aria-label="Import chain from envelope">
        <header class="df-modal-head">
          <app-icon name="upload" [size]="14" class="text-brand-300" />
          <span class="text-xs font-medium text-white">Import chain from JSON</span>
        </header>
        <div class="df-modal-body">
          <p class="text-[12px] text-gray-300 leading-snug">
            Paste an envelope produced by <span class="ck-mono text-brand-300">Export</span>, or
            pick a <span class="ck-mono">.json</span> file. Skills are rebound by slug against
            the current workspace; any missing slugs are listed in the report below — you can
            finish binding manually afterwards.
          </p>
          <label class="df-modal-label" for="import-name">Target name (optional)</label>
          <input
            id="import-name"
            type="text"
            class="df-modal-input"
            [value]="importTargetName()"
            (input)="onImportNameChange($event)"
            placeholder="Imported chain"
            maxlength="200"
            [disabled]="importPending()"
          />
          <label class="df-modal-label" for="import-file">JSON file</label>
          <input
            id="import-file"
            type="file"
            accept="application/json,.json"
            class="df-modal-input"
            (change)="onImportFileChange($event)"
            [disabled]="importPending()"
          />
          <label class="df-modal-label" for="import-paste">… or paste the envelope</label>
          <textarea
            id="import-paste"
            class="df-modal-input df-modal-textarea ck-mono"
            [value]="importPaste()"
            (input)="onImportPasteChange($event)"
            [placeholder]="importPastePlaceholder"
            rows="6"
            [disabled]="importPending()"
          ></textarea>
          @if (importError()) {
            <div class="df-import-error">
              <app-icon name="alert-triangle" [size]="12" class="text-rose-400" />
              <span>{{ importError() }}</span>
            </div>
          }
          @if (importReport(); as rep) {
            <div class="df-import-report">
              <div class="df-import-report-row">
                <span class="text-gray-400">Skills resolved</span>
                <span class="text-emerald-300 ck-mono">{{ rep.resolved_skills.length }}</span>
              </div>
              <div class="df-import-report-row">
                <span class="text-gray-400">Skills unresolved</span>
                <span [class.text-amber-300]="rep.unresolved_skills.length > 0" class="ck-mono">
                  {{ rep.unresolved_skills.length }}
                </span>
              </div>
              @if (rep.unresolved_skills.length > 0) {
                <div class="df-import-report-slugs">
                  @for (s of rep.unresolved_skills; track s) {
                    <code class="df-import-slug-chip">{{ s }}</code>
                  }
                </div>
              }
            </div>
          }
        </div>
        <footer class="df-modal-actions">
          <button
            type="button"
            class="df-modal-btn df-modal-btn--ghost"
            (click)="closeImportModal()"
            [disabled]="importPending()"
          >Cancel</button>
          <button
            type="button"
            class="df-modal-btn df-modal-btn--primary"
            (click)="confirmImport()"
            [disabled]="importPending() || !importPaste().trim()"
          >
            @if (importPending()) {
              <app-icon name="loader-2" [size]="12" class="animate-spin" /> Importing…
            } @else {
              <app-icon name="upload" [size]="12" /> Import
            }
          </button>
        </footer>
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
  readonly flowManifest = signal<FlowRuntimeManifest | null>(null);
  readonly flowManifestLoading = signal(false);

  // Semantic projection of the current canvas.
  readonly nodeCount = signal(0);
  readonly edgeCount = signal(0);
  readonly source = signal<'form' | 'flow'>('flow');
  readonly extended = signal(false);
  readonly issues = signal<FlowValidationIssue[]>([]);
  // Server-side issues returned by ``PATCH /systems/{id}`` when the DAG
  // validator rejects the flow (400 ``flow_invalid``) or emits warnings.
  // Kept separate from ``issues`` so they survive across canvas edits
  // until the next save attempt. Vague E / E3.2.
  readonly serverIssues = signal<FlowValidationIssue[]>([]);
  readonly allIssues = computed<FlowValidationIssue[]>(() => [
    ...this.issues(),
    ...this.serverIssues(),
  ]);

  // Version panel — opens over the right rail. ``versions`` is capped at
  // whatever the backend rolling window enforces (default 500, see
  // ``CUSTOM_CHAIN_VERSION_WINDOW``). Pagination is server-driven.
  readonly versionsPanelOpen = signal(false);
  readonly versions = signal<SystemVersionSummary[]>([]);
  readonly versionsTotal = signal(0);
  readonly versionsLoading = signal(false);
  /** Cached full payload keyed by ``version_number`` — lets the UI
   *  short-circuit repeated previews without re-hitting the backend. */
  readonly versionPreviews = signal<Record<number, SystemVersionFull>>({});
  readonly rollbackTarget = signal<SystemVersionSummary | null>(null);
  readonly rollbackPending = signal(false);
  readonly rollbackMessage = signal('');
  /** Baseline diff reference — the graph the canvas currently holds,
   *  captured once when the version panel opens so diff counts don't
   *  oscillate while the user browses. */
  private versionsDiffBaseline: { nodes: Set<string>; edges: Set<string> } = {
    nodes: new Set(),
    edges: new Set(),
  };

  // Export / Import state (Vague E / E3.4) — download current system as a
  // portable envelope, or create a new system from an uploaded envelope.
  // ``importPaste`` is the source of truth for the modal; file selection
  // simply reads the file into the same signal so the "paste or upload"
  // paths stay symmetric.
  readonly exporting = signal(false);
  readonly importModalOpen = signal(false);
  readonly importPending = signal(false);
  readonly importPaste = signal('');
  readonly importTargetName = signal('');
  readonly importError = signal<string | null>(null);
  readonly importReport = signal<SystemImportReport | null>(null);
  readonly importPastePlaceholder =
    '{\n  "kind": "agentium.system.export",\n  "schema_version": 1,\n  ...\n}';

  // Inspector / Terminal state.
  readonly selectedNodeId = signal<string | null>(null);
  readonly selectedNode = signal<CanonicalFlowNode | null>(null);
  readonly inspectorOpen = signal(true);
  readonly configSheetOpen = signal(false);
  readonly configSheetTab = signal<ConfigSheetTab>('overview');
  readonly promptEditKey = signal<string | null>(null);
  readonly promptDraft = signal('');
  readonly expandedPromptKey = signal<string | null>(null);
  readonly terminalOpen = signal(true);
  readonly terminalLog = signal<TerminalEntry[]>([]);
  readonly loadPhase = signal('Preparing editor…');
  readonly perfMarks = signal<Record<string, number>>({});

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
    () => this.allIssues().filter((i) => i.level === 'error').length,
  );
  readonly warnCount = computed(
    () => this.allIssues().filter((i) => i.level === 'warn').length,
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
    {
      label: 'Runtime',
      value: this.flowManifest()?.operational_sync ? 'Synced' : 'DAG',
      tone: this.flowManifest()?.operational_sync ? 'pos' : 'neutral',
    },
  ]);

  readonly manifestUnitsPreview = computed(() =>
    (this.flowManifest()?.unit_catalog ?? []).slice(0, 8),
  );

  readonly manifestEffectiveRows = computed(() => {
    const cfg = (this.flowManifest()?.effective_config ?? {}) as Record<string, unknown>;
    return [
      ['assistant_profile', cfg['assistant_profile']],
      ['knowledge_scope', cfg['knowledge_scope']],
      ['retrieval', cfg['retrieval_defaults']],
      ['grounding', cfg['grounding']],
      ['source_policy', cfg['source_policy']],
    ]
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => ({ key: String(key), value: this.compactInspectorValue(value, 160) }));
  });

  readonly selectedManifestUnit = computed<FlowManifestUnit | null>(() => {
    const node = this.selectedNode();
    if (!node) return null;
    return (this.flowManifest()?.unit_catalog ?? []).find((unit) => unit.id === node.id) ?? null;
  });

  readonly selectedManifestRows = computed(() => {
    const unit = this.selectedManifestUnit();
    if (!unit) return [];
    return [
      ['unit_type', unit.unit_type],
      ['runtime_status', unit.runtime_status],
      ['runtime_ref', unit.runtime_ref],
      ['skill_slug', unit.skill_slug],
      ['implementation', unit.implementation?.source],
    ]
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => ({ key: String(key), value: this.compactInspectorValue(value, 220) }));
  });

  readonly selectedManifestFieldRows = computed(() =>
    (this.selectedManifestUnit()?.editable_fields ?? []).slice(0, 12).map((field) => ({
      key: field.key,
      value: this.compactInspectorValue(field.current_value ?? field.type ?? 'field', 220),
      source: field.source,
      required: field.required === true,
    })),
  );

  readonly palette: PaletteItem[] = [
    // ── Execution-kind DAG primitives (Vague C) ──
    { type: 'input', icon: 'zap', label: 'Trigger', description: 'Webhook / queue / schedule', tone: 'violet', kind: 'source', typeLabel: 'TRIGGER' },
    { type: 'llm', icon: 'brain', label: 'LLM', description: 'Call a language model', tone: 'cyan', kind: 'task', typeLabel: 'LLM' },
    { type: 'voice_realtime_session_v1', icon: 'mic', label: 'Voice session', description: 'Resolve provider, model, transport and fallback policy', tone: 'cyan', kind: 'task', typeLabel: 'VOICE' },
    { type: 'voice_realtime_transcribe_v1', icon: 'message-circle', label: 'Live transcribe', description: 'Emit text.partial and text.final from speech', tone: 'cyan', kind: 'task', typeLabel: 'VOICE' },
    { type: 'voice_tandem_oracle_v1', icon: 'activity', label: 'Tandem oracle', description: 'Realtime loop + background oracle with latest-wins events', tone: 'violet', kind: 'task', typeLabel: 'ORACLE' },
    { type: 'voice_oracle_turn_v1', icon: 'brain', label: 'Voice oracle', description: 'Decide next voice action from context and evaluation', tone: 'violet', kind: 'task', typeLabel: 'ORACLE' },
    { type: 'voice_realtime_speak_v1', icon: 'volume-2', label: 'Speak', description: 'Emit audio.out through the selected provider', tone: 'cyan', kind: 'task', typeLabel: 'VOICE' },
    { type: 'voice_realtime_translate_v1', icon: 'globe-2', label: 'Translate', description: 'Live translation for multilingual voice sessions', tone: 'emerald', kind: 'task', typeLabel: 'VOICE' },
    { type: 'resolve_action', icon: 'search-check', label: 'Resolve action', description: 'Match chat or voice input to an effective workspace action manifest', tone: 'emerald', kind: 'task', typeLabel: 'ACTION' },
    { type: 'confirm_action', icon: 'shield-check', label: 'Confirm action', description: 'Require human confirmation before side-effect actions execute', tone: 'amber', kind: 'hitl', typeLabel: 'ACTION' },
    { type: 'execute_action', icon: 'play-circle', label: 'Execute action', description: 'Run the selected action handler through IAM and audit', tone: 'emerald', kind: 'task', typeLabel: 'ACTION' },
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
      id: 'chat_transverse_v1',
      label: 'Chat · Transverse workspace',
      description: 'Quick ask → actions/grounding → fast answer → Deep Search',
      build: (add, connect) => {
        const input = add('input', 60, 250);
        const bypass = add('guardrail', 290, 120);
        const actions = add('resolve_action', 290, 250);
        const grounding = add('guardrail', 540, 250);
        const retrieve = add('retrieve', 790, 250);
        const answer = add('llm', 1040, 250);
        const deep = add('tool', 1040, 420);
        const output = add('output', 1290, 250);
        connect(input, bypass);
        connect(input, actions);
        connect(actions, grounding);
        connect(grounding, retrieve);
        connect(retrieve, answer);
        connect(grounding, deep);
        connect(answer, output);
        connect(deep, output);
      },
    },
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
      id: 'voice-v2v',
      label: 'Voice2Voice · Provider-neutral',
      description: 'Voice session → transcribe → tandem oracle → speak',
      build: (add, connect) => {
        const a = add('input', 60, 220);
        const s = add('voice_realtime_session_v1', 290, 220);
        const t = add('voice_realtime_transcribe_v1', 540, 220);
        const o = add('voice_tandem_oracle_v1', 790, 220);
        const c = add('voice_oracle_turn_v1', 1040, 220);
        const sp = add('voice_realtime_speak_v1', 1290, 220);
        const out = add('output', 1540, 220);
        connect(a, s);
        connect(s, t);
        connect(t, o);
        connect(o, c);
        connect(c, sp);
        connect(sp, out);
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

  // Subflow picker state — other Systems in the workspace, loaded lazily
  // the first time a subflow node is inspected. Always excludes the
  // current system id to prevent trivial self-recursion (Vague E / E3.3).
  readonly otherSystems = signal<System[]>([]);
  readonly otherSystemsLoading = signal(false);

  readonly skillSelectOptions = computed<FlowSelectOption[]>(() =>
    this.skills().map((skill) => ({
      value: skill.id,
      label: skill.slug,
      description: skill.name,
      tone: 'cyan',
    })),
  );

  readonly decisionDefaultOptions = computed<FlowSelectOption[]>(() =>
    this.decisionBranches()
      .filter((branch) => !!branch.label.trim())
      .map((branch) => ({
        value: branch.label,
        label: branch.label,
        description: branch.condition || 'Default branch candidate',
        tone: 'violet',
      })),
  );

  readonly joinStrategyOptions: FlowSelectOption[] = [
    { value: 'all', label: 'all', description: 'Wait for every inbound branch', tone: 'emerald' },
    { value: 'any', label: 'any', description: 'Continue as soon as one branch completes', tone: 'cyan' },
    { value: 'race', label: 'race', description: 'First branch wins; others are cancelled', tone: 'amber' },
  ];

  readonly subflowSystemOptions = computed<FlowSelectOption[]>(() =>
    this.otherSystems().map((system) => ({
      value: system.id,
      label: system.name,
      description: system.id,
      tone: 'cyan',
    })),
  );

  private pendingDrop: PaletteItem | null = null;
  private ids = 0;
  private terminalSeq = 0;
  private refreshScheduled = false;
  private validationScheduled = false;
  private refreshRaf: number | null = null;
  private canvasSelectionTimer: number | null = null;
  private perfStart = 0;
  private readonly onCanvasNodePointerCapture = (event: Event) => {
    const target = event.target as HTMLElement | null;
    const nodeEl = target?.closest('.drawflow-node') as HTMLElement | null;
    const rawId = this.rawIdFromCanvasNode(nodeEl);
    if (rawId) this.scheduleCanvasSelection(rawId);
  };

  ngOnInit(): void {
    const sid =
      this.route.snapshot.paramMap.get('systemId') ||
      this.route.snapshot.queryParamMap.get('systemId');
    this.systemId.set(sid);
    if (sid) {
      this.zoomCtx.setCurrentSystem(sid);
    } else {
      this.zoomCtx.setCurrentSystem(null);
    }
    this.zoomCtx.setCurrentRun(null);
    this.ensureSkillsLoaded();
  }

  async ngAfterViewInit(): Promise<void> {
    this.beginPerf('route');
    const el = this.container?.nativeElement;
    if (!el) {
      this.loading.set(false);
      this.error.set('Canvas element not found');
      return;
    }

    await this.zone.runOutsideAngular(async () => {
      try {
        this.setLoadPhase('Loading canvas engine…');
        const mod: any = await import('drawflow');
        this.markPerf('drawflow import');
        const Drawflow = mod.default ?? mod;
        this.setLoadPhase('Starting canvas…');
        this.editor = new Drawflow(el);
        this.editor.reroute = false;
        this.editor.reroute_fix_curvature = false;
        this.editor.start();
        el.addEventListener('mousedown', this.onCanvasNodePointerCapture, true);
        this.markPerf('editor.start');

        if (this.systemId()) {
          this.setLoadPhase('Hydrating System flow…');
          await this.hydrateFromSystem(this.systemId()!);
        } else {
          this.setLoadPhase('Loading template…');
          this.loadTemplate(this.flowTemplates[0]);
        }

        this.setLoadPhase('Binding canvas events…');
        this.attachChangeListeners();
        this.markPerf('ready');
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
    if (this.refreshRaf !== null) {
      cancelAnimationFrame(this.refreshRaf);
      this.refreshRaf = null;
    }
    if (this.canvasSelectionTimer !== null) {
      window.clearTimeout(this.canvasSelectionTimer);
      this.canvasSelectionTimer = null;
    }
    this.container?.nativeElement?.removeEventListener(
      'mousedown',
      this.onCanvasNodePointerCapture,
      true,
    );
    try {
      this.editor?.clear?.();
    } catch {
      // ignore
    }
  }

  private beginPerf(label: string): void {
    this.perfStart = performance.now();
    this.perfMarks.set({ [label]: 0 });
  }

  private markPerf(label: string): void {
    if (!this.perfStart) return;
    const elapsed = Math.round(performance.now() - this.perfStart);
    this.perfMarks.update((marks) => ({ ...marks, [label]: elapsed }));
    if (!label.startsWith('refreshKpis')) {
      console.info(`[FlowBuilder] ${label}: ${elapsed}ms`);
    }
  }

  private recordPerfSample(label: string, durationMs: number): void {
    this.perfMarks.update((marks) => ({ ...marks, [label]: Math.round(durationMs) }));
  }

  private setLoadPhase(phase: string): void {
    this.zone.run(() => this.loadPhase.set(phase));
  }

  readonly perfSummary = computed(() => {
    const marks = this.perfMarks();
    const ready = marks['ready'];
    if (ready == null) return '';
    return `ready ${ready}ms · validation ${marks['refreshKpis:full'] ?? '—'}ms`;
  });

  /**
   * Subscribe to Drawflow's mutation events so the header KPIs stay in
   * sync with the canvas. All events are handled outside the Angular
   * zone — we only poke CD when we actually update a signal.
   */
  private attachChangeListeners(): void {
    if (!this.editor?.on) return;
    const refresh = () => {
      this.scheduleRefreshKpis();
    };
    const onSelect = (id: number | string) => {
      this.zone.run(() => this.onNodeSelected(String(id)));
    };
    const onUnselect = () => {
      this.zone.run(() => {
        this.selectedNodeId.set(null);
        this.selectedNode.set(null);
        this.closeConfigSheet();
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
    this.refreshKpis('full');
  }

  private scheduleRefreshKpis(): void {
    if (this.refreshScheduled) return;
    this.refreshScheduled = true;
    this.refreshRaf = requestAnimationFrame(() => {
      this.refreshScheduled = false;
      this.zone.run(() => this.refreshKpis('light'));
    });
    if (!this.validationScheduled) {
      this.validationScheduled = true;
      window.setTimeout(() => {
        this.validationScheduled = false;
        this.zone.run(() => this.refreshKpis('full'));
      }, 160);
    }
  }

  private refreshKpis(mode: 'light' | 'full' = 'full'): void {
    const start = performance.now();
    const graph = this.exportGraph();
    const flow = this.serializer.project(graph);
    this.nodeCount.set(flow.nodes.length);
    this.edgeCount.set(flow.edges.length);
    this.extended.set(!!flow.extended);
    if (mode === 'full') {
      this.issues.set(this.serializer.validateFlow(flow));
    }
    this.recordPerfSample(`refreshKpis:${mode}`, performance.now() - start);
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
      const fallback = this.canonicalNodeFromRawId(rawId);
      if (fallback) {
        this.selectCanonicalNode(fallback, rawId);
        return;
      }
      this.selectedNodeId.set(null);
      this.selectedNode.set(null);
      return;
    }
    const canonicalId =
      (nodeData.data?.['canonical_id'] as string) || `flow.${rawId}`;
    const type =
      (nodeData.data?.['canonical_type'] as string) || nodeData.name || 'custom';
    const kind = (nodeData.data?.['canonical_kind'] as NodeKind) || 'task';
    const config = (nodeData.data?.['canonical_config'] as Record<string, unknown>) ?? {};
    if (!config['skill_slug'] && this.skills().some((skill) => skill.slug === type)) {
      config['skill_slug'] = type;
    }
    const { canonical_id: _ci, canonical_type: _ct, canonical_kind: _ck,
            canonical_config: _cc, canonical_inputs: _cin, canonical_outputs: _cout,
            canonical_edge_meta: _cem,
            ...rest } = nodeData.data ?? {};
    this.selectedNodeId.set(rawId);
    this.selectedNode.set({
      id: canonicalId,
      type,
      kind,
      label: this.extractLabelFromHtml(nodeData.html ?? ''),
      data: rest,
      config,
      inputs: (nodeData.data?.['canonical_inputs'] as CanonicalFlowNode['inputs']) ?? [],
      outputs: (nodeData.data?.['canonical_outputs'] as CanonicalFlowNode['outputs']) ?? [],
      position: { x: nodeData.pos_x, y: nodeData.pos_y },
    });
  }

  private extractLabelFromHtml(html: string): string {
    const nodeTitle = html.match(/class="df-node-title"[^>]*>([^<]+)</);
    if (nodeTitle?.[1]) return nodeTitle[1].trim();
    const fnTitle = html.match(/class="fn-title"[^>]*>([^<]+)</);
    if (fnTitle?.[1]) return fnTitle[1].trim();
    const match = html.match(/class="df-title[^"]*"[^>]*>([^<]+)</);
    if (match?.[1]) return match[1].trim();
    const fallback = html.match(/>(.*?)</);
    return fallback?.[1]?.trim() ?? 'Node';
  }

  /** Push a line into the Execution Terminal. Capped at 200 entries. */
  pushTerminal(entry: Omit<TerminalEntry, 't' | 'id'>): void {
    const t = new Date().toTimeString().slice(0, 8);
    this.terminalLog.update((log) => {
      const next = [...log, { t, id: `term-${++this.terminalSeq}`, ...entry }];
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
      const next = [...log, { id: `term-${++this.terminalSeq}`, t, tag, tone, text: delta, streamId }];
      return next.length > 200 ? next.slice(next.length - 200) : next;
    });
  }

  clearTerminal(): void {
    this.terminalLog.set([]);
  }

  toggleTerminal(): void {
    this.terminalOpen.update((v) => !v);
    this.redrawConnectionsSoon();
    this.fitCanvasSoon();
  }

  toggleInspector(): void {
    this.inspectorOpen.update((v) => !v);
    this.redrawConnectionsSoon();
    this.fitCanvasSoon();
  }

  openConfigSheet(tab: ConfigSheetTab = 'overview'): void {
    if (!this.selectedNode()) return;
    this.configSheetTab.set(tab);
    this.configSheetOpen.set(true);
    if (tab === 'config' && (this.selectedNode()?.kind ?? 'task') === 'task') {
      this.ensureSkillsLoaded();
    }
    if (tab === 'config' && (this.selectedNode()?.kind ?? 'task') === 'subflow') {
      this.ensureOtherSystemsLoaded();
    }
  }

  closeConfigSheet(): void {
    this.configSheetOpen.set(false);
    this.promptEditKey.set(null);
    this.promptDraft.set('');
  }

  setConfigSheetTab(tab: ConfigSheetTab): void {
    this.configSheetTab.set(tab);
    if (tab === 'config' && (this.selectedNode()?.kind ?? 'task') === 'task') {
      this.ensureSkillsLoaded();
    }
    if (tab === 'config' && (this.selectedNode()?.kind ?? 'task') === 'subflow') {
      this.ensureOtherSystemsLoaded();
    }
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
    this.zone.run(() => {
      this.system.set(sys);
      this.zoomCtx.setCurrentSystem(sys.id, sys.name);
      if (sys.capability_id) this.zoomCtx.setCurrentCapability(sys.capability_id);
      if (sys.context_id) this.zoomCtx.setCurrentContext(sys.context_id);
    });

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
    this.loadFlowManifest(systemId);
  }

  private loadFlowManifest(systemId: string): void {
    this.flowManifestLoading.set(true);
    this.canonical.getSystemFlowManifest(systemId).subscribe({
      next: (manifest) => {
        this.flowManifestLoading.set(false);
        this.flowManifest.set(manifest);
        const firstUnit = manifest?.unit_catalog?.[0];
        if (!this.selectedNode() && firstUnit) {
          this.selectManifestUnit(firstUnit, false);
        }
      },
      error: () => {
        this.flowManifestLoading.set(false);
        this.flowManifest.set(null);
      },
    });
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
    this.fitCanvasSoon();
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
    this.fitCanvasSoon();
  }

  private exportGraph(): DrawflowGraph {
    try {
      return this.editor?.export?.() ?? { drawflow: { Home: { data: {} } } };
    } catch {
      return { drawflow: { Home: { data: {} } } };
    }
  }

  selectCanvasNode(canonicalId: string | undefined): void {
    if (!canonicalId) return;
    const graph = this.exportGraph();
    for (const [rawId, node] of Object.entries(graph.drawflow?.Home?.data ?? {})) {
      const cid = (node.data?.['canonical_id'] as string) || `flow.${rawId}`;
      if (cid !== canonicalId) continue;
      try {
        this.editor?.node_selected?.(rawId);
      } catch {
        // Some Drawflow builds do not expose node_selected. The inspector
        // still updates from the graph, which is the important part.
      }
      this.scheduleCanvasSelection(rawId);
      return;
    }

    const fallbackNode = this.findCanvasNodeByCanonicalId(canonicalId);
    const rawId = this.rawIdFromCanvasNode(fallbackNode);
    if (rawId) {
      this.scheduleCanvasSelection(rawId);
      return;
    }

    this.scheduleCanonicalNodeSelection(canonicalId);
  }

  selectManifestUnit(unit: FlowManifestUnit, syncCanvas = true): void {
    if (!unit?.id) return;
    const node = this.canonicalNodeById(unit.id) ?? this.canonicalNodeFromManifestUnit(unit);
    this.zone.run(() => {
      this.selectCanonicalNode(node, unit.id);
      this.inspectorOpen.set(true);
      this.cdr.markForCheck();
    });
    if (syncCanvas) this.selectCanvasNode(unit.id);
  }

  onCanvasClick(event: MouseEvent): void {
    const target = event.target as HTMLElement | null;
    const nodeEl = target?.closest('.drawflow-node') as HTMLElement | null;
    const rawId = this.rawIdFromCanvasNode(nodeEl);
    if (!rawId) return;
    this.scheduleCanvasSelection(rawId);
  }

  private scheduleCanvasSelection(rawId: string): void {
    if (this.canvasSelectionTimer !== null) {
      window.clearTimeout(this.canvasSelectionTimer);
    }
    this.canvasSelectionTimer = window.setTimeout(() => {
      this.canvasSelectionTimer = null;
      this.zone.run(() => {
        this.onNodeSelected(rawId);
        this.inspectorOpen.set(true);
        this.cdr.markForCheck();
      });
    }, 0);
  }

  private scheduleCanonicalNodeSelection(canonicalId: string): void {
    if (this.canvasSelectionTimer !== null) {
      window.clearTimeout(this.canvasSelectionTimer);
    }
    this.canvasSelectionTimer = window.setTimeout(() => {
      this.canvasSelectionTimer = null;
      const node = this.canonicalNodeById(canonicalId);
      if (!node) return;
      this.zone.run(() => {
        this.selectCanonicalNode(node, canonicalId);
        this.inspectorOpen.set(true);
        this.cdr.markForCheck();
      });
    }, 0);
  }

  private rawIdFromCanvasNode(nodeEl: HTMLElement | null): string | null {
    const id = nodeEl?.id ?? '';
    const match = /^node-(.+)$/.exec(id);
    return match?.[1] ?? null;
  }

  private selectedRawNodeId(): string | null {
    const selected = this.selectedNodeId();
    const graph = this.exportGraph();
    const data = graph.drawflow?.Home?.data ?? {};
    if (selected && data[selected]) return selected;
    const canonicalId = this.selectedNode()?.id ?? selected;
    if (!canonicalId) return null;
    for (const [rawId, node] of Object.entries(data)) {
      if ((node.data?.['canonical_id'] as string) === canonicalId) return rawId;
    }
    return null;
  }

  private canonicalNodeById(canonicalId: string): CanonicalFlowNode | null {
    const flow = this.system()?.flow_definition as unknown as CanonicalFlow | undefined;
    return flow?.nodes?.find((node) => node.id === canonicalId) ?? null;
  }

  private canonicalNodeFromRawId(rawId: string): CanonicalFlowNode | null {
    const idx = Number.parseInt(rawId, 10);
    if (!Number.isFinite(idx) || idx < 1) return null;
    const flow = this.system()?.flow_definition as unknown as CanonicalFlow | undefined;
    return flow?.nodes?.[idx - 1] ?? null;
  }

  private canonicalNodeFromManifestUnit(unit: FlowManifestUnit): CanonicalFlowNode {
    const position =
      typeof unit.position?.x === 'number' && typeof unit.position?.y === 'number'
        ? { x: unit.position.x, y: unit.position.y }
        : undefined;
    return {
      id: unit.id,
      type: unit.node_type || unit.unit_type || 'tool',
      kind: (unit.kind as NodeKind) || 'task',
      label: unit.label || unit.id,
      data: {
        description: unit.description,
        runtime_ref: unit.runtime_ref,
        prompt_contract: unit.prompt_contract ?? undefined,
      },
      config: {
        runtime_ref: unit.runtime_ref,
        skill_slug: unit.skill_slug,
        skill_id: unit.skill_id,
      },
      inputs: [],
      outputs: [],
      position,
    };
  }

  private selectCanonicalNode(node: CanonicalFlowNode, selectedId: string): void {
    const config = { ...((node.config ?? {}) as Record<string, unknown>) };
    if (!config['skill_slug'] && this.skills().some((skill) => skill.slug === node.type)) {
      config['skill_slug'] = node.type;
    }
    this.selectedNodeId.set(selectedId);
    this.selectedNode.set({
      ...node,
      data: { ...((node.data ?? {}) as Record<string, unknown>) },
      config,
      inputs: node.inputs ?? [],
      outputs: node.outputs ?? [],
    });
  }

  private findCanvasNodeByCanonicalId(canonicalId: string): HTMLElement | null {
    const host = this.container?.nativeElement;
    if (!host) return null;
    const nodes = Array.from(host.querySelectorAll<HTMLElement>('.drawflow-node'));
    const graph = this.exportGraph();
    for (const nodeEl of nodes) {
      const rawId = this.rawIdFromCanvasNode(nodeEl);
      if (!rawId) continue;
      const nodeData = graph.drawflow?.Home?.data?.[rawId];
      const cid = (nodeData?.data?.['canonical_id'] as string) || `flow.${rawId}`;
      if (cid === canonicalId) return nodeEl;
    }
    return null;
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

  onPaletteDragStart(payload: { event: DragEvent; node: PaletteItem }): void {
    this.onDragStart(payload.event, payload.node);
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
      this.fitCanvasSoon();
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
    this.redrawConnectionsSoon();
  }

  zoomReset(): void {
    if (!this.editor) return;
    this.editor.zoom_reset();
    this.redrawConnectionsSoon();
  }

  fitCanvas(): void {
    if (!this.editor || !this.container?.nativeElement) return;
    const graph = this.exportGraph();
    const entries = Object.entries(graph.drawflow?.Home?.data ?? {});
    if (!entries.length) return;
    const boxes = entries.map(([rawId, node]) => {
      const el = document.getElementById(`node-${rawId}`);
      const rect = el?.getBoundingClientRect();
      const scale = this.editor?.zoom || 1;
      return {
        x: node.pos_x,
        y: node.pos_y,
        w: rect?.width ? rect.width / scale : 240,
        h: rect?.height ? rect.height / scale : 132,
      };
    });
    const minX = Math.min(...boxes.map((box) => box.x));
    const minY = Math.min(...boxes.map((box) => box.y));
    const maxX = Math.max(...boxes.map((box) => box.x + box.w));
    const maxY = Math.max(...boxes.map((box) => box.y + box.h));
    const width = Math.max(1, maxX - minX);
    const height = Math.max(1, maxY - minY);
    const rect = this.container.nativeElement.getBoundingClientRect();
    const availableW = Math.max(240, rect.width - 128);
    const availableH = Math.max(220, rect.height - 128);
    const zoom = Math.min(1, Math.max(0.5, Math.min(availableW / width, availableH / height)));
    const rawTx = (rect.width - width * zoom) / 2 - minX * zoom;
    const rawTy = (rect.height - height * zoom) / 2 - minY * zoom;
    const tx = Math.max(40, Math.min(120, rawTx));
    const ty = Math.max(36, Math.min(104, rawTy));
    this.editor.zoom = zoom;
    this.editor.canvas_x = tx;
    this.editor.canvas_y = ty;
    const precanvas = this.container.nativeElement.querySelector('.precanvas') as HTMLElement | null;
    if (precanvas) {
      precanvas.style.minWidth = '3600px';
      precanvas.style.minHeight = '2200px';
      precanvas.style.transform = `translate(${tx}px, ${ty}px) scale(${zoom})`;
      precanvas.style.transformOrigin = '0 0';
    }
    this.redrawConnectionsSoon();
  }

  private fitCanvasSoon(): void {
    window.setTimeout(() => this.zone.runOutsideAngular(() => this.fitCanvas()), 80);
  }

  private redrawConnectionsSoon(): void {
    if (!this.editor) return;
    const redraw = () => {
      try {
        const data = this.exportGraph().drawflow?.Home?.data ?? {};
        for (const rawId of Object.keys(data)) {
          this.editor?.updateConnectionNodes?.(`node-${rawId}`);
        }
        this.editor?.updateConnectionNodes?.('node-*');
      } catch {
        // ignore redraw drift on older Drawflow builds
      }
    };
    redraw();
    window.requestAnimationFrame(redraw);
    window.setTimeout(redraw, 80);
    window.setTimeout(redraw, 180);
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
    // Reset any previous server-side rejection so a clean retry doesn't
    // leave stale issues glued under the canvas.
    this.serverIssues.set([]);
    this.saving.set(true);
    this.canonical
      .saveSystemFlow(sid, merged as unknown as Record<string, unknown>)
      .subscribe({
        next: (res) => {
          this.saving.set(false);
          if (!res.ok) {
            if (res.reason === 'invalid') {
              // Map backend codes to the local issue type — the two
              // enumerations are kept in sync (see ``flow-serializer`` +
              // ``dag_validator``). The cast is safe by construction.
              this.serverIssues.set(res.issues as unknown as FlowValidationIssue[]);
              const errs = res.issues.filter((i) => i.level === 'error').length;
              this.toastr.error(
                `Backend rejected the flow — ${errs} structural error${errs > 1 ? 's' : ''}. See validation strip.`,
                'Save blocked',
              );
            } else {
              this.toastr.error(
                res.message || 'Could not save flow — network error.',
                'Save failed',
              );
            }
            return;
          }
          this.system.set(res.system);
          this.source.set('flow');
          this.extended.set(!!merged.extended);
          this.loadFlowManifest(sid);
          // Server-side warnings survive the save — surface them in the
          // strip alongside client issues so the user sees the full
          // picture (e.g. missing HITL prompt that the backend tolerates
          // but still flags).
          this.serverIssues.set(
            (res.warnings ?? []) as unknown as FlowValidationIssue[],
          );
          const versionTag = res.new_version ? ` (v${res.new_version.version_number})` : '';
          this.toastr.success(
            `Flow saved to "${res.system.name}"${versionTag}.`,
            'Saved',
          );
          // Bust the version cache so the panel reflects the new tip
          // the next time the user opens it.
          if (this.versionsPanelOpen()) {
            this.refreshVersions();
          } else {
            this.versions.set([]);
            this.versionsTotal.set(0);
            this.versionPreviews.set({});
          }
        },
        error: () => {
          this.saving.set(false);
          this.toastr.error('Could not save flow — network error.', 'Save failed');
        },
      });
  }

  // ---------- Versions panel (Vague E / E3.2) ----------

  /** Open the right-rail Versions drawer. Loads the first page lazily
   *  and captures the canvas as diff baseline so node/edge deltas stay
   *  stable while the user scrolls through history. */
  openVersionsPanel(): void {
    const sid = this.systemId();
    if (!sid) return;
    this.captureDiffBaseline();
    this.versionsPanelOpen.set(true);
    if (this.versions().length === 0) this.refreshVersions();
  }

  closeVersionsPanel(): void {
    this.versionsPanelOpen.set(false);
  }

  private captureDiffBaseline(): void {
    const graph = this.exportGraph();
    const flow = this.serializer.project(graph);
    this.versionsDiffBaseline = {
      nodes: new Set(flow.nodes.map((n: CanonicalFlowNode) => String(n.id))),
      edges: new Set(
        flow.edges.map((e: CanonicalFlowEdge) => `${e.from}->${e.to}`),
      ),
    };
  }

  refreshVersions(): void {
    const sid = this.systemId();
    if (!sid) return;
    this.versionsLoading.set(true);
    this.canonical.listSystemVersions(sid, { limit: 50, offset: 0 }).subscribe({
      next: (res) => {
        this.versionsLoading.set(false);
        this.versions.set(res.versions ?? []);
        this.versionsTotal.set(res.total ?? 0);
      },
      error: () => {
        this.versionsLoading.set(false);
        this.toastr.error('Could not load version history.', 'Versions');
      },
    });
  }

  /** Friendly relative timestamp — ``3m ago`` / ``2d ago`` / ``Apr 12``.
   *  Falls back to the raw ISO string if parsing fails. */
  formatVersionTimestamp(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    const t = d.getTime();
    if (Number.isNaN(t)) return iso;
    const diffMs = Date.now() - t;
    const sec = Math.round(diffMs / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.round(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.round(hr / 24);
    if (day < 14) return `${day}d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  /** Lightweight symmetric-difference count vs the baseline graph. Returns
   *  ``null`` when the baseline hasn't been captured yet (panel never
   *  opened) so the template can skip rendering. Missing the row's own
   *  full payload still gives a directional count via node/edge totals. */
  versionDiffLabel(v: SystemVersionSummary): string | null {
    const base = this.versionsDiffBaseline;
    if (base.nodes.size === 0 && base.edges.size === 0) return null;
    const preview = this.versionPreviews()[v.version_number];
    if (!preview) {
      const dn = v.node_count - base.nodes.size;
      const de = v.edge_count - base.edges.size;
      if (dn === 0 && de === 0) return '= canvas';
      const parts: string[] = [];
      if (dn !== 0) parts.push(`${dn > 0 ? '+' : ''}${dn}n`);
      if (de !== 0) parts.push(`${de > 0 ? '+' : ''}${de}e`);
      return parts.join(' ');
    }
    const flow = preview.flow_definition as unknown as CanonicalFlow;
    const otherNodes = new Set((flow?.nodes ?? []).map((n: CanonicalFlowNode) => String(n.id)));
    const otherEdges = new Set(
      (flow?.edges ?? []).map((e: CanonicalFlowEdge) => `${e.from}->${e.to}`),
    );
    let added = 0;
    let removed = 0;
    for (const n of otherNodes) if (!base.nodes.has(n)) added++;
    for (const n of base.nodes) if (!otherNodes.has(n)) removed++;
    let edgeAdded = 0;
    let edgeRemoved = 0;
    for (const e of otherEdges) if (!base.edges.has(e)) edgeAdded++;
    for (const e of base.edges) if (!otherEdges.has(e)) edgeRemoved++;
    if (added + removed + edgeAdded + edgeRemoved === 0) return '= canvas';
    const parts: string[] = [];
    if (added || removed) parts.push(`${added ? '+' + added : ''}${removed ? ' -' + removed : ''} n`);
    if (edgeAdded || edgeRemoved) parts.push(`${edgeAdded ? '+' + edgeAdded : ''}${edgeRemoved ? ' -' + edgeRemoved : ''} e`);
    return parts.join(' · ').trim();
  }

  beginRollback(v: SystemVersionSummary): void {
    const sid = this.systemId();
    if (!sid) return;
    this.rollbackTarget.set(v);
    this.rollbackMessage.set('');
    // Prefetch the full payload so the diff count hardens into exact
    // symmetric-difference math while the modal is open.
    if (!this.versionPreviews()[v.version_number]) {
      this.canonical.getSystemVersion(sid, v.version_number).subscribe((full) => {
        if (!full) return;
        this.versionPreviews.update((m) => ({ ...m, [v.version_number]: full }));
      });
    }
  }

  cancelRollback(): void {
    if (this.rollbackPending()) return;
    this.rollbackTarget.set(null);
    this.rollbackMessage.set('');
  }

  onRollbackMessageChange(ev: Event): void {
    const t = ev.target as HTMLInputElement | null;
    this.rollbackMessage.set(t?.value ?? '');
  }

  confirmRollback(): void {
    const sid = this.systemId();
    const tgt = this.rollbackTarget();
    if (!sid || !tgt) return;
    this.rollbackPending.set(true);
    const msg = this.rollbackMessage().trim() || `rollback to v${tgt.version_number}`;
    this.canonical.rollbackSystemVersion(sid, tgt.version_number, msg).subscribe({
      next: (res) => {
        this.rollbackPending.set(false);
        if (!res) {
          this.toastr.error('Rollback failed — see backend logs.', 'Rollback');
          return;
        }
        this.rollbackTarget.set(null);
        this.rollbackMessage.set('');
        // Reload the System + canvas from the rolled-back state and
        // refresh the version list (a new rollback version was just
        // appended on top of history).
        this.system.set(res.system);
        this.importFlow(
          (res.system.flow_definition ?? {}) as unknown as CanonicalFlow,
        );
        this.source.set('flow');
        this.extended.set(
          !!(res.system.flow_definition as { extended?: boolean } | undefined)?.extended,
        );
        this.serverIssues.set([]);
        this.refreshVersions();
        this.toastr.success(
          `Rolled back to v${tgt.version_number} (new v${res.new_version.version_number}).`,
          'Rollback',
        );
      },
      error: () => {
        this.rollbackPending.set(false);
        this.toastr.error('Rollback failed — network error.', 'Rollback');
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

  // ---------- Export / Import (Vague E / E3.4) ----------

  /** Download the current system as a portable JSON envelope. Uses the
   *  browser's Blob + anchor download trick — zero new dependencies. */
  exportCurrentSystem(): void {
    const sid = this.systemId();
    const name = this.system()?.name ?? 'chain';
    if (!sid) return;
    this.exporting.set(true);
    this.canonical.exportSystem(sid).subscribe({
      next: (envelope) => {
        this.exporting.set(false);
        if (!envelope) {
          this.toastr.error('Export failed — backend rejected the request.', 'Export');
          return;
        }
        this.downloadJson(envelope, this.slugifyFileName(name));
        this.toastr.success(`Downloaded "${name}.json"`, 'Export');
      },
      error: () => {
        this.exporting.set(false);
        this.toastr.error('Export failed — network error.', 'Export');
      },
    });
  }

  openImportModal(): void {
    this.importModalOpen.set(true);
    this.importPaste.set('');
    this.importTargetName.set('');
    this.importError.set(null);
    this.importReport.set(null);
  }

  closeImportModal(): void {
    if (this.importPending()) return;
    this.importModalOpen.set(false);
  }

  onImportNameChange(ev: Event): void {
    this.importTargetName.set((ev.target as HTMLInputElement | null)?.value ?? '');
  }

  onImportPasteChange(ev: Event): void {
    this.importPaste.set((ev.target as HTMLTextAreaElement | null)?.value ?? '');
    this.importError.set(null);
    this.importReport.set(null);
  }

  onImportFileChange(ev: Event): void {
    const input = ev.target as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      this.importError.set('File is larger than 2 MiB — refusing to load.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? '');
      this.importPaste.set(text);
      if (!this.importTargetName().trim()) {
        // Default the clone name to "<fileStem> (copy)" so the user sees
        // a sensible value they can tweak before hitting Import.
        const stem = file.name.replace(/\.json$/i, '').trim();
        if (stem) this.importTargetName.set(`${stem} (copy)`);
      }
      this.importError.set(null);
      this.importReport.set(null);
    };
    reader.onerror = () => {
      this.importError.set('Could not read file.');
    };
    reader.readAsText(file);
  }

  confirmImport(): void {
    const raw = this.importPaste().trim();
    if (!raw) {
      this.importError.set('Paste an envelope or pick a JSON file first.');
      return;
    }
    let envelope: Record<string, unknown>;
    try {
      envelope = JSON.parse(raw);
    } catch (err) {
      this.importError.set(
        `Invalid JSON: ${(err as Error)?.message ?? 'could not parse.'}`,
      );
      return;
    }
    if (envelope?.['kind'] !== 'agentium.system.export') {
      this.importError.set(
        'Payload is not an Agentium export envelope (wrong ``kind``).',
      );
      return;
    }
    this.importPending.set(true);
    this.importError.set(null);
    const target = this.importTargetName().trim() || null;
    this.canonical.importSystem(envelope, target).subscribe({
      next: (res) => {
        this.importPending.set(false);
        if (!res.ok) {
          if (res.reason === 'flow_invalid') {
            this.importError.set(
              `Imported flow is invalid — ${res.issues.length} structural issue(s).`,
            );
            this.serverIssues.set(res.issues as unknown as FlowValidationIssue[]);
          } else if (res.reason === 'invalid_envelope') {
            this.importError.set(res.message);
          } else {
            this.importError.set(res.message || 'Network error during import.');
          }
          this.toastr.error(this.importError() ?? 'Import failed', 'Import');
          return;
        }
        this.importReport.set(res.import_report);
        const unresolved = res.import_report.unresolved_skills.length;
        const msg = unresolved > 0
          ? `Imported "${res.system.name}" — ${unresolved} unresolved skill(s).`
          : `Imported "${res.system.name}".`;
        if (unresolved > 0) {
          this.toastr.warning(msg, 'Import');
        } else {
          this.toastr.success(msg, 'Import');
        }
        // Navigate to the newly-created system so the user lands on the
        // editor with the imported flow already loaded. The modal stays
        // open just long enough to show the report, then closes on nav.
        setTimeout(() => {
          this.importModalOpen.set(false);
          this.router.navigate(['/workflow'], {
            queryParams: { systemId: res.system.id },
          });
        }, 800);
      },
      error: () => {
        this.importPending.set(false);
        this.importError.set('Network error during import.');
        this.toastr.error('Import failed — network error.', 'Import');
      },
    });
  }

  private downloadJson(payload: SystemExportEnvelope, baseName: string): void {
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${baseName}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  private slugifyFileName(name: string): string {
    const slug = name
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .toLowerCase();
    return slug || 'chain';
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
    const rawId = this.selectedRawNodeId();
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

  onSkillSelect(value: string | null): void {
    this.bindSkill(value || null);
  }

  // ---------- Kind-specific node-props editors (Vague E / E3.3) ----------
  //
  // The editors below all follow the same two-step pattern the Skill
  // binder uses: (1) mutate ``canonical_config`` on the Drawflow node
  // data through ``updateNodeDataFromId`` so the next ``project()``
  // picks up the change; (2) mirror the mutation into ``selectedNode``
  // so the inspector re-renders without waiting for the canvas event.
  // ``refreshKpis`` at the end re-runs validation (client-side) so the
  // issues strip updates in real time.

  /** Rename the currently selected node. Writes to both the Drawflow
   *  node data (``name`` + ``data.label``) and the canonical projection. */
  onNodeLabelChange(ev: Event): void {
    const rawId = this.selectedRawNodeId();
    const node = this.selectedNode();
    if (!rawId || !node || !this.editor) return;
    const next = (ev.target as HTMLInputElement | null)?.value?.trim() ?? '';
    const graph = this.exportGraph();
    const nodeData = graph?.drawflow?.Home?.data?.[rawId];
    if (!nodeData) return;
    const nextData = {
      ...(nodeData.data ?? {}),
      label: next || node.type,
    };
    try {
      this.editor.updateNodeDataFromId(rawId, nextData);
      const el = document.querySelector(`#node-${rawId} .df-node-title`);
      if (el) (el as HTMLElement).textContent = next || node.type;
    } catch {
      return;
    }
    this.selectedNode.set({ ...node, label: next || node.type });
    this.refreshKpis();
  }

  /** Generic ``canonical_config`` merge — pushes a partial update into
   *  the selected node and keeps the inspector signal in sync. */
  private patchSelectedConfig(partial: Record<string, unknown>): void {
    const rawId = this.selectedRawNodeId();
    const node = this.selectedNode();
    if (!rawId || !node || !this.editor) return;
    const graph = this.exportGraph();
    const nodeData = graph?.drawflow?.Home?.data?.[rawId];
    if (!nodeData) return;
    const prevCfg = (nodeData.data?.['canonical_config'] as Record<string, unknown>) ?? {};
    const nextCfg: Record<string, unknown> = { ...prevCfg, ...partial };
    // Strip keys whose value is explicitly set to ``undefined`` — lets
    // callers request a clean removal (e.g. clearing ``break_on``).
    for (const k of Object.keys(partial)) {
      if (partial[k] === undefined) delete nextCfg[k];
    }
    const nextData = { ...(nodeData.data ?? {}), canonical_config: nextCfg };
    try {
      this.editor.updateNodeDataFromId(rawId, nextData);
    } catch {
      return;
    }
    this.selectedNode.set({
      ...node,
      config: nextCfg as CanonicalFlowNode['config'],
    });
    this.refreshKpis();
  }

  // ── Decision ──────────────────────────────────────────────────────
  decisionBranches(): { label: string; condition: string }[] {
    const cfg = (this.selectedNode()?.config ?? {}) as {
      branches?: { label: string; condition: string }[];
    };
    const b = Array.isArray(cfg.branches) ? cfg.branches : [];
    return b.length >= 2 ? b : [...b, ...Array(2 - b.length).fill({ label: '', condition: '' })];
  }

  decisionDefault(): string | null {
    const cfg = (this.selectedNode()?.config ?? {}) as { default_branch?: string };
    return cfg.default_branch ?? null;
  }

  patchDecisionBranch(index: number, field: 'label' | 'condition', ev: Event): void {
    const value = (ev.target as HTMLInputElement | null)?.value ?? '';
    const current = [...this.decisionBranches()];
    if (!current[index]) return;
    current[index] = { ...current[index], [field]: value };
    this.patchSelectedConfig({ branches: current });
  }

  addDecisionBranch(): void {
    const current = [...this.decisionBranches()];
    current.push({ label: `branch_${current.length + 1}`, condition: '' });
    this.patchSelectedConfig({ branches: current });
  }

  removeDecisionBranch(index: number): void {
    const current = [...this.decisionBranches()];
    if (current.length <= 2) return;
    current.splice(index, 1);
    this.patchSelectedConfig({ branches: current });
  }

  onDecisionDefaultChange(ev: Event): void {
    const v = (ev.target as HTMLSelectElement | null)?.value ?? '';
    this.patchSelectedConfig({ default_branch: v || undefined });
  }

  setDecisionDefault(value: string | null): void {
    this.patchSelectedConfig({ default_branch: value || undefined });
  }

  // ── Fork ──────────────────────────────────────────────────────────
  forkBranches(): string[] {
    const cfg = (this.selectedNode()?.config ?? {}) as { branches?: string[] };
    const b = Array.isArray(cfg.branches) ? cfg.branches : [];
    return b.length >= 2 ? b : [...b, ...Array(2 - b.length).fill('')];
  }

  patchForkBranch(index: number, ev: Event): void {
    const value = (ev.target as HTMLInputElement | null)?.value ?? '';
    const current = [...this.forkBranches()];
    current[index] = value;
    this.patchSelectedConfig({ branches: current });
  }

  addForkBranch(): void {
    const current = [...this.forkBranches()];
    current.push(`branch_${current.length + 1}`);
    this.patchSelectedConfig({ branches: current });
  }

  removeForkBranch(index: number): void {
    const current = [...this.forkBranches()];
    if (current.length <= 2) return;
    current.splice(index, 1);
    this.patchSelectedConfig({ branches: current });
  }

  // ── Join ──────────────────────────────────────────────────────────
  joinStrategy(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as { strategy?: string };
    return cfg.strategy ?? 'all';
  }

  onJoinStrategyChange(ev: Event): void {
    const v = (ev.target as HTMLSelectElement | null)?.value ?? 'all';
    this.patchSelectedConfig({ strategy: v });
  }

  setJoinStrategy(value: string | null): void {
    this.patchSelectedConfig({ strategy: value || 'all' });
  }

  // ── Loop ──────────────────────────────────────────────────────────
  loopIterator(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as { iterator?: string };
    return cfg.iterator ?? '';
  }
  loopMaxIterations(): number {
    const cfg = (this.selectedNode()?.config ?? {}) as { max_iterations?: number };
    return Number.isFinite(cfg.max_iterations) ? (cfg.max_iterations as number) : 10;
  }
  loopBreakOn(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as { break_on?: string };
    return cfg.break_on ?? '';
  }
  patchLoopField(field: 'iterator' | 'max_iterations' | 'break_on', ev: Event): void {
    const raw = (ev.target as HTMLInputElement | null)?.value ?? '';
    if (field === 'max_iterations') {
      const n = Number.parseInt(raw, 10);
      this.patchSelectedConfig({
        max_iterations: Number.isFinite(n) && n > 0 ? n : undefined,
      });
      return;
    }
    this.patchSelectedConfig({ [field]: raw.trim() || undefined });
  }

  // ── Retry ─────────────────────────────────────────────────────────
  retryMaxAttempts(): number {
    const cfg = (this.selectedNode()?.config ?? {}) as { max_attempts?: number };
    return Number.isFinite(cfg.max_attempts) ? (cfg.max_attempts as number) : 3;
  }
  retryBackoffMs(): number {
    const cfg = (this.selectedNode()?.config ?? {}) as { backoff_ms?: number };
    return Number.isFinite(cfg.backoff_ms) ? (cfg.backoff_ms as number) : 1000;
  }
  retryOnErrors(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as { on_errors?: string[] };
    return Array.isArray(cfg.on_errors) ? cfg.on_errors.join(', ') : '';
  }
  patchRetryField(field: 'max_attempts' | 'backoff_ms' | 'on_errors', ev: Event): void {
    const raw = (ev.target as HTMLInputElement | null)?.value ?? '';
    if (field === 'on_errors') {
      const list = raw.split(',').map((s) => s.trim()).filter(Boolean);
      this.patchSelectedConfig({ on_errors: list.length > 0 ? list : undefined });
      return;
    }
    const n = Number.parseInt(raw, 10);
    if (!Number.isFinite(n) || n < 0) return;
    this.patchSelectedConfig({ [field]: n });
  }

  // ── HITL ──────────────────────────────────────────────────────────
  hitlPrompt(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as { prompt?: string };
    return cfg.prompt ?? '';
  }
  hitlTimeoutMs(): number {
    const cfg = (this.selectedNode()?.config ?? {}) as { timeout_ms?: number };
    return Number.isFinite(cfg.timeout_ms) ? (cfg.timeout_ms as number) : 0;
  }
  hitlApprovers(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as { approvers?: string[] };
    return Array.isArray(cfg.approvers) ? cfg.approvers.join(', ') : '';
  }
  patchHitlField(field: 'prompt' | 'timeout_ms' | 'approvers', ev: Event): void {
    const raw = (ev.target as HTMLInputElement | HTMLTextAreaElement | null)?.value ?? '';
    if (field === 'approvers') {
      const list = raw.split(',').map((s) => s.trim()).filter(Boolean);
      this.patchSelectedConfig({ approvers: list.length > 0 ? list : undefined });
      return;
    }
    if (field === 'timeout_ms') {
      const n = Number.parseInt(raw, 10);
      this.patchSelectedConfig({
        timeout_ms: Number.isFinite(n) && n > 0 ? n : undefined,
      });
      return;
    }
    this.patchSelectedConfig({ prompt: raw });
  }

  // ── Subflow ───────────────────────────────────────────────────────
  subflowSystemId(): string | null {
    const cfg = (this.selectedNode()?.config ?? {}) as { system_id?: string };
    return cfg.system_id ?? null;
  }

  subflowInputMap(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as {
      input_map?: Record<string, string>;
    };
    const m = cfg.input_map ?? {};
    return Object.entries(m)
      .map(([k, v]) => `${k} = ${v}`)
      .join('\n');
  }

  /** Load the other systems catalog once per inspector session. */
  ensureOtherSystemsLoaded(): void {
    if (this.otherSystems().length > 0 || this.otherSystemsLoading()) return;
    this.otherSystemsLoading.set(true);
    const currentId = this.systemId();
    this.canonical.listSystems().subscribe({
      next: (rows) => {
        this.otherSystems.set((rows ?? []).filter((s) => s.id !== currentId));
        this.otherSystemsLoading.set(false);
      },
      error: () => {
        this.otherSystemsLoading.set(false);
        this.toastr.warning('Could not load systems catalog — subflow picker offline.', 'Inspector');
      },
    });
  }

  onSubflowSystemChange(ev: Event): void {
    const v = (ev.target as HTMLSelectElement | null)?.value ?? '';
    this.patchSelectedConfig({ system_id: v || undefined });
  }

  setSubflowSystem(value: string | null): void {
    this.patchSelectedConfig({ system_id: value || undefined });
  }

  onSubflowInputMapChange(ev: Event): void {
    const raw = (ev.target as HTMLTextAreaElement | null)?.value ?? '';
    const map = this.parseKvBlock(raw);
    this.patchSelectedConfig({
      input_map: Object.keys(map).length > 0 ? map : undefined,
    });
  }

  // ── Task (Skill params + inputs/outputs map) ──────────────────────
  /** Rendered field descriptors derived from the bound skill's
   *  ``input_schema``. JSON-schema-lite support only: we handle
   *  ``type`` ∈ {string, number, integer, boolean} and optional
   *  ``enum`` lists. Anything more complex falls back to the textarea
   *  advanced editor below (``inputs_map``). */
  taskParamFields(): {
    key: string;
    type: string;
    required: boolean;
    description?: string;
    enum?: string[];
    value: unknown;
  }[] {
    const node = this.selectedNode();
    if (!node) return [];
    const skill = this.currentSkill(node);
    if (!skill) return [];
    const schema = (skill.input_schema ?? {}) as {
      properties?: Record<string, { type?: string; description?: string; enum?: string[] }>;
      required?: string[];
    };
    const props = schema.properties ?? {};
    const required = new Set(schema.required ?? []);
    const cfg = (node.config ?? {}) as { params?: Record<string, unknown> };
    const values = cfg.params ?? {};
    return Object.entries(props).map(([key, def]) => ({
      key,
      type: (def?.type ?? 'string').toString(),
      required: required.has(key),
      description: def?.description,
      enum: Array.isArray(def?.enum) ? def.enum.map(String) : undefined,
      value: values[key],
    }));
  }

  jsonParamValue(value: unknown): string {
    if (value === undefined || value === null || value === '') return '';
    if (typeof value === 'string') return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  onTaskParamJsonChange(key: string, ev: Event): void {
    const raw = (ev.target as HTMLTextAreaElement | null)?.value?.trim() ?? '';
    const node = this.selectedNode();
    const cfg = (node?.config ?? {}) as { params?: Record<string, unknown> };
    const nextParams = { ...(cfg.params ?? {}) };
    if (!raw) {
      delete nextParams[key];
    } else {
      try {
        nextParams[key] = JSON.parse(raw);
      } catch {
        this.toastr.warning(`Invalid JSON for "${key}". Value was not saved.`, 'Skill parameters');
        return;
      }
    }
    this.patchSelectedConfig({
      params: Object.keys(nextParams).length > 0 ? nextParams : undefined,
    });
  }

  onTaskParamChange(key: string, ev: Event, type: string): void {
    const tgt = ev.target as HTMLInputElement | HTMLSelectElement | null;
    if (!tgt) return;
    let parsed: unknown;
    if (type === 'boolean') {
      parsed = (tgt as HTMLInputElement).checked;
    } else if (type === 'number' || type === 'integer') {
      const raw = tgt.value;
      if (raw === '') {
        parsed = undefined;
      } else {
        const n = type === 'integer' ? Number.parseInt(raw, 10) : Number.parseFloat(raw);
        parsed = Number.isFinite(n) ? n : undefined;
      }
    } else {
      parsed = tgt.value || undefined;
    }
    const node = this.selectedNode();
    const cfg = (node?.config ?? {}) as { params?: Record<string, unknown> };
    const nextParams = { ...(cfg.params ?? {}) };
    if (parsed === undefined) delete nextParams[key];
    else nextParams[key] = parsed;
    this.patchSelectedConfig({
      params: Object.keys(nextParams).length > 0 ? nextParams : undefined,
    });
  }

  setTaskParamValue(key: string, value: unknown, type: string): void {
    let parsed = value;
    if (value === '' || value === null) {
      parsed = undefined;
    } else if (type === 'number' || type === 'integer') {
      const raw = String(value);
      const n = type === 'integer' ? Number.parseInt(raw, 10) : Number.parseFloat(raw);
      parsed = Number.isFinite(n) ? n : undefined;
    }
    const node = this.selectedNode();
    const cfg = (node?.config ?? {}) as { params?: Record<string, unknown> };
    const nextParams = { ...(cfg.params ?? {}) };
    if (parsed === undefined) delete nextParams[key];
    else nextParams[key] = parsed;
    this.patchSelectedConfig({
      params: Object.keys(nextParams).length > 0 ? nextParams : undefined,
    });
  }

  enumOptions(field: { enum?: string[] }): FlowSelectOption[] {
    return (field.enum ?? []).map((value) => ({
      value,
      label: value,
      tone: 'cyan',
    }));
  }

  taskInputsMap(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as {
      inputs_map?: Record<string, string>;
    };
    return Object.entries(cfg.inputs_map ?? {})
      .map(([k, v]) => `${k} = ${v}`)
      .join('\n');
  }

  taskOutputsMap(): string {
    const cfg = (this.selectedNode()?.config ?? {}) as {
      outputs_map?: Record<string, string>;
    };
    return Object.entries(cfg.outputs_map ?? {})
      .map(([k, v]) => `${k} = ${v}`)
      .join('\n');
  }

  onTaskInputsMapChange(ev: Event): void {
    const raw = (ev.target as HTMLTextAreaElement | null)?.value ?? '';
    const map = this.parseKvBlock(raw);
    this.patchSelectedConfig({
      inputs_map: Object.keys(map).length > 0 ? map : undefined,
    });
  }

  onTaskOutputsMapChange(ev: Event): void {
    const raw = (ev.target as HTMLTextAreaElement | null)?.value ?? '';
    const map = this.parseKvBlock(raw);
    this.patchSelectedConfig({
      outputs_map: Object.keys(map).length > 0 ? map : undefined,
    });
  }

  /** Parse a ``key = value`` textarea block into a flat map. Empty lines
   *  and lines without ``=`` are silently skipped so the user can type
   *  comments or drafts without the map going half-broken mid-edit. */
  private parseKvBlock(raw: string): Record<string, string> {
    const out: Record<string, string> = {};
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eq = trimmed.indexOf('=');
      if (eq <= 0) continue;
      const k = trimmed.slice(0, eq).trim();
      const v = trimmed.slice(eq + 1).trim();
      if (k && v) out[k] = v;
    }
    return out;
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

    const COL_W = 320;
    const ROW_H = 156;
    const START_X = 96;
    const START_Y = 72;
    const maxRows = Math.max(1, ...Array.from(byLayer.values()).map((ids) => ids.length));

    // Find drawflow numeric id per canonical id.
    const canonicalToNum = new Map<string, string>();
    for (const [key, node] of Object.entries(graph.drawflow?.Home?.data ?? {})) {
      const cid = (node.data?.['canonical_id'] as string) || `flow.${key}`;
      canonicalToNum.set(cid, key);
    }

    let moved = 0;
    byLayer.forEach((ids, l) => {
      const layerOffsetY = ((maxRows - ids.length) * ROW_H) / 2;
      ids.forEach((id, row) => {
        const num = canonicalToNum.get(id);
        if (!num) return;
        const x = START_X + l * COL_W;
        const y = START_Y + layerOffsetY + row * ROW_H;
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

    this.redrawConnectionsSoon();
    this.fitCanvasSoon();
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
    if (typeof id === 'string' && id.length > 0) return id;
    const slug = cfg['skill_slug'];
    if (typeof slug === 'string' && slug.length > 0) {
      return this.skills().find((s) => s.slug === slug)?.id ?? null;
    }
    return null;
  }

  currentSkill(node: CanonicalFlowNode): Skill | null {
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    const id = cfg['skill_id'];
    if (typeof id === 'string' && id.length > 0) {
      const byId = this.skills().find((s) => s.id === id);
      if (byId) return byId;
    }
    const slug = cfg['skill_slug'] || node.type;
    if (typeof slug === 'string' && slug.length > 0) {
      return this.skills().find((s) => s.slug === slug) ?? null;
    }
    return null;
  }

  runtimeEvidenceRows(): { key: string; value: string }[] {
    const node = this.selectedNode();
    if (!node) return [];
    const rows: { key: string; value: string }[] = [];
    const cfg = (node.config ?? {}) as Record<string, unknown>;
    const data = (node.data ?? {}) as Record<string, unknown>;
    const add = (key: string, value: unknown, max = 220) => {
      if (value === undefined || value === null || value === '') return;
      rows.push({ key, value: this.compactInspectorValue(value, max) });
    };

    add('type', node.type, 80);
    add('kind', node.kind ?? 'task', 80);
    add('skill_slug', cfg['skill_slug'], 140);
    add('runtime_ref', cfg['runtime_ref'] ?? data['runtime_ref'], 260);
    add('stage', data['stage'], 120);
    add('surface', data['surface'], 120);
    add('assistant_profile', data['assistant_profile'], 160);
    add('knowledge_scope', data['knowledge_scope'], 180);
    add('system_fallback', data['system_fallback'], 180);
    add('render_contract', data['render_contract'], 180);

    for (const key of [
      'routes',
      'routing_order',
      'handlers',
      'guardrails',
      'triggers',
      'retrieval_defaults',
      'budget_policy',
      'source_policy',
      'grounding',
      'actions',
      'response_contract',
      'input_contract',
      'chunk_types',
    ]) {
      add(key, data[key], 260);
    }

    const branches = (cfg['branches'] ?? data['branches']) as unknown;
    if (Array.isArray(branches)) {
      add(
        'branches',
        branches
          .map((branch) => {
            if (!branch || typeof branch !== 'object') return String(branch);
            const b = branch as Record<string, unknown>;
            return `${b['label'] ?? 'branch'}: ${b['condition'] ?? '—'}`;
          })
          .join(' | '),
        360,
      );
    }
    add('default_branch', cfg['default_branch'], 160);

    return rows;
  }

  promptBlocks(): PromptBlock[] {
    const node = this.selectedNode();
    if (!node) return [];
    const data = (node.data ?? {}) as Record<string, unknown>;
    const unitContract = this.objectValue(this.selectedManifestUnit()?.prompt_contract);
    const nodeContract = this.objectValue(data['prompt_contract']) ?? unitContract;
    const flow = (this.system()?.flow_definition ?? {}) as Record<string, unknown>;
    const flowContract =
      this.objectValue(flow['prompt_contract']) ??
      this.objectValue(this.flowManifest()?.prompt_contract);
    const chatConfig = this.objectValue(flow['chat']);
    const effectiveConfig = (this.flowManifest()?.effective_config ?? {}) as Record<string, unknown>;

    const blocks: PromptBlock[] = [];
    const add = (
      source: 'node' | 'flow',
      path: string,
      title: string,
      value: unknown,
      editable = true,
    ) => {
      if (value === undefined || value === null || value === '') return;
      const body = this.promptValueToBody(value);
      if (body.trim()) {
        blocks.push({
          key: `${source}:${path}`,
          title,
          body: body.trim(),
          source,
          path,
          editable,
        });
      }
    };

    if (nodeContract) {
      add('node', 'system_prompt', 'Node system prompt', nodeContract['system_prompt']);
      add('node', 'base_system_prompt', 'Node base system prompt', nodeContract['base_system_prompt']);
      add('node', 'balanced_grounding_appendix', 'Balanced grounding appendix', nodeContract['balanced_grounding_appendix']);
      add('node', 'balanced_appendix', 'Balanced grounding appendix', nodeContract['balanced_appendix']);
      add('node', 'reasoning_template_factual', 'Reasoning template · factual', nodeContract['reasoning_template_factual']);
      add('node', 'rag_user_prompt_builder', 'RAG user prompt builder', nodeContract['rag_user_prompt_builder']);
      add('node', 'system_prompt_builder', 'System prompt builder', nodeContract['system_prompt_builder']);
      add('node', 'answer_shaping_instructions', 'Answer shaping instructions', nodeContract['answer_shaping_instructions']);
    }
    add('node', 'grounding', 'Grounding policy', data['grounding'], false);
    add('node', 'source_policy', 'Source policy', data['source_policy'], false);
    add('node', 'retrieval_defaults', 'Retrieval profile', data['retrieval_defaults'], false);
    add('node', 'budget_policy', 'Budget policy', data['budget_policy'], false);
    add('node', 'response_contract', 'Response contract', data['response_contract'], false);
    add('node', 'render_contract', 'Render contract', data['render_contract'], false);
    add('node', 'latency_profile', 'Latency profile', data['latency_profile'], false);
    add('node', 'require_sources', 'Source requirement', data['require_sources'], false);
    if (flowContract) {
      add('flow', 'base_system_prompt', 'Flow base system prompt', flowContract['base_system_prompt']);
      add('flow', 'balanced_grounding_appendix', 'Flow balanced appendix', flowContract['balanced_grounding_appendix']);
      add('flow', 'reasoning_template_factual', 'Flow reasoning template · factual', flowContract['reasoning_template_factual']);
      add('flow', 'answer_shaping_instructions', 'Flow answer shaping instructions', flowContract['answer_shaping_instructions']);
    }
    if (chatConfig) {
      add('flow', 'chat.assistant_profile', 'Assistant profile', chatConfig['assistant_profile'], false);
      add('flow', 'chat.knowledge_scope', 'Knowledge scope', chatConfig['knowledge_scope'], false);
      add('flow', 'chat.retrieval_defaults', 'Chat retrieval defaults', chatConfig['retrieval_defaults'], false);
      add('flow', 'chat.grounding', 'Chat grounding defaults', chatConfig['grounding'], false);
      add('flow', 'chat.source_policy', 'Chat source policy defaults', chatConfig['source_policy'], false);
    }
    add('flow', 'effective_config.assistant_profile', 'Effective assistant profile', effectiveConfig['assistant_profile'], false);
    add('flow', 'effective_config.knowledge_scope', 'Effective knowledge scope', effectiveConfig['knowledge_scope'], false);
    add('flow', 'effective_config.system_prompt', 'Effective system prompt', effectiveConfig['system_prompt'], false);
    add('flow', 'effective_config.prompt_type', 'Effective prompt type', effectiveConfig['prompt_type'], false);
    add('flow', 'effective_config.retrieval_defaults', 'Effective retrieval profile', effectiveConfig['retrieval_defaults'], false);
    add('flow', 'effective_config.grounding', 'Effective grounding', effectiveConfig['grounding'], false);
    add('flow', 'effective_config.source_policy', 'Effective source policy', effectiveConfig['source_policy'], false);
    return blocks;
  }

  private promptValueToBody(value: unknown): string {
    if (Array.isArray(value)) return value.map((item) => `- ${String(item)}`).join('\n');
    if (value && typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  }

  private promptBodyToValue(source: 'node' | 'flow', path: string, raw: string): unknown {
    const previous =
      source === 'node'
        ? this.objectValue(this.selectedNode()?.data?.['prompt_contract'])?.[path]
        : this.objectValue(((this.system()?.flow_definition ?? {}) as Record<string, unknown>)['prompt_contract'])?.[path];
    if (Array.isArray(previous)) {
      return raw
        .split(/\r?\n/)
        .map((line) => line.trim().replace(/^-\s*/, ''))
        .filter(Boolean);
    }
    if (previous && typeof previous === 'object') {
      try {
        return JSON.parse(raw);
      } catch {
        this.toastr.warning('Invalid JSON instruction payload; edit was not applied.', 'Instructions');
        return previous;
      }
    }
    return raw;
  }

  beginPromptEdit(block: PromptBlock): void {
    if (!block.editable) return;
    this.promptEditKey.set(block.key);
    this.promptDraft.set(block.body);
    this.configSheetTab.set('prompts');
    this.configSheetOpen.set(true);
  }

  cancelPromptEdit(): void {
    this.promptEditKey.set(null);
    this.promptDraft.set('');
  }

  onPromptDraftChange(ev: Event): void {
    this.promptDraft.set((ev.target as HTMLTextAreaElement | null)?.value ?? '');
  }

  savePromptEdit(block: PromptBlock): void {
    const raw = this.promptDraft();
    const nextValue = this.promptBodyToValue(block.source, block.path, raw);
    if (block.source === 'node') {
      this.patchSelectedNodeDataPrompt(block.path, nextValue);
    } else {
      this.patchFlowPrompt(block.path, nextValue);
    }
    this.promptEditKey.set(null);
    this.promptDraft.set('');
    this.toastr.success('Instruction updated locally. Use Save to System to persist.', 'Instructions');
  }

  copyPrompt(block: PromptBlock): void {
    if (!navigator.clipboard?.writeText) {
      this.toastr.warning('Clipboard is not available.', 'Instructions');
      return;
    }
    navigator.clipboard.writeText(block.body).then(
      () => this.toastr.success('Instruction copied.', 'Instructions'),
      () => this.toastr.warning('Clipboard is not available.', 'Instructions'),
    );
  }

  togglePromptExpanded(block: PromptBlock): void {
    this.expandedPromptKey.update((key) => (key === block.key ? null : block.key));
  }

  private patchSelectedNodeDataPrompt(path: string, value: unknown): void {
    const rawId = this.selectedRawNodeId();
    const node = this.selectedNode();
    if (!rawId || !node || !this.editor) return;
    const graph = this.exportGraph();
    const nodeData = graph.drawflow?.Home?.data?.[rawId];
    if (!nodeData) return;
    const prevContract = this.objectValue(nodeData.data?.['prompt_contract']) ?? {};
    const prompt_contract = { ...prevContract, [path]: value };
    const nextData = { ...(nodeData.data ?? {}), prompt_contract };
    try {
      this.editor.updateNodeDataFromId(rawId, nextData);
    } catch {
      return;
    }
    this.selectedNode.set({
      ...node,
      data: { ...((node.data ?? {}) as Record<string, unknown>), prompt_contract },
    });
    this.refreshKpis();
  }

  private patchFlowPrompt(path: string, value: unknown): void {
    const sys = this.system();
    if (!sys) return;
    const flow = (sys.flow_definition ?? {}) as Record<string, unknown>;
    const prevContract = this.objectValue(flow['prompt_contract']) ?? {};
    const nextFlow = {
      ...flow,
      prompt_contract: { ...prevContract, [path]: value },
    };
    this.system.set({
      ...sys,
      flow_definition: nextFlow,
    });
  }

  private objectValue(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  }

  private compactInspectorValue(value: unknown, maxChars = 160): string {
    let text: string;
    if (Array.isArray(value)) {
      text = value
        .map((item) => {
          if (item && typeof item === 'object') {
            const obj = item as Record<string, unknown>;
            return String(obj['label'] ?? obj['name'] ?? obj['id'] ?? JSON.stringify(obj));
          }
          return String(item);
        })
        .join(', ');
    } else if (value && typeof value === 'object') {
      text = JSON.stringify(value);
    } else {
      text = String(value);
    }
    text = text.replace(/\s+/g, ' ').trim();
    return text.length > maxChars ? text.slice(0, Math.max(0, maxChars - 1)).trimEnd() + '…' : text;
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
