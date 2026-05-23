import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { VpArbitrationCard } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-arbitration-strip',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="arb-strip" aria-label="Sujets à arbitrer">
      <header class="arb-strip-head">
        <div>
          <span class="eyebrow">Sujets à arbitrer</span>
          <h2>
            <strong>{{ cards.length }}</strong>
            <span>décision{{ cards.length > 1 ? 's' : '' }} ce matin</span>
          </h2>
        </div>
      </header>

      @if (!cards.length) {
        <div class="arb-empty" role="status">
          <span class="arb-empty-icon" aria-hidden="true">○</span>
          <strong>File d'arbitrages vide</strong>
          <small>AYA pousse les sujets dès qu'un dossier requiert un arbitrage VP.</small>
        </div>
      } @else {
        <ul class="arb-cards" role="list">
          @for (card of cards; track card.id) {
            <li class="arb-card-wrap">
              <button
                type="button"
                class="arb-card"
                [class.critical]="toneClass(card.tone) === 'critical'"
                [class.elevated]="toneClass(card.tone) === 'elevated'"
                [class.stable]="toneClass(card.tone) === 'stable'"
                (click)="cardSelected.emit(card)"
              >
                <span class="severity-bar" aria-hidden="true"></span>
                <span class="arb-body">
                  <span class="arb-head">
                    <span class="rank">{{ card.rank }} · {{ card.domain_label }}</span>
                    @if (card.aya_prepared) {
                      <i class="aya-tag" aria-label="AYA prête">AYA prêt</i>
                    }
                  </span>
                  <strong>{{ card.title }}</strong>
                  <p>{{ card.summary }}</p>
                  <span class="arb-foot">
                    <em [class]="toneClass(card.tone)">{{ card.status_label }}</em>
                    <small>{{ card.deadline }}</small>
                  </span>
                </span>
                <span class="arb-cta">
                  <span>{{ card.cta_label || 'Décider' }}</span>
                  <span aria-hidden="true">→</span>
                </span>
              </button>
            </li>
          }
        </ul>
      }
    </section>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .arb-strip-head {
        margin-bottom: var(--mission-space-3);
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
        display: inline-flex;
        align-items: baseline;
        gap: var(--mission-space-2);
        font-size: var(--mission-text-md);
        line-height: var(--mission-lh-tight);
        font-weight: 500;
        color: var(--mission-text-secondary);
      }
      h2 strong {
        font-family: var(--mission-font-mono);
        font-size: var(--mission-text-lg);
        font-weight: 600;
        color: var(--mission-text-primary);
      }
      .arb-empty {
        display: grid;
        place-items: center;
        gap: var(--mission-space-2);
        padding: var(--mission-space-6) var(--mission-space-4);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-md);
        color: var(--mission-text-secondary);
        text-align: center;
      }
      .arb-empty-icon {
        color: var(--mission-text-tertiary);
        font-size: 28px;
        line-height: 1;
      }
      .arb-empty strong {
        font-size: var(--mission-text-base);
        color: var(--mission-text-primary);
      }
      .arb-empty small {
        max-width: 320px;
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .arb-cards {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: var(--mission-space-2);
      }
      .arb-card-wrap { min-width: 0; }
      .arb-card {
        position: relative;
        width: 100%;
        display: grid;
        grid-template-columns: 4px minmax(0, 1fr) auto;
        gap: var(--mission-space-3);
        padding: var(--mission-space-3) var(--mission-space-3) var(--mission-space-3) 0;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.62);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
        overflow: hidden;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out),
          transform var(--mission-dur-fast) var(--mission-ease-out);
      }
      .arb-card:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .arb-card:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .arb-card:active { transform: translateY(1px); }
      .severity-bar {
        width: 100%;
        align-self: stretch;
        background: var(--sentinel-accent-muted);
      }
      .arb-card.critical { background: linear-gradient(135deg, var(--mission-critical-soft), rgba(4, 8, 13, 0.66)); }
      .arb-card.critical .severity-bar { background: var(--mission-critical); }
      .arb-card.elevated .severity-bar { background: var(--mission-warning); }
      .arb-card.stable   .severity-bar { background: var(--mission-success); }
      .arb-body {
        min-width: 0;
        display: grid;
        gap: var(--mission-space-1);
        padding: var(--mission-space-1) 0;
      }
      .arb-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--mission-space-2);
      }
      .rank {
        color: var(--mission-orange);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .arb-card strong {
        display: block;
        font-size: var(--mission-text-base);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: 1.25;
        color: var(--mission-text-primary);
      }
      .arb-card p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      .arb-foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--mission-space-2);
        margin-top: var(--mission-space-1);
      }
      .arb-foot em {
        font-style: normal;
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--mission-warning);
      }
      .arb-foot em.critical { color: var(--mission-critical); }
      .arb-foot em.stable   { color: var(--mission-success); }
      .arb-foot small {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
      }
      .arb-cta {
        align-self: center;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--mission-space-3);
        border: 1px solid var(--sentinel-accent-muted);
        border-radius: var(--mission-radius-sm);
        color: var(--sentinel-accent-strong);
        font-family: var(--mission-font-mono);
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.04em;
        white-space: nowrap;
        transition: background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .arb-card:hover .arb-cta {
        background: var(--sentinel-accent-soft);
      }
      .aya-tag {
        padding: 2px 7px;
        border-radius: 999px;
        border: 1px solid rgba(242, 140, 56, 0.38);
        background: var(--agentium-aya-soft);
        color: var(--agentium-aya);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        font-style: normal;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      @media (max-width: 800px) {
        .arb-card {
          grid-template-columns: 4px minmax(0, 1fr);
        }
        .arb-cta {
          grid-column: 2;
          justify-self: start;
          margin-top: var(--mission-space-2);
        }
      }
    `,
  ],
})
export class VpArbitrationStripComponent {
  @Input() cards: VpArbitrationCard[] = [];
  @Output() cardSelected = new EventEmitter<VpArbitrationCard>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }
}
