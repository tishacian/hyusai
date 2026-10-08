import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, output, signal, untracked } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { FlowTerminalComponent } from '@app/features/orchestration/flow/flow-terminal.component';
import { workDecisionAvailable, workDecisionKey } from '@app/features/experience/work/work-decision';
import { RetrainingContextComponent } from './retraining-context.component';
import { retrainingReviewReady } from './retraining-evidence.vm';

/** Scheduled runs attach to the same HITL endpoint used by the Flow terminal. */
@Component({
  selector: 'ck-retraining-run-approval', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FlowTerminalComponent, RetrainingContextComponent],
  template: `
    @if (run().status === 'hitl_pending' && run().hitl?.prompt_kind === 'approve_model_retraining') {
      <section data-testid="run-retraining-approval">
        @if (settled()) {
          <p role="status">{{ i18n.t('models.retraining.decision_saved') }}</p>
        } @else if (run().hitl?.can_decide === true) {
          <app-flow-terminal [runId]="run().id" [status]="'paused'" [hitl]="run().hitl ?? null"
            [hitlResolving]="busy() || !available()" (resolveHitl)="resolve($event.action)" />
        } @else {
          <ck-retraining-context [binding]="run().hitl?.model_retraining" />
          <p>{{ i18n.t('models.retraining.approval_read_only') }}</p>
        }
        @if (error() || (!settled() && run().hitl?.can_decide === true && !available())) {
          <p role="alert">{{ i18n.t('models.retraining.approval_unavailable') }}</p>
          <button type="button" [disabled]="busy()" (click)="refresh.emit()">{{ i18n.t('common.refresh') }}</button>
        }
      </section>
    }
  `,
  styles: [`section{margin:16px 0}p{font-size:12px;color:var(--ck-fg-3)}[role=alert]{color:var(--ck-signal-neg)}button{padding:6px;color:var(--ck-fg-1);background:var(--ck-bg-panel-hi);border:1px solid var(--ck-stroke-2);border-radius:4px}`],
})
export class RetrainingRunApprovalComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroy = inject(DestroyRef);
  readonly run = input.required<Run>();
  readonly changed = output<void>();
  readonly refresh = output<void>();
  readonly busy = signal(false);
  readonly settled = signal(false);
  readonly error = signal(false);
  private generation = 0;
  private identity = '';
  constructor() {
    effect(() => {
      const identity = JSON.stringify([workDecisionKey(this.run()), this.workspace.current()?.id, this.run().hitl?.can_decide]);
      if (identity === this.identity) return;
      this.identity = identity;
      untracked(() => {
        this.generation++; this.busy.set(false); this.error.set(false); this.settled.set(false);
      });
    });
    this.destroy.onDestroy(() => { this.generation++; });
  }
  available(): boolean { return !this.settled() && this.run().hitl?.can_decide === true && workDecisionAvailable(this.run()); }
  async resolve(action: 'accept' | 'reject'): Promise<void> {
    const run = this.run();
    if (this.busy() || !this.available() || run.hitl?.prompt_kind !== 'approve_model_retraining') return;
    if (action === 'accept' && !retrainingReviewReady(run.hitl.model_retraining)) return;
    const key = workDecisionKey(run), generation = ++this.generation, scope = this.workspace.captureRequestScope();
    const current = () => generation === this.generation && key === workDecisionKey(this.run()) && this.workspace.isRequestScopeCurrent(scope);
    this.busy.set(true); this.error.set(false);
    try {
      const updated = await firstValueFrom(this.api.resolveRunHitl(run.id, { action, expected_decision_id: run.hitl.decision_id }));
      if (!current()) return;
      if (updated?.id === run.id) { this.settled.set(true); this.changed.emit(); }
      else this.error.set(true);
    } catch { if (current()) this.error.set(true); }
    finally { if (current()) this.busy.set(false); }
  }
}
