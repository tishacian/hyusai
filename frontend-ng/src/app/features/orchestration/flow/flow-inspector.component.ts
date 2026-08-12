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
  signal,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit/glyph.component';
import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService } from '@app/core/i18n.service';
import type {
  CanonicalFlowNode,
  DecisionNodeConfig,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import { FlowPersistenceService } from './flow-persistence.service';
import { ManifestFieldsComponent } from './manifest-fields.component';
import {
  FlowCollectionsService,
  type FlowDocumentOption,
} from './flow-collections.service';
import { FlowTriggerControlsComponent } from './flow-trigger-controls.component';
import { FlowTriggersPanelComponent } from './flow-triggers-panel.component';
import { FlowIngressEditorComponent } from './flow-ingress-editor.component';
import { FlowDecisionBindingsComponent } from './flow-decision-bindings.component';
import { FlowSchemaEditorComponent } from './flow-schema-editor.component';

/** Engine kind of the node the lexicon calls an Output. */
const OUTPUT_NODE_KIND = 'sink';

export interface RetrievalDocumentRef {
  collection_slug: string;
  document_id: string;
}

export interface RetrievalDocumentOption extends FlowDocumentOption {
  collection: string;
  key: string;
  catalogued: boolean;
}

/** Preserve saved scopes even when their collection is absent from the live
 * catalogue (deleted, unavailable, or tenant catalogue temporarily stale). */
export function buildCollectionOptions(
  catalogued: readonly string[],
  persisted: readonly string[],
): string[] {
  const catalog = [...new Set(catalogued.map((value) => value.trim()).filter(Boolean))];
  const missing = [...new Set(persisted.map((value) => value.trim()).filter(Boolean))]
    .filter((value) => !catalog.includes(value));
  return [...missing, ...catalog];
}

/** Merge the bounded live catalogue with persisted refs. A saved ref may sit
 * beyond the endpoint's first 1000 rows (or reference a temporarily missing
 * document); keeping it visible makes reload faithful and lets the operator
 * explicitly deselect it instead of silently carrying hidden configuration. */
export function buildRetrievalDocumentOptions(
  collections: readonly string[],
  documentsFor: (collection: string) => readonly FlowDocumentOption[],
  persistedRefs: readonly RetrievalDocumentRef[],
): RetrievalDocumentOption[] {
  const options = new Map<string, RetrievalDocumentOption>();
  for (const collection of collections) {
    for (const document of documentsFor(collection)) {
      const key = `${collection}\u0000${document.id}`;
      options.set(key, { ...document, collection, key, catalogued: true });
    }
  }
  const allowed = new Set(collections);
  for (const ref of persistedRefs) {
    if (!allowed.has(ref.collection_slug)) continue;
    const key = `${ref.collection_slug}\u0000${ref.document_id}`;
    if (options.has(key)) continue;
    options.set(key, {
      id: ref.document_id,
      filename: ref.document_id,
      status: null,
      collection: ref.collection_slug,
      key,
      catalogued: false,
    });
  }
  return [...options.values()];
}

@Component({
  selector: 'app-flow-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    A11yModule,
    RouterLink,
    GlyphComponent,
    HelpTooltipComponent,
    EmptyStateComponent,
    ManifestFieldsComponent,
    FlowTriggerControlsComponent,
    FlowTriggersPanelComponent,
    FlowIngressEditorComponent,
    FlowDecisionBindingsComponent,
    FlowSchemaEditorComponent,
  ],
  styleUrl: './flow-inspector.component.scss',
  template: `
    <aside
      class="ck-flow-inspector"
      role="complementary"
      [attr.aria-label]="i18n.t('flow.inspector.aria')"
      cdkTrapFocus
      [cdkTrapFocusAutoCapture]="false"
      (keydown.escape)="close.emit()"
    >
      <header class="ck-flow-inspector__head">
        <div class="ck-flow-inspector__heading">
          <span class="ck-flow-inspector__eyebrow">
            {{ node() ? kindLabel(node()!.kind ?? 'task') : i18n.t('flow.inspector.aria') }}
            @if (dirty()) {
              <span
                class="ck-flow-inspector__dirty"
                [title]="i18n.t('flow.inspector.unsaved.hint')"
              >
                <ck-glyph name="pulse" [size]="11" color="currentColor" />
                {{ i18n.t('flow.inspector.unsaved') }}
              </span>
            }
          </span>
          <h2 class="ck-flow-inspector__title">
            {{ node()?.label || node()?.type || i18n.t('flow.inspector.empty.title') }}
          </h2>
        </div>
        <button
          type="button"
          class="ck-flow-inspector__close"
          (click)="close.emit()"
          [attr.aria-label]="i18n.t('flow.inspector.close.aria')"
          [title]="i18n.t('flow.inspector.close')"
        >
          <ck-glyph name="x" [size]="13" color="currentColor" />
        </button>
      </header>

      <!--
        Three registers, top to bottom: what you name (label, description),
        what you configure (the kind-specific sections, open by default), and
        what you rarely need — identity, ports, contract, deletion — folded
        into disclosures. Folded is not hidden: every field stays one click
        away, in the same place, and none was removed.
      -->
      <div class="ck-flow-inspector__body">
        @if (node(); as n) {
          <section class="ck-flow-section">
            <label class="ck-flow-field">
              <span class="ck-flow-field__label">{{ i18n.t('flow.inspector.field.label') }}</span>
              <input
                class="ck-flow-input"
                type="text"
                [value]="n.label ?? ''"
                (input)="onLabel($event)"
                [attr.placeholder]="i18n.t('flow.inspector.field.label.placeholder')"
              />
            </label>
            <label class="ck-flow-field">
              <span class="ck-flow-field__label">{{
                i18n.t('flow.inspector.field.description')
              }}</span>
              <textarea
                class="ck-flow-input ck-flow-input--area"
                rows="3"
                [value]="description(n)"
                (input)="onDescription($event)"
                [attr.placeholder]="i18n.t('flow.inspector.field.description.placeholder')"
              ></textarea>
            </label>
          </section>

          @if ((n.kind ?? 'task') === 'decision') {
            <section class="ck-flow-section ck-flow-decision">
              <div class="ck-flow-section__heading-row">
                <span class="ck-flow-section__label">
                  {{ i18n.t('flow.inspector.section.decision') }}
                  <ck-help id="concept.decision" />
                </span>
                <button
                  type="button"
                  class="ck-flow-mini-action"
                  (click)="addDecisionBranch()"
                >
                  {{ i18n.t('flow.inspector.decision.add') }}
                </button>
              </div>

              <p class="ck-flow-hint">{{ i18n.t('flow.inspector.decision.hint') }}</p>

              <div class="ck-flow-decision__branches">
                @for (branch of decisionBranches(n); track $index; let i = $index; let first = $first; let last = $last) {
                  <article class="ck-flow-decision__branch">
                    <div class="ck-flow-decision__branch-head">
                      <span class="ck-flow-decision__order">{{ i + 1 }}</span>
                      <span class="ck-flow-decision__route-count">
                        {{
                          i18n.t('flow.inspector.decision.routes', {
                            count: decisionRouteCount(n.id, branch.label),
                          })
                        }}
                      </span>
                      <div class="ck-flow-decision__branch-actions">
                        <button
                          type="button"
                          class="ck-flow-icon-action"
                          [disabled]="first"
                          (click)="moveDecisionBranch(i, -1)"
                          [attr.aria-label]="i18n.t('flow.inspector.decision.up.aria')"
                          [title]="i18n.t('flow.inspector.decision.up')"
                        >↑</button>
                        <button
                          type="button"
                          class="ck-flow-icon-action"
                          [disabled]="last"
                          (click)="moveDecisionBranch(i, 1)"
                          [attr.aria-label]="i18n.t('flow.inspector.decision.down.aria')"
                          [title]="i18n.t('flow.inspector.decision.down')"
                        >↓</button>
                        <button
                          type="button"
                          class="ck-flow-icon-action ck-flow-icon-action--danger"
                          [disabled]="decisionBranches(n).length <= 2"
                          (click)="removeDecisionBranch(i)"
                          [attr.aria-label]="i18n.t('flow.inspector.decision.remove')"
                          [title]="i18n.t('flow.inspector.decision.remove')"
                        >×</button>
                      </div>
                    </div>

                    <label class="ck-flow-field">
                      <span class="ck-flow-field__label">{{
                        i18n.t('flow.inspector.decision.route_label')
                      }}</span>
                      <input
                        class="ck-flow-input mono"
                        type="text"
                        [value]="branch.label"
                        (input)="onDecisionBranchLabel(i, $event)"
                        placeholder="branch_label"
                        spellcheck="false"
                      />
                    </label>

                    <label class="ck-flow-field">
                      <span class="ck-flow-field__label">{{
                        i18n.t('flow.inspector.decision.condition')
                      }}</span>
                      <textarea
                        class="ck-flow-input ck-flow-input--area"
                        rows="2"
                        [value]="branch.condition"
                        (input)="onDecisionCondition(i, $event)"
                        placeholder="value == True"
                        spellcheck="false"
                      ></textarea>
                    </label>
                  </article>
                }
              </div>

              <label class="ck-flow-field">
                <span class="ck-flow-field__label">{{
                  i18n.t('flow.inspector.decision.default')
                }}</span>
                <select
                  class="ck-flow-input"
                  [value]="decisionDefault(n)"
                  (change)="onDecisionDefault($event)"
                >
                  <option value="">{{ i18n.t('flow.inspector.decision.default.none') }}</option>
                  @for (branch of decisionBranches(n); track $index) {
                    <option [value]="branch.label">{{
                      branch.label || i18n.t('flow.inspector.decision.invalid_label')
                    }}</option>
                  }
                </select>
              </label>

              <app-flow-decision-bindings />
            </section>
          }

          @if ((n.kind ?? 'task') === 'asset') {
            <section class="ck-flow-section">
              <span class="ck-flow-section__label">{{
                i18n.t('flow.inspector.section.asset')
              }}</span>

              @if (collectionsState() === 'loaded' && collectionOptions().length > 0) {
                <label class="ck-flow-field">
                  <span class="ck-flow-field__label">{{
                    i18n.t('flow.inspector.asset.collection')
                  }}</span>
                  <select
                    class="ck-flow-input"
                    [value]="collectionSlug(n)"
                    (change)="onCollectionSlug($event)"
                  >
                    <option value="">{{
                      i18n.t('flow.inspector.asset.collection.none')
                    }}</option>
                    @for (slug of collectionOptions(); track slug) {
                      <option [value]="slug">{{ slug }}</option>
                    }
                  </select>
                </label>
              } @else {
                <label class="ck-flow-field">
                  <span class="ck-flow-field__label">{{
                    i18n.t('flow.inspector.asset.slug')
                  }}</span>
                  <input
                    class="ck-flow-input"
                    type="text"
                    [value]="collectionSlug(n)"
                    (input)="onCollectionSlug($event)"
                    [attr.placeholder]="i18n.t('flow.inspector.asset.slug.placeholder')"
                  />
                </label>
                @if (collectionsState() === 'loading') {
                  <p class="ck-flow-hint">{{ i18n.t('flow.inspector.asset.loading') }}</p>
                } @else if (collectionsState() === 'error') {
                  <p class="ck-flow-hint">
                    {{ i18n.t('flow.inspector.asset.error') }}
                    <button type="button" class="ck-flow-hint__btn" (click)="retryCollections()">
                      {{ i18n.t('flow.inspector.asset.retry') }}
                    </button>
                  </p>
                } @else if (collectionsState() === 'loaded') {
                  <p class="ck-flow-hint">{{ i18n.t('flow.inspector.asset.empty') }}</p>
                }
              }

              <label class="ck-flow-field ck-flow-field--row">
                <input
                  type="checkbox"
                  [checked]="workspaceScoped(n)"
                  (change)="onWorkspaceScoped($event)"
                />
                <span class="ck-flow-field__label">{{
                  i18n.t('flow.inspector.asset.workspace_scoped')
                }}</span>
              </label>

              @if (collectionSlug(n); as slug) {
                <a class="ck-flow-action" [routerLink]="['/knowledge', slug]">
                  <ck-glyph name="layers" [size]="12" color="currentColor" />
                  {{ i18n.t('flow.inspector.asset.open') }}
                </a>
              } @else {
                <a class="ck-flow-action" routerLink="/knowledge">
                  <ck-glyph name="layers" [size]="12" color="currentColor" />
                  {{ i18n.t('flow.inspector.asset.open_knowledge') }}
                </a>
              }
            </section>
          }

          @if (isRetrievalNode(n)) {
            <section class="ck-flow-section" data-testid="retrieval-scope-editor">
              <span class="ck-flow-section__label">{{
                i18n.t('flow.inspector.section.retrieval')
              }}</span>
              <p class="ck-flow-hint">{{ i18n.t('flow.inspector.retrieval.hint') }}</p>
              @if (retrievalScopeError(); as scopeError) {
                <p class="ck-flow-hint ck-flow-hint--error" role="alert">{{ scopeError }}</p>
              }

              @if (collectionsState() === 'loaded' && collectionOptions().length > 0) {
                <label class="ck-flow-field">
                  <span class="ck-flow-field__label">{{
                    i18n.t('flow.inspector.retrieval.collections')
                  }}</span>
                  <select
                    class="ck-flow-input ck-flow-input--multi"
                    multiple
                    size="5"
                    (change)="onRetrievalCollections($event)"
                    [attr.aria-label]="i18n.t('flow.inspector.retrieval.collections.aria')"
                  >
                    @for (slug of collectionOptions(); track slug) {
                      <option [value]="slug" [selected]="retrievalCollectionSelected(n, slug)">
                        {{ slug }}
                      </option>
                    }
                  </select>
                </label>
              } @else {
                <label class="ck-flow-field">
                  <span class="ck-flow-field__label">{{
                    i18n.t('flow.inspector.retrieval.slugs')
                  }}</span>
                  <textarea
                    class="ck-flow-input ck-flow-input--area"
                    rows="2"
                    [value]="retrievalCollections(n).join(', ')"
                    (change)="onRetrievalCollectionsText($event)"
                    placeholder="collection-a, collection-b"
                  ></textarea>
                </label>
              }

              @if (retrievalCollections(n).length > 0) {
                @if (retrievalDocumentsLoading()) {
                  <p class="ck-flow-hint">{{
                    i18n.t('flow.inspector.retrieval.documents.loading')
                  }}</p>
                }
                @if (retrievalDocumentsError()) {
                  <p class="ck-flow-hint">
                    {{ i18n.t('flow.inspector.retrieval.documents.error') }}
                    <button type="button" class="ck-flow-hint__btn" (click)="retryRetrievalDocuments()">
                      {{ i18n.t('flow.inspector.retrieval.documents.retry') }}
                    </button>
                  </p>
                }
                @if (retrievalDocumentOptions().length > 0) {
                  <label class="ck-flow-field">
                    <span class="ck-flow-field__label">{{
                      i18n.t('flow.inspector.retrieval.documents')
                    }}</span>
                    <select
                      class="ck-flow-input ck-flow-input--multi"
                      multiple
                      size="7"
                      (change)="onRetrievalDocuments($event)"
                      [attr.aria-label]="i18n.t('flow.inspector.retrieval.documents.aria')"
                    >
                      @for (doc of retrievalDocumentOptions(); track doc.key) {
                        <option
                          [value]="doc.key"
                          [selected]="retrievalDocumentSelected(n, doc.collection, doc.id)"
                        >
                          {{ doc.filename }} · {{ doc.collection }}
                          @if (!doc.catalogued) {
                            · {{ i18n.t('flow.inspector.retrieval.documents.stored') }}
                          }
                        </option>
                      }
                    </select>
                  </label>
                  <p class="ck-flow-hint">
                    {{ i18n.t('flow.inspector.retrieval.documents.all') }}
                    @if (retrievalDocumentsTruncated()) {
                      {{ i18n.t('flow.inspector.retrieval.documents.more') }}
                      <button
                        type="button"
                        class="ck-flow-hint__btn"
                        [disabled]="retrievalDocumentsLoading()"
                        (click)="loadMoreRetrievalDocuments()"
                      >
                        {{ i18n.t('flow.inspector.retrieval.documents.load_more') }}
                      </button>
                    }
                  </p>
                } @else if (!retrievalDocumentsLoading() && !retrievalDocumentsError()) {
                  <p class="ck-flow-hint">{{
                    i18n.t('flow.inspector.retrieval.documents.empty')
                  }}</p>
                }
              } @else {
                <p class="ck-flow-hint">{{ i18n.t('flow.inspector.retrieval.no_scope') }}</p>
              }
            </section>
          }

          @if ((n.kind ?? 'task') === 'source') {
            <section class="ck-flow-section">
              <span class="ck-flow-section__label">
                {{ i18n.t('flow.inspector.section.entry') }}
                <ck-help id="concept.entry-point" />
              </span>
              <app-flow-ingress-editor [systemId]="systemId()" />
            </section>
          }

          @if (isTriggerSource(n)) {
            <section class="ck-flow-section">
              <span class="ck-flow-section__label">
                {{ i18n.t('flow.inspector.section.trigger') }}
                <ck-help id="concept.trigger" />
              </span>
              @if (isSftpTrigger(n)) {
                <a class="ck-flow-action" routerLink="/connectors/sftp">
                  <ck-glyph name="orbit" [size]="12" color="currentColor" />
                  {{ i18n.t('flow.inspector.trigger.sftp') }}
                </a>
              }
              @if (systemId(); as sid) {
                <app-flow-trigger-controls [systemId]="sid" />
                <app-flow-triggers-panel [systemId]="sid" />
              } @else {
                <p class="ck-flow-hint">{{ i18n.t('flow.inspector.trigger.unavailable') }}</p>
              }
            </section>
          }

          <!-- P2: manifest-driven editable fields (write back to the exact
               runtime_read_path via the store's dotted-path writers). -->
          <app-manifest-fields />

          <!-- Kept seam for any further inspector extensions. -->
          <ng-content select="[flowInspectorFields]" />

          <!-- Folded tail: the published contract, the port shapes, the engine
               identifiers and the deletion. Each is a native disclosure —
               closed on arrival, one click from the same content as before. -->
          @if (declaresOutputContract(n)) {
            <details class="ck-flow-section ck-flow-fold">
              <summary class="ck-flow-fold__summary">
                {{ i18n.t('flow.inspector.section.output_contract') }}
              </summary>
              <ck-help id="concept.output" />
              <app-flow-schema-editor
                configKey="output_schema"
                [label]="i18n.t('flow.inspector.output_contract.label')"
                [deriveFrom]="outputContractDeriveFrom(n)"
                [hint]="outputContractHint(n)"
                [fallbackHint]="outputContractFallback(n)"
              />
            </details>
          }

          @if ((n.inputs?.length ?? 0) > 0 || (n.outputs?.length ?? 0) > 0) {
            <details class="ck-flow-section ck-flow-fold">
              <summary class="ck-flow-fold__summary">
                {{ i18n.t('flow.inspector.section.ports') }}
              </summary>
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
            </details>
          }

          <details class="ck-flow-section ck-flow-fold">
            <summary class="ck-flow-fold__summary">
              {{ i18n.t('flow.inspector.section.identity') }}
            </summary>
            <p class="ck-flow-hint">{{ i18n.t('flow.inspector.section.identity.hint') }}</p>
            <dl class="ck-flow-kv">
              <dt>{{ i18n.t('flow.inspector.identity.id') }}</dt>
              <dd class="mono">{{ n.id }}</dd>
              <dt>{{ i18n.t('flow.inspector.identity.type') }}</dt>
              <dd class="mono">{{ n.type }}</dd>
              <dt>{{ i18n.t('flow.inspector.identity.kind') }}</dt>
              <dd class="mono">{{ n.kind ?? 'task' }}</dd>
            </dl>
          </details>

          <details class="ck-flow-section ck-flow-fold ck-flow-danger">
            <summary class="ck-flow-fold__summary">
              {{ i18n.t('flow.inspector.section.danger') }}
            </summary>
            <button
              type="button"
              class="ck-flow-danger__btn"
              [disabled]="editingLocked()"
              (click)="deleteNode()"
              [attr.aria-label]="i18n.t('flow.inspector.danger.delete.aria')"
              aria-keyshortcuts="Delete Backspace"
              [title]="i18n.t('flow.inspector.danger.delete.hint')"
            >
              {{ i18n.t('flow.inspector.danger.delete') }}
            </button>
            <p class="ck-flow-hint">
              {{ i18n.t('flow.inspector.danger.body', { name: n.label || n.id }) }}
            </p>
          </details>
        } @else {
          <div class="ck-flow-empty">
            <app-empty-state
              icon="crosshair"
              size="sm"
              [title]="i18n.t('flow.inspector.empty.title')"
              [description]="i18n.t('flow.inspector.empty.body')"
            />
          </div>
        }
      </div>
    </aside>
  `,
})
export class FlowInspectorComponent {
  private readonly store = inject(FlowStore);
  private readonly collectionsSvc = inject(FlowCollectionsService);
  readonly i18n = inject(I18nService);
  /** Optional: present whenever the inspector renders inside the builder shell. */
  private readonly persistence = inject(FlowPersistenceService, { optional: true });

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

