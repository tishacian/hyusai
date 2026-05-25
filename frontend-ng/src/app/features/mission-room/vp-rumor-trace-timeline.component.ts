import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';

export interface RumorChainStep {
  step?: number;
  channel?: string;
  time?: string;
  actor?: string;
  kind?: string;
  signal?: string;
  confidence?: number;
  source_id?: string;
  source_url?: string;
}

export interface RumorTrace {
  headline?: string;
  summary?: string;
  origin?: string;
  chain?: RumorChainStep[];
  spread?: RumorChainStep[];
  recommended_action?: string;
  aya_sentence?: string;
  verdict?: string | null;
  verdict_label?: string | null;
}

type Phase = 'emergence' | 'amplification' | 'demente';
type TimelineFilter = Phase | 'all';

@Component({
  selector: 'app-vp-rumor-trace-timeline',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (trace && (embedded || open)) {
      <div [class]="embedded ? 'rumor-embedded-root' : 'rumor-drawer-root'" [attr.role]="embedded ? null : 'dialog'" [attr.aria-modal]="embedded ? null : 'true'" aria-label="Dossier rumeur frontière Nord">
        @if (!embedded) {
          <button
            type="button"
            class="rumor-drawer-backdrop"
            aria-label="Fermer le dossier rumeur"
            (click)="closed.emit()"
          ></button>
        }
        <aside [class]="embedded ? 'rumor-embedded-panel' : 'rumor-drawer-panel'">
          <header class="rumor-drawer-head">
            <div class="rumor-drawer-head-copy">
              <span
                class="mission-status-badge"
                [class.is-denied]="hasOfficialDenial()"
                [class.is-watch]="!hasOfficialDenial()"
              >
                {{ hasOfficialDenial() ? 'démenti officiel' : 'vérification' }}
              </span>
              <small class="publisher-badge">Chronologie OSINT</small>
              <h2>{{ trace.headline || 'Dossier rumeur frontière Nord' }}</h2>
              <p class="rumor-drawer-summary">{{ trace.summary || '' }}</p>
            </div>
            @if (!embedded) {
              <button
                type="button"
                class="rumor-drawer-close"
                aria-label="Fermer"
                (click)="closed.emit()"
              >
                ×
              </button>
            }
          </header>

          <div class="rumor-drawer-body">
            @if (hasOfficialDenial()) {
              <section class="verdict-bar verdict-denied mission-row-highlight" aria-live="polite">
                <span class="verdict-icon" aria-hidden="true">✓</span>
                <div class="verdict-copy">
                  <strong>{{ trace.verdict_label || 'DÉMENTI OFFICIEL FANCI' }}</strong>
                  <span>{{ deniedTimingLabel() }} — postes mixtes nominaux, advisory only.</span>
                </div>
              </section>
            } @else {
              <section class="verdict-bar verdict-pending mission-row-highlight" aria-live="polite">
                <span class="verdict-icon" aria-hidden="true">!</span>
                <div class="verdict-copy">
                  <strong>RUMEUR EN COURS DE VÉRIFICATION</strong>
                  <span>Aucun communiqué officiel détecté dans la chaîne OSINT.</span>
                </div>
              </section>
            }

            <section class="rumor-meta">
              <div>
                <span class="eyebrow">Origine</span>
                <p>{{ trace.origin || '—' }}</p>
              </div>
              <div>
                <span class="eyebrow">Étapes</span>
                <p>{{ steps().length }} signaux · {{ countByPhase('emergence') }} émergence · {{ countByPhase('amplification') }} amplification · {{ countByPhase('demente') }} démenti</p>
              </div>
            </section>

            <section class="rumor-metrics" aria-label="Indicateurs de propagation">
              <article>
                <span>Durée</span>
                <strong>{{ rumorDurationLabel() }}</strong>
                <small>premier signal → mise au point</small>
              </article>
              <article>
                <span>Pic relais</span>
                <strong>{{ amplificationPeakLabel() }}</strong>
                <small>avant démenti officiel</small>
              </article>
              <article>
                <span>Démenti</span>
                <strong>{{ denialGapLabel() }}</strong>
                <small>temps jusqu'au premier démenti</small>
              </article>
            </section>

            <section class="rumor-filter-bar" aria-label="Filtres chronologie">
              <button type="button" [class.active]="activeFilter === 'all'" (click)="setFilter('all')">Tout</button>
              <button type="button" [class.active]="activeFilter === 'emergence'" (click)="setFilter('emergence')">Origine</button>
              <button type="button" [class.active]="activeFilter === 'amplification'" (click)="setFilter('amplification')">Amplification</button>
              <button type="button" [class.active]="activeFilter === 'demente'" (click)="setFilter('demente')">Démentis officiels</button>
            </section>

            <section class="rumor-investigation-grid" aria-label="Analyse de propagation">
              <div class="rumor-timeline" aria-label="Chronologie OSINT">
                <span class="eyebrow">Chaîne de propagation</span>
                <ol class="timeline">
                  @for (step of visibleSteps(); track stepKey(step, $index)) {
                    <li class="timeline-item" [attr.data-phase]="phaseFor(step)">
                      <span class="timeline-rail" aria-hidden="true"></span>
                      <span class="timeline-dot" [ngClass]="'phase-' + phaseFor(step)" aria-hidden="true">
                        <span>{{ step.step ?? $index + 1 }}</span>
                      </span>
                      <button
                        type="button"
                        class="timeline-card"
                        [ngClass]="'phase-' + phaseFor(step)"
                        [class.active]="isSelectedStep(step, $index)"
                        (click)="selectStep(step, $index)"
                      >
                        <header>
                          <span class="timeline-channel">
                            <span class="channel-glyph" [ngClass]="'glyph-' + glyphFor(step.channel)" aria-hidden="true">{{ channelLetter(step.channel) }}</span>
                            {{ step.channel || '—' }}
                          </span>
                          @if (step.time) {
                            <small class="timeline-time">{{ step.time }}</small>
                          }
                        </header>
                        <strong class="timeline-actor">{{ step.actor || '—' }}</strong>
                        <p class="timeline-signal">{{ step.signal || '' }}</p>
                        <footer class="timeline-foot">
                          @if (step.confidence !== undefined && step.confidence !== null) {
                            <span class="confidence-chip" [ngClass]="confidenceClass(step.confidence)">
                              confiance {{ confidencePct(step.confidence) }}%
                            </span>
                          }
                          @if (step.source_id) {
                            <span class="timeline-source-id">src · {{ step.source_id }}</span>
                          }
                        </footer>
                      </button>
                    </li>
                  } @empty {
                    <li class="timeline-empty">Aucun signal dans ce filtre.</li>
                  }
                </ol>
              </div>

              @if (selectedStep(); as active) {
                <aside class="rumor-step-detail" aria-live="polite">
                  <span class="eyebrow">Étape active</span>
                  <h3>{{ phaseLabel(phaseFor(active)) }}</h3>
                  <dl>
                    <div><dt>Canal</dt><dd>{{ active.channel || '—' }}</dd></div>
                    <div><dt>Acteur</dt><dd>{{ active.actor || '—' }}</dd></div>
                    <div><dt>Heure</dt><dd>{{ active.time || '—' }}</dd></div>
                    <div><dt>Confiance</dt><dd>{{ active.confidence !== undefined && active.confidence !== null ? confidencePct(active.confidence) + '%' : '—' }}</dd></div>
                    <div><dt>Source</dt><dd>{{ active.source_id || 'source indexée · extrait non disponible' }}</dd></div>
                  </dl>
                  <p>{{ active.signal || 'Signal indexé sans extrait disponible.' }}</p>
                  <div class="detail-callout">
                    <strong>Effet narratif</strong>
                    <span>{{ narrativeEffectFor(active) }}</span>
                  </div>
                  <button type="button" class="action-link primary compact" (click)="draftCommunique.emit()">
                    {{ actionFor(active) }}
                  </button>
                </aside>
              }
            </section>

            @if (trace.recommended_action || trace.aya_sentence) {
              <section class="rumor-recommendation">
                <span class="eyebrow">Recommandation cabinet</span>
                @if (trace.aya_sentence) {
                  <blockquote>« {{ trace.aya_sentence }} »</blockquote>
                }
                @if (trace.recommended_action) {
                  <p>{{ trace.recommended_action }}</p>
                }
              </section>
            }
          </div>

          <footer class="rumor-drawer-foot mission-action-footer">
            <button type="button" class="action-link primary" (click)="draftCommunique.emit()">
              Préparer un communiqué
            </button>
            @if (embedded) {
              <button type="button" class="action-link muted" (click)="showMap.emit()">
                Voir sur carte Nord
              </button>
              <button type="button" class="action-link muted" (click)="filterDenied()">
                Filtrer démentis
              </button>
            } @else {
              <button type="button" class="action-link muted" (click)="closed.emit()">
                Fermer
              </button>
            }
          </footer>
        </aside>
      </div>
    }
  `,
  styles: [
    `
      :host { display: contents; }
      .rumor-drawer-root {
        position: fixed;
        inset: 0;
        z-index: 1300;
        display: flex;
        justify-content: flex-end;
      }
      .rumor-drawer-backdrop {
        position: absolute;
        inset: 0;
        border: 0;
        background: rgba(2, 6, 10, 0.62);
        backdrop-filter: blur(2px);
        cursor: pointer;
      }
      .rumor-drawer-panel {
        position: relative;
        width: min(760px, 100vw);
        height: 100%;
        display: flex;
        flex-direction: column;
        border-left: 1px solid rgba(242, 140, 56, 0.32);
        background: rgba(4, 10, 14, 0.97);
        box-shadow: -16px 0 48px rgba(0, 0, 0, 0.45);
        animation: rumor-drawer-in 200ms var(--mission-ease-out);
      }
      @keyframes rumor-drawer-in {
        from { transform: translateX(16px); opacity: 0.6; }
        to   { transform: translateX(0); opacity: 1; }
      }
      .rumor-embedded-root { display: block; }
      .rumor-embedded-panel {
        width: 100%;
        border: 0;
        background: transparent;
        box-shadow: none;
        animation: none;
      }
      .rumor-drawer-head {
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
      .rumor-drawer-head-copy { min-width: 0; flex: 1 1 auto; }
      .rumor-drawer-head h2 {
        margin: var(--mission-space-2) 0 0;
        font-size: var(--mission-text-lg);
        line-height: 1.3;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .rumor-drawer-summary {
        margin: var(--mission-space-2) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .rumor-drawer-close {
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
      .rumor-drawer-body {
        flex: 1 1 auto;
        overflow-y: auto;
        padding: var(--mission-space-5);
        display: grid;
        gap: var(--mission-space-5);
      }
      .eyebrow {
        display: block;
        margin-bottom: var(--mission-space-2);
        color: var(--mission-orange);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.13em;
        text-transform: uppercase;
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
      .verdict-bar,
      .rumor-meta,
      .rumor-step-detail,
      .rumor-recommendation {
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.55);
      }
      .verdict-bar {
        display: flex;
        gap: var(--mission-space-3);
        align-items: center;
        padding: var(--mission-space-3) var(--mission-space-4);
      }
      .verdict-bar.verdict-denied {
        border-color: rgba(63, 209, 141, 0.45);
        background: rgba(63, 209, 141, 0.10);
      }
      .verdict-bar.verdict-pending {
        border-color: rgba(242, 140, 56, 0.45);
        background: rgba(242, 140, 56, 0.10);
      }
      .verdict-icon {
        flex: 0 0 auto;
        width: 28px;
        height: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        font-family: var(--mission-font-mono);
        font-size: 14px;
        font-weight: 700;
      }
      .verdict-denied .verdict-icon { background: var(--mission-success); color: #03130a; }
      .verdict-pending .verdict-icon { background: var(--mission-orange); color: #1a0d05; }
      .verdict-copy {
        display: grid;
        gap: 2px;
        min-width: 0;
      }
      .verdict-copy strong {
        font-family: var(--mission-font-mono);
        font-size: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--mission-text-primary);
      }
      .verdict-copy span {
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
      }
      .rumor-meta,
      .rumor-metrics {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--mission-space-3);
      }
      .rumor-meta {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
        padding: var(--mission-space-3);
      }
      .rumor-meta p {
        margin: 0;
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .rumor-metrics article {
        min-width: 0;
        padding: var(--mission-space-3);
        border: 1px solid rgba(151, 185, 164, 0.16);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
      }
      .rumor-metrics span,
      .rumor-metrics small {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .rumor-metrics strong {
        display: block;
        margin: 5px 0;
        color: var(--mission-text-primary);
        font-size: 18px;
      }
      .rumor-filter-bar {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .rumor-filter-bar button,
      .action-link,
      .timeline-card {
        font: inherit;
        cursor: pointer;
      }
      .rumor-filter-bar button {
        min-height: 32px;
        padding: 6px 11px;
        border: 1px solid var(--mission-border);
        border-radius: 999px;
        background: transparent;
        color: var(--mission-text-secondary);
      }
      .rumor-filter-bar button.active {
        border-color: rgba(101, 214, 110, 0.45);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
      }
      .rumor-investigation-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(280px, 0.45fr);
        gap: var(--mission-space-4);
        align-items: start;
      }
      .rumor-timeline,
      .timeline,
      .rumor-step-detail {
        display: grid;
        gap: var(--mission-space-3);
      }
      .timeline {
        list-style: none;
        margin: 0;
        padding: 0;
      }
      .timeline-item {
        position: relative;
        display: grid;
        grid-template-columns: 28px 1fr;
        gap: var(--mission-space-3);
      }
      .timeline-rail {
        position: absolute;
        top: 30px;
        bottom: -16px;
        left: 13px;
        width: 2px;
        background: linear-gradient(180deg, rgba(242, 140, 56, 0.45) 0%, rgba(151, 185, 164, 0.18) 100%);
      }
      .timeline-item:last-child .timeline-rail { display: none; }
      .timeline-dot {
        position: relative;
        z-index: 1;
        width: 28px;
        height: 28px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-family: var(--mission-font-mono);
        font-size: 11px;
        font-weight: 700;
        color: #04090c;
        background: var(--mission-warning);
        box-shadow: 0 0 0 4px rgba(4, 10, 14, 0.97);
      }
      .timeline-dot.phase-emergence { background: var(--mission-orange); }
      .timeline-dot.phase-amplification { background: var(--mission-critical); }
      .timeline-dot.phase-demente { background: var(--mission-success); }
      .timeline-card {
        width: 100%;
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-left-width: 3px;
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
        color: inherit;
        text-align: left;
      }
      .timeline-card:hover,
      .timeline-card.active {
        border-color: rgba(101, 214, 110, 0.42);
        background: rgba(15, 111, 63, 0.10);
      }
      .timeline-card.phase-emergence { border-left-color: var(--mission-orange); }
      .timeline-card.phase-amplification { border-left-color: var(--mission-critical); }
      .timeline-card.phase-demente { border-left-color: var(--mission-success); }
      .timeline-card header,
      .timeline-foot {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        justify-content: space-between;
        gap: var(--mission-space-2);
      }
      .timeline-channel {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--mission-text-secondary);
      }
      .channel-glyph {
        width: 18px;
        height: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        color: #04090c;
        background: rgba(151, 185, 164, 0.45);
      }
      .channel-glyph.glyph-twitter { background: #7dd3fc; }
      .channel-glyph.glyph-telegram { background: #93ef74; }
      .channel-glyph.glyph-blog { background: #f1b45a; }
      .channel-glyph.glyph-cabinet { background: #f06476; }
      .channel-glyph.glyph-prefecture { background: var(--mission-success); }
      .timeline-time,
      .timeline-source-id {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
      }
      .timeline-actor {
        font-size: var(--mission-text-sm);
        color: var(--mission-text-primary);
      }
      .timeline-signal,
      .rumor-recommendation p,
      .rumor-step-detail p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .confidence-chip {
        padding: 1px 7px;
        border-radius: 999px;
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        border: 1px solid var(--mission-border);
        color: var(--mission-text-secondary);
      }
      .confidence-chip.low { border-color: rgba(242, 140, 56, 0.42); background: var(--mission-orange-soft); color: var(--mission-orange); }
      .confidence-chip.medium { border-color: rgba(241, 180, 90, 0.42); background: var(--mission-warning-soft); color: var(--mission-warning); }
      .confidence-chip.high { border-color: rgba(63, 209, 141, 0.45); background: var(--mission-success-soft); color: var(--mission-success); }
      .timeline-empty {
        padding: var(--mission-space-3);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-sm);
        color: var(--mission-text-secondary);
      }
      .rumor-step-detail {
        position: sticky;
        top: 84px;
        padding: var(--mission-space-4);
      }
      .rumor-step-detail h3 {
        margin: 0;
        color: var(--mission-text-primary);
        font-size: 16px;
      }
      .rumor-step-detail dl {
        margin: 0;
        display: grid;
        gap: 8px;
      }
      .rumor-step-detail div {
        display: grid;
        grid-template-columns: 86px minmax(0, 1fr);
        gap: 8px;
      }
      .rumor-step-detail dt {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .rumor-step-detail dd {
        margin: 0;
        min-width: 0;
        color: var(--mission-text-secondary);
        overflow-wrap: anywhere;
      }
      .detail-callout {
        display: grid;
        gap: 4px;
        padding: var(--mission-space-3);
        border-radius: var(--mission-radius-sm);
        border: 1px solid rgba(242, 140, 56, 0.28);
        background: rgba(242, 140, 56, 0.08);
      }
      .detail-callout strong {
        color: var(--mission-orange);
        font-size: 12px;
      }
      .detail-callout span {
        color: var(--mission-text-secondary);
        font-size: 13px;
      }
      .rumor-recommendation {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-4);
        border-color: rgba(101, 214, 110, 0.32);
        background: var(--sentinel-accent-soft);
      }
      .rumor-recommendation blockquote {
        margin: 0;
        padding: 0;
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
        color: var(--mission-text-primary);
        font-style: italic;
      }
      .rumor-drawer-foot {
        display: flex;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        padding: var(--mission-space-4) var(--mission-space-5);
        border-top: 1px solid var(--mission-border);
      }
      .action-link {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 36px;
        padding: 8px 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
      }
      .action-link.compact { width: 100%; }
      .action-link.primary {
        border-color: rgba(101, 214, 110, 0.42);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        font-weight: 600;
      }
      .action-link.primary:hover { background: rgba(101, 214, 110, 0.18); }
      .action-link.muted { background: transparent; color: var(--mission-text-secondary); }
      .rumor-drawer-close:hover,
      .action-link:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .rumor-drawer-close:focus-visible,
      .timeline-card:focus-visible,
      .action-link:focus-visible,
      .rumor-filter-bar button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      @media (max-width: 860px) {
        .rumor-investigation-grid,
        .rumor-meta,
        .rumor-metrics { grid-template-columns: 1fr; }
        .rumor-step-detail { position: static; }
      }
      @media (prefers-reduced-motion: reduce) {
        .rumor-drawer-panel { animation: none; }
      }
    `,
  ],
})
export class VpRumorTraceTimelineComponent {
  @Input() embedded = false;
  @Input() open = false;
  @Output() closed = new EventEmitter<void>();
  @Output() draftCommunique = new EventEmitter<void>();
  @Output() showMap = new EventEmitter<void>();

  private _trace: RumorTrace | null = null;
  private requestedFocusStep: number | string | null = null;
  activeFilter: TimelineFilter = 'all';
  private activeStepKey: string | null = null;

  @Input()
  set trace(value: RumorTrace | null) {
    this._trace = value;
    this.applyFocusStep();
  }

  get trace(): RumorTrace | null {
    return this._trace;
  }

  @Input()
  set focusStep(value: number | string | null | undefined) {
    this.requestedFocusStep = value ?? null;
    this.applyFocusStep();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (!this.embedded && this.open) this.closed.emit();
  }

  steps(): RumorChainStep[] {
    return this.trace?.chain || this.trace?.spread || [];
  }

  visibleSteps(): RumorChainStep[] {
    const steps = this.steps();
    if (this.activeFilter === 'all') return steps;
    return steps.filter((step) => this.phaseFor(step) === this.activeFilter);
  }

  selectedStep(): RumorChainStep | null {
    const steps = this.steps();
    if (!steps.length) return null;
    const active = this.activeStepKey
      ? steps.find((step, index) => String(this.stepKey(step, index)) === this.activeStepKey)
      : null;
    if (active) return active;
    return steps.find((step) => this.phaseFor(step) === 'demente') || steps[0] || null;
  }

  selectStep(step: RumorChainStep, visibleIndex: number): void {
    const index = this.steps().indexOf(step);
    this.activeStepKey = String(this.stepKey(step, index >= 0 ? index : visibleIndex));
  }

  isSelectedStep(step: RumorChainStep, visibleIndex: number): boolean {
    const selected = this.selectedStep();
    if (!selected) return false;
    const index = this.steps().indexOf(step);
    const selectedIndex = this.steps().indexOf(selected);
    return String(this.stepKey(step, index >= 0 ? index : visibleIndex)) === String(this.stepKey(selected, selectedIndex));
  }

  setFilter(filter: TimelineFilter): void {
    this.activeFilter = filter;
    const selected = this.selectedStep();
    const selectedStillVisible = selected ? this.visibleSteps().includes(selected) : false;
    if (!selectedStillVisible) {
      const first = this.visibleSteps()[0];
      if (first) this.selectStep(first, 0);
    }
  }

  filterDenied(): void {
    this.setFilter('demente');
  }

  hasOfficialDenial(): boolean {
    return this.steps().some((step) => this.phaseFor(step) === 'demente');
  }

  deniedTimingLabel(): string {
    const denied = this.steps().filter((step) => this.phaseFor(step) === 'demente');
    if (!denied.length) return 'démenti officiel publié';
    const first = denied[0]?.time;
    return first ? `Démenti publié à ${first}` : 'Démenti officiel publié';
  }

  countByPhase(phase: Phase): number {
    return this.steps().filter((step) => this.phaseFor(step) === phase).length;
  }

  rumorDurationLabel(): string {
    return this.durationBetween(this.steps()[0]?.time, this.steps()[this.steps().length - 1]?.time) || '—';
  }

  denialGapLabel(): string {
    const firstDenial = this.steps().find((step) => this.phaseFor(step) === 'demente');
    return this.durationBetween(this.steps()[0]?.time, firstDenial?.time) || '—';
  }

  amplificationPeakLabel(): string {
    const count = this.countByPhase('amplification');
    return count ? `${count} relais` : 'aucun pic';
  }

  phaseFor(step: RumorChainStep): Phase {
    const kind = (step.kind || '').toLowerCase();
    const channel = (step.channel || '').toLowerCase();
    const actor = (step.actor || '').toLowerCase();
    if (
      kind.includes('demente')
      || kind.includes('dementi')
      || kind.includes('denial')
      || channel.includes('communique')
      || channel.includes('prefecture')
      || actor.includes('fanci')
      || actor.includes('prefecture')
    ) {
      return 'demente';
    }
    if (
      kind.includes('amplif')
      || kind.includes('relai')
      || kind.includes('article')
      || channel.includes('blog')
      || channel.includes('telegram')
      || channel.includes('reseaux')
    ) {
      return 'amplification';
    }
    return 'emergence';
  }

  phaseLabel(phase: Phase): string {
    if (phase === 'emergence') return 'Origine du signal';
    if (phase === 'amplification') return 'Amplification publique';
    return 'Démenti officiel';
  }

  narrativeEffectFor(step: RumorChainStep): string {
    const phase = this.phaseFor(step);
    if (phase === 'demente') return 'Stabilise la lecture cabinet : la rumeur est officiellement démentie et peut être traitée en communication maîtrisée.';
    if (phase === 'amplification') return 'Montre où la rumeur a gagné en visibilité avant le démenti, sans valider le fond du récit.';
    return 'Ancre l’origine dans un compte pseudonyme et évite de présenter la rumeur comme un fait établi.';
  }

  actionFor(step: RumorChainStep): string {
    const phase = this.phaseFor(step);
    if (phase === 'demente') return 'Préparer un communiqué';
    if (phase === 'amplification') return 'Préparer réponse proportionnée';
    return 'Cadrer origine';
  }

  glyphFor(channel?: string): string {
    const key = (channel || '').toLowerCase();
    if (key.includes('twitter') || key.includes('x ')) return 'twitter';
    if (key.includes('telegram')) return 'telegram';
    if (key.includes('blog') || key.includes('article')) return 'blog';
    if (key.includes('communique') || key.includes('cabinet')) return 'cabinet';
    if (key.includes('prefecture')) return 'prefecture';
    return 'default';
  }

  channelLetter(channel?: string): string {
    if (!channel) return '·';
    const trimmed = channel.trim();
    if (trimmed.toLowerCase().startsWith('x')) return 'X';
    return trimmed.charAt(0).toUpperCase();
  }

  confidencePct(value: number): number {
    if (value > 1) return Math.round(value);
    return Math.round(value * 100);
  }

  confidenceClass(value: number): 'low' | 'medium' | 'high' {
    const pct = this.confidencePct(value);
    if (pct >= 80) return 'high';
    if (pct >= 50) return 'medium';
    return 'low';
  }

  stepKey(step: RumorChainStep, index: number): string | number {
    return step.source_id || `${step.step ?? index}-${step.actor ?? 'step'}`;
  }

  private applyFocusStep(): void {
    if (this.requestedFocusStep === null || this.requestedFocusStep === undefined || !this.steps().length) return;
    const normalized = String(this.requestedFocusStep).trim();
    const match = this.steps().find((step, index) => String(step.step ?? index + 1) === normalized);
    if (!match) return;
    const index = this.steps().indexOf(match);
    this.activeStepKey = String(this.stepKey(match, index));
  }

  private durationBetween(start?: string, end?: string): string {
    const startMinutes = this.timeToMinutes(start);
    const endMinutes = this.timeToMinutes(end);
    if (startMinutes === null || endMinutes === null || endMinutes < startMinutes) return '';
    const delta = endMinutes - startMinutes;
    const hours = Math.floor(delta / 60);
    const minutes = delta % 60;
    if (!hours) return `${minutes} min`;
    return `${hours}h${String(minutes).padStart(2, '0')}`;
  }

  private timeToMinutes(value?: string): number | null {
    const match = /^(\d{1,2}):(\d{2})$/.exec(value || '');
    if (!match) return null;
    return Number(match[1]) * 60 + Number(match[2]);
  }
}
