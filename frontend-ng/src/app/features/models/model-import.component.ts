import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, output, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { A11yModule } from '@angular/cdk/a11y';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { ModelImportService } from './model-import.service';
import {
  canSubmit, importPhase, lineageChoices, measurementLines, readerCodeKey, refusalKey, validationGaps,
  type ImportForm, type ImportJob, type ImportRefusal, type ImportTask,
} from './model-import.vm';
import type { ModelDto } from './models.vm';

const POLL_MS = 2000;
const POLL_LIMIT = 300;

@Component({
  selector: 'ck-model-import', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, NavLinkDirective],
  template: `
    <div class="fixed inset-0 z-50 flex items-start justify-center p-4 md:p-6 overflow-auto">
      <div class="absolute inset-0" style="background: var(--ck-scrim)" (click)="dismiss()"></div>
      <section class="relative ck-surface rounded-md w-full panel" role="dialog" aria-modal="true"
        aria-labelledby="model-import-title" cdkTrapFocus [cdkTrapFocusAutoCapture]="true" data-testid="model-import">
        <h3 id="model-import-title">{{ t('title') }}</h3>
        <p>{{ t('hint') }}</p>
        <p>{{ t('formats') }}</p>
        @if (phase() === 'idle' || phase() === 'refused' && !job()) {
          <form (submit)="$event.preventDefault(); submit()">
            <label>{{ t('archive') }}
              <input type="file" accept=".zip,application/zip" data-testid="import-archive" (change)="pick('archive', $event)" />
            </label>
            <label>{{ t('validation') }}
              <input type="file" accept=".json,application/json" data-testid="import-validation" (change)="pick('validation', $event)" />
            </label>
            <p class="small">{{ t('validation_hint') }}</p>
            <label>{{ t('task') }}
              <select [value]="form().task" (change)="update('task', $any($event.target).value)">
                <option value="classification">{{ i18n.t('models.import.task.classification') }}</option>
                <option value="regression">{{ i18n.t('models.import.task.regression') }}</option>
              </select>
            </label>
            <label>{{ t('lineage') }}
              <select [value]="form().lineageModelId ?? ''" (change)="update('lineageModelId', $any($event.target).value || null)">
                <option value="">{{ i18n.t('models.import.lineage.new') }}</option>
                @for (choice of lineages(); track choice.id) {
                  <option [value]="choice.id">{{ i18n.t('models.import.lineage.version', { name: choice.name, version: choice.version + 1 }) }}</option>
                }
              </select>
            </label>
            @if (!form().lineageModelId) {
              <label>{{ t('name') }}<input type="text" maxlength="200" [value]="form().name" (input)="update('name', $any($event.target).value)" /></label>
            }
            <label>{{ t('target') }}<input type="text" maxlength="200" [value]="form().target" (input)="update('target', $any($event.target).value)" /></label>
            <div class="actions">
              <button type="button" (click)="dismiss()">{{ t('cancel') }}</button>
              <button type="submit" data-testid="import-submit" [disabled]="!ready()">{{ t('submit') }}</button>
            </div>
          </form>
        }
        @if (phase() === 'pending') { <p role="status" data-testid="import-pending">{{ t('pending') }}</p> }
        @if (phase() === 'accepted') {
          <div role="status" data-testid="import-accepted">
            <p class="verdict">{{ t('accepted') }}</p>
            @for (line of gaps(); track line.key) { <p class="ck-mono">{{ i18n.t(line.key, line.params) }}</p> }
            @for (line of measures(); track line.key) { <p class="ck-mono">{{ i18n.t(line.key, line.params) }}</p> }
            @if (job()?.result?.model_id; as id) {
              <a [navLink]="{ leaf: 'model-doc', ref: id }" (click)="done(id)">{{ t('open') }}</a>
            }
          </div>
        }
        @if (phase() === 'refused') {
          <div role="alert" data-testid="import-refused">
            <p class="verdict">{{ t('refused') }}</p>
            <p>{{ i18n.t(reasonKey()) }}</p>
            @if (readerKey(); as reader) { <p>{{ i18n.t(reader) }}</p> }
            @if (types().length) { <p class="ck-mono">{{ types().join(', ') }}</p> }
            @for (line of gaps(); track line.key) { <p class="ck-mono">{{ i18n.t(line.key, line.params) }}</p> }
            @for (line of measures(); track line.key) {
              <p class="ck-mono" [class.over]="line.over">{{ i18n.t(line.key, line.params) }}</p>
            }
            <button type="button" (click)="retry()">{{ t('retry') }}</button>
          </div>
        }
      </section>
    </div>
  `,
  styles: [`
    .panel{max-width:640px;padding:20px;border:1px solid var(--ck-stroke-strong);font-size:12px}
    h3{margin:0 0 8px;font-size:14px} p{color:var(--ck-fg-3);line-height:1.5;margin:4px 0} .small{font-size:11px}
    form{display:grid;gap:10px;margin-top:12px} label{display:grid;gap:4px;color:var(--ck-fg-2)}
    input[type=text],select{padding:8px;background:var(--ck-bg-2);border:1px solid var(--ck-stroke-2);border-radius:4px;color:var(--ck-fg-1)}
    .actions{display:flex;gap:8px;justify-content:flex-end}
    button{padding:8px 12px;background:var(--ck-bg-2);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:4px;cursor:pointer}
    button:disabled{opacity:.5;cursor:default}
    .verdict{color:var(--ck-fg-1);font-weight:500} [role=alert] .verdict{color:var(--ck-signal-neg)} .over{color:var(--ck-signal-neg)}
  `],
})
export class ModelImportComponent {
  readonly models = input<ModelDto[]>([]);
  /** `permissions.import` from the models list (M1); never inferred from a role. */
  readonly canImport = input(false);
  readonly closed = output<void>();
  readonly imported = output<string>();
  protected readonly i18n = inject(I18nService);
  private readonly api = inject(ModelImportService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  readonly form = signal<ImportForm>({ archive: null, validation: null, task: 'classification', name: '', target: '', lineageModelId: null });
  readonly busy = signal(false);
  readonly job = signal<ImportJob | null>(null);
  readonly refusal = signal<ImportRefusal | null>(null);
  readonly phase = computed(() => this.refusal() ? 'refused' : importPhase(this.job()));
  readonly ready = computed(() => canSubmit(this.form(), this.canImport(), this.busy()));
  readonly lineages = computed(() => lineageChoices(this.models(), this.form().task));
  protected readonly reasonKey = computed(() => refusalKey(this.refusal() ?? this.job()?.result, this.job()?.error));
  protected readonly readerKey = computed(() => readerCodeKey(this.job()?.result));
  protected readonly types = computed(() => (this.refusal()?.types ?? []).slice(0, 8));
  protected readonly gaps = computed(() => validationGaps(this.job()?.result?.metrics));
  protected readonly measures = computed(() => measurementLines(this.job()?.result?.measurements, this.job()?.result?.budgets));
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private polls = 0;

  constructor() {
    const unregister = this.workspace.registerContextReset(() => this.dismiss());
    this.destroyRef.onDestroy(() => { this.stop(); unregister(); });
  }

  protected t(key: string): string { return this.i18n.t('models.import.' + key); }

  update<K extends keyof ImportForm>(key: K, value: ImportForm[K]): void {
    this.form.update(form => {
      const next = { ...form, [key]: value };
      if (key === 'task') next.lineageModelId = null;
      return next;
    });
  }

  pick(key: 'archive' | 'validation', event: Event): void {
    const file = (event.target as HTMLInputElement | null)?.files?.[0] ?? null;
    this.update(key, file);
  }

  async submit(): Promise<void> {
    if (!this.ready()) return;
    const generation = ++this.generation;
    this.busy.set(true); this.refusal.set(null); this.job.set(null);
    try {
      const reply = await this.api.submit({ ...this.form(), task: this.form().task as ImportTask });
      if (!reply || generation !== this.generation) return;
      this.polls = 0;
      this.job.set(reply.job);
      this.schedule(generation);
    } catch (failure) {
      if (generation !== this.generation) return;
      const detail = failure instanceof HttpErrorResponse ? failure.error?.detail : null;
      this.refusal.set(detail && typeof detail.code === 'string' ? detail : { code: 'generic' });
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }

  /** Re-read while the isolated validation runs; bounded and cancelled on close. */
  private schedule(generation: number): void {
    this.stop();
    const job = this.job();
    if (!job || importPhase(job) !== 'pending' || this.polls >= POLL_LIMIT) {
      if (job && importPhase(job) === 'accepted' && job.result.model_id) this.imported.emit(job.result.model_id);
      return;
    }
    this.polls++;
    this.timer = setTimeout(() => void this.poll(generation, job.id), POLL_MS);
  }

  private async poll(generation: number, jobId: string): Promise<void> {
    try {
      const reply = await this.api.status(jobId);
      if (!reply || generation !== this.generation) return;
      this.job.set(reply.job);
      this.schedule(generation);
    } catch {
      if (generation === this.generation) this.refusal.set({ code: 'generic' });
    }
  }

  private stop(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  retry(): void { this.generation++; this.stop(); this.job.set(null); this.refusal.set(null); this.busy.set(false); }

  /** The list already reloaded when the verdict arrived; following the link closes. */
  done(_modelId: string): void { this.dismiss(); }

  dismiss(): void { this.generation++; this.stop(); this.closed.emit(); }
}
