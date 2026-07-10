/**
 * `<app-flow-inspector>` — deterministic, store-driven node inspector.
 *
 * Rebuilt on `--ck-*` tokens + CDK A11y (focus-trap, Escape) instead of the
 * old bespoke z-index-48→70 config sheet. It is a DOCKED panel (normal flow,
 * so it reflows alongside the canvas and has zero z-index conflicts) on wide
 * screens, and a slide-over on narrow screens.
 *
 * Selection is deterministic: it reads `store.selectedNode` (a computed
 * signal), so a click/keyboard selection updates the inspector within one
 * frame. Edits write back through the store's stable API.
 *
 * EXTENSION SEAM (P2): project manifest-driven editable fields into the
 * `[flowInspectorFields]` slot. They write back via `store.updateNodeData`
 * without this component or the store changing:
 *
 *   <app-flow-inspector>
 *     <app-manifest-fields flowInspectorFields />
 *   </app-flow-inspector>
 */
import {
  ChangeDetectionStrategy,
  Component,
  inject,
  output,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { ManifestFieldsComponent } from './manifest-fields.component';

@Component({
  selector: 'app-flow-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, GlyphComponent, ManifestFieldsComponent],
  styleUrl: './flow-inspector.component.scss',
  template: `
    <aside
      class="ck-flow-inspector"
      role="complementary"
      aria-label="Node inspector"
      cdkTrapFocus
      [cdkTrapFocusAutoCapture]="false"
      (keydown.escape)="close.emit()"
    >
      <header class="ck-flow-inspector__head">
        <div class="ck-flow-inspector__heading">
          <span class="ck-flow-inspector__eyebrow">
            {{ node() ? (node()!.kind ?? 'task') : 'inspector' }}
            @if (dirty()) {
              <span class="ck-flow-inspector__dirty" title="Unsaved changes — use Save in the toolbar">
                <ck-glyph name="pulse" [size]="11" color="currentColor" />
                Unsaved
              </span>
            }
          </span>
          <h2 class="ck-flow-inspector__title">
            {{ node()?.label || node()?.type || 'No node selected' }}
          </h2>
        </div>
        <button
          type="button"
          class="ck-flow-inspector__close"
          (click)="close.emit()"
          aria-label="Close inspector"
          title="Close (Esc)"
        >
          <ck-glyph name="x" [size]="13" color="currentColor" />
        </button>
      </header>

      <div class="ck-flow-inspector__body">
        @if (node(); as n) {
          <section class="ck-flow-section">
            <span class="ck-flow-section__label">Identity</span>
            <dl class="ck-flow-kv">
              <dt>ID</dt>
              <dd class="mono">{{ n.id }}</dd>
              <dt>Type</dt>
              <dd>{{ n.type }}</dd>
              <dt>Kind</dt>
              <dd>{{ n.kind ?? 'task' }}</dd>
            </dl>
          </section>

          <section class="ck-flow-section">
            <label class="ck-flow-field">
              <span class="ck-flow-field__label">Label</span>
              <input
                class="ck-flow-input"
                type="text"
                [value]="n.label ?? ''"
                (input)="onLabel($event)"
                placeholder="Node label"
              />
            </label>
            <label class="ck-flow-field">
              <span class="ck-flow-field__label">Description</span>
              <textarea
                class="ck-flow-input ck-flow-input--area"
                rows="3"
                [value]="description(n)"
                (input)="onDescription($event)"
                placeholder="What this node does"
              ></textarea>
            </label>
          </section>

          @if ((n.inputs?.length ?? 0) > 0 || (n.outputs?.length ?? 0) > 0) {
            <section class="ck-flow-section">
              <span class="ck-flow-section__label">Ports</span>
              <div class="ck-flow-ports">
                @for (p of n.inputs ?? []; track p.name) {
                  <span class="ck-flow-chip ck-flow-chip--in">
                    {{ p.name }} · {{ p.schema }}
                  </span>
                }
                @for (p of n.outputs ?? []; track p.name) {
                  <span class="ck-flow-chip ck-flow-chip--out">
                    {{ p.name }} · {{ p.schema }}
                  </span>
                }
              </div>
            </section>
          }

          @if ((n.kind ?? 'task') === 'asset') {
            <section class="ck-flow-section">
              <span class="ck-flow-section__label">Collection asset</span>
              <label class="ck-flow-field">
                <span class="ck-flow-field__label">Collection slug</span>
                <input
                  class="ck-flow-input"
                  type="text"
                  [value]="collectionSlug(n)"
                  (input)="onCollectionSlug($event)"
                  placeholder="my-collection-slug"
                />
              </label>
              <label class="ck-flow-field ck-flow-field--row">
                <input
                  type="checkbox"
                  [checked]="workspaceScoped(n)"
                  (change)="onWorkspaceScoped($event)"
                />
                <span class="ck-flow-field__label">Workspace scoped</span>
              </label>
            </section>
          }

          <!-- P2: manifest-driven editable fields (write back to the exact
               runtime_read_path via the store's dotted-path writers). -->
          <app-manifest-fields />

          <!-- Kept seam for any further inspector extensions. -->
          <ng-content select="[flowInspectorFields]" />
        } @else {
          <div class="ck-flow-empty">
            <ck-glyph name="crosshair" [size]="18" color="currentColor" />
            <p>Select a node on the canvas to inspect and edit it.</p>
          </div>
        }
      </div>
    </aside>
  `,
})
export class FlowInspectorComponent {
  private readonly store = inject(FlowStore);

  /** Deterministic, single-frame selection straight from the store. */
  readonly node = this.store.selectedNode;

  /** Surfaced so the inspector shows the unsaved/dirty state (Save lives in
   *  the toolbar, owned elsewhere — this is a read-only indicator). */
  readonly dirty = this.store.dirty;

  readonly close = output<void>();

  description(n: { data?: Record<string, unknown> }): string {
    const d = n.data?.['description'];
    return typeof d === 'string' ? d : '';
  }

  /** Current `collection_slug` from an asset node's config (empty if unset). */
  collectionSlug(n: CanonicalFlowNode): string {
    const v = (n.config as Record<string, unknown> | undefined)?.['collection_slug'];
    return typeof v === 'string' ? v : '';
  }

  /** Current `workspace_scoped` flag; defaults to true (the palette seed). */
  workspaceScoped(n: CanonicalFlowNode): boolean {
    const v = (n.config as Record<string, unknown> | undefined)?.['workspace_scoped'];
    return v !== false;
  }

  // ponytail: plain text input for the collection slug. A live picker fed by
  // GET /documents/collections can replace this once a shared collections
  // catalog service exists — Phase 1 keeps it declarative to avoid coupling
  // the inspector to an HTTP fetch + loading state.
  onCollectionSlug(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(
      id,
      'collection_slug',
      (event.target as HTMLInputElement).value,
    );
  }

  onWorkspaceScoped(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(
      id,
      'workspace_scoped',
      (event.target as HTMLInputElement).checked,
    );
  }

  onLabel(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.patchNode(id, { label: (event.target as HTMLInputElement).value });
  }

  onDescription(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeData(
      id,
      'description',
      (event.target as HTMLTextAreaElement).value,
    );
  }
}
