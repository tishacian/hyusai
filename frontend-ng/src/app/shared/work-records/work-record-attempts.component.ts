import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { formatRunInstant, runStatusLabel, type RunFollowUp } from '@app/core/run-follow-up';
import { WorkspaceService } from '@app/core/workspace.service';
import { attemptsView } from './work-record-attempts.vm';

export interface WorkRecordAttempt {
  attempt_id: string;
  run_id: string;
  binding_key: string;
  recorded_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  status: string;
  follow_up: RunFollowUp;
  /** Team history: whether the reader started it, and who did. */
  started_by_reader?: boolean;
  started_by?: string | null;
}

interface AttemptsPage {
  attempts: WorkRecordAttempt[];
  has_more: boolean;
  next_offset: number | null;
}

interface BindingResolution {
  binding?: { record_identity?: { namespace: string; input_field: string } | null };
}

type ListState =
  | { s: 'loading' }
  | { s: 'not_configured' }
  | { s: 'error' }
  | { s: 'loaded'; attempts: WorkRecordAttempt[]; hasMore: boolean; nextOffset: number | null; loadingMore: boolean; moreFailed: boolean };

const PAGE = 10;

/**
 * Attempts a Work record received from this reader, newest first.
 *
 * Generic: the record kind comes from the action's released identity
 * contract, never from the screen. A new attempt is listed next to earlier
 * ones; selecting one is the caller's choice and survives refreshes.
 */
