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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CorrectionReviewComponent } from '@app/features/runs/correction-review.component';
import { ApiService } from '@app/core/api.service';
import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { catchError, map, of, switchMap, throwError } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type System,
  type Run,
} from '@app/core/canonical-api.service';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { CkBackLinkComponent, HelpTooltipComponent, NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { FlowStore } from './flow.store';
import {
  FlowCanvasComponent,
  type ConnectFromHandleEvent,
} from './flow-canvas.component';
import { FlowOutlineComponent } from './flow-outline.component';
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
import { FlowRecipeService } from './flow-recipe.service';
import { FlowRecipeWorkshopComponent } from './flow-recipe-workshop.component';
import { isPythonRecipeNode } from './flow-recipe.vm';
import { FlowTransformService } from './flow-transform.service';
import { FlowTransformWorkshopComponent } from './flow-transform-workshop.component';
import { isTransformNode } from './flow-transform.vm';
import { FlowMlService } from './flow-ml.service';
import { FlowTrainWorkshopComponent } from './flow-train-workshop.component';
import { isTrainNode } from './flow-ml.vm';
import {
  toNodeView,
  type ParsedConnector,
} from './flow-foblex.adapter';
import {
  buildPreconnectEdge,
  isPaletteItemConnectable,
} from './flow-preconnect';
import { paletteItemUsage, type PaletteInsertContext } from './flow-palette.vm';
import {
  DEFAULT_PALETTE,
  paletteItemToNode,
  type PaletteItem,
} from './flow.types';

/** How many compatible entries the on-handle menu proposes before deferring
 * to the palette's search. */
const HANDLE_MENU_SHORTLIST = 8;

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
    // One env-resolution cache per builder shell: the inspector summary and
    // the recipe workshop read the same resolved row.
    FlowRecipeService,
    // Same for the data plane: one dataset catalog and one preview client per
    // shell, shared by every transform node the author opens.
    FlowTransformService,
    // And one for the model plane: the registry the serving pickers read and the
    // training run the workshop follows, shared by every model node in the graph.
    FlowMlService,
  ],
  imports: [
    CorrectionReviewComponent,
    NavLinkDirective,
    CkBackLinkComponent,
    IconComponent,
    FlowCanvasComponent,
    FlowOutlineComponent,
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
    FlowRecipeWorkshopComponent,
    FlowTransformWorkshopComponent,
    FlowTrainWorkshopComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    HelpTooltipComponent,
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
          <ck-back-link />
          <span class="flow-builder__sep">/</span>
          @if (system(); as sys) {
            <a [navLink]="{ type: 'system', ref: sys.id }" class="flow-builder__crumb">{{ sys.name }}</a>
            <span class="flow-builder__sep">/</span>
            <span class="flow-builder__here">{{ i18n.t('flow.builder.crumb.here') }}</span>
          } @else {
            <span class="flow-builder__here">{{ i18n.t('flow.builder.crumb.scratchpad') }}</span>
          }
        </div>
        <h1 class="flow-builder__title">
          {{ system()?.name || i18n.t('flow.builder.title') }}
          <ck-help id="concept.flow" />
        </h1>
      </header>

      @if (referenceRunId()) {
        <details class="flow-builder__correction-context" open>
          <summary>{{ i18n.t('runs.correction.reference_run') }} · {{ referenceRunId() }}</summary>
          @if (referenceError()) { <p role="alert">{{ referenceError() }}</p> }
          @if (referenceRun(); as reference) {
            <a [navLink]="{type:'run',ref:reference.id}">{{ i18n.t('runs.correction.back_to_evidence') }}</a>
            @if (referenceEvaluationId(); as evaluationId) {
              <app-correction-review [run]="reference" [evaluationId]="evaluationId"
                [proposalId]="referenceCorrectionId()" [applicationAllowed]="!store.dirty() && persistence.saveState() === 'saved'"
                (applied)="onReferenceCorrectionApplied()" />
            }
          }
        </details>
      }
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
        [automationMode]="automationMode()"
        [workbenchOpen]="workbenchOpen()"
        [workbenchAvailable]="!!systemId()"
        [canvasActive]="surfaceMode() === 'canvas'"
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
          <app-flow-run-controls
            flowToolbarActions
            [compact]="automationMode()"
            (openVersions)="versionsOpen.set(true)"
          />
        }
      </app-flow-toolbar>

      @if (loadState() === 'ready' && persistence.hydrationReady()) {
        @if (persistence.publicationMode() && !automationMode()) {
          <div class="flow-builder__publication-boundary" role="status">
            <strong>
              {{
                i18n.t('flow.builder.boundary.draft', {
                  revision: persistence.draftRevision() ?? '',
                })
              }}
              <ck-help id="concept.draft" />
            </strong>
            <span>
              {{
                i18n.t('flow.builder.boundary.detail', {
                  version: persistence.publishedVersionNumber() ?? '',
                })
              }}
            </span>
            @if (!persistence.publishedContractReady()) {
              <strong>{{ i18n.t('flow.builder.boundary.contract') }}</strong>
            }
          </div>
        } @else if (systemId()) {
          <!-- Per-System sidecar, exactly like the strip it wraps: the
               scratchpad has no runtime contract, so it gets no disclosure
               promising one. -->
          <div class="flow-builder__runtime">
            <button
              type="button"
              class="flow-builder__runtime-toggle"
              [attr.aria-expanded]="manifestStripOpen()"
              aria-controls="flow-builder-runtime-manifest"
              (click)="manifestStripOpen.set(!manifestStripOpen())"
            >
              <app-icon
                [name]="manifestStripOpen() ? 'chevron-down' : 'chevron-right'"
                [size]="12"
              />
              <span>{{ i18n.t('flow.builder.runtime.details') }}</span>
            </button>
            <ck-help id="concept.execution-mode" />
            <div id="flow-builder-runtime-manifest" [hidden]="!manifestStripOpen()">
              <!-- The two facts the badge wall used to shout at the top of the
                   canvas, named in full and read where they are asked for. -->
              <dl class="flow-builder__runtime-facts">
                <dt>{{ i18n.t('flow.builder.runtime.surface') }}</dt>
                <dd>{{ run.executionSurfaceLabel() }}</dd>
                <dt>{{ i18n.t('flow.builder.runtime.mode') }}</dt>
                <dd>{{ run.runtimeModeLabel() }}</dd>
              </dl>
              <app-flow-manifest-strip />
            </div>
          </div>
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
              <strong>{{ i18n.t('flow.builder.autosave.paused') }}</strong>
              {{ i18n.t('flow.builder.autosave.paused.body') }}
            </div>
            <div class="flow-builder__review-actions">
              @if (persistence.reviewRequired() === 'conflict') {
                <button type="button" (click)="reloadAuthoritativeSystem()">
                  {{ i18n.t('flow.builder.autosave.reload') }}
                </button>
              } @else {
                <button type="button" (click)="persistence.saveNow()">
                  {{ i18n.t('flow.builder.autosave.review') }}
                </button>
                <button type="button" (click)="persistence.discardPendingChanges()">
                  {{ i18n.t('flow.builder.autosave.discard') }}
                </button>
              }
            </div>
          </div>
        } @else if (persistence.workbenchAutosaveHeld() && store.dirty()) {
          <!-- The workbench hold used to be silent: the toolbar said "Unsaved"
               and nothing ever saved. Say it, and offer the one action that
               ends it. -->
          <div class="flow-builder__review is-hold" role="status" aria-live="polite">
            <div>
              <strong>{{ i18n.t('flow.builder.autosave.hold') }}</strong>
              {{ i18n.t('flow.builder.autosave.hold.hint') }}
            </div>
            <div class="flow-builder__review-actions">
              <button type="button" (click)="persistence.saveNow()">
                {{ i18n.t('flow.builder.autosave.review') }}
              </button>
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
              [items]="automationMode() ? automationPalette() : palette"
              [simpleMode]="automationMode()"
              [context]="paletteContext()"
              [flowSkillSlugs]="flowSkillSlugs()"
              [nodeCount]="store.nodeCount()"
              (add)="onPaletteAdd($event)"
              (clearContext)="dismissPaletteContext()"
            />
          }

          <div class="flow-builder__surface">
            @if (!focusMode()) {
              <div
                class="flow-builder__view-switch"
                role="group"
                [attr.aria-label]="i18n.t('flow.builder.view.aria')"
              >
                <button
                  id="flow-builder-view-canvas"
                  type="button"
                  [attr.aria-pressed]="surfaceMode() === 'canvas'"
                  [class.is-active]="surfaceMode() === 'canvas'"
                  aria-controls="flow-builder-canvas"
                  (click)="setSurfaceMode('canvas')"
                >
                  {{ i18n.t('flow.builder.view.canvas') }}
                </button>
                <button
                  id="flow-builder-view-outline"
                  type="button"
                  [attr.aria-pressed]="surfaceMode() === 'outline'"
                  [class.is-active]="surfaceMode() === 'outline'"
                  aria-controls="flow-builder-outline"
                  (click)="setSurfaceMode('outline')"
                >
                  {{ i18n.t('flow.builder.view.outline') }}
                </button>
              </div>
            }

            <div
              id="flow-builder-canvas"
              class="flow-builder__canvas"
              role="region"
              [attr.aria-labelledby]="!focusMode() ? 'flow-builder-view-canvas' : null"
              [attr.aria-label]="focusMode() ? i18n.t('flow.builder.view.canvas') : null"
              [hidden]="surfaceMode() !== 'canvas'"
            >
              <app-flow-canvas (connectFromHandle)="onConnectFromHandle($event)" />
              @if (store.nodeCount() === 0) {
                <!-- First-Flow guide. The three steps are the shape of every Flow,
                     named in the words the palette uses, so the empty canvas
                     teaches the model instead of only inviting a click. -->
                <div class="flow-builder__canvas-empty">
                  <app-empty-state
                    icon="git-branch"
                    size="lg"
                    [title]="i18n.t('flow.builder.empty.title')"
                    [description]="i18n.t('flow.builder.empty.body')"
                  >
                    <ol class="flow-builder__canvas-empty-steps">
                      <li>{{ i18n.t('flow.builder.empty.step1') }}</li>
                      <li>{{ i18n.t('flow.builder.empty.step2') }}</li>
                      <li>{{ i18n.t('flow.builder.empty.step3') }}</li>
                    </ol>
                    <button
                      type="button"
                      class="flow-builder__canvas-empty-cta"
                      (click)="startFromPalette()"
                    >
                      <app-icon name="plus" [size]="14" />
                      <span>{{ i18n.t('flow.builder.empty.cta') }}</span>
                    </button>
                  </app-empty-state>
                </div>
              }
            </div>

            <app-flow-outline
              id="flow-builder-outline"
              class="flow-builder__outline"
              role="region"
              aria-labelledby="flow-builder-view-outline"
              [hidden]="surfaceMode() !== 'outline'"
              [editingLocked]="persistence.actionsDisabled()"
              (inspectNode)="onOutlineInspect($event)"
            />
          </div>

          @if (inspectorOpen() && !focusMode()) {
            <app-flow-inspector
              class="flow-builder__inspector"
              [systemId]="systemId()"
              (close)="closeInspector()"
              (openRecipeWorkshop)="openRecipeWorkshop()"
              (openTransformWorkshop)="openTransformWorkshop()"
              (openTrainWorkshop)="openTrainWorkshop()"
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

        @if (recipeWorkshopOpen()) {
          <app-flow-recipe-workshop (close)="closeRecipeWorkshop()" />
        }

        @if (transformWorkshopOpen()) {
          <app-flow-transform-workshop (close)="closeTransformWorkshop()" />
        }

        @if (trainWorkshopOpen()) {
          <app-flow-train-workshop (close)="closeTrainWorkshop()" />
        }
      } @else {
        <div class="flow-builder__load-state" role="status">
          @if (loadState() === 'loading') {
            <strong>{{ i18n.t('flow.builder.load.loading') }}</strong>
            <span>{{ i18n.t('flow.builder.load.loading.body') }}</span>
          } @else {
            <strong>{{ i18n.t('flow.builder.load.error') }}</strong>
            <span>{{ loadError() }}</span>
            @if (systemId(); as sid) {
              <button type="button" (click)="hydrateFromSystem(sid)">
                {{ i18n.t('flow.builder.load.retry') }}
              </button>
            }
          }
        </div>
      }

      @if (handleMenu(); as menu) {
        <div class="flow-builder__handle-backdrop" (click)="closeHandleMenu()"></div>
        <div
          class="flow-builder__handle-menu"
          role="menu"
          [attr.aria-label]="i18n.t('flow.builder.handle.aria')"
          [style.left.px]="menu.position.x"
          [style.top.px]="menu.position.y"
        >
          <div class="flow-builder__handle-title">
            {{
              menu.connector.direction === 'out'
                ? i18n.t('flow.builder.handle.insert.target')
                : i18n.t('flow.builder.handle.insert.source')
            }}
          </div>
          @for (item of handleMenuShortlist(); track item.config?.['skill_slug'] ?? item.type) {
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
            <p class="flow-builder__handle-empty">{{ i18n.t('flow.builder.handle.empty') }}</p>
          }
          @if (handleMenuItems().length > handleMenuShortlist().length) {
            <button
              type="button"
              role="menuitem"
              class="flow-builder__handle-more"
              (click)="promoteHandleMenuToPalette()"
            >
              {{ i18n.t('flow.builder.handle.more', { count: handleMenuItems().length }) }}
            </button>
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
      [title]="i18n.t('flow.builder.clear.title')"
      [description]="clearConfirmationDescription()"
      [confirmLabel]="i18n.t('flow.builder.clear.confirm')"
      [cancelLabel]="i18n.t('flow.builder.clear.cancel')"
      tone="danger"
      icon="trash-2"
      [confirmPhrase]="confirmationPhrase()"
      (confirm)="confirmClear()"
      (cancel)="clearConfirmationOpen.set(false)"
    />

    <app-confirm-dialog
      [open]="persistence.replacementConfirmationRequested()"
      [title]="i18n.t('flow.builder.replace.title')"
      [description]="i18n.t('flow.builder.replace.description')"
      [confirmLabel]="i18n.t('flow.builder.replace.confirm')"
      [cancelLabel]="i18n.t('flow.builder.replace.cancel')"
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
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly referenceApi = inject(ApiService);
  protected readonly referenceRunId = signal<string | null>(null);
  protected readonly referenceCorrectionId = signal<string | null>(null);
  protected readonly referenceNodeId = signal<string | null>(null);
  protected readonly referenceRun = signal<Run | null>(null);
  protected readonly referenceEvaluationId = signal<string | null>(null);
  protected readonly referenceError = signal('');
  private selectedReferenceNode: string | null = null;
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
  protected readonly automationMode = computed(() =>
    this.store.snapshot().variant === 'automation_v1',
  );
  protected readonly automationPalette = computed<PaletteItem[]>(() => {
    const agent = this.store.nodes().find((node) => node.id === 'agent');
    const agentItem: PaletteItem | null = agent ? {
      type: 'skill',
      kind: 'task',
      label: 'Agent',
      description: String(agent.data?.['description'] || 'Run the AI step'),
      icon: 'bot',
      tone: 'cyan',
      inputs: agent.inputs,
      outputs: agent.outputs,
      config: agent.config as Record<string, unknown>,
      data: agent.data,
    } : null;
    const primitives = DEFAULT_PALETTE.filter((item) =>
      item.label === 'Trigger' || item.label === 'Decision' || item.label === 'Output');
    return agentItem
      ? [primitives[0], agentItem, primitives[1], primitives[2]]
      : primitives;
  });
  protected readonly systemId = signal<string | null>(null);
  protected readonly system = signal<System | null>(null);
  protected readonly paletteOpen = signal(true);
  protected readonly inspectorOpen = signal(false);
  protected readonly surfaceMode = signal<'canvas' | 'outline'>('canvas');
  protected readonly focusMode = signal(false);
  protected readonly toolbarCompact = signal(false);
  protected readonly workbenchOpen = signal(false);
  /** Full-screen authoring dialog for the SELECTED Python recipe node. */
  protected readonly recipeWorkshopOpen = signal(false);
  /** Same, for the SELECTED SQL transform node. */
  protected readonly transformWorkshopOpen = signal(false);
  /** Same, for the SELECTED sklearn training node. */
  protected readonly trainWorkshopOpen = signal(false);
  protected readonly versionsOpen = signal(false);
  /** Runtime manifest is operator context, not authoring context: collapsed
   *  until asked for, expanded state kept for the rest of the session. */
  protected readonly manifestStripOpen = signal(false);
  protected readonly routingLabel = signal('segment');
  protected readonly loadState = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly loadError = signal('');
  protected readonly clearConfirmationOpen = signal(false);
  protected readonly confirmationPhrase = computed(
    () => this.system()?.name?.trim() || 'CLEAR',
  );
  protected readonly clearConfirmationDescription = computed(() =>
    this.i18n.t('flow.builder.clear.description', {
      nodes: this.store.nodeCount(),
      edges: this.store.edgeCount(),
    }),
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
    return all
      .filter((item) => isPaletteItemConnectable(item, side, menu.schema))
      .sort(
        (a, b) => paletteItemUsage(b) - paletteItemUsage(a) || a.label.localeCompare(b.label),
      );
  });

  /** The floating menu proposes, it does not enumerate: dozens of compatible
   *  entries at a drop point is the catalog problem in a smaller window. The
   *  remainder is reached through the palette, which can search. */
  protected readonly handleMenuShortlist = computed<PaletteItem[]>(() =>
    this.handleMenuItems().slice(0, HANDLE_MENU_SHORTLIST),
  );

  /** Connector an explicit "search all compatible" promotion anchored the
   *  palette on. Null → the palette follows the current selection instead. */
  private readonly paletteAnchor = signal<ParsedConnector | null>(null);
  /** Node id whose contextual filter the operator dismissed. Selecting another
   *  node re-arms it, so "show all" is an escape hatch, not a mode. */
  private readonly contextDismissedFor = signal<string | null>(null);

  /**
   * Where a palette insertion connects, when it connects to something. The
   * originating connector travels with the context so picking an entry wires
   * the edge in the same undo frame as the node.
   */
  private readonly paletteInsertion = computed<{
    connector: ParsedConnector;
    context: PaletteInsertContext;
  } | null>(() => {
    const anchor = this.paletteAnchor();
    if (anchor) return this.describeInsertion(anchor);
    const selected = this.store.selectedNode();
    if (!selected || this.contextDismissedFor() === selected.id) return null;
    // Extending a selection means appending after it: the first output
    // connector the canvas actually renders (a sink renders none).
    const connector = toNodeView(selected).outputs[0];
    if (!connector) return null;
    return this.describeInsertion({
      nodeId: selected.id,
      direction: 'out',
      port: connector.name || undefined,
    });
  });

  protected readonly paletteContext = computed<PaletteInsertContext | null>(
    () => this.paletteInsertion()?.context ?? null,
  );

  /** Skill slugs already bound in the open Flow — the "used in this flow"
   *  half of the palette's usage signal. */
  protected readonly flowSkillSlugs = computed<string[]>(() =>
    this.store.nodes().flatMap((node) => {
      const slug = (node.config as Record<string, unknown> | undefined)?.['skill_slug'];
      return typeof slug === 'string' && slug ? [slug] : [];
    }),
  );

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
    // Context navigation never hydrates a graph. It reads the referenced Run
    // separately, then selects a node only after normal draft hydration.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      this.referenceRunId.set(params.get('reference_run'));
      this.referenceCorrectionId.set(params.get('correction'));
      this.referenceNodeId.set(params.get('node'));
      this.selectedReferenceNode = null;
      this.loadReferenceContext();
    });
    effect(() => this.selectReferenceNode());

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

  protected selectReferenceNode(): void {
    const node = this.referenceNodeId();
    if (this.loadState() !== 'ready' || !this.referenceRun() || !node || this.selectedReferenceNode === node) return;
    const exists = this.store.nodes().some(candidate => candidate.id === node);
    untracked(() => {
      this.selectedReferenceNode = node;
      if (exists) this.store.setSelection(node);
      else this.referenceError.set(this.i18n.t('runs.correction.node_missing'));
    });
  }

  private loadReferenceContext(): void {
    const id = this.referenceRunId(); const systemId = this.systemId();
    this.referenceRun.set(null); this.referenceEvaluationId.set(null); this.referenceError.set('');
    if (!id || !systemId) return;
    const scope = this.workspace.captureRequestScope();
    this.canonical.getRun(id).pipe(takeUntilDestroyed(this.destroyRef), switchMap(run => {
      if (!this.workspace.isRequestScopeCurrent(scope) || this.referenceRunId() !== id) return of(null);
      if (!run || run.system_id !== systemId) return throwError(() => new Error('reference_run_unavailable'));
      return this.referenceApi.get<{evaluation_id?:string}>(`/evaluation/by-run/${encodeURIComponent(id)}`).pipe(map(evaluation => ({run,evaluation})));
    })).subscribe({next: result => {
      if (!result || !this.workspace.isRequestScopeCurrent(scope) || this.referenceRunId() !== id) return;
      this.referenceRun.set(result.run); this.referenceEvaluationId.set(result.evaluation.evaluation_id || null);
      if (!result.evaluation.evaluation_id) this.referenceError.set(this.i18n.t('runs.correction.evaluation_missing'));
    },error:()=>{if(this.workspace.isRequestScopeCurrent(scope) && this.referenceRunId() === id)this.referenceError.set(this.i18n.t('runs.correction.reference_unavailable'));}});
  }

  protected onReferenceCorrectionApplied(): void {
    // An edit made while the request was in flight must never be overwritten.
    if (this.store.dirty() || this.persistence.saveState() !== 'saved') {
      this.referenceError.set(this.i18n.t('runs.correction.keep_unsaved'));
      return;
    }
    const id = this.systemId(); if (!id) return;
    this.selectedReferenceNode = null;
    this.hydrateFromSystem(id);
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
        this.persistence.hydrationError() ?? this.i18n.t('flow.builder.error.rollback'),
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
              this.persistence.hydrationError() ?? this.i18n.t('flow.builder.error.malformed'),
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
          this.toastr.error(message, this.i18n.t('flow.builder.load.error'));
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
      this.i18n.t('flow.builder.error.generic');
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

  /** Canvas and Outline are two projections of the same FlowStore. Switching
   * only changes presentation; selection, history and graph edits remain live. */
  protected setSurfaceMode(mode: 'canvas' | 'outline'): void {
    if (this.surfaceMode() === mode) return;
    this.surfaceMode.set(mode);
    if (mode === 'canvas') this.scheduleCanvasFit();
  }

  protected onOutlineInspect(nodeId: string): void {
    this.store.setSelection(nodeId);
    this.inspectorOpen.set(true);
  }

  /** Empty-canvas call to action: bring the author back to the one surface
   *  that can put a node down, whatever state the shell was left in. */
  protected startFromPalette(): void {
    if (this.focusMode()) void this.toggleCanvasFocus();
    this.paletteOpen.set(true);
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

  /** The inspector asks; the shell mounts the dialog over the whole builder.
   * Unlike the workbench, autosave keeps running: workshop edits are ordinary
   * node-config edits, meant to be versioned with the flow. */
  protected openRecipeWorkshop(): void {
    if (!isPythonRecipeNode(this.store.selectedNode())) return;
    this.recipeWorkshopOpen.set(true);
  }

  protected closeRecipeWorkshop(): void {
    this.recipeWorkshopOpen.set(false);
  }

  /** Same contract for the SQL transform node: ordinary node-config edits, so
   * autosave keeps running while the workshop is open. */
  protected openTransformWorkshop(): void {
    if (!isTransformNode(this.store.selectedNode())) return;
    this.transformWorkshopOpen.set(true);
  }

  protected closeTransformWorkshop(): void {
    this.transformWorkshopOpen.set(false);
  }

  /** And for the training node. A fit registers a real version, so nothing here
   * is held back either: the spec is node config and it autosaves with the flow. */
  protected openTrainWorkshop(): void {
    if (!isTrainNode(this.store.selectedNode())) return;
    this.trainWorkshopOpen.set(true);
  }

  protected closeTrainWorkshop(): void {
    this.trainWorkshopOpen.set(false);
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
    this.surfaceMode.set('canvas');
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

  /** Palette pick. It carries the contextual insertion when one is active, so
   *  "what connects here" and "wire it" are the same gesture. */
  protected onPaletteAdd(item: PaletteItem): void {
    const insertion = this.paletteInsertion();
    this.paletteAnchor.set(null);
    this.onAddNode(item, insertion?.connector);
  }

  protected dismissPaletteContext(): void {
    this.paletteAnchor.set(null);
    this.contextDismissedFor.set(this.store.selectedNodeId());
  }

  /** Move an on-handle insertion into the palette, which can search the whole
   *  compatible set instead of listing it at the drop point. */
  protected promoteHandleMenuToPalette(): void {
    const menu = this.handleMenu();
    if (!menu) return;
    this.paletteAnchor.set(menu.connector);
    this.handleMenu.set(null);
    if (!this.paletteOpen() || this.focusMode()) {
      this.focusMode.set(false);
      this.paletteOpen.set(true);
      this.scheduleCanvasFit();
    }
  }

  private describeInsertion(connector: ParsedConnector): {
    connector: ParsedConnector;
    context: PaletteInsertContext;
  } | null {
    const node = this.store.nodes().find((candidate) => candidate.id === connector.nodeId);
    if (!node) return null;
    return {
      connector,
      context: {
        // Dragging FROM an output → the new node consumes on its input side.
        side: connector.direction === 'out' ? 'in' : 'out',
        schema: this.originatingSchema(connector),
        originLabel: node.label || node.id,
        originPort: connector.port,
      },
    };
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
