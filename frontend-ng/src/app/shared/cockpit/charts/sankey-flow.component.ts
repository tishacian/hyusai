import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { ckChartUid } from './chart.types';
import {
  layoutSankey,
  type CkSankeySource,
  type SankeyLabel,
  type SankeyLayout,
  type SankeyNode,
  type SankeyRibbon,
  type SankeyStub,
} from './sankey-layout';

export type { CkSankeySource } from './sankey-layout';

@Component({
  selector: 'ck-chart-sankey-flow',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.viewBox]="'0 0 ' + width + ' ' + height"
      [attr.width]="width"
      [attr.height]="height"
      style="display:block;overflow:visible"
    >
      <defs>
        <linearGradient [attr.id]="runsId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="var(--ck-fg-1)" stop-opacity="0.4" />
          <stop offset="1" stop-color="var(--ck-fg-1)" stop-opacity="0.15" />
        </linearGradient>
        <linearGradient [attr.id]="valueId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="var(--ck-fg-1)" stop-opacity="0.15" />
          <stop offset="0.35" stop-color="var(--ck-signal-cool)" stop-opacity="0.55" />
          <stop offset="1" stop-color="var(--ck-signal-cool)" stop-opacity="0.85" />
        </linearGradient>
      </defs>
      @for (ribbon of ribbons; track $index) {
        <path
          [attr.d]="ribbon.d"
          [attr.fill]="ribbon.kind === 'value' ? 'url(#' + valueId + ')' : 'url(#' + runsId + ')'"
        />
      }
      @for (node of nodes; track $index) {
        <rect
          [attr.x]="node.x"
          [attr.y]="node.y"
          [attr.width]="node.w"
          [attr.height]="node.h"
          rx="1.5"
          [attr.fill]="node.fill"
        />
      }
      @for (stub of stubs; track $index) {
        <line
          [attr.x1]="stub.x1"
          [attr.y1]="stub.y1"
          [attr.x2]="stub.x2"
          [attr.y2]="stub.y2"
          stroke="var(--ck-fg-1)"
          stroke-opacity="0.35"
          stroke-width="1"
          stroke-dasharray="2 3"
        />
      }
      @for (label of labels; track $index) {
        <text
          [attr.x]="label.x"
          [attr.y]="label.y"
          [attr.fill]="label.fill"
          [attr.font-family]="label.font === 'mono' ? 'var(--ck-font-mono)' : 'var(--ck-font-sans)'"
          [attr.font-size]="label.size"
          [attr.font-weight]="label.weight ?? 400"
          [attr.letter-spacing]="label.tracking ?? 0"
          [attr.text-anchor]="label.anchor"
          [style.text-transform]="label.tracking ? 'uppercase' : null"
        >@if (label.title) {<title>{{ label.title }}</title>}{{ label.text }}</text>
      }
    </svg>
  `,
  styles: [':host { display: block; }'],
})
export class CkChartSankeyFlowComponent {
  @Input() sources: CkSankeySource[] = [];
  @Input() middleLabel = '';
  @Input() rightLabel = '';
  @Input() leftCaption = '';
  @Input() middleCaption = '';
  @Input() rightCaption = '';
  @Input() width = 336;
  @Input() height = 336;
  @Input() nodeWidth = 6;

  readonly runsId = ckChartUid('ck-sankey-runs');
  readonly valueId = ckChartUid('ck-sankey-val');

  get ribbons(): SankeyRibbon[] {
    return this.layout().ribbons;
  }

  get nodes(): SankeyNode[] {
    return this.layout().nodes;
  }

  get labels(): SankeyLabel[] {
    return this.layout().labels;
  }

  get stubs(): SankeyStub[] {
    return this.layout().stubs;
  }

  private layout(): SankeyLayout {
    return layoutSankey(this.sources, {
      width: this.width,
      height: this.height,
      nodeWidth: this.nodeWidth,
      middleLabel: this.middleLabel,
      rightLabel: this.rightLabel,
      leftCaption: this.leftCaption,
      middleCaption: this.middleCaption,
      rightCaption: this.rightCaption,
    });
  }
}
