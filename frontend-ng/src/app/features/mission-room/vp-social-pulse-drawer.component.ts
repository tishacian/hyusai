import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';

export interface SocialTweet {
  id?: string;
  kind?: string;
  handle?: string;
  author?: string;
  verified?: boolean;
  text?: string;
  language?: string;
  sentiment?: string;
  engagement?: number;
  retweets?: number;
  likes?: number;
  geo?: { label?: string; longitude?: number; latitude?: number } | null;
  posted_at?: string | null;
  tags?: string[];
}

export interface SocialSnapshot {
  captured_at?: string;
  window_label?: string;
  city_focus?: string;
  totals?: {
    tweets?: number;
    officiel?: number;
    citoyen?: number;
    rumeur?: number;
    engagement_total?: number;
    sentiment_positive?: number;
    sentiment_neutral?: number;
    sentiment_negative?: number;
  };
  tweets?: SocialTweet[];
}

type BucketKey = 'officiel' | 'citoyen' | 'rumeur';

interface BucketDescriptor {
  key: BucketKey;
  label: string;
  helper: string;
}

@Component({
  selector: 'app-vp-social-pulse-drawer',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (snapshot && (embedded || open)) {
      <div [class]="embedded ? 'social-embedded-root' : 'social-drawer-root'" [attr.role]="embedded ? null : 'dialog'" [attr.aria-modal]="embedded ? null : 'true'" [attr.aria-label]="i18n.t('mission.social.title')">
        @if (!embedded) {
          <button
            type="button"
            class="social-drawer-backdrop"
            [attr.aria-label]="i18n.t('common.close')"
            (click)="closed.emit()"
          ></button>
        }
        <aside [class]="embedded ? 'social-embedded-panel' : 'social-drawer-panel'">
          <header class="social-drawer-head">
            <div class="social-drawer-head-copy">
              <span class="mission-status-badge is-advisory">{{ i18n.t('mission.social.demo_safe') }}</span>
              <small class="publisher-badge">{{ i18n.t('mission.social.title') }} · {{ cityFocus() }}</small>
              <h2>{{ headerTitle() }}</h2>
              <p class="social-drawer-summary">{{ summarySentence() }}</p>
            </div>
            @if (!embedded) {
              <button
                type="button"
                class="social-drawer-close"
                [attr.aria-label]="i18n.t('common.close')"
                (click)="closed.emit()"
              >
                ×
              </button>
            }
          </header>

          <div class="social-drawer-body">
            <section class="social-stats" [attr.aria-label]="i18n.t('mission.social.stats')">
              <article class="stat-card mission-metric-tile">
                <span class="stat-label">{{ i18n.t('mission.social.stat.posts') }}</span>
                <strong>{{ totals().tweets ?? tweets().length }}</strong>
                <small>{{ i18n.t('mission.social.stat.day_sequence') }}</small>
              </article>
              <article class="stat-card mission-metric-tile">
                <span class="stat-label">{{ i18n.t('mission.social.stat.verified') }}</span>
                <strong>{{ totals().officiel ?? bucketCount('officiel') }}</strong>
                <small>{{ i18n.t('mission.social.stat.verified_hint') }}</small>
              </article>
              <article class="stat-card mission-metric-tile">
                <span class="stat-label">{{ i18n.t('mission.social.stat.citizens') }}</span>
                <strong>{{ totals().citoyen ?? bucketCount('citoyen') }}</strong>
                <small>{{ i18n.t('mission.social.stat.pseudonymised') }}</small>
              </article>
              <article class="stat-card mission-metric-tile is-watch warn">
                <span class="stat-label">{{ i18n.t('mission.social.stat.rumor') }}</span>
                <strong>{{ totals().rumeur ?? bucketCount('rumeur') }}</strong>
                <small>{{ i18n.t('mission.social.stat.rumor_hint') }}</small>
              </article>
            </section>

            <section class="social-sentiment" [attr.aria-label]="i18n.t('mission.social.tone')">
              <span class="eyebrow">{{ i18n.t('mission.social.tone') }}</span>
              <div class="sentiment-bar" role="img" [attr.aria-label]="sentimentAriaLabel()">
                <span class="sb-positive" [style.flex]="sentimentMix().positive"></span>
                <span class="sb-neutral" [style.flex]="sentimentMix().neutral"></span>
                <span class="sb-negative" [style.flex]="sentimentMix().negative"></span>
              </div>
              <ul class="sentiment-legend">
                <li class="positive"><span>{{ sentimentLabel('positive') }}</span><strong>{{ sentimentMix().positive }}</strong></li>
                <li class="neutral"><span>{{ sentimentLabel('neutral') }}</span><strong>{{ sentimentMix().neutral }}</strong></li>
                <li class="negative"><span>{{ sentimentLabel('negative') }}</span><strong>{{ sentimentMix().negative }}</strong></li>
                <li class="engagement"><span>{{ i18n.t('mission.social.engagement') }}</span><strong>{{ engagementTotal() }}</strong></li>
              </ul>
            </section>

            <section class="social-cluster" [attr.aria-label]="i18n.t('mission.social.cluster')">
              <span class="eyebrow">{{ i18n.t('mission.social.cluster_title', { city: cityFocus() }) }}</span>
              <svg class="cluster-svg" viewBox="0 0 320 140" preserveAspectRatio="none" aria-hidden="true">
                <rect class="cluster-bg" x="0" y="0" width="320" height="140" rx="6"></rect>
                @for (point of clusterPoints(); track point.id) {
                  <circle
                    [attr.cx]="point.x"
                    [attr.cy]="point.y"
                    [attr.r]="point.r"
                    [attr.class]="'cluster-dot ' + point.tone"
                  ></circle>
                }
              </svg>
              <div class="cluster-axis">
                @for (label of clusterLabels(); track label) {
                  <span>{{ label }}</span>
                }
              </div>
            </section>

            @for (bucket of bucketsWithTweets(); track bucket.descriptor.key) {
              <section class="social-section" [attr.aria-label]="bucket.descriptor.label">
                <button
                  type="button"
                  class="social-section-head"
                  [attr.aria-expanded]="!isCollapsed(bucket.descriptor.key)"
                  (click)="toggleSection(bucket.descriptor.key)"
                >
                  <span class="eyebrow" [class]="'eyebrow-' + bucket.descriptor.key">
                    {{ bucket.descriptor.label }} ({{ bucket.tweets.length }})
                  </span>
                  <small>{{ bucket.descriptor.helper }}</small>
                  <span class="caret" [class.open]="!isCollapsed(bucket.descriptor.key)" aria-hidden="true">▾</span>
                </button>

                @if (!isCollapsed(bucket.descriptor.key)) {
                  <div class="social-list">
                    @for (tweet of bucket.tweets; track tweet.id) {
                      <article class="tweet-card" [class]="'tweet-card--' + (tweet.kind || 'citoyen')">
                        <header class="tweet-card-head">
                          <span class="tweet-avatar" [attr.aria-hidden]="true">
                            {{ avatarInitial(tweet.handle) }}
                          </span>
                          <div class="tweet-handle">
                            <strong>{{ tweet.handle || '@anonyme' }}</strong>
                            @if (tweet.author) {
                              <small>{{ tweet.author }}</small>
                            }
                          </div>
                          <span class="tweet-kind-pill" [class]="'kind-' + (tweet.kind || 'citoyen')">
                            {{ kindLabel(tweet.kind) }}
                          </span>
                        </header>
                        <p class="tweet-text">{{ tweet.text }}</p>
                        <footer class="tweet-foot">
                          <span class="sentiment-chip" [class]="'sentiment-' + (tweet.sentiment || 'neutral')">
                            {{ sentimentLabel(tweet.sentiment) }}
                          </span>
                          <span class="tweet-engagement" [title]="i18n.t('mission.social.engagement_total')">
                            {{ tweet.engagement || 0 }} {{ i18n.t('mission.social.engagement_short') }}
                          </span>
                          @if (tweet.geo?.label) {
                            <span class="tweet-geo">· {{ tweet.geo?.label }}</span>
                          }
                          @if (tweet.posted_at) {
                            <span class="tweet-time">· {{ formatTime(tweet.posted_at) }}</span>
                          }
                        </footer>
                      </article>
                    }
                  </div>
                }
              </section>
            }
          </div>

          <footer class="social-drawer-foot mission-action-footer">
            <button type="button" class="action-link primary" (click)="askAya.emit()">
              {{ i18n.t('mission.social.send_to', { name: assistantName }) }}
            </button>
            <button type="button" class="action-link muted" (click)="closed.emit()">
              {{ i18n.t('common.close') }}
            </button>
          </footer>
        </aside>
      </div>
    }
  `,
  styles: [
    `
      :host { display: contents; }
      .social-drawer-root {
        position: fixed;
        inset: 0;
        z-index: 1300;
        display: flex;
        justify-content: flex-end;
      }
      .social-drawer-backdrop {
        position: absolute;
        inset: 0;
        border: 0;
        background: rgba(2, 6, 10, 0.62);
        backdrop-filter: blur(2px);
        cursor: pointer;
      }
      .social-drawer-panel {
        position: relative;
        width: min(600px, 100vw);
        height: 100%;
        display: flex;
        flex-direction: column;
        border-left: 1px solid var(--sentinel-accent-muted);
        background: rgba(4, 10, 14, 0.97);
        box-shadow: -16px 0 48px rgba(0, 0, 0, 0.45);
        animation: social-drawer-in 200ms var(--mission-ease-out);
      }
      @keyframes social-drawer-in {
        from { transform: translateX(16px); opacity: 0.6; }
        to   { transform: translateX(0);    opacity: 1; }
      }
      .social-drawer-head {
        position: sticky;
        top: 0;
        z-index: 2;
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--mission-space-3);
        padding: var(--mission-space-5);
        border-bottom: 1px solid var(--mission-border);
        background: rgba(4, 10, 14, 0.97);
      }
      .social-drawer-head-copy { min-width: 0; flex: 1 1 auto; }
      .social-drawer-head h2 {
        margin: var(--mission-space-2) 0 0;
        font-size: var(--mission-text-lg);
        line-height: 1.3;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .social-drawer-summary {
        margin: var(--mission-space-2) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .social-drawer-close {
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
      .social-drawer-close:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .social-drawer-close:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .social-drawer-body {
        flex: 1 1 auto;
        overflow-y: auto;
        padding: var(--mission-space-5);
        display: grid;
        gap: var(--mission-space-5);
      }
      .eyebrow {
        display: block;
        margin-bottom: var(--mission-space-2);
        color: var(--mission-accent);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .eyebrow-officiel { color: var(--mission-success); }
      .eyebrow-citoyen  { color: var(--mission-warning); }
      .eyebrow-rumeur   { color: var(--mission-orange); }

      .risk-pill {
        display: inline-flex;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
        color: var(--mission-text-secondary);
      }
      .risk-pill.stable {
        border-color: rgba(101, 214, 110, 0.32);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
      }
      .publisher-badge {
        display: inline-block;
        margin-left: 6px;
        padding: 3px 8px;
        border: 1px solid rgba(151, 185, 164, 0.18);
        border-radius: 999px;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }

      .social-stats {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: var(--mission-space-2);
      }
      .stat-card {
        display: grid;
        gap: 2px;
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .stat-card.warn { border-color: rgba(242, 140, 56, 0.32); }
      .stat-card .stat-label {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
      }
      .stat-card strong {
        font-size: 22px;
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--mission-text-primary);
      }
      .stat-card small {
        color: var(--mission-text-tertiary);
        font-size: 10px;
      }

      .social-sentiment .sentiment-bar {
        display: flex;
        height: 12px;
        border-radius: 999px;
        overflow: hidden;
        background: rgba(151, 185, 164, 0.12);
      }
      .sentiment-bar > span { display: block; }
      .sb-positive { background: var(--mission-success); }
      .sb-neutral  { background: rgba(151, 185, 164, 0.55); }
      .sb-negative { background: var(--mission-critical); }
      .sentiment-legend {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: var(--mission-space-2);
        margin: var(--mission-space-3) 0 0;
        padding: 0;
        list-style: none;
        font-family: var(--mission-font-mono);
        font-size: 11px;
      }
      .sentiment-legend li {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 6px;
        padding: 4px 8px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .sentiment-legend li span {
        color: var(--mission-text-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .sentiment-legend li strong {
        font-variant-numeric: tabular-nums;
        color: var(--mission-text-primary);
      }
      .sentiment-legend .positive   { border-color: rgba(63, 209, 141, 0.32); }
      .sentiment-legend .negative   { border-color: rgba(240, 100, 118, 0.32); }
      .sentiment-legend .engagement { border-color: rgba(101, 214, 110, 0.32); }

      .social-cluster .cluster-svg {
        width: 100%;
        height: 140px;
        display: block;
        border-radius: var(--mission-radius-sm);
        border: 1px solid var(--mission-border);
        background: rgba(4, 8, 13, 0.55);
      }
      .cluster-bg { fill: rgba(101, 214, 110, 0.04); }
      .cluster-dot {
        opacity: 0.85;
        fill: rgba(151, 185, 164, 0.55);
      }
      .cluster-dot.officiel { fill: var(--mission-success); }
      .cluster-dot.citoyen  { fill: var(--mission-warning); }
      .cluster-dot.rumeur   { fill: var(--mission-orange); }
      .cluster-axis {
        display: flex;
        justify-content: space-between;
        margin-top: var(--mission-space-2);
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .social-section {
        border-top: 1px solid var(--mission-border);
        padding-top: var(--mission-space-4);
      }
      .social-section-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--mission-space-2);
        width: 100%;
        padding: 0;
        border: 0;
        background: transparent;
        color: inherit;
        cursor: pointer;
      }
      .social-section-head small {
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .social-section-head .caret {
        margin-left: auto;
        color: var(--mission-text-tertiary);
        transition: transform var(--mission-dur-fast) var(--mission-ease-out);
      }
      .social-section-head .caret.open { transform: rotate(180deg); }
      .social-section-head:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
        border-radius: var(--mission-radius-sm);
      }

      .social-list {
        display: grid;
        gap: var(--mission-space-2);
        margin-top: var(--mission-space-3);
      }
      .tweet-card {
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-left-width: 3px;
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
        display: grid;
        gap: var(--mission-space-2);
      }
      .tweet-card--officiel { border-left-color: var(--mission-success); }
      .tweet-card--citoyen  { border-left-color: var(--mission-warning); }
      .tweet-card--rumeur   { border-left-color: var(--mission-orange); }

      .tweet-card-head {
        display: flex;
        align-items: center;
        gap: var(--mission-space-2);
      }
      .tweet-avatar {
        flex: 0 0 auto;
        width: 28px;
        height: 28px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: rgba(101, 214, 110, 0.16);
        color: var(--sentinel-accent-strong);
        font-family: var(--mission-font-mono);
        font-size: 12px;
        text-transform: uppercase;
      }
      .tweet-handle {
        display: grid;
        gap: 1px;
        flex: 1 1 auto;
        min-width: 0;
      }
      .tweet-handle strong {
        font-size: var(--mission-text-sm);
        color: var(--mission-text-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .tweet-handle small {
        color: var(--mission-text-tertiary);
        font-size: 10px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .tweet-kind-pill {
        flex: 0 0 auto;
        padding: 2px 8px;
        border-radius: 999px;
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        border: 1px solid var(--mission-border);
        color: var(--mission-text-secondary);
      }
      .kind-officiel {
        border-color: rgba(63, 209, 141, 0.42);
        background: var(--mission-success-soft);
        color: var(--mission-success);
      }
      .kind-citoyen {
        border-color: rgba(241, 180, 90, 0.42);
        background: var(--mission-warning-soft);
        color: var(--mission-warning);
      }
      .kind-rumeur {
        border-color: rgba(242, 140, 56, 0.45);
        background: var(--mission-orange-soft);
        color: var(--mission-orange);
      }

      .tweet-text {
        margin: 0;
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
        display: -webkit-box;
        -webkit-line-clamp: 4;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      .tweet-foot {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        color: var(--mission-text-tertiary);
      }
      .sentiment-chip {
        padding: 1px 7px;
        border-radius: 999px;
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        border: 1px solid var(--mission-border);
      }
      .sentiment-positive {
        border-color: rgba(63, 209, 141, 0.4);
        background: var(--mission-success-soft);
        color: var(--mission-success);
      }
      .sentiment-neutral {
        border-color: rgba(151, 185, 164, 0.32);
        color: var(--mission-text-secondary);
      }
      .sentiment-negative {
        border-color: rgba(240, 100, 118, 0.42);
        background: var(--mission-critical-soft);
        color: var(--mission-critical);
      }
      .tweet-engagement { color: var(--mission-text-secondary); font-variant-numeric: tabular-nums; }
      .tweet-geo, .tweet-time { color: var(--mission-text-tertiary); }

      .social-drawer-foot {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        padding: var(--mission-space-4) var(--mission-space-5);
        border-top: 1px solid var(--mission-border);
      }
      .action-link {
        display: inline-flex;
        align-items: center;
        min-height: 36px;
        padding: 8px 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
        cursor: pointer;
      }
      .action-link.primary {
        border-color: rgba(101, 214, 110, 0.42);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        font-weight: 600;
      }
      .action-link.primary:hover { background: rgba(101, 214, 110, 0.18); }
      .action-link.muted { background: transparent; color: var(--mission-text-secondary); }
      .action-link:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }

      @media (max-width: 540px) {
        .social-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .sentiment-legend { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (prefers-reduced-motion: reduce) {
        .social-drawer-panel { animation: none; }
      }
      .social-embedded-root { display: block; }
      .social-embedded-panel {
        position: relative;
        width: 100%;
        max-height: none;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-lg);
        background: rgba(8, 14, 20, 0.72);
        box-shadow: none;
        animation: none;
      }
    `,
  ],
})
export class VpSocialPulseDrawerComponent {
  readonly i18n = inject(I18nService);

  @Input() embedded = false;
  @Input() open = false;
  @Input() assistantName = 'AYA';
  @Input() snapshot: SocialSnapshot | null = null;
  @Output() closed = new EventEmitter<void>();
  @Output() askAya = new EventEmitter<void>();

  private readonly collapsed = signal<Record<BucketKey, boolean>>({
    officiel: false,
    citoyen: false,
    rumeur: false,
  });

  private get buckets(): BucketDescriptor[] {
    return [
      {
        key: 'officiel',
        label: this.i18n.t('mission.social.bucket.official'),
        helper: this.i18n.t('mission.social.bucket.official_hint'),
      },
      {
        key: 'citoyen',
        label: this.i18n.t('mission.social.bucket.citizen'),
        helper: this.i18n.t('mission.social.bucket.citizen_hint', { city: this.cityFocus() }),
      },
      {
        key: 'rumeur',
        label: this.i18n.t('mission.social.bucket.rumor'),
        helper: this.i18n.t('mission.social.bucket.rumor_hint'),
      },
    ];
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open) this.closed.emit();
  }

  cityFocus(): string {
    return this.snapshot?.city_focus || 'Abidjan';
  }

  headerTitle(): string {
    const window = this.snapshot?.window_label || this.i18n.t('mission.social.window_fallback');
    const captured = this.formatTime(this.snapshot?.captured_at);
    return captured ? `${window} (${captured})` : window;
  }

  totals(): NonNullable<SocialSnapshot['totals']> {
    return this.snapshot?.totals || {};
  }

  tweets(): SocialTweet[] {
    return this.snapshot?.tweets || [];
  }

  bucketCount(kind: BucketKey): number {
    return this.tweets().filter((tweet) => tweet.kind === kind).length;
  }

  engagementTotal(): string {
    const total = this.totals().engagement_total
      ?? this.tweets().reduce((acc, tweet) => acc + (Number(tweet.engagement) || 0), 0);
    if (total >= 1000) return `${(total / 1000).toFixed(1)}k`;
    return String(total);
  }

  sentimentMix(): { positive: number; neutral: number; negative: number } {
    const totals = this.totals();
    const fromTotals = {
      positive: totals.sentiment_positive,
      neutral: totals.sentiment_neutral,
      negative: totals.sentiment_negative,
    };
    if (
      typeof fromTotals.positive === 'number'
      && typeof fromTotals.neutral === 'number'
      && typeof fromTotals.negative === 'number'
    ) {
      return fromTotals as { positive: number; neutral: number; negative: number };
    }
    const counts = { positive: 0, neutral: 0, negative: 0 };
    for (const tweet of this.tweets()) {
      const key = (tweet.sentiment || 'neutral').toLowerCase();
      if (key.includes('positi')) counts.positive += 1;
      else if (key.includes('negati')) counts.negative += 1;
      else counts.neutral += 1;
    }
    return counts;
  }

  sentimentAriaLabel(): string {
    const mix = this.sentimentMix();
    return this.i18n.t('mission.social.tone_aria', {
      positive: mix.positive,
      neutral: mix.neutral,
      negative: mix.negative,
    });
  }

  bucketsWithTweets(): { descriptor: BucketDescriptor; tweets: SocialTweet[] }[] {
    return this.buckets.map((descriptor) => ({
      descriptor,
      tweets: this.tweets().filter((tweet) => (tweet.kind || 'citoyen') === descriptor.key),
    })).filter((bucket) => bucket.tweets.length > 0);
  }

  isCollapsed(key: BucketKey): boolean {
    return !!this.collapsed()[key];
  }

  toggleSection(key: BucketKey): void {
    const next = { ...this.collapsed() };
    next[key] = !next[key];
    this.collapsed.set(next);
  }

  avatarInitial(handle?: string): string {
    if (!handle) return '?';
    const cleaned = handle.replace(/^@/, '').trim();
    return (cleaned[0] || '?').toUpperCase();
  }

  kindLabel(kind?: string): string {
    if (kind === 'officiel') return this.i18n.t('mission.social.kind.official');
    if (kind === 'rumeur') return this.i18n.t('mission.social.kind.rumor');
    return this.i18n.t('mission.social.kind.citizen');
  }

  sentimentLabel(sentiment?: string): string {
    const key = (sentiment || 'neutral').toLowerCase();
    if (key.includes('positi')) return this.i18n.t('mission.social.sentiment.positive');
    if (key.includes('negati')) return this.i18n.t('mission.social.sentiment.negative');
    return this.i18n.t('mission.social.sentiment.neutral');
  }

  formatTime(value?: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    return `${hh}h${mm}`;
  }

  summarySentence(): string {
    const totals = this.totals();
    const total = totals.tweets ?? this.tweets().length;
    const officiels = totals.officiel ?? this.bucketCount('officiel');
    const citoyens = totals.citoyen ?? this.bucketCount('citoyen');
    const rumeur = totals.rumeur ?? this.bucketCount('rumeur');
    return this.i18n.t('mission.social.summary', {
      total,
      verified: officiels,
      citizens: citoyens,
      rumors: rumeur,
    });
  }

  readonly clusterPoints = computed(() => {
    const tweets = this.tweets();
    if (!tweets.length) return [];
    let minLon = Infinity;
    let maxLon = -Infinity;
    let minLat = Infinity;
    let maxLat = -Infinity;
    const located = tweets.filter((tweet) =>
      Number.isFinite(Number(tweet.geo?.longitude))
      && Number.isFinite(Number(tweet.geo?.latitude)),
    );
    if (!located.length) return [];
    for (const tweet of located) {
      const lon = Number(tweet.geo?.longitude);
      const lat = Number(tweet.geo?.latitude);
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
    const lonSpan = Math.max(maxLon - minLon, 0.01);
    const latSpan = Math.max(maxLat - minLat, 0.01);
    return located.map((tweet, index) => {
      const lon = Number(tweet.geo?.longitude);
      const lat = Number(tweet.geo?.latitude);
      const x = 16 + ((lon - minLon) / lonSpan) * 288;
      const y = 16 + (1 - (lat - minLat) / latSpan) * 108;
      const engagement = Number(tweet.engagement) || 1;
      const r = 3 + Math.min(7, Math.log10(engagement + 1) * 2.4);
      return {
        id: tweet.id || `pt-${index}`,
        x: Number.isFinite(x) ? x : 160,
        y: Number.isFinite(y) ? y : 70,
        r,
        tone: tweet.kind || 'citoyen',
      };
    });
  });

  clusterLabels(): string[] {
    const tweets = this.tweets();
    if (!tweets.length) return [];
    const seen = new Set<string>();
    const labels: string[] = [];
    for (const tweet of tweets) {
      const label = tweet.geo?.label;
      if (!label) continue;
      if (seen.has(label)) continue;
      seen.add(label);
      labels.push(label);
      if (labels.length >= 4) break;
    }
    return labels;
  }
}