  /** Same gate the node card and the keyboard shortcut use. */
  readonly editingLocked = computed(() => this.persistence?.actionsDisabled() ?? false);

  /** Live collections catalogue for the asset picker (cached, shared). */
  readonly collectionsState = this.collectionsSvc.state;

  /** Picker options: the catalogue plus the node's current slug when it isn't
   *  in the catalogue, so an existing binding is never dropped from the list. */
  readonly collectionOptions = computed<string[]>(() => {
    const n = this.node();
    const persisted = !n
      ? []
      : this.isRetrievalNode(n)
        ? this.retrievalCollections(n)
        : [this.collectionSlug(n)];
    return buildCollectionOptions(this.collectionsSvc.collections(), persisted);
  });

  readonly retrievalDocumentOptions = computed(() => {
    const node = this.node();
    if (!node) return [];
    return buildRetrievalDocumentOptions(
      this.retrievalCollections(node),
      (collection) => this.collectionsSvc.documentsFor(collection),
      this.retrievalDocumentRefs(node),
    );
  });

  readonly retrievalDocumentsLoading = computed(() => {
    const node = this.node();
    return !!node && this.retrievalCollections(node).some(
      (slug) => this.collectionsSvc.documentStates()[slug] === 'loading',
    );
  });

  readonly retrievalDocumentsError = computed(() => {
    const node = this.node();
    return !!node && this.retrievalCollections(node).some(
      (slug) => this.collectionsSvc.documentStates()[slug] === 'error',
    );
  });

