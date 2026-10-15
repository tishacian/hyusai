/**
 * `<ck-decision-tree-chart>` — a decision tree drawn as a tree.
 *
 * SVG rather than a canvas or a graph library: a tree of a few levels is a
 * handful of boxes and curves, and SVG keeps every node a focusable,
 * hoverable element with its own text, in both themes, with no dependency.
 * The geometry comes from `layoutTree` (pure, tested); this component only
 * draws it and tracks which node is pointed at and which one is selected.
 *
 * Pointing at a node lights the path from the root down to it — the
 * conditions a row meets on its way there — because that path, not the node
 * on its own, is the explanation. Branch thickness carries the share of rows
 * that take it, so a striking leaf that only holds a sliver of the data looks
 * like what it is.
 */
import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';

import { layoutTree, pathTo, type TreeChartNode, type TreeCondition } from './decision-tree.vm';

@Component({
  selector: 'ck-decision-tree-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (layout(); as tree) {
      @if (tree.nodes.length) {
        <div class="ck-viz-tree" data-testid="decision-tree-chart">
          <svg
            role="group"
            [attr.aria-label]="label()"
            [attr.viewBox]="'-2 -2 ' + (tree.width + 4) + ' ' + (tree.height + 4)"
            [attr.width]="tree.width + 4"
            [attr.height]="tree.height + 4"
          >
            @for (edge of tree.edges; track edge.to) {
              <path
                class="ck-viz-tree__edge"
                [class.is-lit]="lit().has(edge.to)"
                [attr.d]="edge.path"
                [attr.stroke-width]="edge.width"
              />
            }
            @for (edge of tree.edges; track edge.to) {
              <g class="ck-viz-tree__label" [class.is-lit]="lit().has(edge.to)">
                <rect
                  [attr.x]="edge.labelX - labelWidth(edge.label) / 2"
                  [attr.y]="edge.labelY - 9"
                  [attr.width]="labelWidth(edge.label)"
                  height="18"
                  rx="9"
                />
                <text [attr.x]="edge.labelX" [attr.y]="edge.labelY + 4" text-anchor="middle">{{ edge.label }}</text>
              </g>
            }
            @for (node of tree.nodes; track node.id) {
              <g
                class="ck-viz-tree__node"
                role="button"
                tabindex="0"
                data-testid="decision-tree-node"
                [attr.data-node]="node.id"
                [attr.aria-pressed]="node.id === selected()"
                [attr.aria-label]="node.title + ', ' + node.value + ', ' + node.detail"
                [class.is-leaf]="!node.children.length"
                [class.is-lit]="lit().has(node.id)"
                [class.is-selected]="node.id === selected()"
                [attr.transform]="'translate(' + node.x + ' ' + node.y + ')'"
                (mouseenter)="pointed.set(node.id)"
                (mouseleave)="pointed.set(null)"
                (focus)="pointed.set(node.id)"
                (blur)="pointed.set(null)"
                (click)="choose(node.id)"
                (keydown.enter)="choose(node.id)"
                (keydown.space)="$event.preventDefault(); choose(node.id)"
              >
                <rect class="ck-viz-tree__box" [attr.width]="tree.nodeWidth" [attr.height]="tree.nodeHeight" rx="6" />
                <rect class="ck-viz-tree__fill" [attr.width]="tree.nodeWidth" [attr.height]="tree.nodeHeight" rx="6" [attr.fill]="node.fill" />
                <text class="ck-viz-tree__title" x="10" y="19">{{ clip(node.title, 20) }}</text>
                <text class="ck-viz-tree__value" x="10" y="37">{{ clip(node.value, 22) }}</text>
                <text class="ck-viz-tree__detail" x="10" y="53">{{ clip(node.detail, 24) }}</text>
                <title>{{ node.title }} — {{ node.value }} — {{ node.detail }}</title>
              </g>
            }
          </svg>
        </div>
      }
    }
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .ck-viz-tree { overflow-x: auto; padding: 4px 0 8px; }
      svg { display: block; margin: 0 auto; overflow: visible; font-family: inherit; }
      .ck-viz-tree__edge {
        fill: none;
        stroke: var(--ck-stroke-3);
        stroke-linecap: round;
        transition: stroke 120ms ease, opacity 120ms ease;
      }
      .ck-viz-tree__edge.is-lit { stroke: var(--ck-accent); }
      .ck-viz-tree__label rect { fill: var(--ck-bg-panel); stroke: var(--ck-stroke-2); }
      .ck-viz-tree__label text {
        fill: var(--ck-fg-3);
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
      }
      .ck-viz-tree__label.is-lit rect { stroke: var(--ck-accent); }
      .ck-viz-tree__label.is-lit text { fill: var(--ck-fg-1); }
      .ck-viz-tree__node { cursor: pointer; outline: none; }
      .ck-viz-tree__box { fill: var(--ck-bg-panel); stroke: var(--ck-stroke-2); stroke-width: 1; }
      .ck-viz-tree__fill { pointer-events: none; }
      .ck-viz-tree__node.is-leaf .ck-viz-tree__box { stroke-dasharray: 0; }
      .ck-viz-tree__node.is-lit .ck-viz-tree__box { stroke: var(--ck-accent); }
      .ck-viz-tree__node.is-selected .ck-viz-tree__box { stroke: var(--ck-accent); stroke-width: 2; }
      .ck-viz-tree__node:focus-visible .ck-viz-tree__box { stroke: var(--ck-accent); stroke-width: 2; }
      .ck-viz-tree__title { fill: var(--ck-fg-1); font-size: 12px; font-weight: 500; }
      .ck-viz-tree__value { fill: var(--ck-fg-2); font-size: 11.5px; font-variant-numeric: tabular-nums; }
      .ck-viz-tree__detail { fill: var(--ck-fg-4); font-size: 10.5px; font-variant-numeric: tabular-nums; }
      text { pointer-events: none; }
      @media (prefers-reduced-motion: reduce) {
        .ck-viz-tree__edge { transition: none; }
      }
    `,
  ],
})
export class DecisionTreeChartComponent {
  readonly nodes = input<readonly TreeChartNode[]>([]);
  /** Words an edge label from its condition; see `conditionLabel`. */
  readonly conditionLabel = input<((condition: TreeCondition) => string) | undefined>(undefined);
  readonly label = input('');
  readonly selected = input<number | null>(null);
  readonly selectedChange = output<number>();

  protected readonly pointed = signal<number | null>(null);
  protected readonly layout = computed(() => {
    const label = this.conditionLabel();
    return layoutTree(this.nodes(), label ? { label } : {});
  });
  /** The path lit up: the pointed node's while pointing, the selected one's otherwise. */
  protected readonly lit = computed(() => pathTo(this.nodes(), this.pointed() ?? this.selected()));

  protected choose(id: number): void {
    this.selectedChange.emit(id);
  }

  /** Box width for an edge label, from its length; a pill wide enough to read. */
  protected labelWidth(text: string): number {
    return Math.max(34, Math.round(String(text).length * 6.4 + 16));
  }

  /** Long feature names are cut in the box and given in full in its tooltip. */
  protected clip(text: string, length: number): string {
    const value = String(text ?? '');
    return value.length > length ? `${value.slice(0, length - 1)}…` : value;
  }
}
