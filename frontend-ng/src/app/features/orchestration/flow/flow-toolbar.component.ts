/**
 * `<app-flow-toolbar>` — the single coherent toolbar.
 *
 * Canvas view controls (undo/redo/zoom/fit/layout/routing/clear) are emitted
 * as outputs the shell wires to the store + canvas. ALL persistence controls
 * live here and are driven by `FlowPersistenceService` (component-scoped, so
 * it shares the builder's `FlowStore` + `ActivatedRoute`): the save-state
 * pill, Save / Export / Import, Share, and scratchpad → System promotion.
 * Manual save (Save button, Ctrl·Cmd+S) and debounced autosave both go
 * through that one service — there is no separate save path on the shell.
 *
 * Three registers, left to right: what the graph *is* (count, save state,
 * revisions), what you *do* to it (author group), and what you do *with* it
 * (Operate / More disclosures). Content fingerprints are never a primary
 * label — they are the `title` of the revision pill that carries them.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowPersistenceService, type SaveState } from './flow-persistence.service';

/** What the save pill says, once the two autosave holds are folded in. */
type PillState = SaveState | 'hold';

@Component({
  selector: 'app-flow-toolbar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, HelpTooltipComponent],
  // FlowPersistenceService is provided one level up by FlowBuilderComponent so
  // the builder shell + the validation strip share the SAME instance (and
  // thus its `serverIssues` signal). The toolbar still injects it here.
  styleUrl: './flow-toolbar.component.scss',
  template: `
    <div
      class="ck-flow-toolbar"
      [class.is-compact]="compact()"
      role="toolbar"
      [attr.aria-label]="i18n.t('flow.toolbar.aria')"
    >
      <div class="ck-flow-toolbar__group">
        <span class="ck-flow-toolbar__meta">{{
          i18n.t('flow.toolbar.nodes', { count: nodeCount() })
        }}</span>
        @let pill = pillState();
        <span
          class="ck-flow-toolbar__state"
          [class.is-saved]="pill === 'saved'"
          [class.is-unsaved]="pill === 'unsaved'"
          [class.is-saving]="pill === 'saving'"
          [class.is-error]="pill === 'error'"
          [class.is-hold]="pill === 'hold'"
          role="status"
          aria-live="polite"
          [title]="stateTitle(pill)"
        >
          @switch (pill) {
            @case ('saving') {
              <app-icon name="loader-2" [size]="11" /><span>{{
                i18n.t('flow.toolbar.state.saving')
              }}</span>
            }
            @case ('hold') {
              <app-icon name="pause" [size]="11" /><span>{{
                i18n.t('flow.toolbar.state.hold')
              }}</span>
            }
            @case ('unsaved') {
              <span>{{ i18n.t('flow.toolbar.state.unsaved') }}</span>
            }
            @case ('error') {
              <app-icon name="alert-triangle" [size]="11" /><span>{{
                i18n.t('flow.toolbar.state.error')
              }}</span>
            }
            @default {
              <app-icon name="check" [size]="11" /><span>{{
                i18n.t('flow.toolbar.state.saved')
              }}</span>
            }
          }
        </span>
        @if (persistence.publicationMode()) {
          <!-- Version is the label; the content fingerprint is the tooltip. -->
          <span
            class="ck-flow-toolbar__revision"
            data-kind="draft"
            [title]="fingerprintTitle(persistence.savedFlowSha256())"
          >
            {{ i18n.t('flow.toolbar.version.draft', { revision: persistence.draftRevision() ?? '' }) }}
          </span>
          <span
            class="ck-flow-toolbar__revision"
            data-kind="published"
            [title]="fingerprintTitle(persistence.publishedFlowSha256())"
          >
            {{
              i18n.t('flow.toolbar.version.published', {
                version: persistence.publishedVersionNumber() ?? '',
              })
            }}
          </span>
          <ck-help id="concept.published" />
        }
      </div>

      <!-- Author surface: everything the person building the graph reaches for
           without opening anything. Operating the graph lives one click away in
           the Operate group; the rarely-used file / view actions in More. -->
      <div class="ck-flow-toolbar__group ck-flow-toolbar__group--author">
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [class.is-active]="paletteOpen() && !focusMode()"
          [disabled]="!hydrationReady() || focusMode()"
          (click)="togglePalette.emit()"
          [attr.aria-pressed]="paletteOpen() && !focusMode()"
          [title]="
            paletteOpen()
              ? i18n.t('flow.toolbar.palette.collapse')
              : i18n.t('flow.toolbar.palette.expand')
          "
          [attr.aria-label]="i18n.t('flow.toolbar.palette.aria')"
        >
          <app-icon name="panel-left" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [class.is-active]="inspectorOpen() && !focusMode()"
          [disabled]="!hydrationReady() || focusMode() || (!canInspect() && !inspectorOpen())"
          (click)="toggleInspector.emit()"
          [attr.aria-pressed]="inspectorOpen() && !focusMode()"
          [title]="
            inspectorOpen()
              ? i18n.t('flow.toolbar.inspector.collapse')
              : i18n.t('flow.toolbar.inspector.expand')
          "
          [attr.aria-label]="i18n.t('flow.toolbar.inspector.aria')"
        >
          <app-icon name="panel-right" [size]="14" />
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [disabled]="controlsDisabled() || !canUndo()"
          (click)="undo.emit()"
          [title]="i18n.t('flow.toolbar.undo')"
          [attr.aria-label]="i18n.t('flow.toolbar.undo.aria')"
        >
          <app-icon name="undo-2" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [disabled]="controlsDisabled() || !canRedo()"
          (click)="redo.emit()"
          [title]="i18n.t('flow.toolbar.redo')"
          [attr.aria-label]="i18n.t('flow.toolbar.redo.aria')"
        >
          <app-icon name="redo-2" [size]="14" />
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="fit.emit()"
          [disabled]="canvasControlsDisabled()"
          [title]="i18n.t('flow.toolbar.fit.aria')"
          [attr.aria-label]="i18n.t('flow.toolbar.fit.aria')"
        >
          <app-icon name="maximize" [size]="14" /><span>{{ i18n.t('flow.toolbar.fit') }}</span>
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <!-- P4 persistence controls — single source of truth via
             FlowPersistenceService (manual save also bound to Ctrl/Cmd+S). -->
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide ck-flow-toolbar__btn--accent"
          (click)="persistence.saveNow()"
          [disabled]="
            controlsDisabled() ||
            persistence.saveState() === 'saving' ||
            persistence.saveValidationBlocked()
          "
          [title]="
            persistence.saveValidationBlocked()
              ? i18n.t('flow.toolbar.save.blocked')
              : persistence.systemId()
              ? i18n.t('flow.toolbar.save.system')
              : i18n.t('flow.toolbar.save.scratch')
          "
          [attr.aria-label]="i18n.t('flow.toolbar.save.aria')"
        >
          <app-icon name="save" [size]="14" />
          <span>{{
            persistence.saveState() === 'saving'
              ? i18n.t('flow.toolbar.save.busy')
              : i18n.t('flow.toolbar.save')
          }}</span>
        </button>
        @if (persistence.publicationMode()) {
          <button
            type="button"
            class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide ck-flow-toolbar__btn--publish"
            (click)="persistence.openPublicationReview()"
            [disabled]="controlsDisabled() || !persistence.canReviewPublication()"
            [title]="
              persistence.canOpenPublishedHome()
                ? i18n.t('experience.home.open.hint')
                : persistence.publicationBlockReason() || i18n.t('flow.toolbar.publish.hint')
            "
            [attr.aria-label]="i18n.t(persistence.canOpenPublishedHome()
              ? 'experience.home.open.hint' : 'flow.toolbar.publish.aria')"
          >
            <app-icon name="upload-cloud" [size]="14" />
            <span>{{ i18n.t(persistence.canOpenPublishedHome()
              ? 'experience.home.open' : 'flow.toolbar.publish') }}</span>
          </button>
        }
        @if (!persistence.systemId()) {
          <button
            type="button"
            class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide ck-flow-toolbar__btn--accent"
            (click)="persistence.promoteToSystem()"
            [disabled]="controlsDisabled() || persistence.promoting()"
            [title]="i18n.t('flow.toolbar.promote.hint')"
            [attr.aria-label]="i18n.t('flow.toolbar.promote.aria')"
          >
            <app-icon name="rocket" [size]="14" />
            <span>{{
              persistence.promoting()
                ? i18n.t('flow.toolbar.promote.busy')
                : i18n.t('flow.toolbar.promote')
            }}</span>
          </button>
        }

        <span class="ck-flow-toolbar__sep"></span>

        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          [class.is-active]="operateOpen()"
          [disabled]="!hydrationReady()"
          (click)="operateOpen.set(!operateOpen())"
          [attr.aria-expanded]="operateOpen()"
          aria-controls="ck-flow-toolbar-operate"
          [attr.aria-label]="i18n.t('flow.toolbar.operate')"
          [title]="i18n.t('flow.toolbar.operate.hint')"
        >
          <app-icon name="play-circle" [size]="14" /><span>{{
            i18n.t('flow.toolbar.operate')
          }}</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          [class.is-active]="moreOpen()"
          (click)="moreOpen.set(!moreOpen())"
          [attr.aria-expanded]="moreOpen()"
          aria-controls="ck-flow-toolbar-more"
          [attr.aria-label]="i18n.t('flow.toolbar.more.aria')"
          [title]="i18n.t('flow.toolbar.more.hint')"
        >
          <app-icon name="more-horizontal" [size]="14" /><span>{{
            i18n.t('flow.toolbar.more')
          }}</span>
        </button>
      </div>

      <!-- Operate group: running the Flow, not authoring it. The shell projects
           the run controls here; they stay in the DOM order the toolbar declares
           so keyboard order matches what the eye reads. -->
      <div
        id="ck-flow-toolbar-operate"
        class="ck-flow-toolbar__panel"
        [class.is-open]="operateOpen()"
        role="group"
        [attr.aria-label]="i18n.t('flow.toolbar.operate')"
      >
        <ng-content select="[flowToolbarActions]" />
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          [class.is-active]="workbenchOpen()"
          [disabled]="!hydrationReady() || !workbenchAvailable()"
          (click)="toggleWorkbench.emit()"
          [attr.aria-pressed]="workbenchOpen()"
          [title]="
            workbenchAvailable()
              ? i18n.t('flow.toolbar.workbench.hint')
              : i18n.t('flow.toolbar.workbench.blocked')
          "
          [attr.aria-label]="i18n.t('flow.toolbar.workbench.aria')"
        >
          <app-icon name="message-square" [size]="14" />
          <span>{{ i18n.t('flow.toolbar.workbench') }}</span>
        </button>
      </div>

      <div
        id="ck-flow-toolbar-more"
        class="ck-flow-toolbar__panel"
        [class.is-open]="moreOpen()"
        role="group"
        [attr.aria-label]="i18n.t('flow.toolbar.more.aria')"
      >
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          [class.is-active]="focusMode()"
          [disabled]="canvasControlsDisabled()"
          (click)="toggleFocus.emit()"
          [attr.aria-pressed]="focusMode()"
          [title]="
            focusMode()
              ? i18n.t('flow.toolbar.focus.exit.hint')
              : i18n.t('flow.toolbar.focus.hint')
          "
          [attr.aria-label]="i18n.t('flow.toolbar.focus.aria')"
        >
          <app-icon [name]="focusMode() ? 'x' : 'maximize'" [size]="14" />
          <span>{{
            focusMode() ? i18n.t('flow.toolbar.focus.exit') : i18n.t('flow.toolbar.focus')
          }}</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [class.is-active]="compact()"
          (click)="toggleCompact.emit()"
          [attr.aria-pressed]="compact()"
          [title]="
            compact()
              ? i18n.t('flow.toolbar.compact.expand')
              : i18n.t('flow.toolbar.compact.collapse')
          "
          [attr.aria-label]="i18n.t('flow.toolbar.compact.aria')"
        >
          <app-icon [name]="compact() ? 'chevron-down' : 'chevron-up'" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="cycleRouting.emit()"
          [disabled]="canvasControlsDisabled()"
          [title]="i18n.t('flow.toolbar.routing', { mode: routingLabel() })"
          [attr.aria-label]="i18n.t('flow.toolbar.routing.aria')"
        >
          <app-icon name="git-branch" [size]="14" /><span>{{ routingLabel() }}</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          (click)="zoomIn.emit()"
          [disabled]="canvasControlsDisabled()"
          [title]="i18n.t('flow.toolbar.zoom_in')"
          [attr.aria-label]="i18n.t('flow.toolbar.zoom_in')"
        >
          <app-icon name="zoom-in" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          (click)="zoomOut.emit()"
          [disabled]="canvasControlsDisabled()"
          [title]="i18n.t('flow.toolbar.zoom_out')"
          [attr.aria-label]="i18n.t('flow.toolbar.zoom_out')"
        >
          <app-icon name="zoom-out" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="autoLayout.emit()"
          [disabled]="canvasControlsDisabled()"
          [title]="i18n.t('flow.toolbar.arrange.hint')"
          [attr.aria-label]="i18n.t('flow.toolbar.arrange.aria')"
        >
          <app-icon name="layout-grid" [size]="14" /><span>{{
            i18n.t('flow.toolbar.arrange')
          }}</span>
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        @if (persistence.systemId()) {
          <button
            type="button"
            class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
            (click)="persistence.validateNow()"
            [disabled]="
              controlsDisabled() ||
              persistence.serverValidationState() === 'validating'
            "
            [title]="
              persistence.serverValidationState() === 'validating'
                ? i18n.t('flow.toolbar.validate.hint.busy')
                : i18n.t('flow.toolbar.validate.hint')
            "
            [attr.aria-label]="i18n.t('flow.toolbar.validate.aria')"
          >
            <app-icon name="shield-check" [size]="14" />
            <span>{{
              persistence.serverValidationState() === 'validating'
                ? i18n.t('flow.toolbar.validate.busy')
                : i18n.t('flow.toolbar.validate')
            }}</span>
          </button>
        }
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="persistence.exportJson()"
          [disabled]="controlsDisabled()"
          [title]="i18n.t('flow.toolbar.export.hint')"
          [attr.aria-label]="i18n.t('flow.toolbar.export.aria')"
        >
          <app-icon name="download" [size]="14" /><span>{{
            i18n.t('flow.toolbar.export')
          }}</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="importInput.click()"
          [disabled]="controlsDisabled()"
          [title]="i18n.t('flow.toolbar.import.hint')"
          [attr.aria-label]="i18n.t('flow.toolbar.import.aria')"
        >
          <app-icon name="upload" [size]="14" /><span>{{
            i18n.t('flow.toolbar.import')
          }}</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="persistence.shareLink()"
          [disabled]="controlsDisabled()"
          [title]="i18n.t('flow.toolbar.share.hint')"
          [attr.aria-label]="i18n.t('flow.toolbar.share.aria')"
        >
          <app-icon name="link-2" [size]="14" /><span>{{ i18n.t('flow.toolbar.share') }}</span>
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--danger"
          (click)="clear.emit()"
          [disabled]="controlsDisabled()"
          [title]="i18n.t('flow.toolbar.clear')"
          [attr.aria-label]="i18n.t('flow.toolbar.clear.aria')"
        >
          <app-icon name="trash-2" [size]="14" />
        </button>
      </div>

      <input
        #importInput
        type="file"
        accept="application/json,.json"
        hidden
        [disabled]="controlsDisabled()"
        (change)="onImportFile($event)"
      />
    </div>
  `,
})
export class FlowToolbarComponent {
  /** P4 persistence brain — shares the builder's FlowStore (component-scoped). */
  protected readonly persistence = inject(FlowPersistenceService);
  readonly i18n = inject(I18nService);

