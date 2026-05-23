import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { VpIntelligenceFeed } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-intelligence-grid',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="intel-grid" aria-label="Flux de renseignement">
      @for (feed of feeds; track feed.key) {
        <article [class]="toneClass(feed.tone)">
          <header>
            <span>{{ feed.label }}</span>
            <strong>{{ feed.metric }}</strong>
          </header>
          <p>{{ feed.subtitle }}</p>
          <footer>
            <small>confiance {{ feed.confidence }}%</small>
            @if (feed.freshness_at) {
              <small>{{ feed.freshness_at }}</small>
            }
          </footer>
        </article>
      }
    </div>
  `,
  styles: [
    `
      :host { display: block; }
      .intel-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
      }
      article {
        min-width: 0;
        padding: 11px 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.58);
      }
      article.critical { border-left: 3px solid var(--mission-danger); }
      article.elevated { border-left: 3px solid var(--mission-warn); }
      article.stable { border-left: 3px solid var(--mission-trust); }
      header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
      }
      header span {
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      header strong {
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 12px;
        font-weight: 700;
        white-space: nowrap;
      }
      p {
        margin: 0;
        color: var(--mission-text-soft);
        font-size: 11px;
        line-height: 1.4;
      }
      footer {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        margin-top: 8px;
      }
      footer small {
        color: var(--mission-text-faint);
        font-family: var(--ck-font-mono);
        font-size: 9px;
      }
      @media (max-width: 1280px) {
        .intel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
    `,
  ],
})
export class VpIntelligenceGridComponent {
  @Input() feeds: VpIntelligenceFeed[] = [];

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }
}
