import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ThinkingOrbComponent, type CkOrbState } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import type { TracePhase, TracePhaseKey } from './chat-proof';

/** A real step as the detail list shows it. */
export interface TraceStepView {
  id: string;
  title: string;
  status: 'pending' | 'active' | 'completed' | 'warning' | 'error' | undefined;
  duration?: number;
}

const ORB_OF_PHASE: Record<TracePhaseKey, CkOrbState> = {
  search: 'searching',
  read: 'solving',
  compose: 'composing',
};

/**
 * L30 — the agent's work above the answer: « Recherche → Lecture →
 * Rédaction », built only from phases that received a real step. While the
 * answer streams, the current phase carries the thinking orb (the only one on
 * screen) and a polite live region says what is happening; once done, the
 * trace folds to one line and the real steps open on demand.
 */
@Component({
  selector: 'app-chat-work-trace',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, ThinkingOrbComponent],
  template: `
    <section
      class="work-trace"
      [class.work-trace--live]="live()"
      [attr.aria-label]="i18n.t('chat.thread.trace.aria')"
      data-testid="chat-work-trace"
    >
      <div class="work-trace-row">
        @if (live()) {
          <span class="work-trace-kicker">{{ i18n.t('chat.thread.trace.live') }}</span>
        }
        @if (live() && !phases().length) {
          <!-- No phase has reported yet: the orb waits alone, no step is invented. -->
          <ck-thinking-orb state="working" [size]="20" [label]="statusLabel() || i18n.t('chat.thread.trace.live')" />
        }
        <ol class="work-trace-phases">
          @for (phase of phases(); track phase.key) {
            <li
              class="work-trace-phase"
              [class.is-current]="phase.status === 'current'"
              [class.is-error]="phase.status === 'error'"
              [attr.aria-current]="phase.status === 'current' ? 'step' : null"
            >
              @if (phase.status === 'current') {
                <ck-thinking-orb [state]="orbOf(phase.key)" [size]="20" [label]="statusLabel() || phaseLabel(phase.key)" />
              } @else if (phase.status === 'error') {
                <app-icon name="alert-triangle" [size]="12" aria-hidden="true" />
              } @else {
                <app-icon name="check" [size]="12" aria-hidden="true" />
              }
              <span>{{ phaseLabel(phase.key) }}</span>
              @if (phase.status === 'error') {
                <span class="visually-hidden">{{ i18n.t('chat.thread.trace.failed') }}</span>
              }
            </li>
          }
        </ol>
        @if (!live() && steps().length) {
          <!-- Folded to one line: the recap itself opens the real steps. -->
          <button
            type="button"
            class="work-trace-toggle"
            [attr.aria-expanded]="expanded()"
            [attr.aria-controls]="expanded() ? detailId : null"
            [title]="i18n.t(expanded() ? 'chat.thread.trace.hide' : 'chat.thread.trace.show')"
            (click)="expanded.set(!expanded())"
          >
            <span class="visually-hidden">{{ i18n.t(expanded() ? 'chat.thread.trace.hide' : 'chat.thread.trace.show') }} · </span>{{ summary() }}
            <app-icon [name]="expanded() ? 'chevron-up' : 'chevron-down'" [size]="12" aria-hidden="true" />
          </button>
        } @else if (!live() && summary()) {
          <span class="work-trace-summary">{{ summary() }}</span>
        }
      </div>
      @if (live() && statusLabel()) {
        <p class="work-trace-status" aria-hidden="true">{{ statusLabel() }}</p>
      }
      <p class="visually-hidden" role="status">{{ live() ? statusLabel() : '' }}</p>
      @if (!live() && expanded()) {
        <ol class="work-trace-steps" [id]="detailId">
          @for (step of steps(); track step.id) {
            <li class="work-trace-step" [class.is-error]="step.status === 'error'">
              <app-icon [name]="step.status === 'error' ? 'alert-triangle' : 'check'" [size]="11" aria-hidden="true" />
              <span class="work-trace-step-title">{{ step.title }}</span>
              @if (step.duration) {
                <span class="work-trace-step-time">{{ durationLabel(step.duration) }}</span>
              }
            </li>
          }
        </ol>
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .work-trace {
      max-width: 72ch;
      padding: 10px 12px;
      border: 1px solid var(--ck-stroke-2);
      border-left: 3px solid var(--ck-stroke-3, var(--ck-stroke-2));
      border-radius: 6px;
      background: var(--ck-bg-panel);
      color: var(--ck-fg-2);
      font-size: 12px;
      line-height: 1.4;
    }
    .work-trace--live { border-left-color: var(--ck-primary); }
    .work-trace-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }
    .work-trace-kicker { font-weight: 600; color: var(--ck-fg-1); }
    .work-trace-phases { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin: 0; padding: 0; list-style: none; }
    .work-trace-phase { display: inline-flex; align-items: center; gap: 5px; color: var(--ck-fg-3); white-space: nowrap; }
    .work-trace-phase + .work-trace-phase::before {
      content: "→" / "";
      margin-right: 4px;
      color: var(--ck-fg-3);
    }
    .work-trace-phase.is-current { color: var(--ck-fg-1); font-weight: 600; }
    .work-trace-phase.is-error { color: var(--ck-signal-warn); }
    .work-trace-summary { margin-left: auto; color: var(--ck-fg-3); white-space: nowrap; }
    .work-trace-toggle {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-left: auto;
      min-height: 24px;
      padding: 0 6px;
      border: 1px solid transparent;
      border-radius: 4px;
      background: transparent;
      color: var(--ck-fg-3);
      font-size: 12px;
      white-space: nowrap;
    }
    .work-trace-toggle:hover { border-color: var(--ck-stroke-2); color: var(--ck-fg-1); }
    .work-trace-toggle:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .work-trace-status { margin: 6px 0 0; color: var(--ck-fg-2); }
    .work-trace-steps { display: flex; flex-direction: column; gap: 4px; margin: 8px 0 0; padding: 8px 0 0; border-top: 1px solid var(--ck-stroke-2); list-style: none; }
    .work-trace-step { display: flex; align-items: center; gap: 6px; color: var(--ck-fg-2); }
    .work-trace-step.is-error { color: var(--ck-signal-warn); }
    .work-trace-step-title { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
    .work-trace-step-time { font: 11px/1 var(--ck-font-mono); color: var(--ck-fg-3); }
    .visually-hidden {
      position: absolute !important;
      width: 1px; height: 1px;
      margin: -1px; padding: 0; border: 0;
      overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%);
      white-space: nowrap;
    }
  `],
})
export class ChatWorkTraceComponent {
  protected readonly i18n = inject(I18nService);

  readonly phases = input<TracePhase[]>([]);
  readonly live = input(false);
  /** Plain-language activity from the real progress events (live only). */
  readonly statusLabel = input('');
  /** One-line recap once done, e.g. « 5 étapes · 2,1 s ». */
  readonly summary = input('');
  readonly steps = input<TraceStepView[]>([]);

  readonly expanded = signal(false);
  private static nextId = 0;
  readonly detailId = `chat-work-trace-${++ChatWorkTraceComponent.nextId}`;

  private readonly locale = computed(() => this.i18n.locale());

  orbOf(key: TracePhaseKey): CkOrbState {
    return ORB_OF_PHASE[key];
  }

  phaseLabel(key: TracePhaseKey): string {
    return this.i18n.t(`chat.thread.phase.${key}`);
  }

  durationLabel(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toLocaleString(this.locale(), { maximumFractionDigits: 1 })} s`;
  }
}
