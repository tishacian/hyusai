import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import type { VpPressPreviewItem } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-press-preview',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="press-preview" [attr.aria-label]="i18n.t('mission.press.title')">
      @if (morningHighlight && !morningDismissed) {
        <div class="morning-banner" role="region" [attr.aria-label]="i18n.t('mission.press.morning')">
          <p>{{ morningHighlight }}</p>
          <div class="morning-actions">
            <button type="button" (click)="morningView.emit()">
              {{ i18n.t('mission.press.view') }}
            </button>
            <button type="button" (click)="morningLater.emit()">
              {{ i18n.t('mission.press.later') }}
            </button>
            <button type="button" (click)="morningVoice.emit()">
              {{ i18n.t('mission.assistant.talk_to', { name: assistantName }) }}
            </button>
          </div>
        </div>
      }

      @if (!items.length) {
        <div class="press-empty" role="status">
          <span class="press-empty-icon" aria-hidden="true">◇</span>
          <strong>{{ i18n.t('mission.press.empty') }}</strong>
          <small>{{ i18n.t('mission.press.empty_hint', { name: assistantName }) }}</small>
        </div>
      } @else {
        <div class="press-cards" [class.is-hero]="items.length === 1">
          @for (item of items; track item.id) {
            <button
              type="button"
              class="press-card"
              [class.highlighted]="highlightId === item.id"
              [class.critical]="toneClass(item.tone || item.risk) === 'critical'"
              [class.elevated]="toneClass(item.tone || item.risk) === 'elevated'"
              (click)="itemSelected.emit(item)"
            >
              <span class="press-card-meta">
                <span class="risk-pill" [class]="toneClass(item.tone || item.risk)">
                  {{ item.risk_label || item.risk }}
                </span>
                @if (highlightId === item.id) {
                  <span
                    class="aya-flag"
                    [attr.aria-label]="i18n.t('mission.press.flagged_by', { name: assistantName })"
                    >{{ i18n.t('mission.press.flag_tag', { name: assistantName }) }}</span
                  >
                }
              </span>
              <strong>{{ item.title }}</strong>
              @if (item.summary) {
                <p>{{ item.summary }}</p>
              }
              <small>{{ item.source }}</small>
            </button>
          }
        </div>
      }
    </section>
  `,
  styles: [
    `
      :host { display: block; }
      .morning-banner {
        margin-bottom: var(--mission-space-3);
        padding: var(--mission-space-3) var(--mission-space-4);
        border: 1px solid rgba(242, 140, 56, 0.28);
        border-radius: var(--mission-radius-md);
        background: var(--agentium-aya-soft);
      }
      .morning-banner p {
        margin: 0 0 var(--mission-space-2);
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .morning-actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
      }
      .morning-actions button {
        padding: var(--mission-space-1) var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font: inherit;
        font-size: var(--mission-text-xs);
        cursor: pointer;
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .morning-actions button:hover {
        border-color: var(--sentinel-accent-muted);
      }
      .morning-actions button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .press-empty {
        display: grid;
        place-items: center;
        gap: var(--mission-space-2);
        padding: var(--mission-space-6) var(--mission-space-4);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.42);
        color: var(--mission-text-secondary);
        text-align: center;
      }
      .press-empty-icon {
        color: var(--mission-text-tertiary);
        font-size: 28px;
        line-height: 1;
      }
      .press-empty strong {
        font-size: var(--mission-text-base);
        color: var(--mission-text-primary);
      }
      .press-empty small {
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
        max-width: 360px;
      }
      .press-cards {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--mission-space-3);
      }
      .press-cards.is-hero {
        grid-template-columns: 1fr;
      }
      .press-card {
        min-width: 0;
        padding: var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.58);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out),
          box-shadow var(--mission-dur-fast) var(--mission-ease-out);
      }
      .press-cards.is-hero .press-card {
        padding: var(--mission-space-5) var(--mission-space-5);
      }
      .press-card:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.05);
      }
      .press-card:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .press-card.highlighted {
        border-color: var(--agentium-aya);
        box-shadow: 0 0 0 1px rgba(242, 140, 56, 0.18), 0 0 24px rgba(242, 140, 56, 0.08);
      }
      .press-card.critical { border-left: 4px solid var(--mission-critical); }
      .press-card.elevated { border-left: 4px solid var(--mission-warning); }
      .press-card-meta {
        display: inline-flex;
        align-items: center;
        gap: var(--mission-space-2);
      }
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
      .aya-flag {
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid rgba(242, 140, 56, 0.38);
        background: var(--agentium-aya-soft);
        color: var(--agentium-aya);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .press-card strong {
        display: block;
        margin-top: var(--mission-space-2);
        font-size: var(--mission-text-base);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: 1.3;
      }
      .press-cards.is-hero .press-card strong {
        font-size: var(--mission-text-lg);
      }
      .press-card p {
        margin: var(--mission-space-2) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
        /* keep press summary aerated but capped (~3 lines) so the hero card
           does not balloon when the wire copy runs long. */
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      .press-card small {
        display: block;
        margin-top: var(--mission-space-2);
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      @media (max-width: 1100px) {
        .press-cards { grid-template-columns: 1fr; }
      }
    `,
  ],
})
export class VpPressPreviewComponent {
  readonly i18n = inject(I18nService);

  @Input() assistantName = 'AYA';
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
