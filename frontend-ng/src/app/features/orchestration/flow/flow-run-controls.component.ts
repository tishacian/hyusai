/**
 * `<app-flow-run-controls>` — the execution action cluster.
 *
 * Projected into the toolbar's `[flowToolbarActions]` content seam so the
 * toolbar component itself stays lean. It is a thin view over `FlowRunService`:
 * Simulate (client-side, always available), Execute through an ephemeral JSON
 * input editor (real backend run), the
 * Debug-mode cycle (off / step / breakpoints), Replay, the terminal toggle and
 * a Versions trigger. Execute / Debug / Versions are gated on a saved System —
 * on the `/orchestration` scratchpad they are disabled with a "promote first"
 * hint. Execute additionally requires a clean saved hash and a matching
 * server-derived runtime manifest. The component holds no graph state and
 * mutates no graph.
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
      <span
        class="ck-run__runtime"
        [attr.data-mode]="run.runtimeMode() ?? 'unknown'"
        [title]="run.executionSurfaceLabel() + ' · ' + run.runtimeModeLabel()"
      >
        {{ run.executionSurfaceLabel() }} · {{ run.runtimeModeLabel() }}
      </span>

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
        (click)="run.openInputEditor()"
        [title]="executeTitle()"
        aria-label="Execute on backend"
      >
        @if (run.executing()) {
          <app-icon name="loader-2" [size]="14" class="ck-run__spin" /><span>Running…</span>
        } @else {
          <app-icon name="play" [size]="14" /><span>{{ executeLabel() }}</span>
        }
      </button>

      <button
        type="button"
        class="ck-run__btn"
        [class.is-on]="run.debugMode() !== 'off'"
        [disabled]="!run.canDebug() && run.debugMode() === 'off'"
        (click)="onCycleDebug()"
        [title]="debugTitle()"
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
        [disabled]="!run.canUseSystemActions()"
        (click)="onVersions()"
        [title]="run.canUseSystemActions() ? 'Open version history' : 'Promote or finish loading the System to track versions'"
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

    @if (run.inputEditorOpen()) {
      <div class="ck-run-input" role="presentation">
        <button
          type="button"
          class="ck-run-input__backdrop"
          aria-label="Close Run input editor"
          (click)="run.closeInputEditor()"
        ></button>
        <section
          class="ck-run-input__dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ck-run-input-title"
          (click)="$event.stopPropagation()"
        >
          <header class="ck-run-input__header">
            <div>
              <p class="ck-run-input__eyebrow">{{ run.runtimeModeLabel() }}</p>
              <h2 id="ck-run-input-title">Run input</h2>
            </div>
            <button
              type="button"
              class="ck-run-input__close"
              aria-label="Close Run input editor"
              [disabled]="run.executing()"
              (click)="run.closeInputEditor()"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </header>

          <p class="ck-run-input__hint">
            Enter the JSON object exposed to the Flow as <code>input_ref</code>.
            Debug metadata is injected separately by the Builder.
          </p>
          @if (run.draftTestMode()) {
            <label class="ck-run-input__label" for="ck-run-input-ingress">
              Draft ingress
            </label>
            <select
              id="ck-run-input-ingress"
              class="ck-run-input__select"
              [value]="run.selectedDraftIngressId()"
              (change)="onDraftIngressChange($event)"
              data-testid="draft-test-ingress-select"
            >
              <option value="" disabled>Select an ingress…</option>
              @for (ingress of run.draftTestIngresses(); track ingress.ingress_id) {
                <option [value]="ingress.ingress_id">
                  {{ ingress.label }} · {{ ingress.kind }} · {{ ingress.ingress_id }}
                </option>
              }
            </select>
            @if (run.draftIngressSelectionError(); as ingressError) {
              <p
                class="ck-run-input__selection-error"
                role="alert"
                data-testid="draft-test-ingress-error"
              >
                {{ ingressError }}
              </p>
            } @else if (run.selectedDraftTestIngress(); as ingress) {
              <p class="ck-run-input__selection-evidence">
                Request authority: <code>{{ ingress.ingress_id }}</code>
                (<code>{{ ingress.kind }}</code>)
              </p>
            }
          }
          <label class="ck-run-input__label" for="ck-run-input-json">JSON object</label>
          <textarea
            id="ck-run-input-json"
            class="ck-run-input__editor"
            rows="12"
            spellcheck="false"
            autocomplete="off"
            [value]="run.inputText()"
            (input)="onInputChange($event)"
          ></textarea>

          @if (run.inputValidationError(); as validationError) {
            <p class="ck-run-input__error" role="alert">{{ validationError }}</p>
          } @else if (run.dispatchError(); as dispatchError) {
            <p class="ck-run-input__error" role="alert">{{ dispatchError }}</p>
          }

          <footer class="ck-run-input__actions">
            <button type="button" (click)="run.closeInputEditor()" [disabled]="run.executing()">
              Cancel
            </button>
            <button
              type="button"
              class="is-primary"
              [disabled]="!run.canSubmitInput()"
              (click)="run.submitInputEditor()"
            >
              @if (run.executing()) {
                <app-icon name="loader-2" [size]="14" class="ck-run__spin" /> Dispatching…
              } @else {
                <app-icon name="play" [size]="14" />
                {{ executeLabel(true) }}
              }
            </button>
          </footer>
        </section>
      </div>
    }
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
      return this.run.executionBlockReason() ?? 'Execute unavailable.';
    }
    return this.run.debugMode() === 'off'
      ? `${this.run.executionSurfaceLabel()} — real skill invocations against the explicitly selected Flow authority`
      : 'Run with the debugger attached — walker pauses on steps / breakpoints';
  }

  protected executeLabel(dialog = false): string {
    if (this.run.debugMode() !== 'off') return dialog ? 'Start debug run' : 'Debug run';
    return this.run.executionSurfaceLabel() === 'Draft test-run'
      ? dialog
        ? 'Start draft test-run'
        : 'Test draft'
      : 'Execute';
  }

  protected debugTitle(): string {
    if (!this.run.canDebug()) {
      return this.run.runtimeMode() === 'sequential_legacy'
        ? 'Debug unavailable: LEGACY · SEQUENTIAL has no DAG debugger.'
        : this.run.executionBlockReason() ?? 'Debug unavailable.';
    }
    return `Debug mode: ${this.run.debugMode()} — click to cycle off / step / breakpoints`;
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
    if (!this.run.canUseSystemActions()) {
      this.toastr.info(
        'Version history is tracked per System — promote this scratchpad first.',
        'Versions',
      );
      return;
    }
    this.openVersions.emit();
  }

  protected onInputChange(event: Event): void {
    this.run.updateInputText((event.target as HTMLTextAreaElement).value);
  }

  protected onDraftIngressChange(event: Event): void {
    this.run.chooseDraftTestIngress((event.target as HTMLSelectElement).value);
  }
}
