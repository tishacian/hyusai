import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';

/**
 * Tiny inline-SVG sparkline. Accepts an array of numbers and renders a smoothed
 * polyline + optional area fill. Zero allocations per render — purely computed.
 *
 * Defaults are tuned to sit inside a stat tile (≈ 80×24 px).
 */
@Component({
  selector: 'app-sparkline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (values().length >= 2) {
      <svg
        [attr.viewBox]="'0 0 ' + width + ' ' + height"
        [attr.width]="width"
        [attr.height]="height"
        preserveAspectRatio="none"
        class="overflow-visible"
      >
        <defs>
          <linearGradient [attr.id]="gradientId()" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" [attr.stop-color]="color" stop-opacity="0.35" />
            <stop offset="100%" [attr.stop-color]="color" stop-opacity="0" />
          </linearGradient>
        </defs>
        <path
          [attr.d]="areaPath()"
          [attr.fill]="'url(#' + gradientId() + ')'"
          stroke="none"
        />
        <path
          [attr.d]="linePath()"
          fill="none"
          [attr.stroke]="color"
          stroke-width="1.5"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
        @if (showDot && lastPoint(); as p) {
          <circle [attr.cx]="p.x" [attr.cy]="p.y" r="2" [attr.fill]="color" />
        }
      </svg>
    } @else {
      <span class="inline-block text-[10px] text-gray-500">—</span>
    }
  `,
})
export class SparklineComponent {
  @Input() width = 80;
  @Input() height = 24;
  @Input() color = 'currentColor';
  @Input() showDot = true;

  values = signal<number[]>([]);

  @Input() set data(v: number[] | null | undefined) {
    this.values.set(Array.isArray(v) ? v.filter((n) => Number.isFinite(n)) : []);
  }

  private readonly pad = 2;
  private readonly _gradientId = 'spark-' + Math.random().toString(36).slice(2, 10);
  readonly gradientId = () => this._gradientId;

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
