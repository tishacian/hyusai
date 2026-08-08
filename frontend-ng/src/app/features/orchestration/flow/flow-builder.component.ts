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
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, map, of, switchMap, throwError } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type System,
} from '@app/core/canonical-api.service';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { WorkspaceService } from '@app/core/workspace.service';
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
import { FlowValidationService } from './flow-validation.service';
import { FlowPublicationPanelComponent } from './flow-publication-panel.component';
import { FlowWorkbenchPanelComponent } from './flow-workbench-panel.component';
import { FlowWorkbenchService } from './flow-workbench.service';
import {
  type ParsedConnector,
} from './flow-foblex.adapter';
import {
  buildPreconnectEdge,
  isPaletteItemConnectable,
} from './flow-preconnect';
import {
  DEFAULT_PALETTE,
  paletteItemToNode,
  type PaletteItem,
} from './flow.types';

/** Publication preconditions `GET /flow-state` refuses on. Each names a
 * repairable server state, so the message is worth showing verbatim. */
const PUBLICATION_HYDRATION_CODES = new Set([
  'FLOW_DRAFT_STATE_MISSING',
  'PUBLISHED_FLOW_VERSION_INVALID',
  'PUBLISHED_FLOW_SHAPE_INVALID',
  'PUBLISHED_FLOW_MIRROR_DRIFT',
  'PUBLISHED_FLOW_VERSION_HASH_DRIFT',
]);

