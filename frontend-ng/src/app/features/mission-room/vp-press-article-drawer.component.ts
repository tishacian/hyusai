import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

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
                Ouvrir la source
              </a>
            }
            @if (newsLabRoute) {
              <a class="action-link" [routerLink]="newsLabRoute" target="_blank" rel="noopener">
                Voir dans News Lab
              </a>
            }
            @if (configRoute) {
              <a class="action-link muted" [routerLink]="configRoute" target="_blank" rel="noopener">
                Configurer les sources
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
    `,
  ],
})
export class VpPressArticleDrawerComponent {
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
}
