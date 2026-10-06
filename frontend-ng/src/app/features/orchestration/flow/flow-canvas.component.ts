/**
 * `<app-flow-canvas>` — the Foblex rendering surface.
 *
 * Renders the FlowStore graph through the engine-agnostic adapter and feeds
 * user intents (connect / reassign / move / select) straight back into the
 * store. It owns NO graph state of its own — the store is the single source
 * of truth, so connections stay attached during drag/zoom/pan automatically
 * (Foblex redraws connector-anchored paths; no manual redraw hack).
 *
 * Public view controls (`fit`, `zoomIn`, `zoomOut`, `resetView`,
 * `autoLayout`, `setRouting`) are called by the toolbar host in the builder
 * shell — the toolbar never touches Foblex directly.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';
import {
  EFConnectionBehavior,
  EFConnectionType,
  EFLayoutDirection,
  FCanvasComponent,
  FFlowModule,
  FLayoutController,
  type FCreateConnectionEvent,
  type FReassignConnectionEvent,
  type FSelectionChangeEvent,
} from '@foblex/flow';
import {
  DagreLayoutEngine,
  EDagreLayoutAlgorithm,
} from '@foblex/flow-dagre-layout';
import { FlowStore } from './flow.store';
import {
  connectorsToEdge,
  parseConnectorId,
  toConnectionViews,
  toNodeViews,
  type ParsedConnector,
} from './flow-foblex.adapter';
import { FlowNodeComponent } from './flow-node.component';

/** Emitted when a connection is dragged from a handle and dropped on empty
 *  canvas — the shell opens a type-filtered insertion palette at `position`. */
export interface ConnectFromHandleEvent {
  connector: ParsedConnector;
  /** Viewport (clientX/Y) drop point, for anchoring the insertion menu. */
  position: { x: number; y: number };
}

@Component({
  selector: 'app-flow-canvas',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FFlowModule, FlowNodeComponent],
  // Foblex 18.6 made `FLayoutEngine` (the base of `DagreLayoutEngine`) inject
  // `FLayoutController` at field-init, and that token is NOT `providedIn:'root'`
  // (it ships only via `provideFLayout()`). Since we instantiate the engine
  // directly (`new DagreLayoutEngine()`), we must provide the controller here or
  // the field-init `inject(FLayoutController)` throws NG0201 — a black screen on
  // this route. The controller stays passive (engine mode is MANUAL).
  providers: [FLayoutController],
  styleUrl: './flow-canvas.component.scss',
  template: `
    <f-flow
      fDraggable
      (fCreateConnection)="onCreateConnection($event)"
      (fReassignConnection)="onReassignConnection($event)"
      (fSelectionChange)="onSelectionChange($event)"
      (fDragEnded)="onDragEnded()"
      (fLoaded)="onLoaded()"
    >
      <f-canvas fZoom [fZoomMinimum]="0.2" [fZoomMaximum]="3">
        <f-background>
          <f-circle-pattern />
        </f-background>

        @for (view of nodeViews(); track view.id) {
          <app-flow-node
            fNode
            [fNodeId]="view.id"
            [fNodePosition]="view.position"
            (fNodePositionChange)="onNodeMoved(view.id, $event)"
            [view]="view"
            [selected]="view.id === selectedId()"
            (runStep)="runStep.emit($event)"
            (click)="onNodeClick(view.id)"
          />
        }

        @for (conn of connectionViews(); track conn.id) {
          <f-connection
            [fConnectionId]="conn.id"
            [fOutputId]="conn.source"
            [fInputId]="conn.target"
            [fType]="routing()"
            [fBehavior]="behavior"
            [attr.data-kind]="conn.kind"
            fReassignableStart
          >
            @if (conn.branchLabel; as branchLabel) {
              <span fConnectionContent class="ck-flow-branch-label" [position]="0.28">
                {{ branchLabel }}
              </span>
            }
          </f-connection>
        }

        <f-connection-for-create [fType]="routing()" [fBehavior]="behavior" />
      </f-canvas>

      <f-minimap [fMinSize]="240" />
    </f-flow>
  `,
})
export class FlowCanvasComponent {
  private readonly store = inject(FlowStore);
  private readonly canvas = viewChild(FCanvasComponent);
  private readonly layout = new DagreLayoutEngine();

  readonly routing = signal<EFConnectionType>(EFConnectionType.SEGMENT);
  readonly behavior = EFConnectionBehavior.FIXED;

  /** On-handle insertion: a connection dropped on empty canvas. */
  readonly connectFromHandle = output<ConnectFromHandleEvent>();
  readonly runStep = output<string>();

