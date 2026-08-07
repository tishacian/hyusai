import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { catchError, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';

interface MacroIndicatorPoint {
  year?: number;
  date?: string;
  value: number;
}

export interface MacroIndicator {
  key: string;
  label: string;
  current: number;
  unit?: string;
  trend?: string;
  trend_direction?: 'up' | 'down' | 'flat';
  series: MacroIndicatorPoint[];
  source?: string;
  source_url?: string;
  description?: string;
  prism?: string;
}

interface MacroIndicatorsResponse {
  indicators?: MacroIndicator[];
  sovereign_indicators?: MacroIndicator[];
  macro_indicators_sovereign?: MacroIndicator[];
  source?: string;
  sovereign_source?: string;
  fetched_at?: string;
}

const MACRO_ANCHOR_DATE = '2026-05-25';
const MACRO_TIMEZONE = 'Africa/Abidjan';

function currentAbidjanDateKey(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: MACRO_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value || '01';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

function rollSeriesDates(series: MacroIndicatorPoint[]): MacroIndicatorPoint[] {
  const datedPoints = series
    .map((point) => point.date)
    .filter((value): value is string => !!value && /^\d{4}-\d{2}-\d{2}$/.test(value))
    .sort();
  if (datedPoints[datedPoints.length - 1] !== MACRO_ANCHOR_DATE) return series;
  const today = new Date(`${currentAbidjanDateKey()}T12:00:00`);
  const anchor = new Date(`${MACRO_ANCHOR_DATE}T12:00:00`);
  const shiftDays = Math.round((today.getTime() - anchor.getTime()) / 86_400_000);
  if (!shiftDays) return series;
  return series.map((point) => {
    if (!point.date || point.year) return point;
    const shifted = new Date(`${point.date}T12:00:00`);
    if (Number.isNaN(shifted.getTime())) return point;
    shifted.setDate(shifted.getDate() + shiftDays);
    return { ...point, date: shifted.toISOString().slice(0, 10) };
  });
}

@Component({
  selector: 'app-vp-macro-indicators',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="macro-strip" aria-label="Indicateurs macro institutionnels">
      <header class="macro-head">
        <div>
          <span class="eyebrow">Indicateurs macro · institutionnels</span>
          <h2>Pouls economique souverain</h2>
        </div>
        @if (sourceLabel()) {
          <small class="source-tag">{{ sourceLabel() }}</small>
        }
      </header>
      @if (sovereignIndicators().length) {
        <div class="macro-cards sovereign-grid">
          @for (indicator of sovereignIndicators(); track indicator.key) {
            <button
              type="button"
              class="macro-card"
              [class.expanded]="expandedKey() === indicator.key"
              [class.up]="trendClass(indicator) === 'up'"
              [class.down]="trendClass(indicator) === 'down'"
              (click)="toggleExpand(indicator.key)"
              [attr.aria-expanded]="expandedKey() === indicator.key"
            >
              <span class="kpi-prism">{{ prismLabel(indicator.prism) }}</span>
              <span class="kpi-label">{{ indicator.label }}</span>
              <span class="kpi-trend-pill">{{ indicator.trend || trendFallback(indicator) }}</span>
              <strong class="kpi-value">
                {{ formatValue(indicator.current) }}<em>{{ indicator.unit || '' }}</em>
              </strong>
              <svg class="sparkline" viewBox="0 0 120 36" preserveAspectRatio="none" aria-hidden="true">
                <path class="spark-area" [attr.d]="areaPath(indicator)" />
                <path class="spark-line" [attr.d]="linePath(indicator)" />
                <circle
                  class="spark-dot"
                  [attr.cx]="lastPoint(indicator).x"
                  [attr.cy]="lastPoint(indicator).y"
                  r="2.4"
                />
              </svg>
              @if (indicator.source) {
                <small class="kpi-source">{{ indicator.source }}</small>
              }
            </button>
          }
        </div>
      } @else {
        <div class="macro-empty" role="status">
          <span class="macro-empty-icon" aria-hidden="true">○</span>
          <strong>Indicateurs en cours de chargement</strong>
          <small>Les indicateurs s'affichent dès que la source du workspace répond.</small>
        </div>
      }

      @if (contextIndicators().length) {
        <div class="macro-context">
          <span class="context-label">Contexte macro · Banque mondiale</span>
          <div class="macro-cards context-grid">
            @for (indicator of contextIndicators(); track indicator.key) {
              <button
                type="button"
                class="macro-card context-card"
                [class.expanded]="expandedKey() === indicator.key"
                [class.up]="trendClass(indicator) === 'up'"
                [class.down]="trendClass(indicator) === 'down'"
                (click)="toggleExpand(indicator.key)"
                [attr.aria-expanded]="expandedKey() === indicator.key"
              >
                <span class="kpi-label">{{ indicator.label }}</span>
                <span class="kpi-trend-pill">{{ indicator.trend || trendFallback(indicator) }}</span>
                <strong class="kpi-value">
                  {{ formatValue(indicator.current) }}<em>{{ indicator.unit || '' }}</em>
                </strong>
                <svg class="sparkline" viewBox="0 0 120 28" preserveAspectRatio="none" aria-hidden="true">
                  <path class="spark-area" [attr.d]="areaPath(indicator, 120, 28)" />
                  <path class="spark-line" [attr.d]="linePath(indicator, 120, 28)" />
                </svg>
              </button>
            }
          </div>
        </div>
      }

      @if (expandedIndicator(); as expanded) {
        <article class="macro-detail" role="region" aria-label="Détail indicateur">
          <header>
            <div>
              <span class="eyebrow">{{ expanded.label }}</span>
              <h3>
                {{ formatValue(expanded.current) }}<em>{{ expanded.unit || '' }}</em>
                <small>{{ expanded.trend || trendFallback(expanded) }}</small>
              </h3>
              @if (expanded.description) {
                <p>{{ expanded.description }}</p>
              }
            </div>
            <button type="button" class="ghost-button" (click)="toggleExpand(expanded.key)" aria-label="Fermer">
              Fermer
            </button>
          </header>
          <svg class="chart" [attr.viewBox]="'0 0 480 160'" preserveAspectRatio="none" aria-hidden="true">
            <path class="chart-area" [attr.d]="areaPath(expanded, 480, 160)" />
            <path class="chart-line" [attr.d]="linePath(expanded, 480, 160)" />
          </svg>
          <footer class="macro-detail-footer">
            <div class="series-axis">
              <span>{{ firstLabel(expanded) }}</span>
              <span>{{ lastLabel(expanded) }}</span>
            </div>
            @if (expanded.source) {
              <small>
                Source :
                @if (expanded.source_url) {
                  <a [attr.href]="expanded.source_url" target="_blank" rel="noopener">{{ expanded.source }}</a>
                } @else {
                  {{ expanded.source }}
                }
              </small>
            }
          </footer>
        </article>
      }
    </section>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .macro-strip {
        display: grid;
        gap: var(--mission-space-3);
      }
      .macro-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--mission-space-3);
      }
      .eyebrow {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      h2 {
        margin: var(--mission-space-1) 0 0;
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: var(--mission-lh-tight);
        color: var(--mission-text-primary);
      }
      .source-tag {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
      }
      .macro-cards {
        display: grid;
        gap: var(--mission-space-3);
      }
      .sovereign-grid {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
      .macro-empty {
        display: grid;
        place-items: center;
        gap: var(--mission-space-2);
        padding: var(--mission-space-6) var(--mission-space-4);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-md);
        color: var(--mission-text-secondary);
        text-align: center;
      }
      .macro-empty-icon {
        color: var(--mission-text-tertiary);
        font-size: 28px;
        line-height: 1;
      }
      .macro-empty strong {
        font-size: var(--mission-text-base);
        color: var(--mission-text-primary);
      }
      .macro-empty small {
        max-width: 320px;
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .context-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .macro-context {
        display: grid;
        gap: var(--mission-space-2);
        padding-top: var(--mission-space-2);
        border-top: 1px solid var(--mission-border);
      }
      .context-label {
        color: var(--mission-text-disabled);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .context-card {
        padding: var(--mission-space-3);
      }
      .context-card .kpi-value {
        font-size: var(--mission-text-lg);
      }
      .kpi-prism {
        grid-area: prism;
        color: var(--sentinel-accent-muted);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .macro-card {
        position: relative;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        grid-template-areas:
          'prism prism'
          'label trend'
          'value value'
          'spark spark'
          'source source';
        column-gap: var(--mission-space-3);
        row-gap: var(--mission-space-2);
        align-items: end;
        padding: var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.58);
        color: inherit;
        text-align: left;
        appearance: none;
        font: inherit;
        cursor: pointer;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out),
          transform var(--mission-dur-fast) var(--mission-ease-out);
      }
      .macro-card:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .macro-card:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .macro-card:active { transform: translateY(1px); }
      .macro-card.up { border-left: 3px solid var(--mission-warning); }
      .macro-card.down { border-left: 3px solid var(--mission-success); }
      .macro-card.expanded {
        border-color: var(--sentinel-accent);
        background: var(--sentinel-accent-soft);
      }
      .kpi-label {
        grid-area: label;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .kpi-value {
        grid-area: value;
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-xl);
        font-weight: 600;
        line-height: 1;
        color: var(--mission-text-primary);
      }
      .kpi-value em {
        margin-left: 2px;
        color: var(--mission-text-tertiary);
        font-style: normal;
        font-size: var(--mission-text-sm);
        font-weight: 500;
      }
      .kpi-trend-pill {
        grid-area: trend;
        align-self: start;
        justify-self: end;
        padding: 2px 7px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        background: rgba(4, 8, 13, 0.6);
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
      }
      .macro-card.up .kpi-trend-pill {
        color: var(--mission-warning);
        border-color: rgba(241, 180, 90, 0.32);
      }
      .macro-card.down .kpi-trend-pill {
        color: var(--mission-success);
        border-color: rgba(63, 209, 141, 0.32);
      }
      .sparkline {
        grid-area: spark;
        width: 100%;
        height: 28px;
        overflow: visible;
      }
      .spark-area {
        fill: rgba(101, 214, 110, 0.14);
        stroke: none;
      }
      .macro-card.up .spark-area { fill: rgba(241, 180, 90, 0.18); }
      .macro-card.down .spark-area { fill: rgba(63, 209, 141, 0.18); }
      .spark-line {
        fill: none;
        stroke: var(--sentinel-accent);
        stroke-width: 1.5;
        stroke-linecap: round;
        stroke-linejoin: round;
      }
      .macro-card.up .spark-line { stroke: var(--mission-warning); }
      .macro-card.down .spark-line { stroke: var(--mission-success); }
      .spark-dot {
        fill: var(--sentinel-accent);
        stroke: var(--mission-bg-base);
        stroke-width: 1;
      }
      .macro-card.up .spark-dot { fill: var(--mission-warning); }
      .macro-card.down .spark-dot { fill: var(--mission-success); }
      .kpi-source {
        grid-area: source;
        color: var(--mission-text-disabled);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .macro-detail {
        padding: var(--mission-space-4);
        border: 1px solid rgba(101, 214, 110, 0.32);
        border-radius: var(--mission-radius-md);
        background: linear-gradient(135deg, var(--sentinel-accent-soft), rgba(4, 8, 13, 0.72));
        animation: macro-detail-in var(--mission-dur-slow) var(--mission-ease-out) both;
      }
      @keyframes macro-detail-in {
        from { opacity: 0; transform: translateY(-4px); }
        to   { opacity: 1; transform: translateY(0); }
      }
      .macro-detail header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 14px;
        margin-bottom: 8px;
      }
      .macro-detail h3 {
        margin: 4px 0 0;
        font-family: var(--ck-font-mono);
        font-size: 22px;
        line-height: 1;
      }
      .macro-detail h3 em {
        margin-left: 3px;
        color: var(--mission-text-muted);
        font-style: normal;
        font-size: 13px;
      }
      .macro-detail h3 small {
        margin-left: 10px;
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 11px;
      }
      .macro-detail p {
        margin: 6px 0 0;
        color: var(--mission-text-muted);
        font-size: 12px;
        line-height: 1.4;
      }
      .ghost-button {
        padding: 6px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: transparent;
        color: var(--mission-text);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
      }
      .chart {
        width: 100%;
        height: 160px;
      }
      .chart-line {
        fill: none;
        stroke: var(--sentinel-accent);
        stroke-width: 1.8;
        stroke-linecap: round;
        stroke-linejoin: round;
      }
      .chart-area {
        fill: var(--sentinel-accent-soft);
        stroke: none;
      }
      .macro-detail-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-top: 8px;
      }
      .series-axis {
        display: flex;
        gap: 8px;
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 10px;
      }
      .macro-detail-footer small {
        color: var(--mission-text-faint);
        font-size: 11px;
      }
      .macro-detail-footer a {
        color: var(--sentinel-accent);
        text-decoration: none;
      }
      .macro-detail-footer a:hover { text-decoration: underline; }
      @media (max-width: 1200px) {
        .sovereign-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (max-width: 960px) {
        .sovereign-grid,
        .context-grid { grid-template-columns: 1fr; }
      }
      @media (prefers-reduced-motion: reduce) {
        .macro-detail { animation: none; }
      }
    `,
  ],
})
export class VpMacroIndicatorsComponent implements OnInit {
  private readonly api = inject(ApiService);

  // The cockpit mounts this strip in every workspace, so it must stay empty
  // until the workspace's own aggregate answers: any seeded placeholder would
  // render one tenant's branding inside another tenant's Mission Room.
  readonly sovereignIndicators = signal<MacroIndicator[]>([]);
  readonly contextIndicators = signal<MacroIndicator[]>([]);
  readonly expandedKey = signal<string | null>(null);
  readonly sourceLabel = signal<string>('');

  readonly expandedIndicator = computed<MacroIndicator | null>(() => {
    const key = this.expandedKey();
    if (!key) return null;
    const all = [...this.sovereignIndicators(), ...this.contextIndicators()];
    return all.find((indicator) => indicator.key === key) || null;
  });

  ngOnInit(): void {
    this.api
      .get<MacroIndicatorsResponse>('/mission-room/macro-indicators')
      .pipe(catchError(() => of(null)))
      .subscribe((response) => {
        if (!response) return;
        const sovereign = this.normalizeIndicators(
          response.sovereign_indicators || response.macro_indicators_sovereign,
        );
        if (sovereign.length) this.sovereignIndicators.set(sovereign);
        const context = this.normalizeIndicators(response.indicators);
        if (context.length) this.contextIndicators.set(context);
        if (response.sovereign_source) {
          this.sourceLabel.set(response.sovereign_source);
        } else if (response.source) {
          this.sourceLabel.set(response.source);
        }
      });
  }

  private normalizeIndicators(raw?: MacroIndicator[]): MacroIndicator[] {
    if (!raw?.length) return [];
    return raw
      .map((indicator) => ({
        ...indicator,
        current: Number(indicator.current ?? (indicator as { value?: number }).value),
        series: Array.isArray(indicator.series)
          ? rollSeriesDates(indicator.series)
          : ((indicator as { sparkline?: number[] }).sparkline || []).map((value, index) => ({
              date: `p${index}`,
              value,
            })),
      }))
      .filter((indicator) => Number.isFinite(indicator.current) && indicator.series.length > 0);
  }

  prismLabel(prism?: string): string {
    switch (prism) {
      case 'matieres_premieres':
        return 'Matieres premieres';
      case 'souverainete_financiere':
        return 'Souverainete financiere';
      case 'securite_opinion':
        return 'Securite et opinion';
      case 'operationnel':
        return 'Operationnel';
      default:
        return 'Indicateur souverain';
    }
  }

  toggleExpand(key: string): void {
    this.expandedKey.update((current) => (current === key ? null : key));
  }

  formatValue(value: number): string {
    if (!Number.isFinite(value)) return '—';
    if (Math.abs(value) >= 1000) {
      return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(value);
    }
    if (Math.abs(value) >= 100) return value.toFixed(0);
    if (Math.abs(value) >= 10) return value.toFixed(1);
    return value.toFixed(2).replace(/\.?0+$/, '');
  }

  trendClass(indicator: MacroIndicator): 'up' | 'down' | 'flat' {
    if (indicator.trend_direction) return indicator.trend_direction;
    const series = indicator.series;
    if (series.length < 2) return 'flat';
    const last = series[series.length - 1].value;
    const prev = series[series.length - 2].value;
    if (last > prev + 0.01) return 'up';
    if (last < prev - 0.01) return 'down';
    return 'flat';
  }

  trendFallback(indicator: MacroIndicator): string {
    const direction = this.trendClass(indicator);
    if (direction === 'up') return '↗';
    if (direction === 'down') return '↘';
    return '→';
  }

  linePath(indicator: MacroIndicator, width = 120, height = 36): string {
    const series = indicator.series;
    if (!series.length) return '';
    return series
      .map((point, index) => {
        const coords = this.pointAt(indicator, index, width, height);
        return `${index === 0 ? 'M' : 'L'}${coords.x.toFixed(2)} ${coords.y.toFixed(2)}`;
      })
      .join(' ');
  }

  areaPath(indicator: MacroIndicator, width = 120, height = 36): string {
    const series = indicator.series;
    if (!series.length) return '';
    const line = this.linePath(indicator, width, height);
    return `${line} L${width} ${height} L0 ${height} Z`;
  }

  lastPoint(indicator: MacroIndicator, width = 120, height = 36): { x: number; y: number } {
    const series = indicator.series;
    if (!series.length) return { x: 0, y: height };
    return this.pointAt(indicator, series.length - 1, width, height);
  }

  firstLabel(indicator: MacroIndicator): string {
    const first = indicator.series[0];
    if (!first) return '';
    return String(first.year || first.date || '');
  }

  lastLabel(indicator: MacroIndicator): string {
    const last = indicator.series[indicator.series.length - 1];
    if (!last) return '';
    return String(last.year || last.date || '');
  }

  private pointAt(
    indicator: MacroIndicator,
    index: number,
    width: number,
    height: number,
  ): { x: number; y: number } {
    const series = indicator.series;
    const values = series.map((point) => point.value);
    const max = Math.max(...values);
    const min = Math.min(...values);
    const span = Math.max(max - min, 0.0001);
    const padding = 2;
    const usableHeight = height - padding * 2;
    const usableWidth = width - 2;
    const x = 1 + (index / Math.max(series.length - 1, 1)) * usableWidth;
    const ratio = (series[index].value - min) / span;
    const y = padding + (1 - ratio) * usableHeight;
    return { x, y };
  }
}
