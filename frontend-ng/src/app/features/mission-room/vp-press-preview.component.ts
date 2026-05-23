import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { VpPressPreviewItem } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-press-preview',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="press-preview" aria-label="Alertes presse">
      @if (morningHighlight && !morningDismissed) {
        <div class="morning-banner">
          <p>{{ morningHighlight }}</p>
          <div class="morning-actions">
            <button type="button" (click)="morningView.emit()">Voir</button>
            <button type="button" (click)="morningLater.emit()">Plus tard</button>
            <button type="button" (click)="morningVoice.emit()">Parler a AYA</button>
          </div>
        </div>
      }
      <div class="press-cards">
        @for (item of items; track item.id) {
          <button
            type="button"
            class="press-card"
            [class.highlighted]="highlightId === item.id"
            [class.critical]="toneClass(item.tone || item.risk) === 'critical'"
            [class.elevated]="toneClass(item.tone || item.risk) === 'elevated'"
            (click)="itemSelected.emit(item)"
          >
            <span class="risk-pill" [class]="toneClass(item.tone || item.risk)">
              {{ item.risk_label || item.risk }}
            </span>
            <strong>{{ item.title }}</strong>
            @if (item.summary) {
              <p>{{ item.summary }}</p>
            }
            <small>{{ item.source }}</small>
          </button>
        }
      </div>
    </section>
  `,
  styles: [
    `
      :host { display: block; }
      .morning-banner {
        margin-bottom: 10px;
        padding: 10px 12px;
        border: 1px solid rgba(242, 140, 56, 0.28);
        border-radius: var(--mission-radius);
        background: rgba(242, 140, 56, 0.08);
      }
      .morning-banner p {
        margin: 0 0 8px;
        color: var(--mission-text-soft);
        font-size: 12px;
        line-height: 1.45;
      }
      .morning-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .morning-actions button {
        padding: 5px 9px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
      }
      .press-cards {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }
      .press-card {
        min-width: 0;
        padding: 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.58);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
      }
      .press-card.highlighted {
        border-color: rgba(242, 140, 56, 0.55);
        box-shadow: 0 0 0 1px rgba(242, 140, 56, 0.18), 0 0 24px rgba(242, 140, 56, 0.08);
      }
      .press-card.critical { border-left: 4px solid var(--mission-danger); }
      .press-card.elevated { border-left: 4px solid var(--mission-warn); }
      .risk-pill {
        display: inline-flex;
        padding: 2px 7px;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .risk-pill.critical {
        border-color: rgba(240, 100, 118, 0.34);
        color: var(--mission-danger);
      }
      .risk-pill.elevated {
        border-color: rgba(241, 180, 90, 0.32);
        color: var(--mission-warn);
      }
      .press-card strong {
        display: block;
        margin-top: 8px;
        font-size: 13px;
        line-height: 1.3;
      }
      .press-card p {
        margin: 6px 0 0;
        color: var(--mission-text-muted);
        font-size: 11px;
        line-height: 1.35;
      }
      .press-card small {
        display: block;
        margin-top: 8px;
        color: var(--mission-text-faint);
        font-size: 10px;
      }
      @media (max-width: 1100px) {
        .press-cards { grid-template-columns: 1fr; }
      }
    `,
  ],
})
export class VpPressPreviewComponent {
  @Input() items: VpPressPreviewItem[] = [];
  @Input() highlightId: string | null = null;
  @Input() morningHighlight: string | null = null;
  @Input() morningDismissed = false;
  @Output() itemSelected = new EventEmitter<VpPressPreviewItem>();
  @Output() morningView = new EventEmitter<void>();
  @Output() morningLater = new EventEmitter<void>();
  @Output() morningVoice = new EventEmitter<void>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 'critical';
    if (normalized === 'elevated' || normalized === 'medium' || normalized === 'watch') return 'elevated';
    return 'stable';
  }
}
