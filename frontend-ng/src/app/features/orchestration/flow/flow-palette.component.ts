/**
 * `<app-flow-palette>` — the PALETTE HOST boundary.
 *
 * P3 (dynamic-palette): the palette now sources two groups —
 *   1. **Skills** — derived at runtime from `CanonicalApiService.listSkills()`
 *      via `FlowCatalogService` (each entry carrying its full skill binding +
 *      typed params), classified into the canonical product taxonomy and
 *      searchable as one catalog.
 *   2. **Primitives** — the structural graph units passed via `[items]`
 *      (`DEFAULT_PALETTE`: source / sink / decision / fork / join / loop).
 *
 * It still only emits `add`; the builder shell calls `store.addNode` with
 * `paletteItemToNode(item)`, which materializes the binding. The
 * `[flowPaletteExtra]` content seam is preserved for future projection.
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
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowCatalogService } from './flow-catalog.service';
import {
  SKILL_PALETTE_CATEGORIES,
  type PaletteItem,
  type SkillPaletteSection,
} from './flow.types';

export interface SkillPaletteSectionView {
  category: SkillPaletteSection;
  items: PaletteItem[];
}

function paletteSkillSlug(item: PaletteItem): string {
  const slug = item.config?.['skill_slug'];
  return typeof slug === 'string' ? slug : item.type;
}

/** Global Skill search shared by the rendered palette and its unit contract. */
export function filterPaletteSkills(
  items: readonly PaletteItem[],
  query: string,
): PaletteItem[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [...items];
  return items.filter((item) =>
    [
      item.label,
      paletteSkillSlug(item),
      item.description,
      item.skillCategory ?? 'Other',
      item.runtimeStatus ?? item.badge ?? '',
    ]
      .join(' ')
      .toLowerCase()
      .includes(normalized),
  );
}

/** Always returns the six canonical sections in product order. `Other` is
 * appended only when the current result contains uncategorised Skills. */
export function buildSkillPaletteSections(
  items: readonly PaletteItem[],
): SkillPaletteSectionView[] {
  const categories: SkillPaletteSection[] = [...SKILL_PALETTE_CATEGORIES];
  if (items.some((item) => (item.skillCategory ?? 'Other') === 'Other')) {
    categories.push('Other');
  }
  return categories.map((category) => ({
    category,
    items: items.filter((item) => (item.skillCategory ?? 'Other') === category),
  }));
}