@Component({
  selector: 'app-flow-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  // FlowPersistenceService lives here (not the toolbar) so the toolbar and the
  // validation strip share one instance — the strip reads its `serverIssues`.
  providers: [
    FlowStore,
    FlowRunService,
    FlowWorkbenchService,
    FlowPersistenceService,
    FlowValidationService,
  ],
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
    FlowPublicationPanelComponent,
    FlowWorkbenchPanelComponent,
    ConfirmDialogComponent,
  ],
  styleUrl: './flow-builder.component.scss',
  template: `
    <section
      #builderRoot
      class="flow-builder"
      [class.is-focus-mode]="focusMode()"
    >
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
        [paletteOpen]="paletteOpen()"
        [inspectorOpen]="inspectorOpen()"
        [canInspect]="!!store.selectedNode()"
        [focusMode]="focusMode()"
        [compact]="toolbarCompact()"
        [workbenchOpen]="workbenchOpen()"
        [workbenchAvailable]="!!systemId()"
        [hydrationReady]="persistence.hydrationReady()"
        (undo)="store.undo()"
        (redo)="store.redo()"
        (zoomIn)="canvas()?.zoomIn()"
        (zoomOut)="canvas()?.zoomOut()"
        (fit)="canvas()?.fit()"
        (autoLayout)="canvas()?.autoLayout()"
        (cycleRouting)="onCycleRouting()"
        (togglePalette)="togglePalette()"
        (toggleInspector)="toggleInspector()"
        (toggleFocus)="toggleCanvasFocus()"
        (toggleCompact)="toggleToolbarCompact()"
        (toggleWorkbench)="toggleWorkbench()"
        (clear)="requestClear()"
      >
        @if (persistence.hydrationReady()) {
          <app-flow-run-controls flowToolbarActions (openVersions)="versionsOpen.set(true)" />
        }
      </app-flow-toolbar>

      @if (loadState() === 'ready' && persistence.hydrationReady()) {
        @if (persistence.publicationMode()) {
          <div class="flow-builder__publication-boundary" role="status">
            <strong>Server Draft r{{ persistence.draftRevision() }}</strong>
            <span>
              Test draft executes this saved revision. Operator Runner and ingress stay on
              Published v{{ persistence.publishedVersionNumber() }} until an explicit Publish.
            </span>
            @if (!persistence.publishedContractReady()) {
              <strong>
                Contract publish required: the migration baseline remains non-executable until
                this draft is explicitly published.
              </strong>
            }
          </div>
        } @else {
          <app-flow-manifest-strip />
        }

        <app-flow-validation-strip
          [serverIssues]="persistence.serverIssues()"
          [serverState]="persistence.serverValidationState()"
          [serverError]="persistence.serverValidationError()"
          (focusNode)="canvas()?.focusNode($event)"
        />

        @if (persistence.autosavePaused()) {
          <div class="flow-builder__review" role="status" aria-live="polite">
            <div>
              <strong>Autosave paused.</strong>
              This bulk or destructive replacement stays local until you explicitly save it.
            </div>
            <div class="flow-builder__review-actions">
              @if (persistence.reviewRequired() === 'conflict') {
                <button type="button" (click)="reloadAuthoritativeSystem()">Reload server Flow</button>
              } @else {
                <button type="button" (click)="persistence.saveNow()">Review &amp; save</button>
                <button type="button" (click)="persistence.discardPendingChanges()">Discard local changes</button>
              }
            </div>
          </div>
        }

        <div
          class="flow-builder__body"
          [class.has-palette]="paletteOpen() && !focusMode()"
          [class.is-inspecting]="inspectorOpen() && !focusMode()"
          [class.is-focus-mode]="focusMode()"
          [class.is-locked]="persistence.actionsDisabled()"
        >
          @if (paletteOpen() && !focusMode()) {
            <app-flow-palette
              class="flow-builder__palette"
              [items]="palette"
              (add)="onAddNode($event)"
            />
          }

          <div class="flow-builder__canvas">
            <app-flow-canvas (connectFromHandle)="onConnectFromHandle($event)" />
          </div>

          @if (inspectorOpen() && !focusMode()) {
            <app-flow-inspector
              class="flow-builder__inspector"
              [systemId]="systemId()"
              (close)="closeInspector()"
            />
          }
        </div>

        @if (workbenchOpen()) {
          <app-flow-workbench-panel
            class="flow-builder__workbench"
            [open]="true"
            (close)="closeWorkbench()"
          />
        }
      } @else {
        <div class="flow-builder__load-state" role="status">
          @if (loadState() === 'loading') {
            <strong>Loading the persisted Flow…</strong>
            <span>Editing and execution remain locked until hydration completes.</span>
          } @else {
            <strong>Flow loading blocked</strong>
            <span>{{ loadError() }}</span>
            @if (systemId(); as sid) {
              <button type="button" (click)="hydrateFromSystem(sid)">Retry strict reload</button>
            }
          }
        </div>
      }

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

      @if (persistence.hydrationReady() && run.terminalOpen()) {
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
      (reloadRequired)="reloadAuthoritativeSystem()"
    />

    <app-confirm-dialog
      [open]="clearConfirmationOpen()"
      title="Clear this Flow?"
      [description]="clearConfirmationDescription()"
      confirmLabel="Clear and pause autosave"
      cancelLabel="Keep Flow"
      tone="danger"
      icon="trash-2"
      [confirmPhrase]="confirmationPhrase()"
      (confirm)="confirmClear()"
      (cancel)="clearConfirmationOpen.set(false)"
    />

    <app-confirm-dialog
      [open]="persistence.replacementConfirmationRequested()"
      title="Replace the active Flow?"
      description="This replacement changes the execution graph of an active System. It will be sent once with explicit replacement authority; autosave remains paused."
      confirmLabel="Replace active Flow"
      cancelLabel="Keep reviewing"
      tone="danger"
      icon="alert-triangle"
      [confirmPhrase]="confirmationPhrase()"
      (confirm)="persistence.confirmReplacementAndSave()"
      (cancel)="persistence.cancelReplacementConfirmation()"
    />

    <app-flow-publication-panel />
  `,
})
export class FlowBuilderComponent {
  protected readonly store = inject(FlowStore);
  protected readonly run = inject(FlowRunService);
  /** Provided here (see decorator) so the toolbar + validation strip share it. */
  protected readonly persistence = inject(FlowPersistenceService);
  protected readonly workbench = inject(FlowWorkbenchService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly catalog = inject(FlowCatalogService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);
  private readonly manifest = inject(FlowManifestService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly workspace = inject(WorkspaceService);
  private readonly validation = inject(FlowValidationService);
  private readonly document = inject(DOCUMENT);

  protected readonly canvas = viewChild(FlowCanvasComponent);
  protected readonly builderRoot = viewChild<ElementRef<HTMLElement>>('builderRoot');

  protected readonly palette: PaletteItem[] = DEFAULT_PALETTE;
  protected readonly systemId = signal<string | null>(null);
  protected readonly system = signal<System | null>(null);
  protected readonly paletteOpen = signal(true);
  protected readonly inspectorOpen = signal(false);
  protected readonly focusMode = signal(false);
  protected readonly toolbarCompact = signal(false);
  protected readonly workbenchOpen = signal(false);
  protected readonly versionsOpen = signal(false);
  protected readonly routingLabel = signal('segment');
  protected readonly loadState = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly loadError = signal('');
  protected readonly clearConfirmationOpen = signal(false);
  protected readonly confirmationPhrase = computed(
    () => this.system()?.name?.trim() || 'CLEAR',
  );
  protected readonly clearConfirmationDescription = computed(
    () =>
      `This will remove ${this.store.nodeCount()} nodes and ${this.store.edgeCount()} edges locally. ` +
      'Autosave will pause; the persisted Flow is unchanged until you explicitly save.',
  );
  private ownsNativeFullscreen = false;
  private lastInspectorSelectionId: string | null = null;

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
    return all.filter((item) => isPaletteItemConnectable(item, side, menu.schema));
  });

