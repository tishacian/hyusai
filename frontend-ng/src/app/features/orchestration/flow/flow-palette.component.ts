/**
 * `<app-flow-palette>` — the PALETTE HOST boundary.
 *
 * The palette answers "what goes here", not "what exists". Three surfaces,
 * one row shape, one search field:
 *
 *   - **Contextual** (`[context]`): extending from a node offers only what
 *     type-checks against the originating port, ranked. `No type-compatible
 *     node` is the empty case, and "show everything" is one click away.
 *   - **Search** — the shell command-palette motif (ranked, ↑/↓/↵), which on
 *     79-plus entries beats scrolling a 232 px column.
 *   - **Browse**, in the canonical layer order: Capabilities first (layer 1),
 *     the Skills of one Capability on drill-in, the whole registry under
 *     Advanced (layer 3) with its sections collapsed.
 *
 * Entries this workspace cannot use are never droppable; they exist so an
 * empty result can state the rule that excluded them.
 *
 * It still only emits `add`; the builder shell calls `store.addNode` with
 * `paletteItemToNode(item)`, which materializes the binding. The
 * `[flowPaletteExtra]` content seam is preserved for future projection.
 */
import { NgTemplateOutlet } from '@angular/common';
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
import { RouterLink } from '@angular/router';
import { agentiumSurfaceRoute } from '@app/core/navigation.catalog';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowCatalogService } from './flow-catalog.service';
import { isPaletteItemConnectable } from './flow-preconnect';
import {
  buildCapabilityGroups,
  buildSkillPaletteSections,
  explainVisibilityReason,
  mostUsedItems,
  paletteItemDetail,
  paletteItemSlug,
  paletteItemUsage,
  searchPaletteItems,
  summariseUnavailable,
  type PaletteCapabilityGroup,
  type PaletteInsertContext,
} from './flow-palette.vm';
import type { PaletteItem, SkillPaletteSection } from './flow.types';

/** Ranked lists stay short on purpose: past this, refining the query is
 * faster than reading further. The remainder is announced, never hidden. */
const RANKED_LIMIT = 12;
const MOST_USED_LIMIT = 5;

