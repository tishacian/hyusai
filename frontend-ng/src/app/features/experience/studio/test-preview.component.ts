import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { Observable, forkJoin, map } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import type { Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { ExperiencePage } from '../runtime/model';
import type { StudioBinding } from './studio-api.service';
import {
  boundOutputs,
  checkOutput,
  previewValue,
  previewShape,
  runStanding,
  runVersionMatches,
} from './test-preview.model';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Preview the selected page on one identified test result (plan lot 4,
 * US34). The author picks a Run of the bound System; the panel names it,
 * says whether it is accepted, and checks every bound output against it. A
 * missing output is an incompatibility that leads to the component setting,
 * never a stand-in value.
 */
@Component({
  selector: 'app-studio-test-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  template: `
    <section class="tp" aria-labelledby="tp-title" data-testid="test-preview">
      <h3 id="tp-title">{{ i18n.t('experience.editor.test_preview.title') }}</h3>
      @if (outputs().length === 0) {
        <p class="muted" data-testid="test-preview-none">{{ i18n.t('experience.editor.test_preview.no_output') }}</p>
      } @else {
        @switch (runsState()) {
          @case ('loading') { <p class="muted" role="status">{{ i18n.t('experience.editor.test_preview.loading') }}</p> }
          @case ('error') {
            <div class="notice is-neg" role="alert" data-testid="test-preview-runs-error">
              <p>{{ i18n.t('experience.editor.test_preview.runs_error') }}</p>
              <button type="button" class="ck-btn ck-btn-quiet ck-btn--sm" (click)="loadRuns()">{{ i18n.t('common.retry') }}</button>
            </div>
          }
          @case ('ready') {
            @if (runs().length === 0) {
              <p class="muted" data-testid="test-preview-no-run">{{ i18n.t('experience.editor.test_preview.no_run') }}</p>
            } @else {
              <label class="field">
                <span>{{ i18n.t('experience.editor.test_preview.pick') }}</span>
                <select [value]="selectedRunId() ?? ''" (change)="pick(value($event))" data-testid="test-preview-run">
                  <option value="">{{ i18n.t('experience.editor.test_preview.none') }}</option>
                  @for (run of runs(); track run.id) {
                    <option [value]="run.id">{{ runLabel(run) }}</option>
                  }
                </select>
              </label>
            }
          }
        }

        @switch (runState()) {
          @case ('loading') { <p class="muted" role="status">{{ i18n.t('experience.editor.test_preview.reading') }}</p> }
          @case ('error') {
            <p class="notice is-neg" role="alert" data-testid="test-preview-run-error">{{ i18n.t('experience.editor.test_preview.run_error') }}</p>
          }
          @case ('ready') {
            @if (run(); as r) {
              <dl class="origin" data-testid="test-preview-origin">
                <dt>{{ i18n.t('experience.editor.test_preview.automation') }}</dt>
                <dd>{{ systemNames()[r.system_id] || i18n.t('experience.editor.test_preview.unnamed_system') }}</dd>
                <dt>{{ i18n.t('experience.editor.test_preview.date') }}</dt>
                <dd>{{ displayDate(r.started_at) }}</dd>
                <dt>{{ i18n.t('experience.editor.test_preview.surface') }}</dt>
                <dd>{{ i18n.t(r.execution_surface === 'draft_test' ? 'experience.editor.test_preview.surface.draft' : 'experience.editor.test_preview.surface.published') }}</dd>
                <dt>{{ i18n.t('experience.editor.test_preview.state') }}</dt>
                <dd [attr.data-standing]="standing()" data-testid="test-preview-standing">{{ i18n.t('experience.editor.test_preview.standing.' + standing()) }}</dd>
              </dl>
              @if (standing() === 'review') {
                <p class="notice is-warn" role="status" data-testid="test-preview-review">{{ i18n.t('experience.editor.test_preview.review') }}</p>
              }
              @if (versionMatches() === false) {
                <p class="notice is-warn" role="status" data-testid="test-preview-version">{{ i18n.t('experience.editor.test_preview.other_version') }}</p>
              }
              <p class="muted" data-testid="test-preview-coverage">{{ i18n.t('experience.editor.test_preview.coverage', { present: presentCount(), total: checks().length }) }}</p>
              <ul class="checks">
                @for (row of checks(); track row.output.componentId) {
                  <li [attr.data-state]="row.state" [attr.data-testid]="'test-preview-check-' + row.output.componentId">
                    <strong>{{ row.output.label || typeLabel(row.output.type) }}</strong>
                    @if (row.state === 'present') {
                      <span class="value">{{ row.shape === 'scalar' ? row.text : i18n.t('experience.editor.test_preview.' + row.shape, { count: row.count }) }}</span>
                    } @else {
                      <span class="miss">{{ i18n.t('experience.editor.test_preview.missing') }}</span>
                      <button type="button" class="ck-btn ck-btn-quiet ck-btn--sm" (click)="openSetting.emit(row.output.componentId)">
                        {{ i18n.t('experience.editor.test_preview.fix') }}
                      </button>
                    }
                    <details class="output-details">
                      <summary>{{ i18n.t('experience.editor.test_preview.details') }}</summary>
                      <p><code>{{ row.output.componentId }}</code> · <code>{{ row.output.selector || i18n.t('experience.editor.data.whole_result') }}</code></p>
                      @if (row.state === 'present' && row.shape !== 'scalar') { <pre>{{ row.structured }}</pre> }
                    </details>
                  </li>
                }
              </ul>
              <details class="run-details" data-testid="test-preview-reference">
                <summary>{{ i18n.t('experience.editor.test_preview.reference') }}</summary>
                <p>{{ i18n.t('experience.editor.test_preview.run') }} · <code>{{ r.id }}</code></p>
              </details>
            }
          }
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .tp { display: grid; gap: var(--ck-space-2); padding: var(--ck-space-3); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-panel); }
    h3 { margin: 0; font-size: 14px; font-weight: 600; color: var(--ck-fg-1); }
    .muted { margin: 0; font-size: 13px; color: var(--ck-fg-3); }
    .field { display: grid; gap: var(--ck-space-1); font-size: 12px; color: var(--ck-fg-2); }
    .field select { min-height: 32px; padding: 4px 8px; border: 1px solid var(--ck-stroke-3); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); color: var(--ck-fg-1); }
    .origin { display: grid; grid-template-columns: max-content 1fr; gap: var(--ck-space-1) var(--ck-space-3); margin: 0; font-size: 13px; }
    .origin dt { color: var(--ck-fg-3); }
    .origin dd { margin: 0; color: var(--ck-fg-1); min-width: 0; overflow-wrap: anywhere; }
    code { font-family: var(--ck-font-mono); font-size: 12px; }
    .notice { margin: 0; padding: var(--ck-space-2) var(--ck-space-3); border-radius: var(--ck-radius-md); font-size: 13px; display: flex; flex-wrap: wrap; gap: var(--ck-space-2); align-items: center; }
    .notice p { margin: 0; flex: 1 1 200px; }
    .is-neg { color: var(--ck-status-neg-fg); background: var(--ck-status-neg-bg); border: 1px solid var(--ck-status-neg-line); }
    .is-warn { color: var(--ck-status-warn-fg); background: var(--ck-status-warn-bg); border: 1px solid var(--ck-status-warn-line); }
    .checks { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--ck-space-2); }
    .checks li { display: grid; grid-template-columns: minmax(8rem, 1fr) minmax(0, 2fr) auto; gap: var(--ck-space-2); align-items: start; padding: var(--ck-space-2) 0; border-top: 1px solid var(--ck-stroke-2); font-size: 13px; color: var(--ck-fg-2); }
    .output-details { grid-column: 1 / -1; }
    summary { color: var(--ck-fg-3); font-size: 12px; cursor: pointer; min-height: 32px; padding-block: 6px; }
    summary:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    details p { margin: var(--ck-space-1) 0; overflow-wrap: anywhere; }
    pre { max-height: 15rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
    @media (max-width: 600px) { .checks li { grid-template-columns: 1fr; } .origin { grid-template-columns: 1fr; } }
    .checks strong { color: var(--ck-fg-1); }
    .value { color: var(--ck-fg-1); overflow-wrap: anywhere; }
    .miss { color: var(--ck-status-warn-fg); font-weight: 600; }
  `],
})
export class StudioTestPreviewComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  readonly page = input<ExperiencePage | null>(null);
  readonly bindings = input<StudioBinding[]>([]);
  readonly systemNames = input<Record<string, string>>({});
  /** Asks the editor to open the setting of this component. */
  readonly openSetting = output<string>();

  readonly outputs = computed(() => boundOutputs(this.page()));
  private readonly systemIds = computed(() => {
    const keys = new Set(this.outputs().map((row) => row.bindingKey));
    return [...new Set(this.bindings().filter((row) => keys.has(row.binding_key)).map((row) => row.system_id))].sort();
  });

  readonly runsState = signal<LoadState>('idle');
  readonly runs = signal<Run[]>([]);
  readonly selectedRunId = signal<string | null>(null);
  readonly runState = signal<LoadState>('idle');
  readonly run = signal<Run | null>(null);

  readonly standing = computed(() => {
    const r = this.run();
    return r ? runStanding(r) : 'failed';
  });

  readonly versionMatches = computed(() => {
    const r = this.run();
    if (!r) return null;
    const binding = this.bindings().find((row) => row.system_id === r.system_id);
    return binding ? runVersionMatches(r, binding.published_flow_version_id) : null;
  });

  readonly checks = computed(() => {
    const r = this.run();
    if (!r) return [];
    const keys = new Set(this.bindings().filter((row) => row.system_id === r.system_id).map((row) => row.binding_key));
    return this.outputs()
      .filter((row) => keys.has(row.bindingKey))
      .map((row) => {
        const check = checkOutput(row, r);
        return { output: row, state: check.state, text: previewValue(check.value), shape: previewShape(check.value),
          count: Array.isArray(check.value) ? check.value.length : 0,
          structured: check.value == null ? '' : JSON.stringify(check.value, null, 2) };

      });
  });

  readonly presentCount = computed(() => this.checks().filter(row => row.state === 'present').length);

  typeLabel(type: string): string {
    const key = 'experience.editor.type.' + type;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('experience.editor.test_preview.component') : label;
  }

  private loadedFor = '';

  constructor() {
    effect(() => {
      const ids = this.systemIds().join(',');
      untracked(() => {
        if (ids === this.loadedFor) return;
        this.loadedFor = ids;
        this.selectedRunId.set(null);
        this.run.set(null);
        this.runState.set('idle');
        if (ids) this.loadRuns();
        else this.runsState.set('idle');
      });
    });
  }

  value(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  displayDate(value: string | null | undefined): string {
    const date = value ? new Date(value) : null;
    return date && Number.isFinite(date.getTime())
      ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'short', timeStyle: 'short' }).format(date)
      : this.i18n.t('experience.editor.test_preview.date_unknown');
  }

  runLabel(run: Run): string {
    const system = this.systemNames()[run.system_id] ?? this.i18n.t('experience.editor.test_preview.unnamed_system');
    const standing = this.i18n.t(`experience.editor.test_preview.standing.${runStanding(run)}`);
    const date = run.started_at ? new Date(run.started_at) : null;
    const when = date && Number.isFinite(date.getTime())
      ? new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'short', timeStyle: 'short' }).format(date)
      : this.i18n.t('experience.editor.test_preview.date_unknown');
    return `${system} · ${when} · ${standing}`;
  }

  loadRuns(): void {
    const ids = this.systemIds();
    const scope = this.workspace.captureRequestScope();
    this.runsState.set('loading');
    const requests: Observable<Run[]>[] = ids.map((id) =>
      this.api.get<Run[] | { runs: Run[] }>('/runs', { system_id: id }).pipe(
        map((body) => (Array.isArray(body) ? body : body.runs ?? [])),
      ));
    forkJoin(requests).subscribe({
      next: (lists) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        const rows = lists.flat();
        rows.sort((a, b) => String(b.started_at ?? '').localeCompare(String(a.started_at ?? '')));
        this.runs.set(rows.slice(0, 20));
        this.runsState.set('ready');
      },
      error: () => {
        if (this.workspace.isRequestScopeCurrent(scope)) this.runsState.set('error');
      },
    });
  }

  pick(id: string): void {
    this.selectedRunId.set(id || null);
    this.run.set(null);
    if (!id) {
      this.runState.set('idle');
      return;
    }
    const scope = this.workspace.captureRequestScope();
    this.runState.set('loading');
    this.api.get<Run & { invocations?: Run['skill_invocations'] }>(`/runs/${encodeURIComponent(id)}`).subscribe({
      next: (row) => {
        if (!this.workspace.isRequestScopeCurrent(scope) || this.selectedRunId() !== id) return;
        this.run.set({ ...row, skill_invocations: row.skill_invocations ?? row.invocations ?? [] });
        this.runState.set('ready');
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope) || this.selectedRunId() !== id) return;
        this.runState.set('error');
      },
    });
  }
}