  constructor() {
    // Opening follows selection identity, not node object mutations. This
    // lets an operator collapse the inspector and keep it closed while moving
    // or editing that same selected node; selecting another node reopens it.
    effect(() => {
      const selectedId = this.store.selectedNodeId();
      if (selectedId === this.lastInspectorSelectionId) return;
      this.lastInspectorSelectionId = selectedId;
      this.inspectorOpen.set(!!selectedId);
    });

    // Escape exits native fullscreen. Mirror that browser-owned transition
    // into the CSS fallback state so the toolbar and side panels recover too.
    const onFullscreenChange = (): void => {
      const root = this.builderRoot()?.nativeElement;
      const ownsFullscreen = !!root && this.document.fullscreenElement === root;
      if (ownsFullscreen) {
        this.ownsNativeFullscreen = true;
        this.focusMode.set(true);
      } else if (this.ownsNativeFullscreen) {
        this.ownsNativeFullscreen = false;
        this.focusMode.set(false);
        this.scheduleCanvasFit();
      }
    };
    this.document.addEventListener('fullscreenchange', onFullscreenChange);
    this.destroyRef.onDestroy(() => {
      this.document.removeEventListener('fullscreenchange', onFullscreenChange);
    });

    // Exactly one bottom panel at a time. Opening the workbench already closes
    // the terminal, but a run reopens the terminal on its own; without the
    // mirror rule both reservations stack and the canvas loses its floor.
    effect(() => {
      if (!this.run.terminalOpen()) return;
      untracked(() => {
        if (this.workbenchOpen()) this.closeWorkbench();
      });
    });

    // Server diagnostics follow the exact live editor revision. The sidecar
    // deduplicates repeated observations and debounces actual HTTP traffic.
    effect(() => {
      this.store.revision();
      if (this.persistence.hydrationReady() && this.systemId()) {
        this.validation.observeCurrentFlow();
      }
    });

    const sid =
      this.route.snapshot.paramMap.get('systemId') ||
      this.route.snapshot.queryParamMap.get('systemId');
    this.systemId.set(sid);

    // Bind the run orchestrator to the route's System (or scratchpad) so the
    // projected controls / terminal / nodes all gate + execute consistently.
    this.run.bindSystem(sid);
    this.workbench.bindSystem(sid);
    this.destroyRef.onDestroy(() => {
      this.persistence.setWorkbenchAutosaveHold(false);
      this.run.dispose();
    });

    // Single, shell-owned manifest fetch for the whole builder. Children
    // (node badges, inspector fields) consume the shared service reactively
    // instead of each re-reading the route.
    this.manifest.ensureLoaded(sid);

    if (sid) {
      this.hydrateFromSystem(sid);
    } else {
      this.persistence.hydrateScratch();
      this.loadState.set('ready');
    }
  }

