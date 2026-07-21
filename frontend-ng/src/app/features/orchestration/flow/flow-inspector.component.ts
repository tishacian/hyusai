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
  computed,
  effect,
  inject,
  input,
  output,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { ManifestFieldsComponent } from './manifest-fields.component';
import { FlowCollectionsService } from './flow-collections.service';
import { FlowTriggerControlsComponent } from './flow-trigger-controls.component';
import { FlowTriggersPanelComponent } from './flow-triggers-panel.component';

@Component({
  selector: 'app-flow-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    A11yModule,
    RouterLink,
    GlyphComponent,
    ManifestFieldsComponent,
    FlowTriggerControlsComponent,
    FlowTriggersPanelComponent,
  ],
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

              @if (collectionsState() === 'loaded' && collectionOptions().length > 0) {
                <label class="ck-flow-field">
                  <span class="ck-flow-field__label">Collection</span>
                  <select
                    class="ck-flow-input"
                    [value]="collectionSlug(n)"
                    (change)="onCollectionSlug($event)"
                  >
                    <option value="">— Sélectionner une collection —</option>
                    @for (slug of collectionOptions(); track slug) {
                      <option [value]="slug">{{ slug }}</option>
                    }
                  </select>
                </label>
              } @else {
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
                @if (collectionsState() === 'loading') {
                  <p class="ck-flow-hint">Chargement des collections…</p>
                } @else if (collectionsState() === 'error') {
                  <p class="ck-flow-hint">
                    Collections indisponibles — saisie manuelle.
                    <button type="button" class="ck-flow-hint__btn" (click)="retryCollections()">
                      Réessayer
                    </button>
                  </p>
                } @else if (collectionsState() === 'loaded') {
                  <p class="ck-flow-hint">Aucune collection indexée — saisie manuelle.</p>
                }
              }

              <label class="ck-flow-field ck-flow-field--row">
                <input
                  type="checkbox"
                  [checked]="workspaceScoped(n)"
                  (change)="onWorkspaceScoped($event)"
                />
                <span class="ck-flow-field__label">Workspace scoped</span>
              </label>

              @if (collectionSlug(n); as slug) {
                <a class="ck-flow-action" [routerLink]="['/knowledge', slug]">
                  <ck-glyph name="layers" [size]="12" color="currentColor" />
                  Ouvrir la collection
                </a>
              } @else {
                <a class="ck-flow-action" routerLink="/knowledge">
                  <ck-glyph name="layers" [size]="12" color="currentColor" />
                  Ouvrir Knowledge
                </a>
              }
            </section>
          }

          @if (isTriggerSource(n)) {
            <section class="ck-flow-section">
              <span class="ck-flow-section__label">Déclencheur (source)</span>
              @if (isSftpTrigger(n)) {
                <a class="ck-flow-action" routerLink="/connectors/sftp">
                  <ck-glyph name="orbit" [size]="12" color="currentColor" />
                  Ouvrir le dépôt SFTP
                </a>
              }
              @if (systemId(); as sid) {
                <app-flow-trigger-controls [systemId]="sid" />
                <app-flow-triggers-panel [systemId]="sid" />
              } @else {
                <p class="ck-flow-hint">
                  Le pilotage des déclencheurs est disponible une fois le flux enregistré
                  dans un Système.
                </p>
              }
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
  private readonly collectionsSvc = inject(FlowCollectionsService);

  /** Active trigger source node types (mirror of the backend
   *  `triggers.TRIGGER_TYPE_TO_EVENT`) — the nodes that offer piloting. */
  private static readonly TRIGGER_TYPES = new Set<string>([
    'source.sftp_arrival',
    'source.deposit_promoted',
    'source.schedule',
    'source.webhook',
  ]);

  /** The System this inspector's flow is bound to (null on the scratchpad).
   *  Passed from the shell so trigger piloting can target the right System. */
  readonly systemId = input<string | null>(null);

  /** Deterministic, single-frame selection straight from the store. */
  readonly node = this.store.selectedNode;

  /** Surfaced so the inspector shows the unsaved/dirty state (Save lives in
   *  the toolbar, owned elsewhere — this is a read-only indicator). */
  readonly dirty = this.store.dirty;

  /** Live collections catalogue for the asset picker (cached, shared). */
  readonly collectionsState = this.collectionsSvc.state;

  /** Picker options: the catalogue plus the node's current slug when it isn't
   *  in the catalogue, so an existing binding is never dropped from the list. */
  readonly collectionOptions = computed<string[]>(() => {
    const list = [...this.collectionsSvc.collections()];
    const n = this.node();
    const cur = n ? this.collectionSlug(n) : '';
    if (cur && !list.includes(cur)) list.unshift(cur);
    return list;
  });

  readonly close = output<void>();

  constructor() {
    // Lazy, cached fetch: only hit the collections endpoint once an asset node
    // is actually inspected (keeps the fetch off the builder's hot path).
    effect(() => {
      const n = this.node();
      if (n && (n.kind ?? 'task') === 'asset') this.collectionsSvc.ensureLoaded();
    });
  }

  /** Retry the collections fetch after a load error (manual-entry fallback
   *  stays available meanwhile). */
  retryCollections(): void {
    this.collectionsSvc.retry();
  }

  /** True for an active trigger source node (SFTP arrival / deposit promoted). */
  isTriggerSource(n: CanonicalFlowNode): boolean {
    return (
      (n.kind ?? 'task') === 'source' &&
      FlowInspectorComponent.TRIGGER_TYPES.has(String(n.type))
    );
  }

  /** True for the SFTP arrival trigger specifically (offers the deposit link). */
  isSftpTrigger(n: CanonicalFlowNode): boolean {
    return (n.kind ?? 'task') === 'source' && String(n.type).startsWith('source.sftp');
  }

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

  // Shared by the live picker (`<select>`, fed by FlowCollectionsService) and
  // the manual-entry fallback (`<input>`, shown while the catalogue is loading,
  // empty or unavailable). Both event targets expose `.value`.
  onCollectionSlug(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.updateNodeConfig(
      id,
      'collection_slug',
      (event.target as HTMLInputElement | HTMLSelectElement).value,
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
