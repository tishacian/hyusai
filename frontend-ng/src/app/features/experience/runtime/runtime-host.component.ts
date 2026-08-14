import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, type Type, computed, input } from '@angular/core';
import { CATALOG, FallbackBlock } from './runtime-blocks';
import {
  type ExperienceDocument,
  type ExperienceNode,
  type ExperiencePage,
  renderableComponents,
  resolveCatalogType,
} from './model';
import { a11yOf, appearanceOf, pageAppearance } from './style';

@Component({
  selector: 'app-experience-runtime-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgComponentOutlet],
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt">
      @for (page of visiblePages(); track page.id) {
        <article
          class="xp-rt-page"
          [class.xp-rt-compact]="pageDensity(page) === 'compact'"
          [attr.data-theme]="pageTheme(page)"
          [attr.aria-labelledby]="page.id + '-title'"
        >
          <h2 [id]="page.id + '-title'">{{ page.title }}</h2>
          @if (pageDescription(page); as desc) {
            <p class="xp-rt-sub">{{ desc }}</p>
          }
          @for (node of page.components; track node.id ?? $index) {
            @if (outlet(node); as item) {
              <div
                class="xp-rt-node"
                [class.xp-rt-compact]="nodeDensity(node) === 'compact'"
                [class.xp-rt-comfortable]="nodeDensity(node) === 'comfortable'"
                [class.xp-rt-accent]="!!nodeAccent(node)"
                [style.--xp-accent]="nodeAccent(node) || null"
              >
                <ng-container
                  [ngComponentOutlet]="item.component"
                  [ngComponentOutletInputs]="item.inputs"
                />
                @if (keyboardHint(node); as hint) {
                  <p class="xp-rt-hint">{{ hint }}</p>
                }
              </div>
            }
          }
        </article>
      }
    </div>
  `,
})
export class ExperienceRuntimeHostComponent {
  readonly document = input.required<ExperienceDocument>();
  readonly pageId = input<string | null>(null);

  readonly visiblePages = computed(() => {
    const pages = this.document().pages;
    const id = this.pageId();
    const shown = id ? pages.filter((page) => page.id === id) : pages;
    return shown.map((page) => ({
      ...page,
      components: renderableComponents(page.components),
    }));
  });

  outlet(node: ExperienceNode): { component: Type<unknown>; inputs: { node: ExperienceNode } } | null {
    const resolved = resolveCatalogType(node.type);
    if (resolved.kind === 'skip') return null;
    const component = resolved.kind === 'ok' ? CATALOG[resolved.type] : FallbackBlock;
    return { component, inputs: { node } };
  }

  pageDensity(page: ExperiencePage): string | null {
    return pageAppearance(page).density;
  }

  pageTheme(page: ExperiencePage): string | null {
    const theme = pageAppearance(page).theme;
    return theme === 'inherit' ? null : theme;
  }

  pageDescription(page: ExperiencePage): string {
    return pageAppearance(page).description;
  }

  nodeDensity(node: ExperienceNode): string | null {
    return appearanceOf(node).density;
  }

  nodeAccent(node: ExperienceNode): string {
    return appearanceOf(node).accent;
  }

  keyboardHint(node: ExperienceNode): string {
    return a11yOf(node).keyboardHint;
  }
}
