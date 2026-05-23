import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GlyphComponent } from '@app/shared/cockpit';
import type { VpArbitrationCard } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-arbitration-strip',
  standalone: true,
  imports: [CommonModule, GlyphComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="arb-strip" aria-label="Sujets a arbitrer">
      <header>
        <div>
          <span class="eyebrow">Sujets a arbitrer</span>
          <h2>{{ cards.length }} decisions ce matin</h2>
        </div>
      </header>
      <div class="arb-cards">
        @for (card of cards; track card.id) {
          <button
            type="button"
            class="arb-card"
            [class.critical]="toneClass(card.tone) === 'critical'"
            [class.elevated]="toneClass(card.tone) === 'elevated'"
            [class.stable]="toneClass(card.tone) === 'stable'"
            (click)="cardSelected.emit(card)"
          >
            <span class="rank">{{ card.rank }} · {{ card.domain_label }}</span>
            <strong>{{ card.title }}</strong>
            <p>{{ card.summary }}</p>
            <footer>
              <em [class]="toneClass(card.tone)">{{ card.status_label }}</em>
              <small>{{ card.deadline }}</small>
            </footer>
            <span class="cta">{{ card.cta_label }}</span>
            @if (card.aya_prepared) {
              <i class="aya-tag">AYA pret</i>
            }
          </button>
        }
      </div>
    </section>
  `,
  styles: [
    `
      :host { display: block; }
      .arb-strip header {
        margin-bottom: 10px;
      }
      .eyebrow {
        display: block;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      h2 {
        margin: 5px 0 0;
        font-size: 18px;
        line-height: 1.15;
      }
      .arb-cards {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }
      .arb-card {
        position: relative;
        min-width: 0;
        padding: 13px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.62);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
      }
      .arb-card.critical {
        border-color: rgba(240, 100, 118, 0.34);
        background: linear-gradient(135deg, var(--mission-danger-wash), rgba(4, 8, 13, 0.66));
      }
      .arb-card.elevated { border-left: 4px solid var(--mission-warn); }
      .arb-card.stable { border-left: 4px solid var(--mission-trust); }
      .rank {
        display: block;
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .arb-card strong {
        display: block;
        margin-top: 6px;
        font-size: 15px;
        line-height: 1.25;
      }
      .arb-card p {
        margin: 7px 0 0;
        color: var(--mission-text-muted);
        font-size: 12px;
        line-height: 1.4;
      }
      footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-top: 10px;
      }
      footer em {
        font-style: normal;
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--mission-warn);
      }
      footer em.critical { color: var(--mission-danger); }
      footer small {
        color: var(--mission-text-faint);
        font-size: 10px;
      }
      .cta {
        display: inline-flex;
        margin-top: 10px;
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        font-weight: 700;
      }
      .aya-tag {
        position: absolute;
        top: 10px;
        right: 10px;
        padding: 2px 6px;
        border-radius: 999px;
        border: 1px solid rgba(101, 214, 110, 0.28);
        background: var(--mission-trust-wash);
        color: var(--mission-trust);
        font-family: var(--ck-font-mono);
        font-size: 8px;
        font-style: normal;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      @media (max-width: 1100px) {
        .arb-cards { grid-template-columns: 1fr; }
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