@Component({
  selector: 'app-flow-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NgTemplateOutlet, RouterLink],
  styleUrl: './flow-palette.component.scss',
  template: `
    <ng-template #row let-item let-active="active">
      <button
        type="button"
        class="ck-flow-palette__row"
        [class.is-active]="active"
        [class.is-unavailable]="!!item.unavailableReason"
        [attr.data-tone]="item.tone"
        [disabled]="!!item.unavailableReason"
        [title]="detail(item)"
        (click)="onPick(item)"
      >
        <app-icon class="ck-flow-palette__row-icon" [name]="item.icon" [size]="13" />
        <span class="ck-flow-palette__row-name">{{ item.label }}</span>
        <span class="ck-flow-palette__row-intent">{{ intent(item) }}</span>
        @if (isInFlow(item)) {
          <span class="ck-flow-palette__row-flag" title="Already used in this Flow">in flow</span>
        }
        @if (usage(item); as calls) {
          <span
            class="ck-flow-palette__row-usage"
            [attr.aria-label]="calls + ' runs in this workspace'"
            >{{ calls }}</span
          >
        }
        @if (hazard(item); as status) {
          <span
            class="ck-flow-palette__row-dot"
            [attr.data-status]="status"
            [attr.aria-label]="'Runtime ' + status"
          ></span>
        }
      </button>
    </ng-template>

    <aside class="ck-flow-palette" role="group" aria-label="Node palette">
      <div class="ck-flow-palette__heading">
        <h3 class="ck-flow-palette__label">
          <app-icon name="boxes" set="phosphor" [size]="12" /> {{ headingLabel() }}
        </h3>
        <span class="ck-flow-palette__count" [attr.aria-label]="headingLabel() + ' count'">
          {{ headingCount() }}
        </span>
      </div>

      @if (context(); as ctx) {
        <div class="ck-flow-palette__context" role="status">
          <span>
            Connects to <strong>{{ ctx.originLabel }}</strong>
            @if (ctx.originPort) {
              · <code>{{ ctx.originPort }}</code>
            }
            @if (ctx.schema) {
              (<code>{{ ctx.schema }}</code>)
            }
          </span>
          <button type="button" (click)="clearContext.emit()">Show all</button>
        </div>
      }

      <label class="ck-flow-palette__search">
        <app-icon name="search" [size]="12" />
        <input
          type="search"
          class="ck-flow-palette__search-input"
          [placeholder]="searchPlaceholder()"
          [attr.aria-label]="searchPlaceholder()"
          [value]="query()"
          (input)="onQuery($event)"
          (keydown)="onSearchKey($event)"
        />
      </label>

      @if (catalog.state() === 'loading') {
        <p class="ck-flow-palette__empty" role="status">Loading skill catalog…</p>
      } @else if (catalog.state() === 'error') {
        <div class="ck-flow-palette__catalog-error" role="alert">
          <span>Skill catalog unavailable.</span>
          <button type="button" (click)="catalog.retry()">Retry</button>
        </div>
      } @else {
        <div class="ck-flow-palette__body">
          @if (rankedMode()) {
            @for (item of rankedItems(); track itemKey(item); let i = $index) {
              <ng-container
                *ngTemplateOutlet="row; context: { $implicit: item, active: i === activeIndex() }"
              />
            } @empty {
              <p class="ck-flow-palette__empty" role="status">{{ rankedEmptyMessage() }}</p>
              @if (context()) {
                <button type="button" class="ck-flow-palette__link" (click)="clearContext.emit()">
                  Show every node
                </button>
              }
            }
            @if (rankedOverflow() > 0) {
              <p class="ck-flow-palette__more">
                {{ rankedOverflow() }} more — refine the search to narrow it.
              </p>
            }
            @if (query() && unavailableMatches().length > 0) {
              <div class="ck-flow-palette__hatch">
                <p class="ck-flow-palette__hatch-why">
                  {{ unavailableMatches().length }} registry
                  {{ unavailableMatches().length === 1 ? 'skill matches' : 'skills match' }}
                  but {{ unavailableMatches().length === 1 ? 'is' : 'are' }} not available in this
                  workspace.
                </p>
                @for (item of unavailableMatches().slice(0, 5); track itemKey(item)) {
                  <ng-container *ngTemplateOutlet="row; context: { $implicit: item }" />
                }
                <a class="ck-flow-palette__link" [routerLink]="curationRoute">
                  Adjust catalog visibility
                </a>
              </div>
            }
          } @else if (openGroup(); as group) {
            <button type="button" class="ck-flow-palette__back" (click)="closeCapability()">
              <app-icon name="chevron-left" [size]="11" /> Capabilities
            </button>
            @if (group.hint) {
              <p class="ck-flow-palette__group-hint">{{ group.hint }}</p>
            }
            @for (item of group.items; track itemKey(item)) {
              <ng-container *ngTemplateOutlet="row; context: { $implicit: item }" />
            }
          } @else if (level() === 'advanced') {
            <button type="button" class="ck-flow-palette__back" (click)="level.set('capabilities')">
              <app-icon name="chevron-left" [size]="11" /> Capabilities
            </button>
            @for (section of categorySections(); track section.category) {
              <h4 class="ck-flow-palette__section-heading" [id]="sectionHeadingId(section.category)">
                <button
                  type="button"
                  class="ck-flow-palette__section-toggle"
                  [attr.aria-expanded]="isSectionExpanded(section.category)"
                  [attr.aria-controls]="sectionPanelId(section.category)"
                  (click)="toggleSection(section.category)"
                >
                  <app-icon
                    [name]="
                      isSectionExpanded(section.category) ? 'chevron-down' : 'chevron-right'
                    "
                    [size]="11"
                  />
                  <span>{{ section.category }}</span>
                  <span class="ck-flow-palette__count">{{ section.items.length }}</span>
                </button>
              </h4>
              @if (isSectionExpanded(section.category)) {
                <div
                  class="ck-flow-palette__list"
                  role="region"
                  [id]="sectionPanelId(section.category)"
                  [attr.aria-labelledby]="sectionHeadingId(section.category)"
                >
                  @for (item of section.items; track itemKey(item)) {
                    <ng-container *ngTemplateOutlet="row; context: { $implicit: item }" />
                  }
                </div>
              }
            } @empty {
              <p class="ck-flow-palette__empty" role="status">
                No skill is available in this workspace.
              </p>
            }
            @if (catalog.filteredItems().length > 0) {
              <div class="ck-flow-palette__hatch">
                <button
                  type="button"
                  class="ck-flow-palette__hatch-toggle"
                  [attr.aria-expanded]="showUnavailable()"
                  (click)="showUnavailable.set(!showUnavailable())"
                >
                  <app-icon
                    [name]="showUnavailable() ? 'chevron-down' : 'chevron-right'"
                    [size]="11"
                  />
                  {{ catalog.filteredItems().length }} in the registry, not available here
                </button>
                @if (showUnavailable()) {
                  <p class="ck-flow-palette__hatch-why">{{ unavailableExplanation() }}</p>
                  @for (item of catalog.filteredItems(); track itemKey(item)) {
                    <ng-container *ngTemplateOutlet="row; context: { $implicit: item }" />
                  }
                  <a class="ck-flow-palette__link" [routerLink]="curationRoute">
                    Adjust catalog visibility
                  </a>
                }
              </div>
            }
          } @else {
            @if (mostUsed().length > 0) {
              <h4 class="ck-flow-palette__section-heading ck-flow-palette__section-heading--plain">
                Used in this workspace
              </h4>
              @for (item of mostUsed(); track itemKey(item)) {
                <ng-container *ngTemplateOutlet="row; context: { $implicit: item }" />
              }
            }

            <h4 class="ck-flow-palette__section-heading ck-flow-palette__section-heading--plain">
              Capabilities
            </h4>
            @for (group of capabilityGroups(); track group.slug) {
              <button
                type="button"
                class="ck-flow-palette__row ck-flow-palette__row--group"
                [title]="group.hint || group.name"
                (click)="openCapability(group.slug)"
              >
                <app-icon class="ck-flow-palette__row-icon" name="boxes" set="phosphor" [size]="13" />
                <span class="ck-flow-palette__row-name">{{ group.name }}</span>
                <span class="ck-flow-palette__row-intent">{{ group.hint }}</span>
                <span class="ck-flow-palette__count">{{ group.items.length }}</span>
                <app-icon name="chevron-right" [size]="11" />
              </button>
            } @empty {
              <p class="ck-flow-palette__empty" role="status">
                No capability carries a skill in this workspace.
              </p>
            }

            <h4 class="ck-flow-palette__section-heading">
              <button
                type="button"
                class="ck-flow-palette__section-toggle"
                [attr.aria-expanded]="structureExpanded()"
                aria-controls="flow-palette-structure-panel"
                (click)="toggleStructure()"
              >
                <app-icon
                  [name]="structureExpanded() ? 'chevron-down' : 'chevron-right'"
                  [size]="11"
                />
                <span>Structure</span>
                <span class="ck-flow-palette__count">{{ items().length }}</span>
              </button>
            </h4>
            @if (structureExpanded()) {
              <div class="ck-flow-palette__list" id="flow-palette-structure-panel">
                @for (item of items(); track item.type) {
                  <ng-container *ngTemplateOutlet="row; context: { $implicit: item }" />
                }
              </div>
            }

            <button
              type="button"
              class="ck-flow-palette__advanced"
              (click)="level.set('advanced')"
            >
              <span>Advanced — the whole registry</span>
              <span class="ck-flow-palette__count">{{ catalog.skillItems().length }}</span>
            </button>
          }
        </div>
      }

      <!-- P3 SEAM: extra groups may still project here. -->
      <ng-content select="[flowPaletteExtra]" />
    </aside>
  `,
})
export class FlowPaletteComponent {
  protected readonly catalog = inject(FlowCatalogService);

