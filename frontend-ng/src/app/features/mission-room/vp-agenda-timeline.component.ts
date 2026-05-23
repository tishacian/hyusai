import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { VpAgendaTimeline, VpAgendaTimelineEvent, VpArbitrationCard } from './vp-cockpit.types';

@Component({
  selector: 'app-vp-agenda-timeline',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="agenda-timeline" aria-label="Agenda ministeriel">
      <header>
        <span class="eyebrow">{{ timeline.label || 'Agenda ministeriel' }}</span>
        <h2>Pilotage du temps</h2>
        @if (timeline.separate_from_actions !== false) {
          <small>Distinct des actions a arbitrer</small>
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
      header { margin-bottom: 10px; }
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
        font-size: 16px;
      }
      header small {
        display: block;
        margin-top: 4px;
        color: var(--mission-text-faint);
        font-size: 10px;
      }
      .timeline-track {
        display: grid;
        gap: 0;
        border-left: 2px solid rgba(148, 163, 184, 0.18);
        margin-left: 8px;
        padding-left: 14px;
      }
      .now-marker {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 4px 0 8px -23px;
      }
      .now-marker span {
        padding: 3px 8px;
        border-radius: 999px;
        border: 1px solid rgba(242, 140, 56, 0.38);
        background: rgba(242, 140, 56, 0.12);
        color: var(--mission-orange);
        font-family: var(--ck-font-mono);
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.12em;
      }
      .now-marker em {
        color: var(--mission-text-muted);
        font-style: normal;
        font-size: 11px;
      }
      .timeline-event {
        position: relative;
        display: grid;
        gap: 3px;
        width: 100%;
        margin-bottom: 10px;
        padding: 9px 10px;
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: rgba(4, 8, 13, 0.52);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
      }
      .timeline-event::before {
        content: "";
        position: absolute;
        left: -21px;
        top: 14px;
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--mission-accent);
        box-shadow: 0 0 0 3px rgba(125, 211, 252, 0.12);
      }
      .timeline-event.critical::before { background: var(--mission-danger); }
      .timeline-event.elevated::before { background: var(--mission-warn); }
      time {
        color: var(--mission-text-muted);
        font-family: var(--ck-font-mono);
        font-size: 10px;
      }
      strong {
        font-size: 13px;
        line-height: 1.25;
      }
      small {
        color: var(--mission-text-faint);
        font-size: 10px;
      }
    `,
  ],
})
export class VpAgendaTimelineComponent {
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