  readonly retrievalDocumentsTruncated = computed(() => {
    const node = this.node();
    return !!node && this.retrievalCollections(node).some(
      (slug) => this.collectionsSvc.documentHasMore()[slug] === true,
    );
  });
  readonly retrievalScopeError = signal<string | null>(null);
  private lastRetrievalScopeNodeId: string | null = null;

  readonly close = output<void>();

  constructor() {
    effect(() => {
      const selectedId = this.store.selectedNodeId();
      if (selectedId === this.lastRetrievalScopeNodeId) return;
      this.lastRetrievalScopeNodeId = selectedId;
      this.retrievalScopeError.set(null);
    });
    // Lazy, cached fetch: only hit the collections endpoint once an asset node
    // is actually inspected (keeps the fetch off the builder's hot path).
    effect(() => {
      const n = this.node();
      if (!n) return;
      if ((n.kind ?? 'task') === 'asset' || this.isRetrievalNode(n)) {
        this.collectionsSvc.ensureLoaded();
      }
      if (this.isRetrievalNode(n)) {
        for (const slug of this.retrievalCollections(n)) {
          this.collectionsSvc.ensureDocumentsLoaded(slug);
        }
      }
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

  /** Nodes whose published output schema is authored rather than derived.
   *  Retry and Loop are excluded: their contract output is the control
   *  envelope produced by the adapter, and publication rejects an override. */
  declaresOutputContract(n: CanonicalFlowNode): boolean {
    const kind = n.kind ?? 'task';
    return kind === 'task' || kind === OUTPUT_NODE_KIND;
  }

  /**
   * Engine node kinds are API values, so the label is looked up at runtime and
   * falls back to the raw kind for anything the dictionary does not name yet.
   */
  kindLabel(kind: string): string {
    const key = `flow.node.kind.${kind}`;
    const label = this.i18n.t(key);
    return label === key ? kind : label;
  }

  /** An Output node publishes what it consumes; every other node, what it emits. */
  outputContractDeriveFrom(n: CanonicalFlowNode): 'inputs' | 'outputs' {
    return this.isOutputNode(n) ? 'inputs' : 'outputs';
  }

  private isOutputNode(n: CanonicalFlowNode): boolean {
    return (n.kind ?? 'task') === OUTPUT_NODE_KIND;
  }

  outputContractHint(n: CanonicalFlowNode): string {
    return this.i18n.t(
      this.isOutputNode(n)
        ? 'flow.inspector.output_contract.hint.output'
        : 'flow.inspector.output_contract.hint.task',
    );
  }

  outputContractFallback(n: CanonicalFlowNode): string {
    return this.i18n.t(
      this.isOutputNode(n)
        ? 'flow.inspector.output_contract.fallback.output'
        : 'flow.inspector.output_contract.fallback.task',
    );
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

  isRetrievalNode(n: CanonicalFlowNode): boolean {
    const config = (n.config ?? {}) as Record<string, unknown>;
    const category = typeof config['skill_category'] === 'string'
      ? config['skill_category'].trim().toLowerCase()
      : '';
    const identity = `${n.type ?? ''} ${config['skill_slug'] ?? ''}`.toLowerCase();
    return (n.kind ?? 'task') === 'task' && (
      category === 'retrieval'
      || /retriev|semantic[._ -]?search|rag[._ -]?search/.test(identity)
    );
  }

  retrievalCollections(n: CanonicalFlowNode): string[] {
    const value = ((n.config ?? {}) as Record<string, unknown>)['collection_slugs'];
    if (!Array.isArray(value)) return [];
    return [...new Set(value.map((item) => String(item ?? '').trim()).filter(Boolean))].sort();
  }

  retrievalCollectionSelected(n: CanonicalFlowNode, slug: string): boolean {
    return this.retrievalCollections(n).includes(slug);
  }

  retrievalDocumentRefs(n: CanonicalFlowNode): RetrievalDocumentRef[] {
    const value = ((n.config ?? {}) as Record<string, unknown>)['document_refs'];
    if (!Array.isArray(value)) return [];
    const refs = value.flatMap((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return [];
      const record = item as Record<string, unknown>;
      const collection_slug = String(record['collection_slug'] ?? '').trim();
      const document_id = String(record['document_id'] ?? '').trim();
      return collection_slug && document_id ? [{ collection_slug, document_id }] : [];
    });
    return refs.filter(
      (ref, index) =>
        refs.findIndex(
          (candidate) =>
            candidate.collection_slug === ref.collection_slug &&
            candidate.document_id === ref.document_id,
        ) === index,
    );
  }

  retrievalDocumentSelected(
    n: CanonicalFlowNode,
    collection: string,
    documentId: string,
  ): boolean {
    return this.retrievalDocumentRefs(n).some(
      (ref) => ref.collection_slug === collection && ref.document_id === documentId,
    );
  }

  /** Current `workspace_scoped` flag; defaults to true (the palette seed). */
  workspaceScoped(n: CanonicalFlowNode): boolean {
    const v = (n.config as Record<string, unknown> | undefined)?.['workspace_scoped'];
    return v !== false;
  }

  decisionBranches(n: CanonicalFlowNode): DecisionNodeConfig['branches'] {
    const raw = (n.config as Record<string, unknown> | undefined)?.['branches'];
    if (!Array.isArray(raw)) return [];
    return raw.map((branch) => {
      const record = branch && typeof branch === 'object' && !Array.isArray(branch)
        ? branch as Record<string, unknown>
        : {};
      return {
        label: typeof record['label'] === 'string' ? record['label'] : '',
        condition: typeof record['condition'] === 'string' ? record['condition'] : '',
      };
    });
  }

  decisionDefault(n: CanonicalFlowNode): string {
    const value = (n.config as Record<string, unknown> | undefined)?.['default_branch'];
    return typeof value === 'string' ? value : '';
  }

  decisionRouteCount(nodeId: string, label: string): number {
    return this.store.edges().filter((edge) =>
      edge.from === nodeId &&
      (edge.kind ?? 'data') === 'branch' &&
      (edge.branch_label ?? edge.label) === label
    ).length;
  }

  addDecisionBranch(): void {
    const id = this.node()?.id;
    if (id) this.store.mutateDecision(id, { type: 'add' });
  }

  onDecisionBranchLabel(index: number, event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.mutateDecision(id, {
      type: 'update',
      index,
      patch: { label: (event.target as HTMLInputElement).value },
    });
  }

  onDecisionCondition(index: number, event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    this.store.mutateDecision(id, {
      type: 'update',
      index,
      patch: { condition: (event.target as HTMLTextAreaElement).value },
    });
  }

  removeDecisionBranch(index: number): void {
    const id = this.node()?.id;
    if (id) this.store.mutateDecision(id, { type: 'remove', index });
  }

  moveDecisionBranch(index: number, direction: -1 | 1): void {
    const id = this.node()?.id;
    if (id) this.store.mutateDecision(id, { type: 'move', index, direction });
  }

  onDecisionDefault(event: Event): void {
    const id = this.node()?.id;
    if (!id) return;
    const label = (event.target as HTMLSelectElement).value;
    this.store.mutateDecision(id, {
      type: 'set_default',
      ...(label ? { label } : {}),
    });
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

  onRetrievalCollections(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.patchRetrievalCollections(
      Array.from(select.selectedOptions).map((option) => option.value),
    );
  }

  onRetrievalCollectionsText(event: Event): void {
    const value = (event.target as HTMLTextAreaElement).value;
    this.patchRetrievalCollections(value.split(/[\n,]/g));
  }

  onRetrievalDocuments(event: Event): void {
    const node = this.node();
    if (!node) return;
    const refs = Array.from((event.target as HTMLSelectElement).selectedOptions).flatMap((option) => {
      const separator = option.value.indexOf('\u0000');
      if (separator <= 0) return [];
      const collection_slug = option.value.slice(0, separator);
      const document_id = option.value.slice(separator + 1);
      return collection_slug && document_id ? [{ collection_slug, document_id }] : [];
    });
    if (refs.length > 1000) {
      this.retrievalScopeError?.set(
        this.i18n.t('flow.inspector.retrieval.error.documents'),
      );
      return;
    }
    this.retrievalScopeError?.set(null);
    this.patchRetrievalConfig(node, {
      collection_slugs: this.retrievalCollections(node),
      document_refs: refs,
    });
  }

  retryRetrievalDocuments(): void {
    const node = this.node();
    if (!node) return;
    for (const slug of this.retrievalCollections(node)) {
      this.collectionsSvc.ensureDocumentsLoaded(slug, true);
    }
  }

  loadMoreRetrievalDocuments(): void {
    const node = this.node();
    if (!node) return;
    for (const slug of this.retrievalCollections(node)) {
      if (this.collectionsSvc.documentHasMore()[slug] === true) {
        this.collectionsSvc.loadMoreDocuments(slug);
      }
    }
  }

  private patchRetrievalCollections(rawCollections: string[]): void {
    const node = this.node();
    if (!node) return;
    const collection_slugs = [...new Set(
      rawCollections.map((item) => String(item ?? '').trim()).filter(Boolean),
    )].sort();
    if (collection_slugs.length > 32) {
      this.retrievalScopeError?.set(
        this.i18n.t('flow.inspector.retrieval.error.collections'),
      );
      return;
    }
    this.retrievalScopeError?.set(null);
    const allowed = new Set(collection_slugs);
    const document_refs = this.retrievalDocumentRefs(node).filter((ref) =>
      allowed.has(ref.collection_slug),
    );
    this.patchRetrievalConfig(node, { collection_slugs, document_refs });
  }

  private patchRetrievalConfig(
    node: CanonicalFlowNode,
    scope: {
      collection_slugs: string[];
      document_refs: Array<{ collection_slug: string; document_id: string }>;
    },
  ): void {
    this.store.patchNode(node.id, {
      config: {
        ...(node.config ?? {}),
        collection_slugs: scope.collection_slugs,
        document_refs: scope.document_refs,
      },
    });
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

  /** Same store mutation as the node card's trash and the Delete/Backspace
   *  shortcut, so all three share one undo frame semantics. */
  deleteNode(): void {
    const id = this.node()?.id;
    if (!id || this.editingLocked()) return;
    this.store.removeNode(id);
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