  /** Structural primitives, supplied by the shell (`DEFAULT_PALETTE`). */
  readonly items = input<PaletteItem[]>([]);
  /** Set while an insertion extends an existing node: the palette then offers
   * only entries that connect, and the shell wires the edge on add. */
  readonly context = input<PaletteInsertContext | null>(null);
  /** Skill slugs already bound in the open Flow — the "used in this flow"
   * half of the usage signal. */
  readonly flowSkillSlugs = input<readonly string[]>([]);
  /** An empty graph has exactly one sensible next move, so the structural
   * primitives open themselves rather than hiding behind a disclosure. */
  readonly nodeCount = input(0);

  readonly add = output<PaletteItem>();
  readonly clearContext = output<void>();

  protected readonly curationRoute = `${agentiumSurfaceRoute('capabilities')}/curation`;

  protected readonly query = signal('');
  protected readonly level = signal<'capabilities' | 'advanced'>('capabilities');
  protected readonly activeIndex = signal(0);
  protected readonly showUnavailable = signal(false);
  private readonly openCapabilitySlug = signal<string | null>(null);
  private readonly structureOverride = signal<boolean | null>(null);
  private readonly expandedSections = signal<ReadonlySet<SkillPaletteSection>>(new Set());

  /** Primitives and Skills are one searchable catalog: a Decision and a
   * summariser are both answers to "what goes here". */
  private readonly allItems = computed<PaletteItem[]>(() => [
    ...this.items(),
    ...this.catalog.skillItems(),
  ]);