  readonly nodeViews = computed(() => toNodeViews(this.store.nodes()));
  readonly connectionViews = computed(() =>
    toConnectionViews(this.store.edges(), this.store.nodes()),
  );
  readonly selectedId = this.store.selectedNodeId;

  /** True while a node drag is in progress (one undo checkpoint per drag). */
  private moving = false;
  /** Guards the one-shot initial auto-fit once the first nodes render. */
  private hasFitted = false;

  constructor() {
    // Auto-fit the first time the graph gains content (covers async loads
    // where `fLoaded` fired before the system flow arrived).
    effect(() => {
      const count = this.store.nodeCount();
      if (count > 0 && !this.hasFitted) {
        this.hasFitted = true;
        queueMicrotask(() => this.fit());
      } else if (count === 0) {
        this.hasFitted = false;
      }
    });
  }

  // ---- Foblex interaction handlers ------------------------------------
  onCreateConnection(event: FCreateConnectionEvent): void {
    const edge = connectorsToEdge(event.sourceId, event.targetId, this.store.nodes());
    if (edge) {
      this.store.connect(edge);
      return;
    }
    // Only react to a drop on EMPTY canvas (no target connector). A defined
    // but incompatible target is left as a no-op, like stock Foblex.
    if (event.targetId) return;
    // Offer to insert a type-compatible node wired to the originating handle.
    // Foblex's dropPosition is in viewport coords — used only to anchor the menu.
    const connector = parseConnectorId(event.sourceId);
    if (!connector) return;
    const drop = event.dropPosition;
    this.connectFromHandle.emit({
      connector,
      position: { x: drop?.x ?? 0, y: drop?.y ?? 0 },
    });
  }

  /** Recentre the canvas on a node (used by the validation strip click-to-error). */
  focusNode(nodeId: string): void {
    this.canvas()?.centerGroupOrNode(nodeId, true);
  }

  onReassignConnection(event: FReassignConnectionEvent): void {
    const previous = this.connectionViews().find(
      (c) => c.id === event.connectionId,
    );
    if (!previous) return;
    const next = connectorsToEdge(
      event.nextSourceId ?? previous.source,
      event.nextTargetId ?? previous.target,
      this.store.nodes(),
    );
    if (!next) return;
    this.store.reassignEdge(previous.edge, next);
  }

  onSelectionChange(event: FSelectionChangeEvent): void {
    this.store.setSelection(event.nodeIds.length > 0 ? event.nodeIds[0] : null);
  }

  onNodeClick(id: string): void {
    this.store.setSelection(id);
  }

  onNodeMoved(id: string, position: { x: number; y: number }): void {
    if (!this.moving) {
      this.moving = true;
      this.store.checkpoint();
    }
    this.store.moveNode(id, position);
  }

  onDragEnded(): void {
    this.moving = false;
  }

  onLoaded(): void {
    if (this.store.nodeCount() > 0) {
      this.hasFitted = true;
      this.fit();
    }
  }

  // ---- public view controls (called by the toolbar host) --------------
  fit(): void {
    this.canvas()?.fitToScreen({ x: 56, y: 56 }, true);
  }

  zoomIn(): void {
    const c = this.canvas();
    if (!c) return;
    c.setScale(Math.min(3, c.getScale() * 1.2));
  }

  zoomOut(): void {
    const c = this.canvas();
    if (!c) return;
    c.setScale(Math.max(0.2, c.getScale() / 1.2));
  }

  resetView(): void {
    this.canvas()?.resetScaleAndCenter(true);
  }

  setRouting(type: EFConnectionType): void {
    this.routing.set(type);
  }

  cycleRouting(): EFConnectionType {
    const order = [
      EFConnectionType.SEGMENT,
      EFConnectionType.BEZIER,
      EFConnectionType.STRAIGHT,
      EFConnectionType.ADAPTIVE_CURVE,
    ];
    const next = order[(order.indexOf(this.routing()) + 1) % order.length];
    this.routing.set(next);
    return next;
  }

  async autoLayout(): Promise<void> {
    const nodes = this.store.nodes();
    const edges = this.store.edges();
    if (nodes.length === 0) return;
    const result = await this.layout.calculate(
      nodes.map((n) => ({ id: n.id, size: { width: 200, height: 84 } })),
      edges.map((e) => ({ source: e.from, target: e.to })),
      {
        direction: EFLayoutDirection.LEFT_RIGHT,
        algorithm: EDagreLayoutAlgorithm.NETWORK_SIMPLEX,
        nodeGap: 48,
        layerGap: 140,
        defaultNodeSize: { width: 200, height: 84 },
      },
    );
    const positions: Record<string, { x: number; y: number }> = {};
    for (const n of result.nodes) positions[n.id] = n.position;
    this.store.setPositions(positions);
    setTimeout(() => this.fit(), 40);
  }
}
