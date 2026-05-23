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
      <span class="assistant-orb" aria-hidden="true">
        <span class="assistant-orb-halo"></span>
        <span class="assistant-orb-letter">{{ assistantName.slice(0, 1) }}</span>
      </span>
      <div class="copy">
        <span class="eyebrow">{{ assistantName }} · Directive du jour</span>
        <h2>{{ directive.text }}</h2>
        @if (recommendation?.answer || directive.window || directive.deadline) {
          <p>{{ recommendation?.answer || directive.window || directive.deadline }}</p>
        }
      </div>
      <div class="actions">
        <button type="button" class="action-button primary" (click)="voiceRequest.emit(recommendation?.prompt)">
          <ck-glyph name="bolt" [size]="14" />
          <span>{{ recommendation?.cta_primary || 'Parler à ' + assistantName }}</span>
        </button>
        <button type="button" class="action-button compact" (click)="briefingRequest.emit()">
          <ck-glyph name="ledger" [size]="14" />
          <span>{{ directive.primary_cta || 'Comparer les options' }}</span>
        </button>
        <button type="button" class="action-button ghost" (click)="voiceListen.emit()">
          <ck-glyph name="pulse" [size]="14" />
          <span>{{ directive.voice_cta || 'Écouter le briefing' }}</span>
        </button>
      </div>
    </article>
  `,
  styles: [
    `
      :host { display: block; }
      .aya-banner {
        position: relative;
        display: grid;
        grid-template-columns: 56px minmax(0, 1fr) auto;
        gap: var(--mission-space-4);
        align-items: center;
        padding: var(--mission-space-4) var(--mission-space-5) var(--mission-space-4) var(--mission-space-5);
        border: 1px solid rgba(242, 140, 56, 0.18);
        border-left: 3px solid var(--agentium-aya);
        border-radius: var(--mission-radius-md);
        background:
          linear-gradient(135deg, var(--agentium-aya-soft), rgba(4, 8, 13, 0.72)),
          var(--mission-surface-1);
        box-shadow: var(--mission-shadow-soft);
      }
      .assistant-orb {
        position: relative;
        width: 56px;
        height: 56px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .assistant-orb-halo {
        position: absolute;
        inset: -2px;
        border-radius: 18px;
        background: radial-gradient(circle at 30% 30%, rgba(242, 140, 56, 0.42), transparent 70%);
        filter: blur(6px);
        opacity: 0.95;
      }
      .assistant-orb-letter {
        position: relative;
        width: 100%;
        height: 100%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 16px;
        border: 1px solid rgba(242, 140, 56, 0.48);
        background: linear-gradient(135deg, rgba(242, 140, 56, 0.24), rgba(101, 214, 110, 0.08));
        color: var(--agentium-aya);
        font-family: var(--mission-font-mono);
        font-size: 22px;
        font-weight: 700;
        letter-spacing: -0.02em;
      }
      .copy { min-width: 0; }
      .eyebrow {
        display: block;
        color: var(--sentinel-accent);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      h2 {
        margin: var(--mission-space-2) 0 var(--mission-space-1);
        font-size: var(--mission-text-md);
        font-weight: 600;
        font-style: italic;
        line-height: var(--mission-lh-tight);
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
        /* keep the directive succinct on a single comex screen — 2 lines max */
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        justify-content: flex-end;
      }
      .action-button {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 12px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font: inherit;
        font-size: var(--mission-text-sm);
        cursor: pointer;
        text-decoration: none;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .action-button:hover {
        border-color: var(--sentinel-accent-muted);
        background: var(--sentinel-accent-soft);
      }
      .action-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .action-button.primary {
        border-color: rgba(101, 214, 110, 0.42);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        font-weight: 600;
      }
      .action-button.primary:hover {
        background: rgba(101, 214, 110, 0.18);
      }
      .action-button.ghost {
        background: transparent;
        color: var(--mission-text-secondary);
      }
      .action-button.compact {
        padding-inline: 10px;
      }
      @media (max-width: 1100px) {
        .aya-banner {
          grid-template-columns: 56px minmax(0, 1fr);
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