  private readonly connectable = computed<PaletteItem[]>(() => {
    const ctx = this.context();
    if (!ctx) return this.allItems();
    return this.allItems().filter((item) =>
      isPaletteItemConnectable(item, ctx.side, ctx.schema),
    );
  });

  /** Both the contextual surface and a query produce one ranked list. */
  protected readonly rankedMode = computed(() => !!this.context() || !!this.query().trim());

  private readonly ranked = computed<PaletteItem[]>(() => {
    const query = this.query().trim();
    const pool = this.connectable();
    if (!query) return [...pool].sort(this.byRelevance);
    return searchPaletteItems(pool, query);
  });

  protected readonly rankedItems = computed(() => this.ranked().slice(0, RANKED_LIMIT));
  protected readonly rankedOverflow = computed(() =>
    Math.max(0, this.ranked().length - RANKED_LIMIT),
  );

  /** Registry rows matching the query that this workspace cannot use. The
   * reason travels with the row, so a dead end explains itself. */
  protected readonly unavailableMatches = computed<PaletteItem[]>(() => {
    const query = this.query().trim();
    if (!query) return [];
    return searchPaletteItems(this.catalog.filteredItems(), query);
  });

  protected readonly capabilityGroups = computed<PaletteCapabilityGroup[]>(() =>
    buildCapabilityGroups(this.catalog.skillItems(), this.catalog.capabilities()),
  );

  protected readonly openGroup = computed<PaletteCapabilityGroup | null>(() => {
    if (this.rankedMode()) return null;
    const slug = this.openCapabilitySlug();
    if (!slug) return null;
    return this.capabilityGroups().find((group) => group.slug === slug) ?? null;
  });

  protected readonly categorySections = computed(() =>
    buildSkillPaletteSections(this.catalog.skillItems()),
  );

  protected readonly mostUsed = computed(() =>
    mostUsedItems(this.catalog.skillItems(), MOST_USED_LIMIT),
  );

  private readonly flowSlugs = computed(() => new Set(this.flowSkillSlugs()));

  constructor() {
    // Any change of surface re-anchors keyboard selection to the first row.
    effect(() => {
      this.rankedItems();
      this.activeIndex.set(0);
    });
  }

