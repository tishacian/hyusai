import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { interval, startWith, switchMap, takeWhile } from 'rxjs';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { summarizeAutomationRun, type AutomationRunSummary } from './automation-turn';

interface AutomationTurnResponse {
  intent: string;
  verified: boolean;
  read: { nodes: Array<{ id: string; type: string }> };
  run: { id: string; status: string } | null;
}

@Component({
  selector: 'app-automation-turn',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './automation-turn.component.scss',
  template: `
    <form class="automation-turn" (submit)="send($event)">
      <label for="automation-turn-message">{{ i18n.t('flow.automation.turn.title') }}</label>
      <p>{{ i18n.t('flow.automation.turn.hint') }}</p>
      <textarea
        id="automation-turn-message"
        [value]="message()"
        rows="3"
        [disabled]="busy()"
        (input)="onMessage($event)"
      ></textarea>
      <button type="submit" [disabled]="busy() || !message().trim()">
        {{ busy() ? i18n.t('flow.automation.turn.sending') : i18n.t('flow.automation.turn.send') }}
      </button>
      @if (readBlocks()) {
        <p role="status">{{ i18n.t('flow.automation.turn.read', { blocks: readBlocks() }) }}</p>
      }
      @if (verified()) {
        <p role="status">{{ i18n.t('flow.automation.turn.verified') }}</p>
      }
      @if (summaryText()) {
        <p role="status">{{ summaryText() }}</p>
      }
      @if (errorText()) {
        <p role="alert">{{ errorText() }}</p>
      }
    </form>
  `,
})
export class AutomationTurnComponent {
  readonly systemId = input.required<string>();
  readonly saved = output<void>();

  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly message = signal('');
  protected readonly busy = signal(false);
  protected readonly verified = signal(false);
  protected readonly readBlocks = signal('');
  protected readonly summaryText = signal('');
  protected readonly errorText = signal('');

  protected onMessage(event: Event): void {
    const target = event.target;
    if (target instanceof HTMLTextAreaElement) this.message.set(target.value);
  }

  protected send(event: Event): void {
    event.preventDefault();
    const message = this.message().trim();
    if (!message || this.busy()) return;
    this.busy.set(true);
    this.verified.set(false);
    this.readBlocks.set('');
    this.summaryText.set('');
    this.errorText.set('');
    this.canonical
      .automationTurn(this.systemId(), message)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (turn) => this.accept(turn),
        error: (error: unknown) => {
          this.busy.set(false);
          this.errorText.set(this.i18n.t('flow.automation.turn.error', { message: this.errorMessage(error) }));
        },
      });
  }

  private accept(turn: AutomationTurnResponse): void {
    this.readBlocks.set(turn.read.nodes.map((node) => node.type).join(', '));
    this.verified.set(turn.verified);
    if (turn.verified) this.saved.emit();
    if (!turn.run) {
      this.busy.set(false);
      return;
    }
    let polls = 0;
    let misses = 0;
    interval(1500)
      .pipe(
        startWith(0),
        switchMap(() => this.canonical.getRun(turn.run!.id)),
        takeWhile((run) => {
          polls += 1;
          if (!run) misses += 1;
          else misses = 0;
          return polls < 40 && misses < 3 && this.stillRunning(run);
        }, true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (run) => {
          if (run && !this.stillRunning(run)) {
            this.busy.set(false);
            this.summaryText.set(this.summary(run));
            return;
          }
          if (polls >= 40 || misses >= 3) {
            this.busy.set(false);
            if (run) this.summaryText.set(this.summary(run));
            else this.errorText.set(this.i18n.t('flow.automation.turn.stopped'));
          }
        },
        error: () => this.busy.set(false),
      });
  }

  private stillRunning(run: Run | null): boolean {
    return !run || run.status === 'pending' || run.status === 'running';
  }

  private summary(run: Run): string {
    const summary: AutomationRunSummary = summarizeAutomationRun({
      status: run.status,
      checkpoints: run.checkpoints,
      skill_invocations: run.skill_invocations,
    });
    if (summary.kind === 'retrieve' && summary.passage) {
      return this.i18n.t('flow.automation.turn.retrieve', {
        passage: summary.passage,
        source: summary.source || '',
      });
    }
    if (summary.kind === 'retrieve') return this.i18n.t('flow.automation.turn.retrieve.empty');
    if (summary.kind === 'sap_write' && summary.sealed && !summary.called) {
      return this.i18n.t('flow.automation.turn.sealed');
    }
    if (summary.kind === 'sap_write' && summary.called) return this.i18n.t('flow.automation.turn.called');
    if (summary.kind === 'approval_pause') return this.i18n.t('flow.automation.turn.pause');
    return this.i18n.t('flow.automation.turn.run', { status: run.status });
  }

  private errorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detail = error.error?.detail;
      if (typeof detail === 'string' && detail.trim()) return detail;
      if (detail && typeof detail.message === 'string') return detail.message;
    }
    return this.i18n.t('flow.automation.turn.stopped');
  }
}
