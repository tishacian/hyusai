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
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowPersistenceService, type SaveState } from './flow-persistence.service';

@Component({
  selector: 'app-flow-toolbar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  // FlowPersistenceService is provided one level up by FlowBuilderComponent so
  // the builder shell + the validation strip share the SAME instance (and
  // thus its `serverIssues` signal). The toolbar still injects it here.
  styleUrl: './flow-toolbar.component.scss',
  template: `
    <div class="ck-flow-toolbar" role="toolbar" aria-label="Flow canvas tools">
      <!-- Execution actions are projected here by the shell (run controls)
           so this toolbar stays a thin view-controls component. -->
      <div class="ck-flow-toolbar__group ck-flow-toolbar__group--actions">
        <ng-content select="[flowToolbarActions]" />
      </div>

      <div class="ck-flow-toolbar__group">
        <span class="ck-flow-toolbar__meta">{{ nodeCount() }} nodes</span>
        @let state = persistence.saveState();
        <span
          class="ck-flow-toolbar__state"
          [class.is-saved]="state === 'saved'"
          [class.is-unsaved]="state === 'unsaved'"
          [class.is-saving]="state === 'saving'"
          [class.is-error]="state === 'error'"
          role="status"
          aria-live="polite"
          [title]="stateTitle(state)"
        >
          @switch (state) {
            @case ('saving') {
              <app-icon name="loader-2" [size]="11" /><span>Saving…</span>
            }
            @case ('unsaved') {
              <span>Unsaved</span>
            }
            @case ('error') {
              <app-icon name="alert-triangle" [size]="11" /><span>Save failed</span>
            }
            @default {
              <app-icon name="check" [size]="11" /><span>Saved</span>
            }
          }
        </span>
        @if (persistence.publicationMode()) {
          <span class="ck-flow-toolbar__revision" data-kind="draft">
            Draft r{{ persistence.draftRevision() }} · {{ shortHash(persistence.savedFlowSha256()) }}
          </span>
          <span class="ck-flow-toolbar__revision" data-kind="published">
            Published v{{ persistence.publishedVersionNumber() }} · {{ shortHash(persistence.publishedFlowSha256()) }}
          </span>
        }
      </div>

      <div class="ck-flow-toolbar__group">
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [disabled]="controlsDisabled() || !canUndo()"
          (click)="undo.emit()"
          title="Undo (Ctrl/Cmd+Z)"
          aria-label="Undo"
        >
          <app-icon name="undo-2" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [disabled]="controlsDisabled() || !canRedo()"
          (click)="redo.emit()"
          title="Redo (Ctrl/Cmd+Shift+Z)"
          aria-label="Redo"
        >
          <app-icon name="redo-2" [size]="14" />
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <button type="button" class="ck-flow-toolbar__btn" (click)="zoomIn.emit()" [disabled]="controlsDisabled()" title="Zoom in" aria-label="Zoom in">
          <app-icon name="zoom-in" [size]="14" />
        </button>
        <button type="button" class="ck-flow-toolbar__btn" (click)="zoomOut.emit()" [disabled]="controlsDisabled()" title="Zoom out" aria-label="Zoom out">
          <app-icon name="zoom-out" [size]="14" />
        </button>
        <button type="button" class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide" (click)="fit.emit()" [disabled]="controlsDisabled()" title="Fit to view" aria-label="Fit to view">
          <app-icon name="maximize" [size]="14" /><span>Fit</span>
        </button>
        <button type="button" class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide" (click)="autoLayout.emit()" [disabled]="controlsDisabled()" title="Auto-arrange — repositions all nodes (Ctrl/Cmd+Z to undo)" aria-label="Auto-arrange all nodes">
          <app-icon name="layout-grid" [size]="14" /><span>Arrange</span>
        </button>
        <button type="button" class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide" (click)="cycleRouting.emit()" [disabled]="controlsDisabled()" [title]="'Routing: ' + routingLabel()" aria-label="Cycle routing">
          <app-icon name="git-branch" [size]="14" /><span>{{ routingLabel() }}</span>
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <!-- P4 persistence controls — single source of truth via
             FlowPersistenceService (manual save also bound to Ctrl/Cmd+S). -->
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
                ? 'Validating the current Flow revision…'
                : 'Validate the current Flow revision on the server'
            "
            aria-label="Validate current flow"
          >
            <app-icon name="shield-check" [size]="14" />
            <span>{{ persistence.serverValidationState() === 'validating' ? 'Validating…' : 'Validate' }}</span>
          </button>
        }
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
              ? 'Fix the current server validation errors before saving'
              : persistence.systemId()
              ? 'Save flow to System (Ctrl/Cmd+S)'
              : 'Save scratchpad draft locally (Ctrl/Cmd+S)'
          "
          aria-label="Save flow"
        >
          <app-icon name="save" [size]="14" />
          <span>{{ persistence.saveState() === 'saving' ? 'Saving…' : 'Save' }}</span>
        </button>
        @if (persistence.publicationMode()) {
          <button
            type="button"
            class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide ck-flow-toolbar__btn--publish"
            (click)="persistence.openPublicationReview()"
            [disabled]="controlsDisabled() || !persistence.canReviewPublication()"
            [title]="
              persistence.publicationBlockReason() ||
              'Review the semantic diff and publish an immutable version (does not activate the System)'
            "
            aria-label="Review and publish server draft"
          >
            <app-icon name="upload-cloud" [size]="14" />
            <span>Publish</span>
          </button>
        }
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="persistence.exportJson()"
          [disabled]="controlsDisabled()"
          title="Export flow as JSON"
          aria-label="Export flow"
        >
          <app-icon name="download" [size]="14" /><span>Export</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="importInput.click()"
          [disabled]="controlsDisabled()"
          title="Import flow JSON (round-trip)"
          aria-label="Import flow"
        >
          <app-icon name="upload" [size]="14" /><span>Import</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="persistence.shareLink()"
          [disabled]="controlsDisabled()"
          title="Copy a shareable link to this flow"
          aria-label="Share flow"
        >
          <app-icon name="link-2" [size]="14" /><span>Share</span>
        </button>
        @if (!persistence.systemId()) {
          <button
            type="button"
            class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide ck-flow-toolbar__btn--accent"
            (click)="persistence.promoteToSystem()"
            [disabled]="controlsDisabled() || persistence.promoting()"
            title="Save this scratchpad draft as a real System"
            aria-label="Save as System"
          >
            <app-icon name="rocket" [size]="14" />
            <span>{{ persistence.promoting() ? 'Saving…' : 'To System' }}</span>
          </button>
        }

        <span class="ck-flow-toolbar__sep"></span>

        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--danger"
          (click)="clear.emit()"
          [disabled]="controlsDisabled()"
          title="Clear canvas"
          aria-label="Clear canvas"
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

  readonly nodeCount = input(0);
  readonly canUndo = input(false);
  readonly canRedo = input(false);
  readonly routingLabel = input('segment');
  /** The bound System must be authoritatively hydrated before controls can
   * read or mutate its graph. Scratchpad routes explicitly bind this to true. */
  readonly hydrationReady = input(false);

  protected readonly controlsDisabled = computed(
    () => this.persistence.actionsDisabled() || !this.hydrationReady(),
  );

  readonly undo = output<void>();
  readonly redo = output<void>();
  readonly zoomIn = output<void>();
  readonly zoomOut = output<void>();
  readonly fit = output<void>();
  readonly autoLayout = output<void>();
  readonly cycleRouting = output<void>();
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

  protected stateTitle(state: SaveState): string {
    if (this.persistence.reviewRequired()) {
      return 'Review required — autosave is paused until you explicitly save or discard this replacement';
    }
    if (this.persistence.autosavePaused()) {
      return 'Autosave paused — review these changes, then press Save explicitly';
    }
    switch (state) {
      case 'saving':
        return 'Saving…';
      case 'unsaved':
        return 'Unsaved changes — autosaves, or press Ctrl/Cmd+S';
      case 'error':
        return 'Last save failed — edit again to retry';
      default:
        return 'All changes saved';
    }
  }

  protected shortHash(value: string | null): string {
    return value ? value.slice(0, 8) : '—';
  }
}
