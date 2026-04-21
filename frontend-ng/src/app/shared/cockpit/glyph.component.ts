import { ChangeDetectionStrategy, Component, Input, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

export type CkGlyphName =
  | 'flow'
  | 'pulse'
  | 'cube'
  | 'sliders'
  | 'focus'
  | 'bolt'
  | 'arrow-up'
  | 'arrow-down'
  | 'arrow-right'
  | 'ledger'
  | 'telemetry'
  | 'warn'
  | 'check'
  | 'x'
  | 'zoom-in'
  | 'zoom-out'
  | 'crosshair'
  | 'play'
  | 'pause'
  | 'orbit'
  | 'brand';

/**
 * Custom 14×14 line glyphs ported from docs/mockups (chrome.jsx, primitives.jsx).
 * Use these for cockpit-grade chrome (side rail, breadcrumb, inline status).
 * Lucide remains the right choice for content-grade icons (connectors, apps).
 *
 * Each glyph is intentionally minimal: 1px stroke, square cap, no fill.
 *
 * SVG fragments must be marked as trusted HTML: Angular's default sanitizer
 * strips `<path>` / `<circle>` etc. from `[innerHTML]`, which would render
 * empty icon slots in production.
 */
@Component({
  selector: 'ck-glyph',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.width]="size"
      [attr.height]="size"
      viewBox="0 0 14 14"
      fill="none"
      [attr.stroke]="color"
      stroke-width="1"
      stroke-linecap="square"
      stroke-linejoin="miter"
      [style.display]="'inline-block'"
      [style.verticalAlign]="'middle'"
      [innerHTML]="safePath"
    ></svg>
  `,
})
export class GlyphComponent {
  private readonly sanitizer = inject(DomSanitizer);

  @Input() name: CkGlyphName = 'cube';
  @Input() size = 14;
  @Input() color = 'currentColor';

  get safePath(): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(GLYPHS[this.name] ?? '');
  }
}

/* eslint-disable @typescript-eslint/quotes */
const GLYPHS: Record<CkGlyphName, string> = {
  flow:
    `<circle cx="3" cy="3" r="1.5" />` +
    `<circle cx="11" cy="3" r="1.5" />` +
    `<circle cx="3" cy="11" r="1.5" />` +
    `<circle cx="11" cy="11" r="1.5" />` +
    `<path d="M4.5 3 H9.5 M3 4.5 V9.5 M11 4.5 V9.5 M4.5 11 H9.5" />`,
  pulse:
    `<path d="M0.5 7 H3 L5 2 L9 12 L11 7 H13.5" />`,
  cube:
    `<path d="M7 1 L13 4 V10 L7 13 L1 10 V4 Z" />` +
    `<path d="M1 4 L7 7 L13 4 M7 7 V13" />`,
  sliders:
    `<path d="M1 3 H13 M1 7 H13 M1 11 H13" />` +
    `<circle cx="4" cy="3" r="1.5" />` +
    `<circle cx="9" cy="7" r="1.5" />` +
    `<circle cx="5" cy="11" r="1.5" />`,
  focus:
    `<path d="M1 4 V1 H4 M10 1 H13 V4 M13 10 V13 H10 M4 13 H1 V10" />` +
    `<circle cx="7" cy="7" r="2.5" />`,
  bolt:
    `<path d="M8 1 L3 8 H7 L6 13 L11 6 H7 Z" />`,
  'arrow-up':
    `<path d="M7 12 V2 M3 6 L7 2 L11 6" />`,
  'arrow-down':
    `<path d="M7 2 V12 M3 8 L7 12 L11 8" />`,
  'arrow-right':
    `<path d="M2 7 H12 M8 3 L12 7 L8 11" />`,
  ledger:
    `<rect x="2" y="1.5" width="10" height="11" rx="0.5" />` +
    `<path d="M4 4 H10 M4 7 H10 M4 10 H8" />`,
  telemetry:
    `<path d="M1 13 V1 M1 13 H13" />` +
    `<path d="M3 10 L5 7 L7 9 L10 4 L13 6" />`,
  warn:
    `<path d="M7 1 L13 12 H1 Z" />` +
    `<path d="M7 5 V8 M7 10 V10.5" />`,
  check:
    `<path d="M2 7 L6 11 L12 3" />`,
  x:
    `<path d="M3 3 L11 11 M11 3 L3 11" />`,
  'zoom-in':
    `<circle cx="6" cy="6" r="4" />` +
    `<path d="M9 9 L13 13 M4 6 H8 M6 4 V8" />`,
  'zoom-out':
    `<circle cx="6" cy="6" r="4" />` +
    `<path d="M9 9 L13 13 M4 6 H8" />`,
  crosshair:
    `<circle cx="7" cy="7" r="3" />` +
    `<path d="M7 0 V3 M7 11 V14 M0 7 H3 M11 7 H14" />`,
  play:
    `<path d="M3 2 L12 7 L3 12 Z" />`,
  pause:
    `<path d="M4 2 V12 M10 2 V12" />`,
  orbit:
    `<ellipse cx="7" cy="7" rx="6" ry="2.5" transform="rotate(30 7 7)" />` +
    `<circle cx="7" cy="7" r="1.5" />`,
  brand:
    `<circle cx="7" cy="7" r="6" />` +
    `<circle cx="7" cy="7" r="3" />` +
    `<path d="M7 0 V14 M0 7 H14" />`,
};
