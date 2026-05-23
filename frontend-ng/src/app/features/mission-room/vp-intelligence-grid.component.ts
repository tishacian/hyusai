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
        <button
          type="button"
          class="intel-card"
          [class]="toneClass(feed.tone)"
          (click)="feedSelected.emit(feed)"
        >
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
        </button>
      }
    </div>
  `,
  styles: [
    `
      :host { display: block; }
      .intel-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: var(--mission-space-3);
      }
      .intel-card {
        min-width: 0;
        min-height: 96px;
        display: grid;
        grid-template-rows: auto 1fr auto;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.58);
        width: 100%;
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
      .intel-card:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .intel-card:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .intel-card:active { transform: translateY(1px); }
      .intel-card.critical { border-left: 3px solid var(--mission-critical); }
      .intel-card.elevated { border-left: 3px solid var(--mission-warning); }
      .intel-card.stable   { border-left: 3px solid var(--mission-success); }
      header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--mission-space-2);
      }
      header span {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      header strong {
        color: var(--sentinel-accent);
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-sm);
        font-weight: 600;
        white-space: nowrap;
      }
      p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-xs);
        line-height: var(--mission-lh-body);
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      footer {
        display: flex;
        justify-content: space-between;
        gap: var(--mission-space-2);
      }
      footer small {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      @media (max-width: 1280px) {
        .intel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (max-width: 640px) {
        .intel-grid { grid-template-columns: 1fr; }
      }
    `,
  ],
})
export class VpIntelligenceGridComponent {
  @Input() feeds: VpIntelligenceFeed[] = [];
  @Output() feedSelected = new EventEmitter<VpIntelligenceFeed>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }
}
