import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GlyphComponent } from '@app/shared/cockpit';
import type { VpAyaRecommendation, VpDirectiveOfDay } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-aya-priority-banner',
  standalone: true,
  imports: [CommonModule, GlyphComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="aya-banner" aria-label="Directive AYA">
      <span class="assistant-orb" aria-hidden="true">{{ assistantName.slice(0, 1) }}</span>
      <div class="copy">
        <span class="eyebrow">{{ assistantName }} · Directive du jour</span>
        <h2>{{ directive.text }}</h2>
        <p>{{ recommendation?.answer || directive.window || directive.deadline }}</p>
      </div>
      <div class="actions">
        <button type="button" class="action-button primary" (click)="voiceRequest.emit(recommendation?.prompt)">
          <ck-glyph name="bolt" [size]="14" />
          <span>{{ recommendation?.cta_primary || 'Parler a ' + assistantName }}</span>
        </button>
        <button type="button" class="action-button compact" (click)="briefingRequest.emit()">
          <ck-glyph name="ledger" [size]="14" />
          <span>{{ directive.primary_cta || 'Comparer les options' }}</span>
        </button>
        <button type="button" class="action-button compact" (click)="voiceListen.emit()">
          <ck-glyph name="pulse" [size]="14" />
          <span>{{ directive.voice_cta || 'Ecouter' }}</span>
        </button>
      </div>
    </article>
  `,
  styles: [
    `
      :host { display: block; }
      .aya-banner {
        display: grid;
        grid-template-columns: 54px minmax(0, 1fr) auto;
        gap: 14px;
        align-items: center;
        padding: 14px 16px;
        border: 1px solid rgba(101, 214, 110, 0.22);
        border-radius: var(--mission-radius);
        background:
          linear-gradient(135deg, rgba(101, 214, 110, 0.08), rgba(4, 8, 13, 0.72)),
          var(--mission-panel);
      }
      .assistant-orb {
        width: 54px;
        height: 54px;
        border-radius: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(242, 140, 56, 0.38);
        background: linear-gradient(135deg, rgba(242, 140, 56, 0.18), rgba(101, 214, 110, 0.08));
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 20px;
        font-weight: 850;
      }
      .eyebrow {
        display: block;
        color: var(--mission-trust);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      h2 {
        margin: 6px 0 4px;
        font-size: 18px;
        line-height: 1.2;
      }
      p {
        margin: 0;
        color: var(--mission-text-muted);
        font-size: 12px;
        line-height: 1.4;
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        justify-content: flex-end;
      }
      .action-button {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 11px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text);
        font: inherit;
        font-size: 12px;
        cursor: pointer;
        text-decoration: none;
      }
      .action-button.primary {
        border-color: rgba(101, 214, 110, 0.28);
        background: var(--mission-trust-wash);
      }
      .action-button.compact {
        padding-inline: 9px;
      }
      @media (max-width: 1100px) {
        .aya-banner {
          grid-template-columns: 54px minmax(0, 1fr);
        }
        .actions {
          grid-column: 1 / -1;
          justify-content: flex-start;
        }
      }
    `,
  ],
})
export class VpAyaPriorityBannerComponent {
  @Input() assistantName = 'AYA';
  @Input() directive: VpDirectiveOfDay = { text: '' };
  @Input() recommendation: VpAyaRecommendation | null = null;
  @Output() voiceRequest = new EventEmitter<string | undefined>();
  @Output() voiceListen = new EventEmitter<void>();
  @Output() briefingRequest = new EventEmitter<void>();
}
