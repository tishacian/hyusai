import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import { VpMapPreviewComponent } from './vp-map-preview.component';
import { VpSovereignGaugesComponent } from './vp-sovereign-gauges.component';
import { VpIntelligenceGridComponent } from './vp-intelligence-grid.component';
import { VpArbitrationStripComponent } from './vp-arbitration-strip.component';
import { VpAgendaTimelineComponent } from './vp-agenda-timeline.component';
import { VpAyaPriorityBannerComponent } from './vp-aya-priority-banner.component';
import { VpPressPreviewComponent } from './vp-press-preview.component';
import type {
  VpAgendaTimeline,
  VpAgendaTimelineEvent,
  VpArbitrationCard,
  VpAyaRecommendation,
  VpDirectiveOfDay,
  VpIntelligenceFeed,
  VpMapPreviewContext,
  VpPressPreviewItem,
  VpScenarioMode,
  VpSovereignIndicator,
  VpStatusBarItem,
} from './vp-cockpit.types';

@Component({
  selector: 'app-vp-cockpit',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    GlyphComponent,
    VpMapPreviewComponent,
    VpSovereignGaugesComponent,
    VpIntelligenceGridComponent,
    VpArbitrationStripComponent,
    VpAgendaTimelineComponent,
    VpAyaPriorityBannerComponent,
    VpPressPreviewComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="vp-cockpit" aria-label="Cockpit Vice-Presidence">
      <section class="vp-stratum vp-stratum-monitoring" aria-label="Monitoring">
        <section class="vp-status-bar" aria-label="Posture nationale">
          @for (item of statusBar; track item.key) {
            <article [class]="toneClass(item.tone)">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              @if (item.detail) {
                <small>{{ item.detail }}</small>
              }
            </article>
          }
        </section>

        <div class="monitoring-row">
          <app-vp-map-preview [context]="mapPreview" (openMap)="openMap.emit()" />
          <app-vp-sovereign-gauges [indicators]="sovereignIndicators" />
        </div>

        <app-vp-intelligence-grid [feeds]="intelligenceFeeds" />

        <app-vp-agenda-timeline [timeline]="agendaTimeline" (eventSelected)="agendaEvent.emit($event)" />
      </section>

      <section class="vp-stratum vp-stratum-alerting" aria-label="Alerting">
        <app-vp-aya-priority-banner
          [assistantName]="assistantName"
          [directive]="directive"
          [recommendation]="ayaRecommendation"
          (voiceRequest)="voiceRequest.emit($event)"
          (voiceListen)="voiceListen.emit()"
          (briefingRequest)="briefingRequest.emit()"
        />

        <app-vp-arbitration-strip [cards]="arbitrationCards" (cardSelected)="arbitrationSelected.emit($event)" />

        <app-vp-press-preview
          [items]="pressPreview"
          [highlightId]="pressHighlightId"
          [morningHighlight]="morningHighlight"
          [morningDismissed]="morningDismissed"
          (itemSelected)="pressSelected.emit($event)"
          (morningView)="morningView.emit()"
          (morningLater)="morningLater.emit()"
          (morningVoice)="morningVoice.emit()"
        />
      </section>

      <section class="vp-stratum vp-stratum-decision" aria-label="Decision">
        @if (decisionTeaser; as teaser) {
          <article class="decision-teaser content-panel">
            <span class="eyebrow">Option AYA recommandee</span>
            <strong>{{ teaser.recommended_option }}</strong>
            <p>{{ teaser.title }} · {{ teaser.deadline || 'avant Conseil 15h00' }}</p>
            <button type="button" class="inline-link" (click)="briefingRequest.emit()">Comparer les options</button>
          </article>
        }

        <article class="decision-cta content-panel">
          <div class="cta-copy">
            <span class="eyebrow">{{ assistantName }} · Action VP</span>
            <p>Preparer l'arbitrage sous validation humaine — vocal ou brouillon advisory.</p>
          </div>
          <div class="cta-actions">
            <button type="button" class="action-button primary" (click)="voiceRequest.emit(ayaRecommendation?.prompt)">
              <ck-glyph name="bolt" [size]="14" />
              <span>Parler a {{ assistantName }}</span>
            </button>
            <button type="button" class="action-button compact" (click)="voiceListen.emit()">
              <ck-glyph name="pulse" [size]="14" />
              <span>Ecouter le briefing</span>
            </button>
          </div>
        </article>

        <footer class="explorer-footer">
          @for (mode of scenarioModes; track mode.key) {
            <button type="button" (click)="scenarioMode.emit(mode)">
              <strong>{{ mode.label }}</strong>
              <small>{{ mode.goal }}</small>
            </button>
          }
        </footer>
      </section>
    </div>
  `,
  styles: [
    `
      :host { display: block; min-width: 0; }
      .vp-cockpit { display: grid; gap: 14px; }
      .vp-stratum {
        display: grid;
        gap: 12px;
        padding: 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.42);
      }
      .vp-stratum-monitoring { min-height: 50vh; }
      .vp-stratum-alerting { min-height: 22vh; }
      .vp-stratum-decision { min-height: 18vh; }
      .vp-status-bar {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 8px;
      }
      .vp-status-bar article {
        padding: 10px 11px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.58);
      }
      .vp-status-bar article.critical { border-color: rgba(240, 100, 118, 0.34); }
      .vp-status-bar article.elevated { border-color: rgba(241, 180, 90, 0.32); }
      .vp-status-bar article.stable { border-color: rgba(63, 209, 141, 0.28); }
      .vp-status-bar span {
        display: block;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .vp-status-bar strong {
        display: block;
        margin-top: 4px;
        font-size: 18px;
        line-height: 1;
      }
      .vp-status-bar small {
        display: block;
        margin-top: 4px;
        color: var(--mission-text-faint);
        font-size: 10px;
      }
      .monitoring-row {
        display: grid;
        grid-template-columns: minmax(0, 2fr) minmax(220px, 1fr);
        gap: 12px;
        align-items: stretch;
      }
      .content-panel {
        padding: 12px 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius);
        background: rgba(4, 8, 13, 0.58);
      }
      .eyebrow {
        display: block;
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      .decision-teaser strong {
        display: block;
        margin-top: 6px;
        font-size: 16px;
        line-height: 1.25;
      }
      .decision-teaser p {
        margin: 6px 0 0;
        color: var(--mission-text-muted);
        font-size: 12px;
      }
      .decision-cta {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
      }
      .cta-actions { display: flex; flex-wrap: wrap; gap: 8px; }
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
      }
      .action-button.primary {
        border-color: rgba(101, 214, 110, 0.28);
        background: var(--mission-trust-wash);
      }
      .inline-link {
        display: inline-flex;
        margin-top: 8px;
        padding: 0;
        border: 0;
        background: transparent;
        color: var(--mission-accent);
        font-family: var(--ck-font-mono);
        font-size: 11px;
        cursor: pointer;
      }
      .explorer-footer {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }
      .explorer-footer button {
        min-width: 140px;
        padding: 8px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.52);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
      }
      .explorer-footer strong { display: block; font-size: 12px; }
      .explorer-footer small {
        display: block;
        margin-top: 3px;
        color: var(--mission-text-faint);
        font-size: 10px;
        line-height: 1.35;
      }
      @media (max-width: 1200px) {
        .vp-status-bar { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .monitoring-row { grid-template-columns: 1fr; }
      }
      @media (max-width: 840px) {
        .vp-status-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
    `,
  ],
})
export class VpCockpitComponent {
  @Input() assistantName = 'AYA';
  @Input() statusBar: VpStatusBarItem[] = [];
  @Input() mapPreview: VpMapPreviewContext = {
    route: '/hypervisor/mission-room/strategie',
    label: 'Carte fusionnee',
    zones: [],
    map: null,
    mapSystem: null,
    geoPreview: { zone_scores: [] },
    topZoneId: null,
  };
  @Input() sovereignIndicators: VpSovereignIndicator[] = [];
  @Input() intelligenceFeeds: VpIntelligenceFeed[] = [];
  @Input() agendaTimeline: VpAgendaTimeline = { events: [] };
  @Input() directive: VpDirectiveOfDay = { text: '' };
  @Input() ayaRecommendation: VpAyaRecommendation | null = null;
  @Input() arbitrationCards: VpArbitrationCard[] = [];
  @Input() pressPreview: VpPressPreviewItem[] = [];
  @Input() pressHighlightId: string | null = null;
  @Input() morningHighlight: string | null = null;
  @Input() morningDismissed = false;
  @Input() decisionTeaser: {
    id: string;
    title: string;
    recommended_option: string;
    deadline?: string;
    confidence?: number;
  } | null = null;
  @Input() scenarioModes: VpScenarioMode[] = [];

  @Output() openMap = new EventEmitter<void>();
  @Output() arbitrationSelected = new EventEmitter<VpArbitrationCard>();
  @Output() pressSelected = new EventEmitter<VpPressPreviewItem>();
  @Output() agendaEvent = new EventEmitter<VpAgendaTimelineEvent>();
  @Output() voiceRequest = new EventEmitter<string | undefined>();
  @Output() voiceListen = new EventEmitter<void>();
  @Output() briefingRequest = new EventEmitter<void>();
  @Output() morningView = new EventEmitter<void>();
  @Output() morningLater = new EventEmitter<void>();
  @Output() morningVoice = new EventEmitter<void>();
  @Output() scenarioMode = new EventEmitter<VpScenarioMode>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    if (normalized === 'stable') return 'stable';
    return 'monitoring';
  }
}