  protected headingLabel(): string {
    if (this.context()) return 'Connects here';
    if (this.query().trim()) return 'Matches';
    const group = this.openGroup();
    if (group) return group.name;
    return this.level() === 'advanced' ? 'All skills' : 'Add node';
  }

  protected headingCount(): string {
    if (this.rankedMode()) return String(this.ranked().length);
    const group = this.openGroup();
    if (group) return String(group.items.length);
    return this.level() === 'advanced'
      ? String(this.catalog.skillItems().length)
      : String(this.capabilityGroups().length);
  }

  protected searchPlaceholder(): string {
    return this.context() ? 'Search what connects here…' : 'Search or describe a step…';
  }

  protected rankedEmptyMessage(): string {
    if (this.context()) return 'No type-compatible node.';
    return `Nothing available matches “${this.query()}”.`;
  }

  protected unavailableExplanation(): string {
    const summary = summariseUnavailable(
      this.catalog.filteredItems(),
      this.catalog.summary().industriesConfigured,
    );
    return summary ? `${summary}.` : '';
  }

  protected onQuery(event: Event): void {
    this.query.set((event.target as HTMLInputElement).value);
  }

  protected onSearchKey(event: KeyboardEvent): void {
    if (!this.rankedMode()) return;
    const items = this.rankedItems();
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.activeIndex.update((index) => Math.min(items.length - 1, index + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.activeIndex.update((index) => Math.max(0, index - 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const item = items[this.activeIndex()];
      if (item) this.onPick(item);
    } else if (event.key === 'Escape' && this.query()) {
      event.preventDefault();
      this.query.set('');
    }
  }

  protected onPick(item: PaletteItem): void {
    if (item.unavailableReason) return;
    this.add.emit(item);
  }

  protected openCapability(slug: string): void {
    this.openCapabilitySlug.set(slug);
  }

  protected closeCapability(): void {
    this.openCapabilitySlug.set(null);
  }

  protected structureExpanded(): boolean {
    return this.structureOverride() ?? this.nodeCount() === 0;
  }

  protected toggleStructure(): void {
    this.structureOverride.set(!this.structureExpanded());
  }

  /** Collapsed by default: nine expanded sections is the inventory the palette
   * stopped being. */
  protected isSectionExpanded(category: SkillPaletteSection): boolean {
    return this.expandedSections().has(category);
  }

  protected toggleSection(category: SkillPaletteSection): void {
    this.expandedSections.update((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  protected sectionHeadingId(category: SkillPaletteSection): string {
    return `flow-palette-${category.toLowerCase().replace(/\s+/g, '-')}-heading`;
  }

  protected sectionPanelId(category: SkillPaletteSection): string {
    return `flow-palette-${category.toLowerCase().replace(/\s+/g, '-')}-panel`;
  }

  protected itemKey(item: PaletteItem): string {
    return `${item.type}:${paletteItemSlug(item)}`;
  }

  protected detail(item: PaletteItem): string {
    return paletteItemDetail(item);
  }

  /** One line: name plus intention. An unusable row states its lever instead. */
  protected intent(item: PaletteItem): string {
    if (item.unavailableReason) {
      return explainVisibilityReason(
        item.unavailableReason,
        item.unavailableKey,
        this.catalog.summary().industriesConfigured,
      );
    }
    const slug = paletteItemSlug(item);
    return item.description && item.description !== slug ? item.description : '';
  }

  protected isInFlow(item: PaletteItem): boolean {
    const slug = item.config?.['skill_slug'];
    return typeof slug === 'string' && this.flowSlugs().has(slug);
  }

  protected usage(item: PaletteItem): number {
    return paletteItemUsage(item);
  }

  /** A dot only when the runtime state is a trap. Silence means bound. */
  protected hazard(item: PaletteItem): string | null {
    const status = item.runtimeStatus;
    return status && status !== 'bound' ? status.replace(/_/g, ' ') : null;
  }

  private readonly byRelevance = (a: PaletteItem, b: PaletteItem): number =>
    paletteItemUsage(b) - paletteItemUsage(a) || a.label.localeCompare(b.label);
}