  readonly nodeCount = input(0);
  readonly canUndo = input(false);
  readonly canRedo = input(false);
  readonly routingLabel = input('segment');
  readonly paletteOpen = input(true);
  readonly inspectorOpen = input(false);
  readonly canInspect = input(false);
  readonly focusMode = input(false);
  readonly compact = input(false);
  readonly workbenchOpen = input(false);
  readonly workbenchAvailable = input(false);
  /** Canvas-only viewport controls are inert while the accessible Outline is
   * the active projection; graph editing and persistence stay available. */
  readonly canvasActive = input(true);
  /** The bound System must be authoritatively hydrated before controls can
   * read or mutate its graph. Scratchpad routes explicitly bind this to true. */
  readonly hydrationReady = input(false);

  /** Operate / More are inline disclosures, not overlays: they wrap onto their
   *  own toolbar row so nothing is ever painted over the canvas, and every
   *  control inside stays exactly one click from the closed state. */
  protected readonly operateOpen = signal(false);
  protected readonly moreOpen = signal(false);

  protected readonly controlsDisabled = computed(
    () => this.persistence.actionsDisabled() || !this.hydrationReady(),
  );
  protected readonly canvasControlsDisabled = computed(
    () => this.controlsDisabled() || !this.canvasActive(),
  );

