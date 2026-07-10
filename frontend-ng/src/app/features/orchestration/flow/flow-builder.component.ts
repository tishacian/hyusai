/**
 * `<app-flow-builder>` — the Flow Builder shell.
 *
 * This is the "éclaté" composition the plan calls for: it hydrates the store
 * from a System (or the scratchpad), and assembles the palette, canvas,
 * inspector, and the single toolbar. It owns NO graph logic and NO
 * persistence — everything routes through `FlowStore`, and all save / export /
 * import / share / autosave + keyboard shortcuts (Ctrl·Cmd+S / undo / redo /
 * delete) live in `FlowToolbarComponent` + `FlowPersistenceService`.
 *
 * Routes here from `/orchestration` (scratchpad) and `/systems/:systemId/flow`.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type System,
} from '@app/core/canonical-api.service';
import {
  primitivesIncompatible,
  type CanonicalFlow,
  type CanonicalFlowEdge,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import {
  FlowCanvasComponent,
  type ConnectFromHandleEvent,
} from './flow-canvas.component';
import { FlowInspectorComponent } from './flow-inspector.component';
import { FlowPaletteComponent } from './flow-palette.component';
import { FlowToolbarComponent } from './flow-toolbar.component';
import { FlowManifestService } from './flow-manifest.service';
import { FlowPersistenceService } from './flow-persistence.service';
import { FlowCatalogService } from './flow-catalog.service';
import { FlowRunService } from './flow-run.service';
import { FlowRunControlsComponent } from './flow-run-controls.component';
import { FlowTerminalComponent } from './flow-terminal.component';
import { FlowVersionsComponent } from './flow-versions.component';
import { FlowManifestStripComponent } from './flow-manifest-strip.component';
import { FlowValidationStripComponent } from './flow-validation-strip.component';
import {
  connectorsToEdge,
  inputConnectorId,
  outputConnectorId,
  type ParsedConnector,
} from './flow-foblex.adapter';
import {
  DEFAULT_PALETTE,
  defaultScratchFlow,
  paletteItemToNode,
  type PaletteItem,
} from './flow.types';

@Component({
  selector: 'app-flow-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  // FlowPersistenceService lives here (not the toolbar) so the toolbar and the
  // validation strip share one instance — the strip reads its `serverIssues`.
  providers: [FlowStore, FlowRunService, FlowPersistenceService],
  imports: [
    RouterLink,
    FlowCanvasComponent,
    FlowInspectorComponent,
    FlowPaletteComponent,
    FlowToolbarComponent,
    FlowRunControlsComponent,
    FlowTerminalComponent,
    FlowVersionsComponent,
    FlowManifestStripComponent,
    FlowValidationStripComponent,
  ],
  styleUrl: './flow-builder.component.scss',
  template: `
    <section class="flow-builder">
      <header class="flow-builder__header">
        <div class="flow-builder__crumbs">
          <a routerLink="/systems" class="flow-builder__crumb">Systems</a>
          <span class="flow-builder__sep">/</span>
          @if (system(); as sys) {
            <a [routerLink]="['/systems', sys.id]" class="flow-builder__crumb">{{ sys.name }}</a>
            <span class="flow-builder__sep">/</span>
            <span class="flow-builder__here">Flow builder</span>
          } @else {
            <span class="flow-builder__here">Scratchpad flow</span>
          }
        </div>
        <h1 class="flow-builder__title">
          {{ system()?.name || 'Flow builder' }}
        </h1>
      </header>

      <app-flow-toolbar
        class="flow-builder__toolbar"
        [nodeCount]="store.nodeCount()"
        [canUndo]="store.canUndo()"
        [canRedo]="store.canRedo()"
        [routingLabel]="routingLabel()"
        (undo)="store.undo()"
        (redo)="store.redo()"
        (zoomIn)="canvas()?.zoomIn()"
        (zoomOut)="canvas()?.zoomOut()"
        (fit)="canvas()?.fit()"
        (autoLayout)="canvas()?.autoLayout()"
        (cycleRouting)="onCycleRouting()"
        (clear)="store.clear()"
      >
        <app-flow-run-controls flowToolbarActions (openVersions)="versionsOpen.set(true)" />
      </app-flow-toolbar>

      <app-flow-manifest-strip />

      <app-flow-validation-strip
        [serverIssues]="persistence.serverIssues()"
        (focusNode)="canvas()?.focusNode($event)"
      />

      <div class="flow-builder__body" [class.is-inspecting]="inspectorOpen()">
        <app-flow-palette
          class="flow-builder__palette"
          [items]="palette"
          (add)="onAddNode($event)"
        />

        <div class="flow-builder__canvas">
          <app-flow-canvas (connectFromHandle)="onConnectFromHandle($event)" />
        </div>

        @if (inspectorOpen()) {
          <app-flow-inspector
            class="flow-builder__inspector"
            [systemId]="systemId()"
            (close)="inspectorOpen.set(false)"
          />
        }
      </div>

      @if (handleMenu(); as menu) {
        <div class="flow-builder__handle-backdrop" (click)="closeHandleMenu()"></div>
        <div
          class="flow-builder__handle-menu"
          role="menu"
          aria-label="Insert connected node"
          [style.left.px]="menu.position.x"
          [style.top.px]="menu.position.y"
        >
          <div class="flow-builder__handle-title">
            Insert {{ menu.connector.direction === 'out' ? 'target' : 'source' }} node
          </div>
          @for (item of handleMenuItems(); track item.config?.['skill_slug'] ?? item.type) {
            <button
              type="button"
              role="menuitem"
              class="flow-builder__handle-item"
              [attr.data-tone]="item.tone"
              [title]="item.description"
              (click)="onPickHandleItem(item)"
            >
              {{ item.label }}
            </button>
          } @empty {
            <p class="flow-builder__handle-empty">No type-compatible node.</p>
          }
        </div>
      }

      @if (run.terminalOpen()) {
        <app-flow-terminal
          class="flow-builder__terminal"
          [entries]="run.log()"
          [status]="run.status()"
          [hitl]="run.pendingHitl()"
          [debug]="run.pendingDebug()"
          [hitlResolving]="run.hitlResolving()"
          [debugStepping]="run.debugStepping()"
          [debugModeLabel]="run.debugMode()"
          (resolveHitl)="run.resolveHitl($event)"
          (debugAction)="run.debugAction($event)"
          (clear)="run.clearLog()"
          (close)="run.terminalOpen.set(false)"
        />
      }
    </section>

    <app-flow-versions
      [open]="versionsOpen()"
      [systemId]="systemId()"
      (close)="versionsOpen.set(false)"
      (rolledBack)="onRolledBack($event)"
    />
  `,
})
export class FlowBuilderComponent {
  protected readonly store = inject(FlowStore);
  protected readonly run = inject(FlowRunService);
  /** Provided here (see decorator) so the toolbar + validation strip share it. */
  protected readonly persistence = inject(FlowPersistenceService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly catalog = inject(FlowCatalogService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);
  private readonly manifest = inject(FlowManifestService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly canvas = viewChild(FlowCanvasComponent);

  protected readonly palette: PaletteItem[] = DEFAULT_PALETTE;
  protected readonly systemId = signal<string | null>(null);
  protected readonly system = signal<System | null>(null);
  protected readonly inspectorOpen = signal(false);
  protected readonly versionsOpen = signal(false);
  protected readonly routingLabel = signal('segment');

  /** On-handle insertion: open menu state (connector + drop anchor + schema). */
  protected readonly handleMenu = signal<{
    connector: ParsedConnector;
    position: { x: number; y: number };
    schema: string | undefined;
  } | null>(null);

  /** Palette items (primitives + live skills) compatible with the dragged
   *  handle's port type, filtered for the open insertion menu. */
  protected readonly handleMenuItems = computed<PaletteItem[]>(() => {
    const menu = this.handleMenu();
    if (!menu) return [];
    // Dragging FROM an output → the new node consumes (its input side); FROM
    // an input → the new node produces (its output side).
    const side = menu.connector.direction === 'out' ? 'in' : 'out';
    const all = [...this.palette, ...this.catalog.skillItems()];
    return all.filter((item) => this.itemConnectable(item, side, menu.schema));
  });

  constructor() {
    // Deterministic, single-frame: opening the inspector follows selection.
    effect(() => {
      if (this.store.selectedNode()) this.inspectorOpen.set(true);
    });

    const sid =
      this.route.snapshot.paramMap.get('systemId') ||
      this.route.snapshot.queryParamMap.get('systemId');
    this.systemId.set(sid);

    // Bind the run orchestrator to the route's System (or scratchpad) so the
    // projected controls / terminal / nodes all gate + execute consistently.
    this.run.bindSystem(sid);
    this.destroyRef.onDestroy(() => this.run.dispose());

    // Single, shell-owned manifest fetch for the whole builder. Children
    // (node badges, inspector fields) consume the shared service reactively
    // instead of each re-reading the route.
    this.manifest.ensureLoaded(sid);

    if (sid) {
      this.hydrateFromSystem(sid);
    } else {
      this.store.load(defaultScratchFlow());
    }
  }

  /** Sync shell state after a versions-drawer rollback reloads the graph. */
  onRolledBack(system: System): void {
    this.system.set(system);
    this.manifest.reload();
  }

  private hydrateFromSystem(sid: string): void {
    this.canonical.getSystem(sid).subscribe((sys) => {
      if (!sys) {
        this.toastr.warning('System not found — opening scratchpad.', 'Flow builder');
        this.systemId.set(null);
        this.store.load(defaultScratchFlow());
        return;
      }
      this.system.set(sys);
      const flow = (sys.flow_definition ?? {}) as unknown as CanonicalFlow;
      if (Array.isArray(flow.nodes) && flow.nodes.length > 0) {
        this.store.load(flow);
      } else {
        this.toastr.info('This System has no flow yet — starting fresh.', 'Flow builder');
        this.store.load(defaultScratchFlow());
        this.store.setSource('form');
      }
    });
  }

  /**
   * Add a palette node. When `preconnect` is given (on-handle insertion), the
   * new node is placed beside the originating node and its compatible port is
   * wired to the handle the connection was dragged from.
   */
  onAddNode(item: PaletteItem, preconnect?: ParsedConnector): void {
    const count = this.store.nodeCount();
    let position = { x: 160 + (count % 4) * 60, y: 140 + (count % 4) * 60 };
    if (preconnect) {
      const src = this.store.nodes().find((n) => n.id === preconnect.nodeId);
      const base = src?.position ?? position;
      const dx = preconnect.direction === 'out' ? 260 : -260;
      position = { x: base.x + dx, y: base.y };
    }
    const id = this.store.addNode(paletteItemToNode(item, position));
    if (!preconnect) return;
    const edge = this.preconnectEdge(preconnect, item, id);
    if (edge) this.store.connect(edge);
  }

  // ---- on-handle insertion ------------------------------------------------
  onConnectFromHandle(event: ConnectFromHandleEvent): void {
    this.handleMenu.set({
      connector: event.connector,
      position: event.position,
      schema: this.originatingSchema(event.connector),
    });
  }

  onPickHandleItem(item: PaletteItem): void {
    const menu = this.handleMenu();
    if (!menu) return;
    this.onAddNode(item, menu.connector);
    this.handleMenu.set(null);
  }

  closeHandleMenu(): void {
    this.handleMenu.set(null);
  }

  /** Schema of the handle the connection was dragged from (undefined for the
   *  implicit default port → no type filter). */
  private originatingSchema(connector: ParsedConnector): string | undefined {
    const node = this.store.nodes().find((n) => n.id === connector.nodeId);
    if (!node || !connector.port) return undefined;
    const ports = connector.direction === 'out' ? node.outputs : node.inputs;
    return (ports ?? []).find((p) => p.name === connector.port)?.schema;
  }

  /** A palette item can connect on `side` when it declares a compatible port
   *  there (or none → implicit passthrough), and isn't a source/sink that
   *  structurally lacks the needed connector. */
  private itemConnectable(
    item: PaletteItem,
    side: 'in' | 'out',
    schema: string | undefined,
  ): boolean {
    if (side === 'in' && item.kind === 'source') return false;
    if (side === 'out' && item.kind === 'sink') return false;
    if (!schema) return true;
    const ports = (side === 'in' ? item.inputs : item.outputs) ?? [];
    if (ports.length === 0) return true; // implicit passthrough accepts anything
    return ports.some((p) => !primitivesIncompatible(p.schema, schema));
  }

  /** Build the edge wiring the new node's first compatible port to the
   *  originating handle. Reuses the adapter's connector id scheme. */
  private preconnectEdge(
    connector: ParsedConnector,
    item: PaletteItem,
    newId: string,
  ): CanonicalFlowEdge | null {
    if (connector.direction === 'out') {
      const sourceId = outputConnectorId(connector.nodeId, connector.port);
      const targetId = inputConnectorId(newId, (item.inputs ?? [])[0]?.name);
      return connectorsToEdge(sourceId, targetId);
    }
    const targetId = inputConnectorId(connector.nodeId, connector.port);
    const sourceId = outputConnectorId(newId, (item.outputs ?? [])[0]?.name);
    return connectorsToEdge(sourceId, targetId);
  }

  onCycleRouting(): void {
    const next = this.canvas()?.cycleRouting();
    if (next) this.routingLabel.set(next);
  }
}
