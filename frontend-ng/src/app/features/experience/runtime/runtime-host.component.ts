import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, type Type, computed, input } from '@angular/core';
import { CATALOG, FallbackBlock } from './runtime-blocks';
import {
  type ExperienceDocument,
  type ExperienceNode,
  type ExperiencePage,
  type RuntimeMode,
  type RuntimeNodeContext,
  renderableComponents,
  resolveCatalogType,
  runtimeDataBinding,
  runtimeStateKey,
  textFallback,
} from './model';
import { a11yOf, appearanceOf, onAccentColor, pageAppearance } from './style';

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
          <h2 [id]="page.id + '-title'">{{ pageTitle(page.title) }}</h2>
          @if (pageDescription(page); as desc) {
            <p class="xp-rt-sub">{{ desc }}</p>
          }
          @for (node of page.components; track node.id ?? $index) {
            @if (outlet(page, node, $index); as item) {
              <div
                class="xp-rt-node"
                [class.xp-rt-compact]="nodeDensity(node) === 'compact'"
                [class.xp-rt-comfortable]="nodeDensity(node) === 'comfortable'"
                [class.xp-rt-accent]="!!nodeAccent(node)"
                [style.--xp-accent]="nodeAccent(node) || null"
                [style.--xp-on-accent]="nodeAccent(node) ? nodeAccentText(node) : null"
                [attr.data-component-id]="item.context.componentId"
                [attr.data-component-type]="node.type"
                [attr.tabindex]="node.type === 'result' ? -1 : null"
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
  readonly experienceSlug = input('');
  readonly mode = input<RuntimeMode>('preview');

  readonly visiblePages = computed(() => {
    const pages = this.document().pages;
    const id = this.pageId();
    const shown = id ? pages.filter((page) => page.id === id) : pages;
    return shown.map((page) => ({
      ...page,
      components: renderableComponents(page.components),
    }));
  });

  outlet(
    page: ExperiencePage,
    node: ExperienceNode,
    index: number,
  ): {
    component: Type<unknown>;
    inputs: Record<string, unknown>;
    context: RuntimeNodeContext;
  } | null {
    const resolved = resolveCatalogType(node.type);
    if (resolved.kind === 'skip') return null;
    const component = resolved.kind === 'ok' ? CATALOG[resolved.type] : FallbackBlock;
    const context = this.context(page, node, index);
    const inputs: Record<string, unknown> = { node };
    if (CONTEXT_TYPES.has(node.type)) inputs['context'] = context;
    return { component, inputs, context };
  }

  private context(page: ExperiencePage, node: ExperienceNode, index: number): RuntimeNodeContext {
    const componentId = node.id || `${node.type}-${index}`;
    const binding = runtimeDataBinding(node);
    const explicit =
      binding?.source === 'run-output'
        ? binding.componentId
        : typeof node.props?.['sourceComponentId'] === 'string'
          ? node.props['sourceComponentId']
          : null;
    const previous = [...page.components]
      .slice(0, index)
      .reverse()
      .find((item) => item.type === 'form' || item.type === 'action_button');
    const sourceId =
      binding?.source === 'system-binding'
        ? componentId
        : explicit || previous?.id || componentId;
    return {
      experienceSlug: this.experienceSlug(),
      pageId: page.id,
      componentId,
      stateKey: runtimeStateKey(this.experienceSlug(), page.id, componentId),
      sourceStateKey: runtimeStateKey(this.experienceSlug(), page.id, sourceId),
      mode: this.mode(),
    };
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

  pageTitle(title: ExperiencePage['title']): string {
    return textFallback(title);
  }

  nodeDensity(node: ExperienceNode): string | null {
    return appearanceOf(node).density;
  }

  nodeAccent(node: ExperienceNode): string {
    return appearanceOf(node).accent;
  }

  nodeAccentText(node: ExperienceNode): string {
    return onAccentColor(this.nodeAccent(node));
  }

  keyboardHint(node: ExperienceNode): string {
    return a11yOf(node).keyboardHint;
  }
}

const CONTEXT_TYPES = new Set([
  'form',
  'action_button',
  'approval_card',
  'result',
  'runtime_status',
  'evidence',
  'history',
  'table',
  'queue',
  'kpi',
  'map_panel',
  'agenda_panel',
  'intelligence_feed',
  'decision_queue',
]);
