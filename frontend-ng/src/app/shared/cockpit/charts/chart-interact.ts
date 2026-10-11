/** Pure helpers for hypervisor chart hover. Hover must not rebuild paths. */

export interface LayoutMemo<T> {
  key: string;
  value: T | null;
}

export interface TipAnchor {
  x: number;
  y: number;
}

export interface TipSize {
  w: number;
  h: number;
}

export interface TipBounds {
  w: number;
  h: number;
}

const HOVER_INPUTS = ['hoverDay', 'hoverSystem', 'hoverWeek'] as const;

export function memoizeLayout<T>(slot: LayoutMemo<T>, key: string, build: () => T): T {
  if (slot.value !== null && slot.key === key) return slot.value;
  slot.key = key;
  slot.value = build();
  return slot.value;
}

/** True when a change-detection pass must recompute geometry. */
export function shouldRebuildLayout(
  changed: readonly string[],
  hoverKeys: readonly string[] = HOVER_INPUTS,
): boolean {
  return changed.some((key) => !hoverKeys.includes(key));
}

export function nearestDayIndex(
  x: number,
  plotLeft: number,
  plotWidth: number,
  count: number,
): number {
  if (count <= 1) return 0;
  const t = (x - plotLeft) / (plotWidth || 1);
  return Math.min(count - 1, Math.max(0, Math.round(t * (count - 1))));
}

export function placeTooltip(
  anchor: TipAnchor,
  tip: TipSize,
  bounds: TipBounds,
  gap = 8,
): TipAnchor {
  let x = anchor.x + gap;
  let y = anchor.y - tip.h - gap;
  if (x + tip.w > bounds.w) x = anchor.x - tip.w - gap;
  if (x < 0) x = Math.max(0, bounds.w - tip.w);
  if (y < 0) y = anchor.y + gap;
  if (y + tip.h > bounds.h) y = Math.max(0, bounds.h - tip.h);
  return { x, y };
}

/** Word-wrap a System name onto at most two lines. */
export function wrapLabelLines(text: string, maxChars: number): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [''];
  if (trimmed.length <= maxChars) return [trimmed];
  const words = trimmed.split(/\s+/);
  if (words.length === 1) {
    return [`${trimmed.slice(0, Math.max(1, maxChars - 1))}…`];
  }
  let split = 0;
  let len = 0;
  for (let i = 0; i < words.length - 1; i += 1) {
    const next = len + words[i]!.length + (i ? 1 : 0);
    if (next > maxChars) break;
    len = next;
    split = i + 1;
  }
  if (split === 0) split = 1;
  return [words.slice(0, split).join(' '), words.slice(split).join(' ')];
}

let measureCanvas: HTMLCanvasElement | null = null;

export function measureLabelWidth(
  text: string,
  font = '500 10.5px ui-sans-serif, system-ui, sans-serif',
): number {
  if (typeof document === 'undefined') return Math.ceil(text.length * 6.4);
  measureCanvas ??= document.createElement('canvas');
  const ctx = measureCanvas.getContext('2d');
  if (!ctx) return Math.ceil(text.length * 6.4);
  ctx.font = font;
  return ctx.measureText(text).width;
}

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Ease-out used by the monument count-up (`--ck-ease-out` shape). */
export function easeOutProgress(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return 1 - (1 - x) ** 3;
}

export function svgPointerPoint(
  svg: SVGSVGElement,
  clientX: number,
  clientY: number,
): TipAnchor {
  const ctm = svg.getScreenCTM();
  if (!ctm) return { x: 0, y: 0 };
  const pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  const mapped = pt.matrixTransform(ctm.inverse());
  return { x: mapped.x, y: mapped.y };
}

export function hostPointerPoint(
  host: HTMLElement,
  clientX: number,
  clientY: number,
): TipAnchor {
  const rect = host.getBoundingClientRect();
  return { x: clientX - rect.left, y: clientY - rect.top };
}

export function observeHostWidth(
  el: HTMLElement,
  onWidth: (width: number) => void,
): () => void {
  if (typeof ResizeObserver === 'undefined') {
    onWidth(el.clientWidth);
    return () => undefined;
  }
  const ro = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width ?? el.clientWidth;
    if (width > 0) onWidth(width);
  });
  ro.observe(el);
  if (el.clientWidth > 0) onWidth(el.clientWidth);
  return () => ro.disconnect();
}

export function attrFromTarget(target: EventTarget | null, name: string): string | null {
  if (!(target instanceof Element)) return null;
  const node = target.closest(`[${name}]`);
  return node?.getAttribute(name) ?? null;
}
