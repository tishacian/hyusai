import { ChangeDetectionStrategy, Component, OnDestroy, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription, exhaustMap, forkJoin, take, takeWhile, timer } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import type { I18nKey } from '@app/core/i18n.dict';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { catalogModelName, selectableTextModel, type ModelCatalogEntry } from '@app/core/model-catalog';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ModelExecutionComponent } from '@app/shared/cockpit/model-execution.component';
import { STRICT } from '@app/shared/ui/load-state';
import { formatSkillCost } from '../skills/skill-cost';
import { comparisonDecision } from './decision-comparison.vm';

interface DecisionSample {
  invocation_id: string; run_id: string; system_id: string; system_name: string;
  started_at: string | null; objective: string; observations_count: number;
  input_sha256: string; instruction_sha256: string;
  model: { provider?: string; model?: string };
}
interface DecisionSamples { can_compare: boolean; blockers?: Array<{ message: string }>; samples: DecisionSample[] }

@Component({
  selector: 'app-decision-comparison', standalone: true,
  imports: [FormsModule, NavLinkDirective, ModelExecutionComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="comparison ck-surface" aria-labelledby="decision-comparison-title">
      <header>
        <div><h3 id="decision-comparison-title">{{ i18n.t('resources.compare.title') }}</h3>
          <p>{{ i18n.t('resources.compare.description') }}</p></div>
        <button type="button" class="ck-btn-quiet" (click)="load()" [disabled]="busy() || loading()">{{ i18n.t('resources.compare.open') }}</button>
      </header>
      @if (loading()) { <p role="status">{{ i18n.t('resources.test.loading_targets') }}</p> }
      @for (blocker of blockers(); track blocker) { <p>{{ blocker }}</p> }
      @if (loaded() && !loading() && !samples().length && !blockers().length && !error()) { <p>{{ i18n.t('resources.compare.empty') }}</p> }
      @if (samples().length) {
        <label class="source">{{ i18n.t('resources.compare.source') }}
          <select [ngModel]="selectedId()" (ngModelChange)="selectSample($event)" [disabled]="busy()">
            <option value="">{{ i18n.t('resources.compare.open') }}</option>
            @for (sample of samples(); track sample.invocation_id) {
              <option [value]="sample.invocation_id">{{ sample.system_name }} · {{ date(sample.started_at) }} · {{ sample.observations_count }}</option>
            }
          </select>
        </label>
      }
      @if (selected(); as sample) {
        <div class="context"><p class="objective">{{ sample.objective }}</p>
          <p>{{ i18n.t('resources.compare.context', {count: sample.observations_count}) }}</p>
          <a [navLink]="{type: 'run', ref: sample.run_id}">{{ i18n.t('resources.test.open_run') }}</a>
        </div>
        <div class="candidates">
          @for (index of [0, 1]; track index) {
            <label>{{ i18n.t('resources.compare.candidate', {number: index + 1}) }}
              <select [ngModel]="candidateKeys[index]" (ngModelChange)="setCandidate(index, $event)" [disabled]="busy()">
                <option value="">{{ i18n.t('resources.models.choose_model') }}</option>
                @for (model of selectableModels(); track key(model)) {
                  <option [value]="key(model)">{{ model.provider }} · {{ modelName(model) }}</option>
                }
              </select>
            </label>
          }
        </div>
        <label class="ack"><input type="checkbox" [(ngModel)]="acknowledged" [disabled]="busy()" />{{ i18n.t('resources.compare.ack') }}</label>
        <div class="actions"><button type="button" class="ck-btn-quiet" (click)="start()" [disabled]="!canStart()">{{ i18n.t(busy() ? 'resources.test.running' : 'resources.compare.start') }}</button>
          @if (runs().length) { <button type="button" class="ck-btn-quiet" [disabled]="busy()" (click)="poll()">{{ i18n.t('resources.compare.refresh') }}</button> }
        </div>
      }
      @if (error()) { <p role="alert" class="error">{{ error() }}</p> }
      @if (runs().length) {
        <p>{{ i18n.t('resources.compare.same_input') }}</p>
        <div class="results">
          @for (run of runs(); track run.id; let index = $index) {
            @let result = decision(run);
            <article><header><h4>{{ i18n.t('resources.compare.candidate', {number: index + 1}) }}</h4>
              <span>{{ status(run) }}</span></header>
              @if (result.available) {
                <p class="decision">{{ result.nextSkill || i18n.t('experience.agent_choices.state.' + result.state) }}</p>
                <p class="caption">{{ i18n.t('resources.compare.choice') }}</p>
                @if (result.rationale) { <p class="rationale">{{ result.rationale }}</p> }
                <p class="caption">{{ i18n.t(result.normalized ? 'experience.agent_choices.normalized' : 'resources.compare.contract') }}</p>
              } @else { <p>{{ i18n.t('resources.compare.unavailable') }}</p> }
              @if (run.error) { <p class="error">{{ run.error }}</p> }
              <app-model-execution [resolution]="result.resolution" />
              <dl><div><dt>{{ i18n.t('resources.test.duration') }}</dt><dd>{{ result.duration === null ? '—' : result.duration + ' ms' }}</dd></div>
                <div><dt>{{ i18n.t('resources.test.cost') }}</dt><dd>{{ cost(run) }}</dd></div>
                <div><dt>{{ i18n.t('resources.test.tokens') }}</dt><dd>{{ result.tokens ?? '—' }}</dd></div></dl>
              <a [navLink]="{type: 'run', ref: run.id}">{{ i18n.t('resources.test.open_run') }}</a>
            </article>
          }
        </div>
        <p class="quality">{{ i18n.t('resources.compare.quality') }}</p>
        <details><summary>{{ i18n.t('resources.compare.provenance') }}</summary>
          <p>{{ submittedSource()?.system_name }}</p><code>{{ submittedSource()?.input_sha256 }}</code>
        </details>
      }
    </section>
  `,
  styles: [`
    :host{display:block;margin-top:1.25rem}.comparison{padding:1.25rem;border:1px solid var(--ck-stroke-soft);border-radius:.5rem;color:var(--ck-fg-1)}
    header,.actions{display:flex;align-items:start;justify-content:space-between;gap:1rem;flex-wrap:wrap}h3,h4{font-size:.9375rem;font-weight:600;margin:0}p{font-size:.8125rem;color:var(--ck-fg-3);margin:.5rem 0;line-height:1.55}
    button{font-size:.8125rem;padding:.45rem .75rem;white-space:nowrap}button:disabled{opacity:.5}label{display:block;font-size:.8125rem}select{display:block;width:100%;margin-top:.4rem;padding:.55rem .7rem;background:var(--ck-bg-inset);border:1px solid var(--ck-stroke-soft);border-radius:.375rem;color:var(--ck-fg-1)}
    .source{margin-top:1rem}.context{padding:.75rem 0}.objective{color:var(--ck-fg-2)}.candidates,.results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.ack{display:flex;gap:.5rem;align-items:start;margin:1rem 0;color:var(--ck-fg-2)}.ack input{margin-top:.2rem}.actions{justify-content:start;margin:.5rem 0 1rem}
    article{min-width:0;padding:1rem;border:1px solid var(--ck-stroke-soft);border-radius:.375rem;background:var(--ck-bg-inset)}article header span,.caption,dt{font-size:.75rem;color:var(--ck-fg-3)}.decision{font-size:1rem;color:var(--ck-fg-1);font-weight:600;margin-top:1rem}.rationale{color:var(--ck-fg-2);white-space:pre-wrap;overflow-wrap:anywhere}.caption{margin:.35rem 0 .8rem}dl{display:flex;gap:1.25rem;flex-wrap:wrap;margin:1rem 0}dd{margin:.25rem 0 0;font-size:.8125rem}a{font-size:.8125rem;color:var(--ck-signal-cool)}.error{color:var(--ck-neg)}.quality{padding-top:.5rem}details{font-size:.75rem;color:var(--ck-fg-3)}code{display:block;overflow-wrap:anywhere;margin-top:.5rem}@media(max-width:700px){.candidates,.results{grid-template-columns:1fr}}
  `],
})
export class DecisionComparisonComponent implements OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly models = input<ModelCatalogEntry[]>([]);
  readonly selectableModels = computed(() => this.models().filter(selectableTextModel));
  readonly samples = signal<DecisionSample[]>([]);
  readonly selectedId = signal('');
  readonly selected = computed(() => this.samples().find((sample) => sample.invocation_id === this.selectedId()) ?? null);
  readonly submittedSource = signal<DecisionSample | null>(null);
  readonly runs = signal<Run[]>([]);
  readonly busy = signal(false);
  readonly loading = signal(false);
  readonly loaded = signal(false);
  readonly allowed = signal(false);
  readonly blockers = signal<string[]>([]);
  readonly error = signal<string | null>(null);
  candidateKeys = ['', ''];
  acknowledged = false;
  private requestKey: string | null = null;
  private subscription = new Subscription();
  private readonly view = new WorkspaceViewContext(this.workspace, () => this.reset(), () => {});
  readonly modelName = catalogModelName;
  readonly decision = comparisonDecision;
  date(value: string | null): string {
    const date = value ? new Date(value) : null;
    return date && Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(this.i18n.locale(), {dateStyle: 'short', timeStyle: 'short'}).format(date) : '—';
  }
  status(run: Run): string { return this.i18n.t(`runs.status.${run.status}` as I18nKey); }
  key(model: ModelCatalogEntry): string { return `${model.provider}:${catalogModelName(model)}`; }
  cost(run: Run): string {
    const cost = comparisonDecision(run).cost;
    return cost ? formatSkillCost(cost.amount, cost.currency, this.i18n.locale()) : this.i18n.t('resources.cost.unavailable');
  }
  load(): void {
    const request = this.view.beginRequest();
    this.subscription.unsubscribe(); this.subscription = new Subscription();
    this.loading.set(true); this.error.set(null);
    this.subscription.add(this.api.get<DecisionSamples>('/models/decision-samples').subscribe({
      next: (data) => {
        if (!this.view.isCurrent(request)) return;
        this.samples.set(data.samples); this.allowed.set(data.can_compare); this.blockers.set((data.blockers ?? []).map((item) => item.message));
        this.loaded.set(true); this.loading.set(false);
      }, error: () => { if (this.view.isCurrent(request)) { this.loading.set(false); this.error.set(this.i18n.t('resources.compare.load_error')); } },
    }));
  }
  selectSample(id: string): void {
    this.selectedId.set(id); this.clearResults();
    const sample = this.selected();
    const model = this.selectableModels().find((item) => item.provider === sample?.model.provider && catalogModelName(item) === sample?.model.model);
    this.candidateKeys = [model ? this.key(model) : '', ''];
  }
  setCandidate(index: number, value: string): void { this.candidateKeys[index] = value; this.clearResults(); }
  canStart(): boolean {
    return this.allowed() && !!this.selected() && !this.busy() && this.acknowledged && this.candidateKeys[0] !== this.candidateKeys[1]
      && this.candidateKeys.every((key) => this.selectableModels().some((item) => this.key(item) === key));
  }
  start(): void {
    const sample = this.selected();
    if (!sample || !this.canStart()) return;
    const candidates = this.candidateKeys.map((key) => this.selectableModels().find((item) => this.key(item) === key)!);
    this.requestKey ??= crypto.randomUUID();
    const request = this.view.beginRequest();
    this.busy.set(true); this.error.set(null); this.submittedSource.set(sample);
    this.subscription.add(this.api.post<{ runs: Run[] }>('/models/decision-comparisons', {
      invocation_id: sample.invocation_id, expected_input_sha256: sample.input_sha256, request_key: this.requestKey,
      candidates: candidates.map((item) => ({ provider: item.provider, model: catalogModelName(item) })), acknowledge_generation_cost: true,
    }).subscribe({
      next: (data) => { if (this.view.isCurrent(request)) { this.runs.set(data.runs); this.poll(); } },
      error: () => { if (this.view.isCurrent(request)) { this.busy.set(false); this.error.set(this.i18n.t('resources.compare.failed')); } },
    }));
  }
  poll(): void {
    const original = this.runs();
    if (!original.length) return;
    const request = this.view.beginRequest();
    this.busy.set(true); this.error.set(null);
    this.subscription.add(timer(0, 1500).pipe(take(80),
      exhaustMap(() => forkJoin(original.map((run) => this.canonical.getRun(run.id, STRICT)))),
      takeWhile((runs) => runs.some((run) => run && ['pending', 'running'].includes(run.status)), true),
    ).subscribe({
      next: (runs) => {
        if (!this.view.isCurrent(request)) return;
        this.runs.set(runs.map((run, index) => run ? { ...original[index], ...run } : original[index]));
      },
      error: () => { if (this.view.isCurrent(request)) { this.busy.set(false); this.error.set(this.i18n.t('resources.compare.poll_error')); } },
      complete: () => { if (this.view.isCurrent(request)) this.busy.set(false); },
    }));
  }
  private clearResults(): void {
    this.view.invalidate(); this.subscription.unsubscribe(); this.subscription = new Subscription();
    this.requestKey = null; this.runs.set([]); this.submittedSource.set(null); this.error.set(null); this.acknowledged = false;
  }
  private reset(): void {
    this.clearResults(); this.samples.set([]); this.selectedId.set(''); this.candidateKeys = ['', ''];
    this.allowed.set(false); this.busy.set(false); this.loading.set(false); this.loaded.set(false); this.blockers.set([]);
  }
  ngOnDestroy(): void { this.view.destroy(); }
}