@Component({
  selector: 'app-work-record-attempts',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="attempts" data-testid="work-record-attempts" [attr.aria-labelledby]="titleId">
      <h3 [id]="titleId">{{ i18n.t('experience.record_attempts.title') }}</h3>
      @switch (state().s) {
        @case ('loading') { <p role="status" class="note">{{ i18n.t('experience.record_attempts.loading') }}</p> }
        @case ('not_configured') { <p class="note">{{ i18n.t('experience.record_attempts.not_configured') }}</p> }
        @case ('error') {
          <p role="alert" class="note">{{ i18n.t('experience.record_attempts.failed') }}</p>
          <button type="button" class="more" (click)="reload.update(bump)">{{ i18n.t('common.retry') }}</button>
        }
        @default {
          @if (loaded(); as list) {
            @if (view(); as shown) {
              @if (shown.empty) {
                <p class="note">{{ i18n.t('experience.record_attempts.empty') }}</p>
              } @else {
                <ol>
                  @for (line of shown.lines; track line.runId; let n = $index) {
                    <li>
                      <button
                        type="button"
                        class="attempt"
                        [class.is-selected]="line.runId === selectedRunId()"
                        [attr.aria-current]="line.runId === selectedRunId() ? 'true' : null"
                        [attr.data-testid]="'work-record-attempt-' + line.runId"
                        (click)="selectRun.emit(line.runId)"
                      >
                        @if (line.attempt; as attempt) {
                          <span class="when">{{ when(attempt) }}</span>
                          <span class="state">{{ stateLabel(attempt) }}</span>
                          @if (attempt.started_by_reader === false && attempt.started_by) { <span class="state">· {{ i18n.t('experience.record_attempts.by', { name: attempt.started_by }) }}</span> }
                        } @else {
                          <span class="when">{{ i18n.t('experience.record_attempts.shown_run', { id: line.runId.slice(0, 8) }) }}</span>
                          <span class="state">{{ i18n.t('experience.record_attempts.not_in_history') }}</span>
                        }
                        @if (n === 0) { <span class="tag">{{ i18n.t('experience.record_attempts.latest') }}</span> }
                      </button>
                    </li>
                  }
                </ol>
                @if (list.hasMore) {
                  <button type="button" class="more" [disabled]="list.loadingMore" (click)="loadMore()">
                    {{ i18n.t(list.loadingMore ? 'experience.record_attempts.loading_more' : 'experience.record_attempts.more') }}
                  </button>
                  @if (list.moreFailed) { <p role="alert" class="note">{{ i18n.t('experience.record_attempts.failed') }}</p> }
                }
              }
              @if (shown.historyIncomplete) { <p class="note" data-testid="work-record-attempts-incomplete">{{ i18n.t('experience.record_attempts.history_incomplete') }}</p> }
            }
            <p class="note scope">{{ i18n.t('experience.record_attempts.scope') }}</p>
          }
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .attempts { padding: var(--ck-space-3); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-panel); color: var(--ck-fg-1); }
    h3 { margin: 0 0 var(--ck-space-2); font-family: var(--ck-font-display); font-weight: 600; font-size: 14px; }
    ol { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--ck-space-1); }
    .attempt {
      width: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: var(--ck-space-2);
      padding: var(--ck-space-2) var(--ck-space-3); text-align: left;
      border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-sm);
      background: transparent; color: inherit; font-size: 13px;
    }
    .attempt:hover { background: var(--ck-bg-panel-hi); }
    .attempt.is-selected { border-color: var(--ck-primary); background: var(--ck-bg-panel-hi); }
    .attempt:focus-visible, .more:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .when { font-variant-numeric: tabular-nums; }
    .state { color: var(--ck-fg-2); }
    .tag { margin-left: auto; padding: 0 var(--ck-space-2); border: 1px solid var(--ck-stroke-3); border-radius: var(--ck-radius-sm); font-size: 12px; color: var(--ck-fg-2); }
    .note { margin: var(--ck-space-2) 0 0; font-size: 12px; color: var(--ck-fg-3); }
    .more { margin-top: var(--ck-space-2); padding: var(--ck-space-1) var(--ck-space-3); border: 1px solid var(--ck-stroke-3); border-radius: var(--ck-radius-sm); background: transparent; color: inherit; }
    .more:disabled { opacity: .6; }
  `],
})
export class WorkRecordAttemptsComponent {
  readonly slug = input.required<string>();
  readonly bindingKey = input.required<string>();
  readonly recordRef = input.required<string>();
  readonly selectedRunId = input<string | null>(null);
  /** A Run of this record the page already shows (e.g. its Situation). */
  readonly currentRunId = input<string | null>(null);
  /** Bump when the caller knows a new attempt exists (e.g. after starting one). */
  readonly refreshKey = input<unknown>(null);
  readonly selectRun = output<string>();
  /** The newest attempt once the list is read (null when there is none). */
  readonly latestRun = output<string | null>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private static sequence = 0;
  readonly titleId = `work-record-attempts-${++WorkRecordAttemptsComponent.sequence}`;

  readonly state = signal<ListState>({ s: 'loading' });
  readonly reload = signal(0);
  readonly bump = (value: number) => value + 1;
  private namespace: string | null = null;
  private request = 0;

  readonly loaded = computed(() => {
    const state = this.state();
    return state.s === 'loaded' ? state : null;
  });
  readonly view = computed(() => {
    const list = this.loaded();
    return list ? attemptsView(list.attempts, list.hasMore, this.currentRunId()) : null;
  });

  constructor() {
    effect(() => {
      const view = this.view();
      if (view) this.latestRun.emit(view.lines[0]?.runId ?? null);
    });
    effect((onCleanup) => {
      this.reload();
      this.refreshKey();
      const slug = this.slug(), key = this.bindingKey(), ref = this.recordRef();
      const request = ++this.request;
      const scope = this.workspace.captureRequestScope();
      const current = () => request === this.request && this.workspace.isRequestScopeCurrent(scope);
      this.state.set({ s: 'loading' });
      const sub = this.api
        .get<BindingResolution>(`/work/${encodeURIComponent(slug)}/bindings/${encodeURIComponent(key)}/resolve`)
        .subscribe({
          next: (resolution) => {
            if (!current()) return;
            const namespace = resolution?.binding?.record_identity?.namespace ?? null;
            this.namespace = namespace;
            if (!namespace) { this.state.set({ s: 'not_configured' }); return; }
            this.fetch(slug, namespace, ref, 0, current);
          },
          error: () => { if (current()) this.state.set({ s: 'error' }); },
        });
      onCleanup(() => sub.unsubscribe());
    });
  }

  loadMore(): void {
    const state = this.state();
    if (state.s !== 'loaded' || !state.hasMore || state.loadingMore || !this.namespace || state.nextOffset === null) return;
    const request = this.request;
    const scope = this.workspace.captureRequestScope();
    this.state.set({ ...state, loadingMore: true, moreFailed: false });
    this.fetch(this.slug(), this.namespace, this.recordRef(), state.nextOffset,
      () => request === this.request && this.workspace.isRequestScopeCurrent(scope));
  }

  private fetch(slug: string, namespace: string, ref: string, offset: number, current: () => boolean): void {
    this.api
      .get<AttemptsPage>(`/work/${encodeURIComponent(slug)}/records/${encodeURIComponent(ref)}/runs`, { namespace, limit: String(PAGE), offset: String(offset) })
      .subscribe({
        next: (page) => {
          if (!current()) return;
          if (!page || !Array.isArray(page.attempts)) { this.failPage(offset); return; }
          const before = offset > 0 && this.state().s === 'loaded' ? (this.state() as Extract<ListState, { s: 'loaded' }>).attempts : [];
          this.state.set({
            s: 'loaded',
            attempts: [...before, ...page.attempts.filter((row) => !before.some((seen) => seen.attempt_id === row.attempt_id))],
            hasMore: !!page.has_more,
            nextOffset: page.next_offset ?? null,
            loadingMore: false,
            moreFailed: false,
          });
        },
        error: () => { if (current()) this.failPage(offset); },
      });
  }

  private failPage(offset: number): void {
    const state = this.state();
    if (offset > 0 && state.s === 'loaded') this.state.set({ ...state, loadingMore: false, moreFailed: true });
    else this.state.set({ s: 'error' });
  }

  when(attempt: WorkRecordAttempt): string {
    return formatRunInstant(attempt.started_at ?? attempt.recorded_at, this.i18n.locale())
      ?? this.i18n.t('experience.record_attempts.date_unknown');
  }

  stateLabel(attempt: WorkRecordAttempt): string {
    return runStatusLabel({ status: attempt.status, follow_up: attempt.follow_up }, this.i18n.t);
  }
}
