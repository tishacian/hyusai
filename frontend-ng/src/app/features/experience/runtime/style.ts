/**
 * Appearance + a11y projections the renderer and Studio inspector share.
 * Angular-free so `runtime.spec.ts` / `studio.spec.ts` can assert them.
 */

import type { ExperienceNode, ExperiencePage } from './model';

export type Density = 'comfortable' | 'compact';
export type PageTheme = 'inherit' | 'light' | 'dark';

export interface NodeAppearance {
  title: string;
  description: string;
  density: Density | null;
  accent: string;
}

export interface NodeA11y {
  ariaLabel: string;
  headingLevel: 2 | 3 | 4 | null;
  emptyText: string;
  keyboardHint: string;
}

const TITLE_TYPES = new Set([
  'header',
  'section',
  'approval_card',
  'form',
  'table',
  'queue',
  'map_panel',
  'agenda_panel',
  'intelligence_feed',
  'decision_queue',
]);
const DESC_TYPES = new Set([...TITLE_TYPES, 'kpi', 'callout']);
const ACCENT_TYPES = new Set(['action_button', 'kpi', 'header', 'callout', 'approval_card']);
const EMPTY_TYPES = new Set([
  'form',
  'table',
  'queue',
  'approval_card',
  'chart',
  'map_panel',
  'agenda_panel',
  'intelligence_feed',
  'decision_queue',
]);
const HEADING_TYPES = new Set(['header', 'section']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function strProp(props: Record<string, unknown> | undefined, key: string): string {
  const value = props?.[key];
  return typeof value === 'string' ? value : '';
}

export function densityOf(props: Record<string, unknown> | undefined): Density | null {
  const value = props?.['density'];
  if (value === 'compact' || value === 'comfortable') return value;
  return null;
}

export function themeOf(props: Record<string, unknown> | undefined): PageTheme {
  const value = props?.['theme'];
  if (value === 'light' || value === 'dark') return value;
  return 'inherit';
}

export function appearanceOf(node: ExperienceNode): NodeAppearance {
  return {
    title: strProp(node.props, 'title'),
    description: strProp(node.props, 'description'),
    density: densityOf(node.props),
    accent: strProp(node.props, 'accent'),
  };
}

export function pageAppearance(page: ExperiencePage): {
  description: string;
  density: Density | null;
  theme: PageTheme;
} {
  return {
    description: strProp(page.props, 'description'),
    density: densityOf(page.props),
    theme: themeOf(page.props),
  };
}

export function a11yOf(node: ExperienceNode): NodeA11y {
  const raw = node.props?.['a11y'];
  const bag = isRecord(raw) ? raw : {};
  const headingRaw = bag['headingLevel'];
  const headingLevel =
    headingRaw === 2 || headingRaw === '2'
      ? 2
      : headingRaw === 4 || headingRaw === '4'
        ? 4
        : headingRaw === 3 || headingRaw === '3'
          ? 3
          : null;
  return {
    ariaLabel: strProp(bag, 'ariaLabel') || strProp(node.props, 'ariaLabel'),
    headingLevel,
    emptyText: strProp(bag, 'emptyText'),
    keyboardHint: strProp(bag, 'keyboardHint'),
  };
}

/** Raw authoring value; runtime calls `a11yOf` only after document localisation. */
export function a11yValue(node: ExperienceNode, key: keyof NodeA11y): unknown {
  const raw = node.props?.['a11y'];
  const bag = isRecord(raw) ? raw : {};
  if (key === 'ariaLabel' && bag[key] === undefined) return node.props?.['ariaLabel'];
  return bag[key];
}

export function a11yPayload(node: ExperienceNode, key: keyof NodeA11y, value: unknown): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  for (const item of ['ariaLabel', 'emptyText', 'keyboardHint'] as const) {
    const current = a11yValue(node, item);
    if (current !== '' && current !== undefined && current !== null) next[item] = current;
  }
  const heading = a11yOf(node).headingLevel;
  if (heading) next['headingLevel'] = heading;
  if (value === '' || value === undefined || value === null) delete next[key];
  else next[key] = value;
  return next;
}

export function supportsTitle(type: string): boolean {
  return TITLE_TYPES.has(type);
}

export function supportsDescription(type: string): boolean {
  return DESC_TYPES.has(type);
}

export function supportsAccent(type: string): boolean {
  return ACCENT_TYPES.has(type);
}

export function needsEmptyText(type: string): boolean {
  return EMPTY_TYPES.has(type);
}

export function supportsHeading(type: string): boolean {
  return HEADING_TYPES.has(type);
}

/** WCAG-ish 3:1 UI contrast against cockpit panel surfaces. */
export function accentContrastWarning(accent: string, theme: PageTheme): boolean {
  const rgb = parseHex(accent);
  if (!rgb) return false;
  const lum = luminance(rgb);
  const weakDark = contrast(lum, luminance({ r: 12, g: 16, b: 20 })) < 3;
  const weakLight = contrast(lum, luminance({ r: 250, g: 250, b: 246 })) < 3;
  if (theme === 'dark') return weakDark;
  if (theme === 'light') return weakLight;
  return weakDark || weakLight;
}

/** Chooses the higher-contrast text colour for any valid custom accent. */
export function onAccentColor(accent: string): '#05070a' | '#ffffff' {
  const rgb = parseHex(accent);
  if (!rgb) return '#05070a';
  const background = luminance(rgb);
  return contrast(background, 0) >= contrast(background, 1) ? '#05070a' : '#ffffff';
}

function parseHex(value: string): { r: number; g: number; b: number } | null {
  const raw = value.trim();
  const match = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!match) return null;
  let hex = match[1]!;
  if (hex.length === 3) hex = hex.split('').map((ch) => ch + ch).join('');
  return {
    r: Number.parseInt(hex.slice(0, 2), 16),
    g: Number.parseInt(hex.slice(2, 4), 16),
    b: Number.parseInt(hex.slice(4, 6), 16),
  };
}

function luminance({ r, g, b }: { r: number; g: number; b: number }): number {
  const lin = [r, g, b].map((channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lin[0]! + 0.7152 * lin[1]! + 0.0722 * lin[2]!;
}

function contrast(a: number, b: number): number {
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}