  /** A rollback response is the new authoritative baseline. */
  onRolledBack(system: System): void {
    if (this.persistence.hydrateSystem(system)) {
      this.run.acknowledgeAuthoritativeHydration();
      this.validation.bindSystem(system.id);
      this.validation.validateNow();
      this.system.set(system);
      this.loadError.set('');
      this.loadState.set('ready');
      this.manifest.reload();
    } else {
      this.loadError.set(
        this.persistence.hydrationError() ?? 'Rollback returned a malformed Flow.',
      );
      this.loadState.set('error');
    }
  }

  protected hydrateFromSystem(sid: string): void {
    this.loadState.set('loading');
    this.loadError.set('');
    this.validation.bindSystem(null);
    this.persistence.beginHydration();
    const scope = this.workspace.captureRequestScope();
    this.canonical
      .getSystemStrict(sid)
      .pipe(
        switchMap((sys) =>
          this.canonical.getSystemFlowState(sid).pipe(
            map((flowState) => ({ sys, flowState })),
            catchError((error: unknown) =>
              this.publicationEndpointUnavailable(error)
                ? of({ sys, flowState: null })
                : throwError(() => error),
            ),
          ),
        ),
      )
      .subscribe({
        next: ({ sys, flowState }) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          const hydrated = flowState
            ? this.persistence.hydratePublicationState(sys, flowState)
            : this.persistence.hydrateSystem(sys);
          if (!hydrated) {
            this.loadError.set(
              this.persistence.hydrationError() ?? 'The persisted Flow is malformed.',
            );
            this.loadState.set('error');
            return;
          }
          this.run.acknowledgeAuthoritativeHydration();
          this.validation.bindSystem(sid);
          this.validation.validateNow();
          this.system.set(sys);
          this.loadState.set('ready');
        },
        error: (error: unknown) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          const message = this.hydrationFailureMessage(error);
          this.persistence.markHydrationFailed(message);
          this.loadError.set(message);
          this.loadState.set('error');
          this.toastr.error(message, 'Flow loading blocked');
        },
      });
  }

  /** Fallback is intentionally narrow: feature-off and an older server with
   * no route may use legacy System persistence. A deleted System or malformed
   * publication state must remain blocked. */
  private publicationEndpointUnavailable(error: unknown): boolean {
    if (!(error instanceof HttpErrorResponse) || error.status !== 404) return false;
    const detail = error.error?.detail ?? error.error;
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      return (detail as { code?: unknown }).code === 'FLOW_PUBLICATION_DISABLED';
    }
    return detail === 'Not Found';
  }

  /** A publication precondition failure names something an operator can fix,
   * so its server message replaces the generic refusal instead of hiding it. */
  private hydrationFailureMessage(error: unknown): string {
    const generic =
      'The System could not be loaded. No fallback graph was opened, so the persisted Flow cannot be overwritten accidentally.';
    if (!(error instanceof HttpErrorResponse)) return generic;
    const detail = error.error?.detail ?? error.error;
    if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return generic;
    const { code, message } = detail as { code?: unknown; message?: unknown };
    if (typeof code !== 'string' || !PUBLICATION_HYDRATION_CODES.has(code)) return generic;
    return typeof message === 'string' && message.trim() ? message : `${generic} (${code})`;
  }

  protected requestClear(): void {
    if (!this.persistence.hydrationReady() || this.persistence.actionsDisabled()) return;
    this.clearConfirmationOpen.set(true);
  }

  protected confirmClear(): void {
    this.clearConfirmationOpen.set(false);
    this.persistence.confirmClear();
  }

  protected togglePalette(): void {
    if (this.focusMode()) return;
    this.paletteOpen.update((open) => !open);
    this.scheduleCanvasFit();
  }

  protected toggleInspector(): void {
    if (this.focusMode()) return;
    if (this.inspectorOpen()) {
      this.closeInspector();
      return;
    }
    if (this.store.selectedNode()) {
      this.inspectorOpen.set(true);
      this.scheduleCanvasFit();
    }
  }

  /** Closing is view-only: the graph selection remains authoritative for
   * keyboard actions and toolbar reopening. Selecting another node changes
   * `selectedNode()` and the constructor effect reopens the inspector. */
  protected closeInspector(): void {
    this.inspectorOpen.set(false);
    this.scheduleCanvasFit();
  }

  protected toggleToolbarCompact(): void {
    this.toolbarCompact.update((compact) => !compact);
    this.scheduleCanvasFit();
  }

  protected toggleWorkbench(): void {
    if (!this.systemId() || !this.persistence.hydrationReady()) return;
    const open = !this.workbenchOpen();
    this.workbenchOpen.set(open);
    this.persistence.setWorkbenchAutosaveHold(open);
    if (open) this.run.terminalOpen.set(false);
    this.scheduleCanvasFit();
  }

  protected closeWorkbench(): void {
    if (!this.workbenchOpen()) return;
    this.workbenchOpen.set(false);
    this.persistence.setWorkbenchAutosaveHold(false);
    this.scheduleCanvasFit();
  }

  /** Enter browser fullscreen when permitted; the fixed-position CSS class is
   * the safe fallback when the API is missing or denied by browser policy. */
  protected async toggleCanvasFocus(): Promise<void> {
    const root = this.builderRoot()?.nativeElement;
    if (!root) return;

    if (this.focusMode()) {
      if (
        this.document.fullscreenElement === root &&
        typeof this.document.exitFullscreen === 'function'
      ) {
        try {
          await this.document.exitFullscreen();
        } catch {
          if (this.document.fullscreenElement === root) return;
        }
      }
      this.ownsNativeFullscreen = false;
      this.focusMode.set(false);
      this.scheduleCanvasFit();
      return;
    }

    this.handleMenu.set(null);
    this.focusMode.set(true);
    this.scheduleCanvasFit();
    if (typeof root.requestFullscreen !== 'function') return;
    try {
      await root.requestFullscreen();
      this.ownsNativeFullscreen = this.document.fullscreenElement === root;
    } catch {
      // Browser policy may deny fullscreen (embedded window, lost user
      // gesture). Keep CSS focus mode active as the explicit fallback.
      this.ownsNativeFullscreen = false;
    }
  }

  private scheduleCanvasFit(): void {
    const view = this.document.defaultView;
    if (view) {
      view.requestAnimationFrame(() => this.canvas()?.fit());
      return;
    }
    queueMicrotask(() => this.canvas()?.fit());
  }

  protected reloadAuthoritativeSystem(): void {
    const sid = this.systemId();
    if (sid) this.hydrateFromSystem(sid);
  }

  /**
   * Add a palette node. When `preconnect` is given (on-handle insertion), the
   * new node is placed beside the originating node and its compatible port is
   * wired to the handle the connection was dragged from.
   */
  onAddNode(item: PaletteItem, preconnect?: ParsedConnector): void {
    if (this.persistence.actionsDisabled()) return;
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
    const edge = buildPreconnectEdge(
      preconnect,
      item,
      id,
      this.originatingSchema(preconnect),
      this.store.nodes().find((node) => node.id === preconnect.nodeId),
    );
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
    if (this.persistence.actionsDisabled()) return;
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

  onCycleRouting(): void {
    if (this.persistence.actionsDisabled()) return;
    const next = this.canvas()?.cycleRouting();
    if (next) this.routingLabel.set(next);
  }
}
