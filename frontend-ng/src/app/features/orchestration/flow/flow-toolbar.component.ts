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
      </div>

      <div class="ck-flow-toolbar__group">
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [disabled]="!canUndo()"
          (click)="undo.emit()"
          title="Undo (Ctrl/Cmd+Z)"
          aria-label="Undo"
        >
          <app-icon name="undo-2" [size]="14" />
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn"
          [disabled]="!canRedo()"
          (click)="redo.emit()"
          title="Redo (Ctrl/Cmd+Shift+Z)"
          aria-label="Redo"
        >
          <app-icon name="redo-2" [size]="14" />
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <button type="button" class="ck-flow-toolbar__btn" (click)="zoomIn.emit()" title="Zoom in" aria-label="Zoom in">
          <app-icon name="zoom-in" [size]="14" />
        </button>
        <button type="button" class="ck-flow-toolbar__btn" (click)="zoomOut.emit()" title="Zoom out" aria-label="Zoom out">
          <app-icon name="zoom-out" [size]="14" />
        </button>
        <button type="button" class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide" (click)="fit.emit()" title="Fit to view" aria-label="Fit to view">
          <app-icon name="maximize" [size]="14" /><span>Fit</span>
        </button>
        <button type="button" class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide" (click)="autoLayout.emit()" title="Auto-layout (Dagre)" aria-label="Auto-layout">
          <app-icon name="layout-grid" [size]="14" /><span>Layout</span>
        </button>
        <button type="button" class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide" (click)="cycleRouting.emit()" [title]="'Routing: ' + routingLabel()" aria-label="Cycle routing">
          <app-icon name="git-branch" [size]="14" /><span>{{ routingLabel() }}</span>
        </button>

        <span class="ck-flow-toolbar__sep"></span>

        <!-- P4 persistence controls — single source of truth via
             FlowPersistenceService (manual save also bound to Ctrl/Cmd+S). -->
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide ck-flow-toolbar__btn--accent"
          (click)="persistence.saveNow()"
          [disabled]="persistence.saveState() === 'saving'"
          [title]="
            persistence.systemId()
              ? 'Save flow to System (Ctrl/Cmd+S)'
              : 'Save scratchpad draft locally (Ctrl/Cmd+S)'
          "
          aria-label="Save flow"
        >
          <app-icon name="save" [size]="14" />
          <span>{{ persistence.saveState() === 'saving' ? 'Saving…' : 'Save' }}</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="persistence.exportJson()"
          title="Export flow as JSON"
          aria-label="Export flow"
        >
          <app-icon name="download" [size]="14" /><span>Export</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="importInput.click()"
          title="Import flow JSON (round-trip)"
          aria-label="Import flow"
        >
          <app-icon name="upload" [size]="14" /><span>Import</span>
        </button>
        <button
          type="button"
          class="ck-flow-toolbar__btn ck-flow-toolbar__btn--wide"
          (click)="persistence.shareLink()"
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
            [disabled]="persistence.promoting()"
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
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => this.persistence.importJson(String(reader.result));
    reader.readAsText(file);
    input.value = '';
  }

  protected stateTitle(state: SaveState): string {
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
}
