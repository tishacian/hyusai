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

            <section class="rumor-timeline" aria-label="Chronologie OSINT">
              <span class="eyebrow">Chaîne de propagation</span>
              <ol class="timeline">
                @for (step of steps(); track stepKey(step, $index)) {
                  <li class="timeline-item" [attr.data-phase]="phaseFor(step)">
                    <span class="timeline-rail" aria-hidden="true"></span>
                    <span class="timeline-dot" [class]="'phase-' + phaseFor(step)" aria-hidden="true">
                      <span>{{ step.step ?? $index + 1 }}</span>
                    </span>
                    <article class="timeline-card" [class]="'phase-' + phaseFor(step)">
                      <header>
                        <span class="timeline-channel">
                          <span class="channel-glyph" [class]="'glyph-' + glyphFor(step.channel)" aria-hidden="true">{{ channelLetter(step.channel) }}</span>
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
                          <span class="confidence-chip" [class]="confidenceClass(step.confidence)">
                            confiance {{ confidencePct(step.confidence) }}%
                          </span>
                        }
                        @if (step.source_url) {
                          <a class="timeline-source" [href]="step.source_url" target="_blank" rel="noopener noreferrer">Source</a>
                        } @else if (step.source_id) {
                          <span class="timeline-source-id">src · {{ step.source_id }}</span>
                        }
                      </footer>
                    </article>
                  </li>
                }
              </ol>
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
            <button type="button" class="action-link muted" (click)="closed.emit()">
              Fermer
            </button>
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
        width: min(620px, 100vw);
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
        to   { transform: translateX(0);    opacity: 1; }
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
      .rumor-drawer-close:hover {
        border-color: var(--sentinel-accent-muted);
        color: var(--mission-text-primary);
      }
      .rumor-drawer-close:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
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
      .risk-pill.success {
        border-color: rgba(63, 209, 141, 0.45);
        background: var(--mission-success-soft);
        color: var(--mission-success);
      }
      .risk-pill.warn {
        border-color: rgba(242, 140, 56, 0.42);
        background: var(--mission-orange-soft);
        color: var(--mission-orange);
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

      .verdict-bar {
        display: flex;
        gap: var(--mission-space-3);
        align-items: center;
        padding: var(--mission-space-3) var(--mission-space-4);
        border-radius: var(--mission-radius-md);
        border: 1px solid var(--mission-border);
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
      .verdict-denied .verdict-icon {
        background: var(--mission-success);
        color: #03130a;
      }
      .verdict-pending .verdict-icon {
        background: var(--mission-orange);
        color: #1a0d05;
      }
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

      .rumor-meta {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
        gap: var(--mission-space-4);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .rumor-meta p {
        margin: 0;
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }

      .rumor-timeline {
        display: grid;
        gap: var(--mission-space-3);
      }
      .timeline {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: var(--mission-space-3);
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
      .timeline-dot.phase-emergence    { background: var(--mission-orange); }
      .timeline-dot.phase-amplification { background: var(--mission-critical); }
      .timeline-dot.phase-demente      { background: var(--mission-success); }

      .timeline-card {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-left-width: 3px;
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.55);
      }
      .timeline-card.phase-emergence    { border-left-color: var(--mission-orange); }
      .timeline-card.phase-amplification { border-left-color: var(--mission-critical); }
      .timeline-card.phase-demente      { border-left-color: var(--mission-success); }

      .timeline-card header {
        display: flex;
        align-items: center;
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
      .channel-glyph.glyph-twitter  { background: #7dd3fc; }
      .channel-glyph.glyph-telegram { background: #93ef74; }
      .channel-glyph.glyph-blog     { background: #f1b45a; }
      .channel-glyph.glyph-cabinet  { background: #f06476; }
      .channel-glyph.glyph-prefecture { background: var(--mission-success); }
      .timeline-time {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
      }
      .timeline-actor {
        font-size: var(--mission-text-sm);
        color: var(--mission-text-primary);
      }
      .timeline-signal {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
      }
      .timeline-foot {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--mission-space-2);
        font-family: var(--mission-font-mono);
        font-size: 10px;
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
      .confidence-chip.low {
        border-color: rgba(242, 140, 56, 0.42);
        background: var(--mission-orange-soft);
        color: var(--mission-orange);
      }
      .confidence-chip.medium {
        border-color: rgba(241, 180, 90, 0.42);
        background: var(--mission-warning-soft);
        color: var(--mission-warning);
      }
      .confidence-chip.high {
        border-color: rgba(63, 209, 141, 0.45);
        background: var(--mission-success-soft);
        color: var(--mission-success);
      }
      .timeline-source {
        color: var(--sentinel-accent-strong);
        text-decoration: none;
      }
      .timeline-source:hover { text-decoration: underline; }
      .timeline-source-id {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
      }

      .rumor-recommendation {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-4);
        border: 1px solid rgba(101, 214, 110, 0.32);
        border-radius: var(--mission-radius-md);
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
      .rumor-recommendation p {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
        line-height: var(--mission-lh-body);
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
        min-height: 36px;
        padding: 8px 14px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: var(--mission-text-primary);
        font-size: var(--mission-text-sm);
        cursor: pointer;
      }
      .action-link.primary {
        border-color: rgba(101, 214, 110, 0.42);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        font-weight: 600;
      }
      .action-link.primary:hover { background: rgba(101, 214, 110, 0.18); }
      .action-link.muted { background: transparent; color: var(--mission-text-secondary); }
      .action-link:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }

      @media (max-width: 540px) {
        .rumor-meta { grid-template-columns: 1fr; }
      }
      @media (prefers-reduced-motion: reduce) {
        .rumor-drawer-panel { animation: none; }
      }
      .rumor-embedded-root { display: block; }
      .rumor-embedded-panel {
        position: relative;
        width: 100%;
        max-height: none;
        border: none;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
        animation: none;
      }
    `,
  ],
})
export class VpRumorTraceTimelineComponent {
  @Input() embedded = false;
  @Input() open = false;
  @Input() trace: RumorTrace | null = null;
  @Output() closed = new EventEmitter<void>();
  @Output() draftCommunique = new EventEmitter<void>();

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open) this.closed.emit();
  }

  steps(): RumorChainStep[] {
    return this.trace?.chain || this.trace?.spread || [];
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
}
