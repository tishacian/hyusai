import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import type { RunFollowUpDetail } from '@app/core/run-follow-up';
import { situationLines, type QualityValue, type Read, type SituationLine } from './run-situation.vm';
import { WorkspaceService } from '@app/core/workspace.service';
import { qualityState } from '@app/features/observability/quality-messages';
import {
  orderedEvaluationRecords,
  type EvaluationSummary,
} from '@app/features/observability/evaluation-records.models';

/**
 * Situation of one Run, shared by the Run page and Work case readers.
 *
 * Reads `GET /runs/{id}/follow-up` (state, object, proposal, human decision
 * and its server-computed deadline) and the Run's quality checks. Each line
 * says what the server knows; a missing fact is "unknown", a failed read
 * says it failed and offers a retry.
 */
@Component({
  selector: 'app-run-situation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <section class="situation" [class.compact]="compact()" data-testid="run-situation" [attr.aria-labelledby]="titleId">
      <h2 [id]="titleId">{{ i18n.t('runs.situation.title') }}</h2>
      @switch (followUp().s) {
        @case ('loading') { <p role="status" class="note">{{ i18n.t('runs.situation.loading') }}</p> }
        @case ('error') {
          <p role="alert" class="note">{{ i18n.t('runs.situation.unavailable') }}</p>
          <button type="button" class="retry" (click)="reload.update(bump)">{{ i18n.t('common.retry') }}</button>
        }
        @default {
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
          @if (!showRunLink() && workOrigin(); as origin) {
            <a class="detail run-link" data-testid="run-situation-work-case"
              [routerLink]="['/work', origin.experience_slug, origin.page_id]"
              [queryParams]="origin.record_ref ? { record: origin.record_ref, attempt: runId() } : {}">{{
                i18n.t(origin.record_ref ? 'runs.situation.open_work_case' : 'runs.situation.open_work_app', { ref: origin.record_ref ?? '' }) }}</a>
          }
          @if (showRunLink()) {
            <a class="detail run-link" [routerLink]="['/runs', runId()]">{{ i18n.t('runs.situation.open_run', { id: runId().slice(0, 8) }) }}</a>
          }
        }
      }
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
    .situation.compact { padding: var(--ck-space-3); }
    h2 { font-family: var(--ck-font-display); font-weight: 600; font-size: 16px; margin: 0 0 var(--ck-space-3); }
    .compact h2 { font-size: 14px; }
    dl { display: grid; gap: var(--ck-space-3); margin: 0; }
    .line { display: grid; grid-template-columns: minmax(140px, 220px) 1fr; gap: var(--ck-space-4); }
    .compact .line { grid-template-columns: 1fr; gap: var(--ck-space-1); }
    dt { color: var(--ck-fg-3); font-size: 13px; }
    dd { margin: 0; display: flex; flex-direction: column; gap: var(--ck-space-1); font-size: 14px; overflow-wrap: anywhere; }
    dd.unknown, .note { color: var(--ck-fg-3); }
    .note { margin: 0; font-size: 13px; }
    .detail { color: var(--ck-fg-2); font-size: 12px; }
    a.detail { color: var(--ck-primary); }
    a.detail:focus-visible, .retry:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .run-link { display: inline-block; margin-top: var(--ck-space-3); }
    .retry {
      align-self: flex-start;
      margin-top: var(--ck-space-2);
      padding: var(--ck-space-1) var(--ck-space-3);
      border: 1px solid var(--ck-stroke-3);
      border-radius: var(--ck-radius-sm);
      background: transparent;
      color: inherit;
    }
    @media (max-width: 640px) { .line { grid-template-columns: 1fr; gap: var(--ck-space-1); } }
  `],
})
export class RunSituationComponent {
  readonly runId = input.required<string>();
  /** Bump to re-read after the caller learned the Run changed. */
  readonly refreshKey = input<unknown>(null);
  readonly compact = input(false);
  readonly showRunLink = input(false);
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private static sequence = 0;
  readonly titleId = `run-situation-title-${++RunSituationComponent.sequence}`;

  readonly followUp = signal<Read<RunFollowUpDetail>>({ s: 'loading' });
  readonly quality = signal<Read<QualityValue>>({ s: 'loading' });
  readonly reload = signal(0);
  readonly bump = (value: number) => value + 1;

  constructor() {
    effect((onCleanup) => {
      this.reload();
      this.refreshKey();
      const id = this.runId();
      const scope = this.workspace.captureRequestScope();
      const current = () => this.runId() === id && this.workspace.isRequestScopeCurrent(scope);
      // Keep the last situation of the same Run while it is re-read.
      this.followUp.update((read) => (read.s === 'loaded' && read.value.run_id === id ? read : { s: 'loading' }));
      this.quality.set({ s: 'loading' });
      const encoded = encodeURIComponent(id);
      const followUp = this.api.get<RunFollowUpDetail>(`/runs/${encoded}/follow-up`).subscribe({
        next: (value) => {
          if (!current()) return;
          this.followUp.set(value?.run_id === id ? { s: 'loaded', value } : { s: 'error' });
        },
        error: () => { if (current()) this.followUp.set({ s: 'error' }); },
      });
      const quality = this.api.get<EvaluationSummary>(`/evaluation/by-run/${encoded}/summary`).subscribe({
        next: (summary) => {
          if (!current()) return;
          if (summary?.schema_version !== 1 || !Array.isArray(summary.records) || !summary.totals) {
            this.quality.set({ s: 'error' });
            return;
          }
          const latest = orderedEvaluationRecords(summary.records)[0];
          this.quality.set({
            s: 'loaded',
            value: latest ? { quality: latest.quality_status, execution: latest.execution_status, count: summary.records.length } : null,
          });
        },
        error: () => { if (current()) this.quality.set({ s: 'error' }); },
      });
      onCleanup(() => { followUp.unsubscribe(); quality.unsubscribe(); });
    });
  }

  private readonly detail = computed(() => {
    const read = this.followUp();
    return read.s === 'loaded' ? read.value : null;
  });

  readonly attempt = computed(() => this.detail()?.attempt ?? null);
  readonly workOrigin = computed(() => this.detail()?.work_origin ?? null);

  readonly lines = computed<SituationLine[]>(() => {
    const detail = this.detail();
    if (!detail) return [];
    return situationLines(detail, this.quality(), (key, params) => this.i18n.t(key, params), this.i18n.locale(), (value, execution) => qualityState(this.i18n, value, execution));
  });
}