@Component({
  selector: 'app-flow-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  styleUrl: './flow-palette.component.scss',
  template: `
    <aside class="ck-flow-palette" role="group" aria-label="Node palette">
      <div class="ck-flow-palette__group">
        <div class="ck-flow-palette__heading">
          <h3 class="ck-flow-palette__label">
            <app-icon name="boxes" set="phosphor" [size]="12" /> Skills
          </h3>
          <span class="ck-flow-palette__count" aria-label="Visible skills">
            {{ skillCountLabel() }}
          </span>
        </div>

        <label class="ck-flow-palette__search">
          <app-icon name="search" [size]="12" />
          <input
            type="search"
            class="ck-flow-palette__search-input"
            placeholder="Search all skills…"
            aria-label="Search all skills"
            [value]="query()"
            (input)="onQuery($event)"
          />
        </label>

        @if (catalog.state() === 'loading') {
          <p class="ck-flow-palette__empty" role="status">Loading skill catalog…</p>
        } @else if (catalog.state() === 'error') {
          <div class="ck-flow-palette__catalog-error" role="alert">
            <span>Skill catalog unavailable.</span>
            <button type="button" (click)="catalog.retry()">Retry</button>
          </div>
        } @else if (catalog.skillItems().length === 0) {
          <p class="ck-flow-palette__empty" role="status">No skills in the catalog yet.</p>
        } @else if (filteredSkills().length === 0) {
          <p class="ck-flow-palette__empty" role="status">No skill matches “{{ query() }}”.</p>
        }

        <div class="ck-flow-palette__sections">
          @for (section of skillSections(); track section.category) {
            <section class="ck-flow-palette__section">
              <h4
                class="ck-flow-palette__section-heading"
                [id]="sectionHeadingId(section.category)"
              >
                <button
                  type="button"
                  class="ck-flow-palette__section-toggle"
                  [attr.aria-expanded]="isSectionExpanded(section.category)"
                  [attr.aria-controls]="sectionPanelId(section.category)"
                  (click)="toggleSection(section.category)"
                >
                  <app-icon
                    [name]="isSectionExpanded(section.category) ? 'chevron-down' : 'chevron-right'"
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
                  @for (item of section.items; track item.config?.['skill_slug'] ?? item.label) {
                    <button
                      type="button"
                      class="ck-flow-palette__item"
                      [attr.data-tone]="item.tone"
                      [title]="item.description"
                      (click)="add.emit(item)"
                    >
                      <span class="ck-flow-palette__icon" [attr.data-tone]="item.tone">
                        <app-icon [name]="item.icon" [size]="14" />
                      </span>
                      <span class="ck-flow-palette__text">
                        <span class="ck-flow-palette__name">{{ item.label }}</span>
                        <span class="ck-flow-palette__type">{{ skillSlug(item) }}</span>
                      </span>
                      <span
                        class="ck-flow-palette__badge"
                        [attr.data-status]="item.runtimeStatus ?? 'catalog_only'"
                        [attr.aria-label]="'Runtime ' + runtimeStatusLabel(item)"
                      >
                        {{ runtimeStatusLabel(item) }}
                      </span>
                    </button>
                  }
                </div>
              }
            </section>
          }
        </div>
      </div>

      <!-- Primitives group: structural graph semantics. -->
      <div class="ck-flow-palette__group">
        <h3 class="ck-flow-palette__section-heading" id="flow-palette-primitives-heading">
          <button
            type="button"
            class="ck-flow-palette__section-toggle ck-flow-palette__section-toggle--root"
            [attr.aria-expanded]="primitivesExpanded()"
            aria-controls="flow-palette-primitives-panel"
            (click)="togglePrimitives()"
          >
            <app-icon [name]="primitivesExpanded() ? 'chevron-down' : 'chevron-right'" [size]="11" />
            <app-icon name="layers" set="phosphor" [size]="12" />
            <span>Primitives</span>
            <span class="ck-flow-palette__count">{{ items().length }}</span>
          </button>
        </h3>
        @if (primitivesExpanded()) {
          <div
            class="ck-flow-palette__list"
            id="flow-palette-primitives-panel"
            role="region"
            aria-labelledby="flow-palette-primitives-heading"
          >
            @for (item of items(); track item.type) {
              <button
                type="button"
                class="ck-flow-palette__item"
                [attr.data-tone]="item.tone"
                [title]="item.description"
                (click)="add.emit(item)"
              >
                <span class="ck-flow-palette__icon" [attr.data-tone]="item.tone">
                  <app-icon [name]="item.icon" [size]="14" />
                </span>
                <span class="ck-flow-palette__text">
                  <span class="ck-flow-palette__name">{{ item.label }}</span>
                  <span class="ck-flow-palette__type">{{ item.type }}</span>
                </span>
                @if (item.badge) {
                  <span class="ck-flow-palette__badge" [attr.data-tone]="item.tone">
                    {{ item.badge }}
                  </span>
                }
              </button>
            }
          </div>
        }
      </div>

      <!-- P3 SEAM: extra groups may still project here. -->
      <ng-content select="[flowPaletteExtra]" />
    </aside>
  `,
})
export class FlowPaletteComponent {
  protected readonly catalog = inject(FlowCatalogService);

  /** Structural primitives, supplied by the shell (`DEFAULT_PALETTE`). */
  readonly items = input<PaletteItem[]>([]);
  readonly add = output<PaletteItem>();

  protected readonly query = signal('');
  protected readonly primitivesExpanded = signal(true);
  private readonly collapsedSections = signal<ReadonlySet<SkillPaletteSection>>(new Set());

  protected readonly filteredSkills = computed<PaletteItem[]>(() => {
    return filterPaletteSkills(this.catalog.skillItems(), this.query());
  });

  protected readonly skillSections = computed<SkillPaletteSectionView[]>(() =>
    buildSkillPaletteSections(this.filteredSkills()),
  );

  protected onQuery(event: Event): void {
    this.query.set((event.target as HTMLInputElement).value);
    if (!this.query().trim()) return;
    const matching = new Set(
      this.skillSections()
        .filter((section) => section.items.length > 0)
        .map((section) => section.category),
    );
    this.collapsedSections.update((current) => {
      const next = new Set(current);
      for (const category of matching) next.delete(category);
      return next;
    });
  }

  protected toggleSection(category: SkillPaletteSection): void {
    this.collapsedSections.update((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  protected togglePrimitives(): void {
    this.primitivesExpanded.update((open) => !open);
  }

  protected isSectionExpanded(category: SkillPaletteSection): boolean {
    return !this.collapsedSections().has(category);
  }

  protected sectionHeadingId(category: SkillPaletteSection): string {
    return `flow-palette-${category.toLowerCase()}-heading`;
  }

  protected sectionPanelId(category: SkillPaletteSection): string {
    return `flow-palette-${category.toLowerCase()}-panel`;
  }

  protected skillCountLabel(): string {
    const visible = this.filteredSkills().length;
    return this.query().trim()
      ? `${visible} / ${this.catalog.skillItems().length}`
      : String(visible);
  }

  protected skillSlug(item: PaletteItem): string {
    return paletteSkillSlug(item);
  }

  protected runtimeStatusLabel(item: PaletteItem): string {
    return (item.runtimeStatus ?? 'catalog_only').replace(/_/g, ' ');
  }
}
