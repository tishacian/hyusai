/**
 * `<app-flow-run-controls>` — the execution action cluster.
 *
 * Projected into the toolbar's `[flowToolbarActions]` content seam so the
 * toolbar component itself stays lean. It is a thin view over `FlowRunService`:
 * Simulate (client-side, always available), Execute (real backend run), the
 * Debug-mode cycle (off / step / breakpoints), Replay, the terminal toggle and
 * a Versions trigger. Execute / Debug / Versions are gated on a saved System —
 * on the `/orchestration` scratchpad they are disabled with a "promote first"
 * hint. The component holds no run state and mutates no graph.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  output,
} from '@angular/core';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowRunService } from './flow-run.service';

@Component({
  selector: 'app-flow-run-controls',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  styleUrl: './flow-run-controls.component.scss',
  template: `
    <div class="ck-run" role="group" aria-label="Run controls">
      <button
        type="button"
        class="ck-run__btn"
        (click)="run.simulate()"
        title="Client-side dry run — no backend call"
        aria-label="Simulate"
      >
        <app-icon name="play-circle" [size]="14" /><span>Simulate</span>
      </button>

      <button
        type="button"
        class="ck-run__btn ck-run__btn--accent"
        [disabled]="!run.canExecute() || run.executing()"
        (click)="onExecute()"
        [title]="executeTitle()"
        aria-label="Execute on backend"
      >
        @if (run.executing()) {
          <app-icon name="loader-2" [size]="14" class="ck-run__spin" /><span>Running…</span>
        } @else {
          <app-icon name="play" [size]="14" /><span>{{ run.debugMode() === 'off' ? 'Execute' : 'Debug run' }}</span>
        }
      </button>

      <button
        type="button"
        class="ck-run__btn"
        [class.is-on]="run.debugMode() !== 'off'"
        [disabled]="!run.canExecute()"
        (click)="onCycleDebug()"
        [title]="'Debug mode: ' + run.debugMode() + ' — click to cycle off / step / breakpoints'"
        aria-label="Cycle debug mode"
      >
        <app-icon name="bug" [size]="14" /><span>Debug: {{ run.debugMode() }}</span>
        @if (breakpointCount() > 0) {
          <span class="ck-run__count">{{ breakpointCount() }}</span>
        }
      </button>

      <button
        type="button"
        class="ck-run__btn"
        [disabled]="!run.canReplay()"
        (click)="run.replayRun()"
        title="Replay this run's checkpoints into the terminal"
        aria-label="Replay run"
      >
        <app-icon name="history" [size]="14" /><span>Replay</span>
      </button>

      <button
        type="button"
        class="ck-run__btn"
        [disabled]="!run.canExecute()"
        (click)="onVersions()"
        [title]="run.canExecute() ? 'Open version history' : 'Promote to a System to track versions'"
        aria-label="Versions"
      >
        <app-icon name="git-commit" [size]="14" /><span>Versions</span>
      </button>

      <button
        type="button"
        class="ck-run__btn ck-run__btn--icon"
        [class.is-on]="run.terminalOpen()"
        (click)="run.toggleTerminal()"
        title="Toggle execution terminal"
        aria-label="Toggle terminal"
      >
        <app-icon name="terminal" [size]="14" />
      </button>
    </div>
  `,
})
export class FlowRunControlsComponent {
  protected readonly run = inject(FlowRunService);
  private readonly toastr = inject(ToastrService);

  /** Asks the shell to open the Versions drawer (gated on a saved System). */
  readonly openVersions = output<void>();

  protected readonly breakpointCount = computed(() => this.run.breakpoints().length);

  protected executeTitle(): string {
    if (!this.run.canExecute()) {
      return 'Scratchpad cannot Execute — promote to a System first (To System).';
    }
    return this.run.debugMode() === 'off'
      ? 'Run this flow on the backend — real skill invocations, real Outcome'
      : 'Run with the debugger attached — walker pauses on steps / breakpoints';
  }

  protected onExecute(): void {
    if (!this.run.canExecute()) {
      this.toastr.info(
        'Save this flow to a System first — the scratchpad cannot Execute.',
        'Promote to System',
      );
      return;
    }
    this.run.executeOnBackend();
  }

  protected onCycleDebug(): void {
    const next = this.run.cycleDebugMode();
    if (next === 'breakpoints' && this.run.breakpoints().length === 0) {
      this.toastr.info(
        'Toggle breakpoints with the dot on each node (visible while debug mode is on).',
        'Debugger',
      );
    }
  }

  protected onVersions(): void {
    if (!this.run.canExecute()) {
      this.toastr.info(
        'Version history is tracked per System — promote this scratchpad first.',
        'Versions',
      );
      return;
    }
    this.openVersions.emit();
  }
}
