import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import type { VpAgendaTimeline, VpAgendaTimelineEvent, VpArbitrationCard } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-agenda-timeline',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="agenda-timeline" aria-label="Agenda ministeriel">
      <header>
        <span class="eyebrow">{{ timeline.label || i18n.t('mission.agenda.timeline_eyebrow') }}</span>
        <h2>{{ i18n.t('mission.agenda.timeline_title') }}</h2>
        @if (timeline.separate_from_actions !== false) {
          <small>{{ i18n.t('mission.agenda.timeline_hint') }}</small>
        }
      </header>
      <div class="timeline-track">
        @for (event of timeline.events; track event.id || event.time + event.title; let idx = $index) {
          @if (event.is_now || isNowMarker(idx)) {
            <div class="now-marker">
              <span>{{ timeline.now_marker || 'MAINTENANT' }}</span>
              @if (event.countdown) {
                <em>{{ event.countdown }}</em>
              }
            </div>
          }
          <button type="button" class="timeline-event" [class]="toneClass(event.tone)" (click)="eventSelected.emit(event)">
            <time>{{ event.time }}@if (event.end_time) {–{{ event.end_time }}}</time>
            <strong>{{ event.title }}</strong>
            @if (event.location) {
              <small>{{ event.location }}</small>
            }
          </button>
        }
      </div>
    </section>
  `,
  styles: [
    `
      :host { display: block; }
      header { margin-bottom: var(--mission-space-3); }
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
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      header small {
        display: block;
        margin-top: var(--mission-space-1);
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .timeline-track {
        display: grid;
        gap: 0;
        border-left: 2px solid var(--mission-border);
        margin-left: var(--mission-space-2);
        padding-left: var(--mission-space-4);
      }
      .now-marker {
        display: flex;
        align-items: center;
        gap: var(--mission-space-2);
        margin: var(--mission-space-1) 0 var(--mission-space-2) calc(-1 * var(--mission-space-6) - 1px);
      }
      .now-marker span {
        padding: 3px 9px;
        border-radius: 999px;
        border: 1px solid rgba(242, 140, 56, 0.42);
        background: var(--agentium-aya-soft);
        color: var(--mission-orange);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: var(--mission-tracking-micro);
      }
      .now-marker em {
        color: var(--mission-text-tertiary);
        font-style: normal;
        font-family: var(--mission-font-mono);
        font-size: var(--mission-text-xs);
      }
      .timeline-event {
        position: relative;
        display: grid;
        gap: var(--mission-space-1);
        width: 100%;
        margin-bottom: var(--mission-space-2);
        padding: var(--mission-space-2) var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.52);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .timeline-event::before {
        content: "";
        position: absolute;
        left: calc(-1 * var(--mission-space-5) - 1px);
        top: 14px;
        width: 9px;
        height: 9px;
        border-radius: 999px;
        background: var(--sentinel-accent);
        box-shadow: 0 0 0 3px rgba(101, 214, 110, 0.14);
      }
      .timeline-event:hover {
        border-color: var(--sentinel-accent-muted);
        background: rgba(101, 214, 110, 0.04);
      }
      .timeline-event:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .timeline-event.elevated::before { background: var(--mission-warning); box-shadow: 0 0 0 3px rgba(241, 180, 90, 0.14); }
      .timeline-event.critical::before { background: var(--mission-critical); box-shadow: 0 0 0 3px rgba(240, 100, 118, 0.14); }
      .timeline-event.critical { border-left: 2px solid var(--mission-critical); }
      .timeline-event.elevated { border-left: 2px solid var(--mission-warning); }
      time {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.04em;
      }
      strong {
        font-size: var(--mission-text-sm);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: 1.3;
        color: var(--mission-text-primary);
      }
      small {
        color: var(--mission-text-tertiary);
        font-size: 10px;
      }
    `,
  ],
})
export class VpAgendaTimelineComponent {
  readonly i18n = inject(I18nService);
  @Input() timeline: VpAgendaTimeline = { events: [] };
  @Output() eventSelected = new EventEmitter<VpAgendaTimelineEvent>();

  toneClass(tone?: string): string {
    const normalized = (tone || '').toLowerCase();
    if (normalized === 'critical') return 'critical';
    if (normalized === 'elevated' || normalized === 'watch') return 'elevated';
    return 'stable';
  }

  isNowMarker(index: number): boolean {
    return index === 1 && !this.timeline.events.some((event) => event.is_now);
  }
}
