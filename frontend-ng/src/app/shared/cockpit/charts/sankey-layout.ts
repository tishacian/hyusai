import { wrapLabelLines } from './chart-interact';
import { type CkChartTipLine } from './chart-tip.component';
import { sankeyRibbonPath } from './svg-path';

export interface CkSankeySource {
  id?: string;
  label: string;
  /** Mono caption under the name when the node is tall enough (e.g. `612 runs`). */
  detail?: string;
  value: number;
  /** Set when the source stops at its own result instead of converging (dashed stub). */
  stubLabel?: string;
  tip?: { title: string; lines: readonly CkChartTipLine[] };
}

export interface SankeyRibbon {
  d: string;
  kind: 'runs' | 'value';
  sourceId?: string;
  /** Carries an estimate (hours × a declared rate): hatched as well as teal. */
  declared?: boolean;
}

export interface SankeyNode {
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
  sourceId?: string;
  role?: 'source' | 'hours' | 'value' | 'stub';
  /** Carries an estimate: hatched as well as teal. */
  declared?: boolean;
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
  /** Column caption under the chart (sentence case, sans: no mono eyebrow). */
  caption?: boolean;
  /** Full text when `text` was shortened. */
  title?: string;
  sourceId?: string;
  role?: 'source' | 'hours' | 'value';
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
const XA = 130;
const XB = 184;
const XC = 322;
const TOP = 14;
const HOURS_TOP = 44;
const BOTTOM = 20;
const GAP = 18;
const MIN_NODE = 4;
const MAX_NODE_SHARE = 0.55;

export function truncateLabel(text: string, max = 16): string {
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

  const maxChars = Math.max(16, Math.floor((xa - 10) / 6.2));
  let acc = HOURS_TOP;
  for (const row of rows) {
    const sourceId = row.source.id;
    if (row.converts) {
      ribbons.push({
        d: sankeyRibbonPath({ x: xa + nw, y: row.y, height: row.h }, { x: xb, y: acc, height: row.h }),
        kind: 'runs',
        sourceId,
      });
      acc += row.h;
    } else {
      ribbons.push({
        d: sankeyRibbonPath({ x: xa + nw, y: row.y, height: row.h }, { x: xb, y: row.y, height: row.h }),
        kind: 'runs',
        sourceId,
      });
    }
  }
  if (convertingCount > 0) {
    ribbons.push({
      d: sankeyRibbonPath({ x: xb + nw, y: HOURS_TOP, height: hoursH }, { x: xc, y: HOURS_TOP, height: hoursH }),
      kind: 'value',
      declared: true,
    });
  }

  for (const row of rows) {
    const sourceId = row.source.id;
    nodes.push({ x: xa, y: row.y, w: nw, h: row.h, fill: 'var(--ck-data-measured)', sourceId, role: 'source' });
    const lines = wrapLabelLines(row.source.label, maxChars);
    const mid = row.y + row.h / 2;
    const nameOffset = lines.length > 1 ? 6 : 0;
    lines.forEach((line, lineIndex) => {
      labels.push({
        x: xa - 8,
        y: mid + 3.5 + (lineIndex - (lines.length - 1) / 2) * 12 - (row.source.detail && row.h >= 38 ? 4 : 0),
        text: line,
        fill: 'var(--ck-fg-1)',
        size: 10.5,
        anchor: 'end',
        font: 'sans',
        title: row.source.label,
        sourceId,
        role: 'source',
      });
    });
    if (row.source.detail && row.h >= (lines.length > 1 ? 38 : 26)) {
      labels.push({
        x: xa - 8,
        y: mid + 14 + nameOffset,
        text: row.source.detail,
        fill: 'var(--ck-fg-3)',
        size: 8.5,
        anchor: 'end',
        font: 'mono',
        sourceId,
        role: 'source',
      });
    }
  }

  if (convertingCount > 0) {
    nodes.push({ x: xb, y: HOURS_TOP, w: nw, h: hoursH, fill: 'var(--ck-data-measured)', role: 'hours' });
    nodes.push({ x: xc, y: HOURS_TOP, w: nw, h: hoursH, fill: 'var(--ck-data-declared)', role: 'value', declared: true });
    if (options.middleLabel) {
      labels.push({
        x: xb + 3,
        y: HOURS_TOP - 5,
        text: options.middleLabel,
        fill: 'var(--ck-fg-1)',
        size: 10.5,
        anchor: 'middle',
        font: 'mono',
        role: 'hours',
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
        role: 'value',
      });
    }
  }

  for (const row of rows) {
    if (row.converts) continue;
    nodes.push({ x: xb, y: row.y, w: nw, h: row.h, fill: 'var(--ck-data-measured)', sourceId: row.source.id, role: 'stub' });
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
    labels.push({ x, y: capY, text, fill: 'var(--ck-fg-3)', size: 10, anchor, font: 'sans', caption: true });
  }

  return { ribbons, nodes, labels, stubs };
}
