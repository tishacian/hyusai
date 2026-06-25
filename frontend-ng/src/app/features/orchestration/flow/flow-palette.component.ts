/**
 * `<app-flow-palette>` — the PALETTE HOST boundary.
 *
 * P3 (dynamic-palette): the palette now sources two groups —
 *   1. **Skills** — derived at runtime from `CanonicalApiService.listSkills()`
 *      via `FlowCatalogService` (each entry carrying its full skill binding +
 *      typed params), filterable by name/slug.
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
import type { PaletteItem } from './flow.types';

@Component({
  selector: 'app-flow-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  styleUrl: './flow-palette.component.scss',
  template: `
    <aside class="ck-flow-palette" role="group" aria-label="Node palette">
      <!-- Skills group: dynamic, from the live /skills catalog. -->
      <div class="ck-flow-palette__group">
        <h3 class="ck-flow-palette__label">
          <app-icon name="boxes" [size]="12" /> Skills
          <span class="ck-flow-palette__count">{{ filteredSkills().length }}</span>
        </h3>

        <label class="ck-flow-palette__search">
          <app-icon name="search" [size]="12" />
          <input
            type="search"
            class="ck-flow-palette__search-input"
            placeholder="Filter skills…"
            aria-label="Filter skills"
            [value]="query()"
            (input)="onQuery($event)"
          />
        </label>

        <div class="ck-flow-palette__list">
          @for (item of filteredSkills(); track item.config?.['skill_slug'] ?? item.label) {
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
              @if (item.badge) {
                <span class="ck-flow-palette__badge" [attr.data-tone]="item.tone">
                  {{ item.badge }}
                </span>
              }
            </button>
          } @empty {
            <p class="ck-flow-palette__empty">
              {{ query() ? 'No skill matches.' : 'No skills in the catalog yet.' }}
            </p>
          }
        </div>
      </div>

      <!-- Primitives group: structural graph semantics. -->
      <div class="ck-flow-palette__group">
        <h3 class="ck-flow-palette__label">
          <app-icon name="layers" [size]="12" /> Primitives
        </h3>
        <div class="ck-flow-palette__list">
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
            </button>
          }
        </div>
      </div>

      <!-- P3 SEAM: extra groups may still project here. -->
      <ng-content select="[flowPaletteExtra]" />
    </aside>
  `,
})
export class FlowPaletteComponent {
  private readonly catalog = inject(FlowCatalogService);

  /** Structural primitives, supplied by the shell (`DEFAULT_PALETTE`). */
  readonly items = input<PaletteItem[]>([]);
  readonly add = output<PaletteItem>();

  protected readonly query = signal('');

  protected readonly filteredSkills = computed<PaletteItem[]>(() => {
    const q = this.query().trim().toLowerCase();
    const skills = this.catalog.skillItems();
    if (!q) return skills;
    return skills.filter((item) =>
      `${item.label} ${this.skillSlug(item)} ${item.description}`
        .toLowerCase()
        .includes(q),
    );
  });

  protected onQuery(event: Event): void {
    this.query.set((event.target as HTMLInputElement).value);
  }

  protected skillSlug(item: PaletteItem): string {
    const slug = item.config?.['skill_slug'];
    return typeof slug === 'string' ? slug : item.type;
  }
}
