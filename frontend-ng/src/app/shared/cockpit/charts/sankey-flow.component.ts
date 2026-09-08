import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { ckChartUid } from './chart.types';
import { sankeyRibbonPath } from './svg-path';

export interface CkSankeySource {
  label: string;
  detail?: string;
  value: number;
  stubLabel?: string;
}

interface SankeyRibbon {
  d: string;
  kind: 'runs' | 'value';
}

interface SankeyNode {
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
}

interface SankeyLabel {
  x: number;
  y: number;
  text: string;
  fill: string;
  size: number;
  anchor: 'start' | 'middle' | 'end';
  font: 'sans' | 'mono';
  weight?: number;
  opacity?: number;
  tracking?: number;
}

interface SankeyStub {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

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
          [attr.fill-opacity]="label.opacity ?? 1"
          [attr.font-family]="label.font === 'mono' ? 'var(--ck-font-mono)' : 'var(--ck-font-sans)'"
          [attr.font-size]="label.size"
          [attr.font-weight]="label.weight ?? 400"
          [attr.letter-spacing]="label.tracking ?? 0"
          [attr.text-anchor]="label.anchor"
        >{{ label.text }}</text>
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

  private layout(): {
    ribbons: SankeyRibbon[];
    nodes: SankeyNode[];
    labels: SankeyLabel[];
    stubs: SankeyStub[];
  } {
    const sources = this.sources;
    const n = sources.length;
    const ribbons: SankeyRibbon[] = [];
    const nodes: SankeyNode[] = [];
    const labels: SankeyLabel[] = [];
    const stubs: SankeyStub[] = [];
    if (!n) return { ribbons, nodes, labels, stubs };

    const sx = this.width / 336;
    const xa = 100 * sx;
    const xb = 184 * sx;
    const xc = 322 * sx;
    const nw = this.nodeWidth;
    const top = 22;
    const bottom = 16;
    const gap = 18;
    const available = Math.max(24, this.height - top - bottom - gap * Math.max(0, n - 1));
    const total = sources.reduce((sum, source) => sum + Math.max(0, source.value), 0) || 1;
    const scale = available / total;

    let y = top;
    const left = sources.map((source) => {
      const h = Math.max(4, Math.max(0, source.value) * scale);
      const row = { ...source, y, h, converts: source.stubLabel == null || source.stubLabel === '' };
      y += h + gap;
      return row;
    });

    const converting = left.filter((row) => row.converts);
    const hoursH = converting.reduce((sum, row) => sum + row.h, 0);
    const hoursY = converting[0]?.y ?? top;

    let acc = hoursY;
    for (const row of converting) {
      ribbons.push({
        d: sankeyRibbonPath(
          { x: xa + nw, y: row.y, height: row.h },
          { x: xb, y: acc, height: row.h },
        ),
        kind: 'runs',
      });
      acc += row.h;
    }
    for (const row of left) {
      if (row.converts) continue;
      ribbons.push({
        d: sankeyRibbonPath(
          { x: xa + nw, y: row.y, height: row.h },
          { x: xb, y: row.y, height: row.h },
        ),
        kind: 'runs',
      });
    }
    if (converting.length) {
      ribbons.push({
        d: sankeyRibbonPath(
          { x: xb + nw, y: hoursY, height: hoursH },
          { x: xc, y: hoursY, height: hoursH },
        ),
        kind: 'value',
      });
    }

    for (const row of left) {
      nodes.push({ x: xa, y: row.y, w: nw, h: row.h, fill: 'var(--ck-fg-1)' });
      labels.push({
        x: xa - 8,
        y: row.y + row.h / 2 + 3.5,
        text: row.label,
        fill: 'var(--ck-fg-1)',
        size: 10.5,
        anchor: 'end',
        font: 'sans',
      });
      if (row.detail && row.h >= 26) {
        labels.push({
          x: xa - 8,
          y: row.y + row.h / 2 + 14,
          text: row.detail,
          fill: 'var(--ck-fg-3)',
          size: 8.5,
          anchor: 'end',
          font: 'mono',
        });
      }
    }

    if (converting.length) {
      nodes.push({ x: xb, y: hoursY, w: nw, h: hoursH, fill: 'var(--ck-fg-1)' });
      nodes.push({ x: xc, y: hoursY, w: nw, h: hoursH, fill: 'var(--ck-signal-cool)' });
      if (this.middleLabel) {
        labels.push({
          x: xb + 3,
          y: hoursY - 5,
          text: this.middleLabel,
          fill: 'var(--ck-fg-1)',
          size: 10.5,
          anchor: 'middle',
          font: 'mono',
        });
      }
      if (this.rightLabel) {
        labels.push({
          x: xc + 3,
          y: hoursY - 5,
          text: this.rightLabel,
          fill: 'var(--ck-signal-cool)',
          size: 10.5,
          anchor: 'end',
          font: 'mono',
        });
      }
    }

    for (const row of left) {
      if (row.converts) continue;
      nodes.push({ x: xb, y: row.y, w: nw, h: row.h, fill: 'var(--ck-fg-1)' });
      const midY = row.y + row.h / 2;
      stubs.push({ x1: xb + nw + 2, y1: midY, x2: xb + nw + 40, y2: midY });
      if (row.stubLabel) {
        labels.push({
          x: xb + nw + 46,
          y: midY + 3.5,
          text: row.stubLabel,
          fill: 'var(--ck-fg-2)',
          size: 9,
          anchor: 'start',
          font: 'mono',
        });
      }
    }

    const capY = this.height - 4;
    if (this.leftCaption) {
      labels.push({
        x: xa + 3,
        y: capY,
        text: this.leftCaption,
        fill: 'var(--ck-fg-3)',
        size: 8,
        anchor: 'middle',
        font: 'mono',
        tracking: 1,
      });
    }
    if (this.middleCaption) {
      labels.push({
        x: xb + 3,
        y: capY,
        text: this.middleCaption,
        fill: 'var(--ck-fg-3)',
        size: 8,
        anchor: 'middle',
        font: 'mono',
        tracking: 1,
      });
    }
    if (this.rightCaption) {
      labels.push({
        x: xc + 3,
        y: capY,
        text: this.rightCaption,
        fill: 'var(--ck-fg-3)',
        size: 8,
        anchor: 'end',
        font: 'mono',
        tracking: 1,
      });
    }

    return { ribbons, nodes, labels, stubs };
  }
}