  /**
   * The workbench hold used to be invisible: the pill said "Unsaved" while the
   * builder had deliberately stopped autosaving, so the wait never ended and
   * nothing said why. Surface it as its own state, but only when there is
   * something at stake — with a clean graph, held or not, nothing is pending.
   */
  protected readonly pillState = computed<PillState>(() => {
    const state = this.persistence.saveState();
    if (state === 'unsaved' && this.persistence.workbenchAutosaveHeld()) return 'hold';
    return state;
  });

  readonly undo = output<void>();
  readonly redo = output<void>();
  readonly zoomIn = output<void>();
  readonly zoomOut = output<void>();
  readonly fit = output<void>();
  readonly autoLayout = output<void>();
  readonly cycleRouting = output<void>();
  readonly togglePalette = output<void>();
  readonly toggleInspector = output<void>();
  readonly toggleFocus = output<void>();
  readonly toggleCompact = output<void>();
  readonly toggleWorkbench = output<void>();
  readonly clear = output<void>();

  /** Read an imported JSON file and round-trip it through the store. */
  onImportFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (this.controlsDisabled()) {
      input.value = '';
      return;
    }
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      // Hydration/save state may have changed while the browser was reading a
      // large file. Re-check at mutation time, not only when opening the picker.
      if (!this.controlsDisabled()) this.persistence.importJson(String(reader.result));
    };
    reader.readAsText(file);
    input.value = '';
  }

  protected stateTitle(state: PillState): string {
    if (this.persistence.reviewRequired()) {
      return this.i18n.t('flow.toolbar.state.title.review');
    }
    if (this.persistence.autosavePaused()) {
      return this.i18n.t('flow.toolbar.state.title.paused');
    }
    switch (state) {
      case 'hold':
        return this.i18n.t('flow.builder.autosave.hold.hint');
      case 'saving':
        return this.i18n.t('flow.toolbar.state.title.saving');
      case 'unsaved':
        return this.i18n.t('flow.toolbar.state.title.unsaved');
      case 'error':
        return this.i18n.t('flow.toolbar.state.title.error');
      default:
        return this.i18n.t('flow.toolbar.state.title.saved');
    }
  }

  /** Fingerprints identify a revision but never label it. */
  protected fingerprintTitle(value: string | null): string {
    return this.i18n.t('flow.toolbar.version.fingerprint', {
      hash: value ? value.slice(0, 8) : '—',
    });
  }
}
