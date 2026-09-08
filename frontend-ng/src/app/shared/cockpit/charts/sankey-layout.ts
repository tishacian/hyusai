import { sankeyRibbonPath } from './svg-path';

export interface CkSankeySource {
  label: string;
  /** Mono caption under the name when the node is tall enough (e.g. `612 runs`). */
  detail?: string;
  value: number;
  /** Set when the source stops at its own result instead of converging (dashed stub). */
  stubLabel?: string;
}

export interface SankeyRibbon {
  d: string;
  kind: 'runs' | 'value';
}

export interface SankeyNode {
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
}

export interface SankeyLabel {
  x: number;
  y: number;
  text: string;
  fill: string;
  size: number;
  anchor: 'start' | 'middle' | 'end';
  font: 'sans' | 'mono';
  weight?: number;
  tracking?: number;
  /** Full text when `text` was shortened. */
  title?: string;
}

export interface SankeyStub {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface SankeyLayout {
  ribbons: SankeyRibbon[];
  nodes: SankeyNode[];
  labels: SankeyLabel[];
  stubs: SankeyStub[];
}

export interface SankeyLayoutOptions {
  width: number;
  height: number;
  nodeWidth: number;
  middleLabel: string;
  rightLabel: string;
  leftCaption: string;
  middleCaption: string;
  rightCaption: string;
}

/** Approved geometry on the 336 canvas: node columns, stacking origin and gap. */
const XA = 100;
const XB = 184;
const XC = 322;
const TOP = 14;
const HOURS_TOP = 44;
const BOTTOM = 20;
const GAP = 18;
const MIN_NODE = 4;
const MAX_NODE_SHARE = 0.55;
const NAME_MAX_CHARS = 16;

export function truncateLabel(text: string, max = NAME_MAX_CHARS): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

export function layoutSankey(
  sources: readonly CkSankeySource[],
  options: SankeyLayoutOptions,
): SankeyLayout {
  const ribbons: SankeyRibbon[] = [];
  const nodes: SankeyNode[] = [];
  const labels: SankeyLabel[] = [];
  const stubs: SankeyStub[] = [];
  const n = sources.length;
  if (!n) return { ribbons, nodes, labels, stubs };

  const sx = options.width / 336;
  const xa = XA * sx;
  const xb = XB * sx;
  const xc = XC * sx;
  const nw = options.nodeWidth;
  const height = options.height;

  const converts = (source: CkSankeySource): boolean => !source.stubLabel;
  const ordered = [...sources.filter(converts), ...sources.filter((source) => !converts(source))];
  const values = ordered.map((source) => Math.max(0, source.value));
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  const convertingCount = ordered.filter(converts).length;
  const convertingTotal = ordered
    .filter(converts)
    .reduce((sum, source) => sum + Math.max(0, source.value), 0) || 1;

  // Stubs stack under the hours node; with few converging rows the hours node
  // (which starts lower so its ribbons curve) pushes them down by `extra`.
  const extra = convertingCount > 0 && convertingCount < n
    ? Math.max(0, (HOURS_TOP - TOP) - GAP * (convertingCount - 1))
    : 0;
  const availableLeft = Math.max(24, height - TOP - BOTTOM - GAP * (n - 1) - extra);
  const availableHours = Math.max(24, height - HOURS_TOP - BOTTOM);
  let scale = Math.min(availableLeft / total, availableHours / convertingTotal);
  const maxValue = Math.max(...values);
  if (maxValue * scale > MAX_NODE_SHARE * availableLeft) {
    scale = (MAX_NODE_SHARE * availableLeft) / maxValue;
  }

  const heights = values.map((value) => Math.max(MIN_NODE, value * scale));
  const hoursH = ordered.reduce((sum, source, index) => sum + (converts(source) ? heights[index] : 0), 0);

  const rows: Array<{ source: CkSankeySource; y: number; h: number; converts: boolean }> = [];
  let y = TOP;
  ordered.forEach((source, index) => {
    const isConverting = converts(source);
    if (!isConverting && convertingCount > 0 && rows.every((row) => row.converts)) {
      y = Math.max(y, HOURS_TOP + hoursH + GAP);
    }
    rows.push({ source, y, h: heights[index], converts: isConverting });
    y += heights[index] + GAP;
  });

  let acc = HOURS_TOP;
  for (const row of rows) {
    if (row.converts) {
      ribbons.push({
        d: sankeyRibbonPath({ x: xa + nw, y: row.y, height: row.h }, { x: xb, y: acc, height: row.h }),
        kind: 'runs',
      });
      acc += row.h;
    } else {
      ribbons.push({
        d: sankeyRibbonPath({ x: xa + nw, y: row.y, height: row.h }, { x: xb, y: row.y, height: row.h }),
        kind: 'runs',
      });
    }
  }
  if (convertingCount > 0) {
    ribbons.push({
      d: sankeyRibbonPath({ x: xb + nw, y: HOURS_TOP, height: hoursH }, { x: xc, y: HOURS_TOP, height: hoursH }),
      kind: 'value',
    });
  }

  for (const row of rows) {
    nodes.push({ x: xa, y: row.y, w: nw, h: row.h, fill: 'var(--ck-fg-1)' });
    const shortName = truncateLabel(row.source.label);
    labels.push({
      x: xa - 8,
      y: row.y + row.h / 2 + 3.5,
      text: shortName,
      fill: 'var(--ck-fg-1)',
      size: 10.5,
      anchor: 'end',
      font: 'sans',
      ...(shortName !== row.source.label ? { title: row.source.label } : {}),
    });
    if (row.source.detail && row.h >= 26) {
      labels.push({
        x: xa - 8,
        y: row.y + row.h / 2 + 14,
        text: row.source.detail,
        fill: 'var(--ck-fg-3)',
        size: 8.5,
        anchor: 'end',
        font: 'mono',
      });
    }
  }

  if (convertingCount > 0) {
    nodes.push({ x: xb, y: HOURS_TOP, w: nw, h: hoursH, fill: 'var(--ck-fg-1)' });
    nodes.push({ x: xc, y: HOURS_TOP, w: nw, h: hoursH, fill: 'var(--ck-signal-cool)' });
    if (options.middleLabel) {
      labels.push({
        x: xb + 3,
        y: HOURS_TOP - 5,
        text: options.middleLabel,
        fill: 'var(--ck-fg-1)',
        size: 10.5,
        anchor: 'middle',
        font: 'mono',
      });
    }
    if (options.rightLabel) {
      labels.push({
        x: xc + 3,
        y: HOURS_TOP - 5,
        text: options.rightLabel,
        fill: 'var(--ck-signal-cool)',
        size: 10.5,
        anchor: 'end',
        font: 'mono',
      });
    }
  }

  for (const row of rows) {
    if (row.converts) continue;
    nodes.push({ x: xb, y: row.y, w: nw, h: row.h, fill: 'var(--ck-fg-1)' });
    const midY = row.y + row.h / 2;
    stubs.push({ x1: xb + nw + 2, y1: midY, x2: xb + nw + 40, y2: midY });
    labels.push({
      x: xb + nw + 46,
      y: midY + 3.5,
      text: row.source.stubLabel ?? '',
      fill: 'var(--ck-fg-2)',
      size: 9,
      anchor: 'start',
      font: 'mono',
    });
  }

  const capY = height - 4;
  const captions: Array<[number, string, SankeyLabel['anchor']]> = [
    [xa + 3, options.leftCaption, 'middle'],
    [xb + 3, options.middleCaption, 'middle'],
    [xc + 3, options.rightCaption, 'end'],
  ];
  for (const [x, text, anchor] of captions) {
    if (!text) continue;
    labels.push({ x, y: capY, text, fill: 'var(--ck-fg-3)', size: 8, anchor, font: 'mono', tracking: 1 });
  }

  return { ribbons, nodes, labels, stubs };
}
