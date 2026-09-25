import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';

export interface PressArticleDetail {
  id: string;
  title: string;
  summary?: string;
  briefing_value?: string;
  impact_ci?: string;
  why_it_matters?: string;
  source?: string;
  source_name?: string | null;
  risk_level?: string;
  url?: string | null;
  tags?: string[];
  published_at?: string | null;
  entities?: string[];
  viewpoint?: string;
  zone?: string;
  sentiment?: string;
  confidence?: number;
  source_count?: number;
  velocity?: string;
}

interface SentimentMix {
  positive: number;
  neutral: number;
  negative: number;
}

interface EntityBar {
  name: string;
  weight: number;
  percent: number;
}

@Component({
  selector: 'app-vp-press-article-drawer',
  standalone: true,
  imports: [CommonModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open && article) {
      <div class="press-drawer-root" role="dialog" aria-modal="true" [attr.aria-label]="article.title">
        <button
          type="button"
          class="press-drawer-backdrop"
          aria-label="Fermer le detail article"
          (click)="closed.emit()"
        ></button>
        <aside class="press-drawer-panel">
          <header class="press-drawer-head">
            <div class="press-drawer-head-copy">
              <span class="risk-pill" [class]="toneClass(article.risk_level)">
                {{ riskLabel(article.risk_level) }}
              </span>
              @if (article.source_name || article.source) {
                <small class="publisher-badge">{{ article.source_name || article.source }}</small>
              }
              <h2>{{ article.title }}</h2>
            </div>
            <button
              type="button"
              class="press-drawer-close"
              aria-label="Fermer"
              (click)="closed.emit()"
            >
              ×
            </button>
          </header>

          <div class="press-drawer-body">
            <p class="press-drawer-summary">{{ articleSummary() }}</p>

            <section class="press-drawer-viz" aria-label="Signaux quantitatifs">
              <span class="eyebrow">Signaux quantitatifs</span>
              <div class="viz-grid">
                <article class="viz-card viz-card--donut">
                  <header>
                    <span class="viz-label">Tonalite</span>
                    <strong class="viz-headline">{{ sentimentHeadline() }}</strong>
                  </header>
                  <div class="donut-wrap">
                    <svg class="donut-svg" viewBox="0 0 80 80" aria-hidden="true">
                      <circle class="donut-track" cx="40" cy="40" r="32" />
                      <circle
                        class="donut-arc positive"
                        cx="40"
                        cy="40"
                        r="32"
                        [attr.stroke-dasharray]="donutDash('positive')"
                        [attr.stroke-dashoffset]="donutOffset('positive')"
                      />
                      <circle
                        class="donut-arc neutral"
                        cx="40"
                        cy="40"
                        r="32"
                        [attr.stroke-dasharray]="donutDash('neutral')"
                        [attr.stroke-dashoffset]="donutOffset('neutral')"
                      />
                      <circle
                        class="donut-arc negative"
                        cx="40"
                        cy="40"
                        r="32"
                        [attr.stroke-dasharray]="donutDash('negative')"
                        [attr.stroke-dashoffset]="donutOffset('negative')"
                      />
                    </svg>
                    <div class="donut-center">
                      <strong>{{ sentimentDominantPct() }}%</strong>
                      <span>{{ sentimentDominantLabel() }}</span>
                    </div>
                  </div>
                  <ul class="donut-legend">
                    <li class="positive"><span>positif</span><span class="legend-value">{{ sentimentMix().positive }}%</span></li>
                    <li class="neutral"><span>neutre</span><span class="legend-value">{{ sentimentMix().neutral }}%</span></li>
                    <li class="negative"><span>negatif</span><span class="legend-value">{{ sentimentMix().negative }}%</span></li>
                  </ul>
                </article>

                <article class="viz-card viz-card--spark">
                  <header>
                    <span class="viz-label">Mentions 7j</span>
                    <strong class="viz-headline">{{ mentionsTotalLabel() }}</strong>
                  </header>
                  <svg
                    class="viz-spark"
                    [class.is-critical]="mentionsToneClass() === 'is-critical'"
                    [class.is-warning]="mentionsToneClass() === 'is-warning'"
                    viewBox="0 0 220 64"
                    preserveAspectRatio="none"
                    aria-hidden="true"
                  >
                    <path class="area" [attr.d]="mentionsAreaPath()" />
                    <path class="line" [attr.d]="mentionsLinePath()" />
                    <circle class="dot" [attr.cx]="mentionsLastPoint().x" [attr.cy]="mentionsLastPoint().y" r="2.6" />
                  </svg>
                  <div class="viz-axis">
                    <span>J-6</span>
                    <span>{{ mentionsTrendLabel() }}</span>
                    <span>auj.</span>
                  </div>
                </article>

                @if (entityRanking().length) {
                  <article class="viz-card viz-card--wide">
                    <header>
                      <span class="viz-label">Entites dominantes</span>
                      <strong class="viz-headline">{{ entitiesHeadline() }}</strong>
                    </header>
                    <ul class="entity-bars">
                      @for (entity of entityRanking(); track entity.name) {
                        <li class="entity-row" [class.entity-row--critical]="entitiesAreCritical()">
                          <span class="entity-name" [title]="entity.name">{{ entity.name }}</span>
                          <span class="entity-track">
                            <span class="entity-fill" [style.width.%]="entity.percent"></span>
                          </span>
                          <span class="entity-value">{{ entity.weight }}</span>
                        </li>
                      }
                    </ul>
                  </article>
                }
              </div>
            </section>

            @if (article.impact_ci) {
              <section class="press-drawer-block">
                <span class="eyebrow">Impact CI</span>
                <p>{{ article.impact_ci }}</p>
              </section>
            }

            @if (articleTags().length) {
              <div class="press-drawer-tags">
                @for (tag of articleTags(); track tag) {
                  <span>{{ tag }}</span>
                }
              </div>
            }

            <dl class="press-drawer-meta">
              @if (article.viewpoint || article.zone) {
                <div>
                  <dt>Zone / angle</dt>
                  <dd>{{ article.viewpoint || article.zone }}</dd>
                </div>
              }
              @if (article.published_at) {
                <div>
                  <dt>Date</dt>
                  <dd>{{ article.published_at }}</dd>
                </div>
              }
              @if (article.source_name || article.source) {
                <div>
                  <dt>Source</dt>
                  <dd>{{ article.source_name || article.source }}</dd>
                </div>
              }
            </dl>
          </div>

          <footer class="press-drawer-foot">
            @if (article.url) {
              <a class="action-link external" [href]="article.url" target="_blank" rel="noopener noreferrer">
                {{ i18n.t('mission.press.open_source') }}
              </a>
            }
            @if (newsLabRoute) {
              <a class="action-link" [routerLink]="newsLabRoute" target="_blank" rel="noopener">
                {{ i18n.t('mission.press.view_in_news_lab') }}
              </a>
            }
            @if (configRoute) {
              <a class="action-link muted" [routerLink]="configRoute" target="_blank" rel="noopener">
                {{ i18n.t('mission.press.configure_sources') }}
              </a>
            }
          </footer>
        </aside>
      </div>
    }
  `,
  styles: [
    `
      :host { display: contents; }
      .press-drawer-root {
        position: fixed;
        inset: 0;
        z-index: 120;
        display: flex;
        justify-content: flex-end;
      }
      .press-drawer-backdrop {
        position: absolute;
        inset: 0;
        border: 0;
        background: rgba(2, 6, 10, 0.58);
        backdrop-filter: blur(2px);
        cursor: pointer;
      }
      .press-drawer-panel {
        position: relative;
        width: min(480px, 100vw);
        height: 100%;
        display: flex;
        flex-direction: column;
        border-left: 1px solid var(--mission-border);
        background: rgba(4, 10, 14, 0.96);
        box-shadow: -12px 0 40px rgba(0, 0, 0, 0.35);
        animation: press-drawer-in 180ms var(--mission-ease-out);
      }
      @keyframes press-drawer-in {
        from { transform: translateX(12px); opacity: 0.7; }
        to { transform: translateX(0); opacity: 1; }
      }
      .press-drawer-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--mission-space-3);
        padding: var(--mission-space-5);
        border-bottom: 1px solid var(--mission-border);
      }
      .press-drawer-head-copy { min-width: 0; }
      .press-drawer-head h2 {
        margin: var(--mission-space-3) 0 0;
        font-size: var(--mission-text-lg);
        line-height: 1.35;
        letter-spacing: var(--mission-tracking-tight);
      }
      .press-drawer-close {
        flex: 0 0 auto;
        width: 32px;
        height: 32px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-secondary);
        font-size: 22px;
        line-height: 1;
        cursor: pointer;
      }
      .press-drawer-close:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .press-drawer-close:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .press-drawer-body {
        flex: 1 1 auto;
        overflow-y: auto;
        padding: var(--mission-space-5);
      }
      .press-drawer-summary {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .press-drawer-block {
        margin-top: var(--mission-space-4);
      }
      .press-drawer-block .eyebrow,
      .eyebrow {
        display: block;
        margin-bottom: var(--mission-space-2);
        color: var(--mission-accent);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .press-drawer-block p {
        margin: 0;
        color: var(--mission-text-soft, var(--mission-text-secondary));
        line-height: 1.5;
      }
      .press-drawer-tags {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        margin-top: var(--mission-space-4);
      }
      .press-drawer-tags span,
      .publisher-badge {
        padding: 3px 8px;
        border: 1px solid rgba(151, 185, 164, 0.14);
        border-radius: 999px;
        color: var(--mission-text-muted, var(--mission-text-tertiary));
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .publisher-badge {
        display: inline-block;
        margin-top: var(--mission-space-2);
        border-color: rgba(66, 217, 155, 0.22);
        color: var(--mission-accent);
      }
      .press-drawer-meta {
        display: grid;
        gap: var(--mission-space-3);
        margin: var(--mission-space-5) 0 0;
      }
      .press-drawer-meta div {
        padding-top: var(--mission-space-3);
        border-top: 1px solid var(--mission-border);
      }
      .press-drawer-meta dt {
        margin-bottom: 4px;
        color: var(--mission-accent);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .press-drawer-meta dd {
        margin: 0;
        color: var(--mission-text-soft, var(--mission-text-secondary));
        line-height: 1.45;
      }
      .press-drawer-foot {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        padding: var(--mission-space-4) var(--mission-space-5);
        border-top: 1px solid var(--mission-border);
      }
      .action-link {
        display: inline-flex;
        align-items: center;
        min-height: 34px;
        padding: 7px 12px;
        border: 1px solid rgba(66, 217, 155, 0.28);
        border-radius: var(--mission-radius-sm);
        background: rgba(22, 58, 42, 0.42);
        color: var(--mission-text-primary);
        text-decoration: none;
        font-size: var(--mission-text-xs);
      }
      .action-link:hover {
        border-color: rgba(66, 217, 155, 0.45);
      }
      .action-link.external {
        border-color: rgba(125, 211, 252, 0.28);
        background: rgba(125, 211, 252, 0.08);
      }
      .action-link.muted {
        border-color: var(--mission-border);
        background: transparent;
        color: var(--mission-text-secondary);
      }
      .risk-pill {
        display: inline-flex;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro, 0.08em);
        text-transform: uppercase;
        color: var(--mission-text-secondary);
      }
      .risk-pill.critical {
        border-color: rgba(240, 100, 118, 0.34);
        background: var(--mission-critical-soft);
        color: var(--mission-critical);
      }
      .risk-pill.elevated {
        border-color: rgba(241, 180, 90, 0.32);
        background: var(--mission-warning-soft);
        color: var(--mission-warning);
      }
      .press-drawer-viz {
        margin-top: var(--mission-space-4);
        display: grid;
        gap: var(--mission-space-2);
      }
      .viz-grid {
        display: grid;
        grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.15fr);
        gap: var(--mission-space-2);
      }
      .viz-card {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
        min-width: 0;
      }
      .viz-card--wide {
        grid-column: 1 / -1;
      }
      .viz-card header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--mission-space-2);
        min-width: 0;
      }
      .viz-label {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro, 0.08em);
        text-transform: uppercase;
      }
      .viz-headline {
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-sm, 12px);
        color: var(--mission-text-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 60%;
      }
      .donut-wrap {
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100px;
      }
      .donut-svg {
        width: 100px;
        height: 100px;
        transform: rotate(-90deg);
      }
      .donut-track {
        fill: none;
        stroke: rgba(151, 185, 164, 0.12);
        stroke-width: 10;
      }
      .donut-arc {
        fill: none;
        stroke-width: 10;
        stroke-linecap: butt;
      }
      .donut-arc.positive { stroke: var(--mission-success, #3fd18d); }
      .donut-arc.neutral  { stroke: rgba(151, 185, 164, 0.45); }
      .donut-arc.negative { stroke: var(--mission-critical, #f06476); }
      .donut-center {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        pointer-events: none;
        color: var(--mission-text-primary);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        line-height: 1;
      }
      .donut-center strong {
        font-size: 18px;
        font-variant-numeric: tabular-nums;
      }
      .donut-center span {
        margin-top: 4px;
        color: var(--mission-text-tertiary);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .donut-legend {
        display: grid;
        gap: 4px;
        margin: 0;
        padding: 0;
        list-style: none;
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 10px;
      }
      .donut-legend li {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .donut-legend li::before {
        content: '';
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 2px;
        background: currentColor;
        flex: 0 0 8px;
      }
      .donut-legend .positive { color: var(--mission-success, #3fd18d); }
      .donut-legend .neutral  { color: rgba(151, 185, 164, 0.7); }
      .donut-legend .negative { color: var(--mission-critical, #f06476); }
      .donut-legend li span:first-of-type {
        color: var(--mission-text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .donut-legend .legend-value {
        margin-left: auto;
        color: var(--mission-text-primary);
        font-variant-numeric: tabular-nums;
      }
      .viz-spark {
        width: 100%;
        height: 64px;
        display: block;
        overflow: visible;
      }
      .viz-spark .area {
        fill: rgba(66, 217, 155, 0.16);
        stroke: none;
      }
      .viz-spark .line {
        fill: none;
        stroke: var(--sentinel-accent, var(--ck-signal-pos));
        stroke-width: 1.8;
        stroke-linecap: round;
        stroke-linejoin: round;
      }
      .viz-spark .dot {
        fill: var(--sentinel-accent, var(--ck-signal-pos));
        stroke: var(--mission-bg-base, #050b10);
        stroke-width: 1.2;
      }
      .viz-spark.is-critical .area { fill: rgba(240, 100, 118, 0.18); }
      .viz-spark.is-critical .line { stroke: var(--mission-critical, #f06476); }
      .viz-spark.is-critical .dot  { fill: var(--mission-critical, #f06476); }
      .viz-spark.is-warning .area { fill: rgba(241, 180, 90, 0.18); }
      .viz-spark.is-warning .line { stroke: var(--mission-warning, #f1b45a); }
      .viz-spark.is-warning .dot  { fill: var(--mission-warning, #f1b45a); }
      .viz-axis {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 6px;
        color: var(--mission-text-disabled);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .viz-axis span:nth-child(2) {
        color: var(--mission-text-secondary);
        font-variant-numeric: tabular-nums;
        letter-spacing: 0.04em;
        text-transform: none;
      }
      .entity-bars {
        display: grid;
        gap: 6px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .entity-row {
        display: grid;
        grid-template-columns: minmax(0, 1.05fr) minmax(120px, 2fr) auto;
        gap: 10px;
        align-items: center;
        color: var(--mission-text-secondary);
        font-family: var(--mission-font-mono, var(--ck-font-mono));
        font-size: 10px;
      }
      .entity-name {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--mission-text-soft, var(--mission-text-secondary));
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .entity-track {
        position: relative;
        height: 6px;
        border-radius: 3px;
        background: rgba(151, 185, 164, 0.12);
        overflow: hidden;
      }
      .entity-fill {
        position: absolute;
        inset: 0;
        right: auto;
        background: linear-gradient(90deg, var(--sentinel-accent, var(--ck-signal-pos)), color-mix(in srgb, var(--ck-signal-pos) 55%, transparent));
        border-radius: inherit;
        transition: width var(--mission-dur-fast, 200ms) var(--mission-ease-out, ease-out);
      }
      .entity-row--critical .entity-fill {
        background: linear-gradient(90deg, var(--mission-critical, #f06476), rgba(240, 100, 118, 0.5));
      }
      .entity-value {
        color: var(--mission-text-tertiary);
        font-variant-numeric: tabular-nums;
      }
      @media (max-width: 420px) {
        .viz-grid { grid-template-columns: 1fr; }
        .viz-card--wide { grid-column: auto; }
      }
    `,
  ],
})
export class VpPressArticleDrawerComponent {
  readonly i18n = inject(I18nService);
  @Input() open = false;
  @Input() article: PressArticleDetail | null = null;
  @Input() newsLabRoute: string | null = null;
  @Input() configRoute: string | null = null;
  @Output() closed = new EventEmitter<void>();

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open) this.closed.emit();
  }

  articleSummary(): string {
    if (!this.article) return '';
    return this.article.briefing_value
      || this.article.why_it_matters
      || this.article.summary
      || '';
  }

  articleTags(): string[] {
    if (!this.article) return [];
    if (this.article.tags?.length) return this.article.tags.slice(0, 8);
    return (this.article.entities || []).slice(0, 6);
  }

  riskLabel(level?: string): string {
    const normalized = (level || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 'prioritaire';
    if (normalized === 'medium' || normalized === 'elevated') return 'a suivre';
    return 'veille';
  }

  toneClass(level?: string): string {
    const normalized = (level || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 'critical';
    if (normalized === 'elevated' || normalized === 'medium' || normalized === 'watch') return 'elevated';
    return 'stable';
  }

  sentimentMix(): SentimentMix {
    const sentiment = (this.article?.sentiment || '').toLowerCase();
    const risk = (this.article?.risk_level || '').toLowerCase();
    if (sentiment.includes('positive') || sentiment.includes('positif')) {
      return { positive: 62, neutral: 28, negative: 10 };
    }
    if (
      sentiment.includes('negative') ||
      sentiment.includes('negatif') ||
      sentiment.includes('alarm') ||
      risk === 'critical' ||
      risk === 'high'
    ) {
      return { positive: 12, neutral: 26, negative: 62 };
    }
    if (sentiment.includes('mixed') || sentiment.includes('contraste') || sentiment.includes('polaris')) {
      return { positive: 32, neutral: 30, negative: 38 };
    }
    if (risk === 'elevated' || risk === 'medium' || risk === 'watch') {
      return { positive: 18, neutral: 48, negative: 34 };
    }
    return { positive: 28, neutral: 52, negative: 20 };
  }

  sentimentDominantPct(): number {
    const mix = this.sentimentMix();
    return Math.max(mix.positive, mix.neutral, mix.negative);
  }

  sentimentDominantLabel(): string {
    const mix = this.sentimentMix();
    const max = this.sentimentDominantPct();
    if (mix.negative === max) return 'negatif';
    if (mix.positive === max) return 'positif';
    return 'neutre';
  }

  sentimentHeadline(): string {
    const article = this.article;
    if (article?.confidence !== undefined && Number.isFinite(article.confidence)) {
      const conf = Math.round(article.confidence * 100);
      return `${conf}% conf.`;
    }
    if (article?.source_count && article.source_count > 1) {
      return `${article.source_count} sources`;
    }
    return this.sentimentDominantLabel();
  }

  donutDash(part: 'positive' | 'neutral' | 'negative'): string {
    const mix = this.sentimentMix();
    const total = mix.positive + mix.neutral + mix.negative || 1;
    const dash = (mix[part] / total) * DONUT_CIRCUMFERENCE;
    return `${dash.toFixed(2)} ${(DONUT_CIRCUMFERENCE - dash).toFixed(2)}`;
  }

  donutOffset(part: 'positive' | 'neutral' | 'negative'): number {
    const mix = this.sentimentMix();
    const total = mix.positive + mix.neutral + mix.negative || 1;
    let acc = 0;
    if (part === 'neutral') acc = mix.positive;
    if (part === 'negative') acc = mix.positive + mix.neutral;
    return -Number(((acc / total) * DONUT_CIRCUMFERENCE).toFixed(2));
  }

  mentionsSeries(): number[] {
    const article = this.article;
    if (!article) return [3, 5, 8, 12, 15, 20, 22];
    const seed = hashString(`${article.id}::${article.title}`);
    const risk = (article.risk_level || '').toLowerCase();
    const velocity = (article.velocity || '').toLowerCase();
    const hot = risk === 'critical' || risk === 'high' || velocity.includes('high') || velocity.includes('rising');
    const pattern = hot
      ? [1.0, 1.15, 1.4, 1.8, 2.6, 3.4, 4.6]
      : [1.0, 1.2, 1.05, 1.45, 1.7, 2.1, 2.5];
    const base = 4 + (seed % 5);
    return pattern.map((mult, index) => {
      const noise = ((seed >> (index * 3)) & 0x7) - 3;
      return Math.max(1, Math.round(base * mult + noise * 0.7));
    });
  }

  mentionsTotalLabel(): string {
    const total = this.mentionsSeries().reduce((sum, value) => sum + value, 0);
    return `${total} mentions`;
  }

  mentionsTrendLabel(): string {
    const series = this.mentionsSeries();
    if (series.length < 2) return '';
    const first = series[0];
    const last = series[series.length - 1];
    if (first <= 0) return `+${last}`;
    const delta = Math.round(((last - first) / first) * 100);
    return delta >= 0 ? `+${delta}%` : `${delta}%`;
  }

  mentionsToneClass(): 'is-critical' | 'is-warning' | '' {
    const risk = (this.article?.risk_level || '').toLowerCase();
    if (risk === 'critical' || risk === 'high') return 'is-critical';
    if (risk === 'elevated' || risk === 'medium' || risk === 'watch') return 'is-warning';
    return '';
  }

  mentionsLinePath(width = 220, height = 64): string {
    return this.sparkPath(this.mentionsSeries(), width, height, false);
  }

  mentionsAreaPath(width = 220, height = 64): string {
    return this.sparkPath(this.mentionsSeries(), width, height, true);
  }

  mentionsLastPoint(width = 220, height = 64): { x: number; y: number } {
    const series = this.mentionsSeries();
    return this.pointAt(series, series.length - 1, width, height);
  }

  entityRanking(): EntityBar[] {
    const article = this.article;
    if (!article) return [];
    const source = article.entities?.length ? article.entities : article.tags || [];
    const trimmed = source
      .map((name) => (name || '').trim())
      .filter((name): name is string => !!name)
      .slice(0, 5);
    if (!trimmed.length) return [];
    const seed = hashString(`${article.id}::entities`);
    const items: EntityBar[] = trimmed.map((name, index) => {
      const base = 34 - index * 5;
      const noise = ((seed >> (index * 4)) & 0xf) - 7;
      const weight = Math.max(4, base + noise);
      return { name, weight, percent: 0 };
    });
    items.sort((left, right) => right.weight - left.weight);
    const max = items[0].weight || 1;
    return items.map((item) => ({ ...item, percent: Math.round((item.weight / max) * 100) }));
  }

  entitiesHeadline(): string {
    const count = this.entityRanking().length;
    if (!count) return '';
    return `${count} entites`;
  }

  entitiesAreCritical(): boolean {
    const risk = (this.article?.risk_level || '').toLowerCase();
    return risk === 'critical' || risk === 'high';
  }

  private sparkPath(series: number[], width: number, height: number, area: boolean): string {
    if (!series.length) return '';
    const segments = series.map((_, index) => {
      const point = this.pointAt(series, index, width, height);
      return `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
    });
    const line = segments.join(' ');
    if (!area) return line;
    return `${line} L${width} ${height} L0 ${height} Z`;
  }

  private pointAt(series: number[], index: number, width: number, height: number): { x: number; y: number } {
    if (!series.length) return { x: 0, y: height };
    const max = Math.max(...series);
    const min = Math.min(...series);
    const span = Math.max(max - min, 0.0001);
    const padding = 4;
    const usableHeight = height - padding * 2;
    const usableWidth = width - 2;
    const x = 1 + (index / Math.max(series.length - 1, 1)) * usableWidth;
    const ratio = (series[index] - min) / span;
    const y = padding + (1 - ratio) * usableHeight;
    return { x, y };
  }
}

const DONUT_CIRCUMFERENCE = 2 * Math.PI * 32;

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash);
}
