import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';

/**
 * Cockpit-grade sparkline. Inline SVG, signal-driven, with optional gradient
 * fill, drop-shadow glow (Concept B touch) and end-dot. Ported from the Spark
 * primitive in docs/mockups/primitives.jsx.
 *
 * Default size matches the chrome readouts (60×16). Hero variants pass
 * `[height]="40"` and `[glow]="true"` to get the executive treatment.
 */
@Component({
  selector: 'ck-spark',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (values().length >= 2) {
      <svg
        [attr.viewBox]="'0 0 ' + width + ' ' + height"
        [attr.width]="width"
        [attr.height]="height"
        preserveAspectRatio="none"
        [style.filter]="glow ? 'drop-shadow(0 0 6px ' + color + ')' : null"
        [style.display]="'block'"
      >
        <defs>
          <linearGradient [attr.id]="gradientId" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" [attr.stop-color]="color" stop-opacity="0.32" />
            <stop offset="100%" [attr.stop-color]="color" stop-opacity="0" />
          </linearGradient>
        </defs>
        @if (fill) {
          <path [attr.d]="areaPath()" [attr.fill]="'url(#' + gradientId + ')'" stroke="none" />
        }
        <path
          [attr.d]="linePath()"
          fill="none"
          [attr.stroke]="color"
          [attr.stroke-width]="strokeWidth"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
        @if (showDot && lastPoint(); as p) {
          <circle [attr.cx]="p.x" [attr.cy]="p.y" [attr.r]="dotRadius" [attr.fill]="color" />
        }
      </svg>
    } @else {
      <span class="ck-mono" style="font-size:10px;color:var(--ck-fg-5)">—</span>
    }
  `,
})
export class SparkComponent {
  @Input() width = 60;
  @Input() height = 16;
  @Input() color = 'var(--ck-signal-cool)';
  @Input() showDot = true;
  @Input() fill = true;
  @Input() glow = false;
  @Input() strokeWidth = 1.25;
  @Input() dotRadius = 1.6;

  values = signal<number[]>([]);

  @Input() set data(v: number[] | null | undefined) {
    this.values.set(Array.isArray(v) ? v.filter((n) => Number.isFinite(n)) : []);
  }

  readonly gradientId = 'ck-spark-' + Math.random().toString(36).slice(2, 10);

  private readonly pad = 2;

  readonly points = computed(() => {
    const v = this.values();
    if (v.length < 2) return [] as { x: number; y: number }[];
    const w = this.width;
    const h = this.height;
    const pad = this.pad;
    const min = Math.min(...v);
    const max = Math.max(...v);
    const range = max - min || 1;
    const stepX = (w - pad * 2) / (v.length - 1);
    return v.map((val, i) => {
      const x = pad + i * stepX;
      const y = pad + (h - pad * 2) * (1 - (val - min) / range);
      return { x, y };
    });
  });

  readonly linePath = computed(() => {
    const pts = this.points();
    if (!pts.length) return '';
    return pts.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
  });

  readonly areaPath = computed(() => {
    const pts = this.points();
    if (pts.length < 2) return '';
    const first = pts[0];
    const last = pts[pts.length - 1];
    const body = pts.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
    return `${body} L${last.x},${this.height} L${first.x},${this.height} Z`;
  });

  readonly lastPoint = computed(() => {
    const pts = this.points();
    return pts.length ? pts[pts.length - 1] : null;
  });
}
