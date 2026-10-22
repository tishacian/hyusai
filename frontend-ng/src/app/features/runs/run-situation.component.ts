import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { qualityState } from '@app/features/observability/quality-messages';
import {
  orderedEvaluationRecords,
  type EvaluationSummary,
} from '@app/features/observability/evaluation-records.models';

type QualityRead =
  | { s: 'loading' }
  | { s: 'error' }
  | { s: 'empty' }
  | { s: 'loaded'; quality: string; execution: string; count: number };

interface SituationLine {
  id: 'subject' | 'proposal' | 'quality' | 'decision' | 'effect';
  label: string;
  value: string;
  detail?: string | null;
  /** The Run does not expose this information: said, never reconstructed. */
  unknown: boolean;
}

/** Identifier keys a Run input commonly carries for the business object it treats. */
const SUBJECT_KEY = /(^|_)(id|ref|reference|number)$/i;

/**
 * Situation of a Run: what it treats, what it proposes, what the quality
 * check said, which human decision is expected and which effect is recorded.
 * Each line only reads what the Run projection already exposes; an absent
 * fact is shown as unknown.
 */
@Component({
  selector: 'app-run-situation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <section class="situation" data-testid="run-situation" aria-labelledby="run-situation-title">
      <h2 id="run-situation-title">{{ i18n.t('runs.situation.title') }}</h2>
      <dl>
        @for (line of lines(); track line.id) {
          <div class="line" [attr.data-testid]="'run-situation-' + line.id">
            <dt>{{ line.label }}</dt>
            <dd [class.unknown]="line.unknown">
              <span>{{ line.value }}</span>
              @if (line.detail) { <span class="detail">{{ line.detail }}</span> }
              @if (line.id === 'quality' && quality().s === 'error') {
                <button type="button" class="retry" (click)="reload.update(bump)">{{ i18n.t('common.retry') }}</button>
              }
            </dd>
          </div>
        }
        @if (attempt(); as previous) {
          <div class="line" data-testid="run-situation-attempt">
            <dt>{{ i18n.t('runs.situation.attempt') }}</dt>
            <dd>
              <span>{{ previous.index ? i18n.t('runs.situation.attempt_retry', { index: previous.index }) : i18n.t('runs.situation.attempt_replay') }}</span>
              @if (previous.previous_run_id) {
                <a class="detail" [routerLink]="['/runs', previous.previous_run_id]">{{ i18n.t('runs.situation.attempt_previous', { id: previous.previous_run_id.slice(0, 8) }) }}</a>
              }
            </dd>
          </div>
        }
      </dl>
    </section>
  `,
  styles: [`
    :host { display: block; margin-bottom: var(--ck-space-6); }
    .situation {
      padding: var(--ck-space-4);
      background: var(--ck-bg-panel);
      border: 1px solid var(--ck-stroke-2);
      border-radius: var(--ck-radius-md);
      color: var(--ck-fg-1);
    }
    h2 { font-family: var(--ck-font-display); font-weight: 600; font-size: 16px; margin: 0 0 var(--ck-space-3); }
    dl { display: grid; gap: var(--ck-space-3); margin: 0; }
    .line { display: grid; grid-template-columns: minmax(140px, 220px) 1fr; gap: var(--ck-space-4); }
    dt { color: var(--ck-fg-3); font-size: 13px; }
    dd { margin: 0; display: flex; flex-direction: column; gap: var(--ck-space-1); font-size: 14px; overflow-wrap: anywhere; }
    dd.unknown { color: var(--ck-fg-3); }
    .detail { color: var(--ck-fg-2); font-size: 12px; }
    a.detail { color: var(--ck-primary); }
    a.detail:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .retry {
      align-self: flex-start;
      padding: var(--ck-space-1) var(--ck-space-3);
      border: 1px solid var(--ck-stroke-3);
      border-radius: var(--ck-radius-sm);
      background: transparent;
      color: inherit;
    }
    .retry:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    @media (max-width: 640px) { .line { grid-template-columns: 1fr; gap: var(--ck-space-1); } }
  `],
})
export class RunSituationComponent {
  readonly run = input.required<Run>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  readonly quality = signal<QualityRead>({ s: 'loading' });
  readonly reload = signal(0);
  readonly bump = (value: number) => value + 1;

  constructor() {
    effect((onCleanup) => {
      this.reload();
      const id = this.run().id;
      const workspaceId = this.workspace.current()?.id;
      this.quality.set({ s: 'loading' });
      const subscription = this.api
        .get<EvaluationSummary>(`/evaluation/by-run/${encodeURIComponent(id)}/summary`)
        .subscribe({
          next: (summary) => {
            if (this.run().id !== id || this.workspace.current()?.id !== workspaceId) return;
            if (summary?.schema_version !== 1 || !Array.isArray(summary.records) || !summary.totals) {
              this.quality.set({ s: 'error' });
              return;
            }
            const latest = orderedEvaluationRecords(summary.records)[0];
            this.quality.set(
              latest
                ? {
                    s: 'loaded',
                    quality: latest.quality_status,
                    execution: latest.execution_status,
                    count: summary.records.length,
                  }
                : { s: 'empty' },
            );
          },
          error: () => {
            if (this.run().id !== id || this.workspace.current()?.id !== workspaceId) return;
            this.quality.set({ s: 'error' });
          },
        });
      onCleanup(() => subscription.unsubscribe());
    });
  }

  /** Replay or evaluation retry: linked to the Run it repeats, never merged with it. */
  readonly attempt = computed(() => this.run().follow_up?.attempt ?? null);

  readonly lines = computed<SituationLine[]>(() => [
    this.subjectLine(),
    this.proposalLine(),
    this.qualityLine(),
    this.decisionLine(),
    this.effectLine(),
  ]);

  private t(key: string, params?: Record<string, string | number>): string {
    return this.i18n.t(key, params);
  }

  private unknownLine(id: SituationLine['id']): SituationLine {
    return { id, label: this.t(`runs.situation.${id}`), value: this.t('runs.situation.unknown'), unknown: true };
  }

  private subjectLine(): SituationLine {
    const input = this.run().input_ref ?? {};
    const entry = Object.entries(input).find(
      ([key, value]) =>
        !key.startsWith('_') &&
        SUBJECT_KEY.test(key) &&
        (typeof value === 'string' || typeof value === 'number') &&
        String(value).trim() !== '',
    );
    if (!entry) return this.unknownLine('subject');
    return {
      id: 'subject',
      label: this.t('runs.situation.subject'),
      value: String(entry[1]),
      detail: this.t('runs.situation.subject_field', { field: entry[0] }),
      unknown: false,
    };
  }

  private proposalLine(): SituationLine {
    const run = this.run();
    const proposal = text(run.hitl?.decision_title) ?? text(run.hitl?.prompt) ?? text(run.outcome?.decision);
    if (!proposal) return this.unknownLine('proposal');
    return { id: 'proposal', label: this.t('runs.situation.proposal'), value: proposal, unknown: false };
  }

  private qualityLine(): SituationLine {
    const label = this.t('runs.situation.quality');
    const read = this.quality();
    if (read.s === 'loading') return { id: 'quality', label, value: this.t('runs.situation.quality_loading'), unknown: true };
    if (read.s === 'error') return { id: 'quality', label, value: this.t('runs.situation.quality_unavailable'), unknown: true };
    if (read.s === 'empty') return { id: 'quality', label, value: this.t('runs.situation.quality_none'), unknown: false };
    const execution = qualityState(this.i18n, read.execution, true);
    return {
      id: 'quality',
      label,
      value: read.execution === 'failed' ? execution : qualityState(this.i18n, read.quality),
      detail: this.t('runs.situation.quality_count', { count: read.count }),
      unknown: false,
    };
  }

  private decisionLine(): SituationLine {
    const run = this.run();
    const label = this.t('runs.situation.decision');
    const state = run.follow_up?.business_state;
    if (state === 'awaiting_human_decision') {
      const expires = formatInstant(run.hitl?.expires_at, this.i18n.locale());
      return {
        id: 'decision',
        label,
        value: this.t('runs.situation.decision_expected'),
        detail: expires ? this.t('runs.situation.decision_expires', { at: expires }) : null,
        unknown: false,
      };
    }
    if (state === 'stopped_at_review_boundary') {
      return { id: 'decision', label, value: this.t('runs.situation.decision_boundary'), unknown: false };
    }
    if (state === 'in_progress' || state === 'paused_for_debug') {
      return { id: 'decision', label, value: this.t('runs.situation.decision_not_yet'), unknown: false };
    }
    if (state === 'completed' || state === 'failed' || state === 'cancelled') {
      return { id: 'decision', label, value: this.t('runs.situation.decision_none'), unknown: false };
    }
    return this.unknownLine('decision');
  }

  private effectLine(): SituationLine {
    if (this.run().follow_up?.business_state === 'stopped_at_review_boundary') {
      return {
        id: 'effect',
        label: this.t('runs.situation.effect'),
        value: this.t('runs.situation.effect_none_boundary'),
        unknown: false,
      };
    }
    return this.unknownLine('effect');
  }
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/** Instants carry their time zone so two screens never disagree silently. */
function formatInstant(value: string | null | undefined, locale: string): string | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const time = Date.parse(normalized);
  if (!Number.isFinite(time)) return null;
  // dateStyle/timeStyle cannot be combined with timeZoneName: spell the parts.
  return new Date(time).toLocaleString(locale, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  });
}
