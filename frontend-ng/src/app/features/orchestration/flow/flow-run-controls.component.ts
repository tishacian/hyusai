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
  effect,
  input,
  inject,
  output,
  untracked,
} from '@angular/core';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { FlowRunService } from './flow-run.service';
import { FlowStore } from './flow.store';
import { ingressPrefillText, resolveIngressNode } from './flow-ingress-prefill';

@Component({
  selector: 'app-flow-run-controls',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  styleUrl: './flow-run-controls.component.scss',
  template: `
    <div class="ck-run" role="group" [attr.aria-label]="i18n.t('flow.run.aria')">
      @if (!compact()) {
      <span
        class="ck-run__runtime"
        [attr.data-mode]="run.runtimeMode() ?? 'unknown'"
        [title]="run.executionSurfaceLabel() + ' · ' + run.runtimeModeLabel()"
      >
        {{ run.executionSurfaceLabel() }} · {{ run.runtimeModeLabel() }}
      </span>
      }

      @if (!compact()) {
        <button
          type="button"
          class="ck-run__btn"
          (click)="run.simulate()"
          [title]="i18n.t('flow.run.simulate.hint')"
          [attr.aria-label]="i18n.t('flow.run.simulate')"
        >
          <app-icon name="play-circle" [size]="14" /><span>{{ i18n.t('flow.run.simulate') }}</span>
        </button>
      }

      <button
        type="button"
        class="ck-run__btn ck-run__btn--accent"
        [disabled]="!run.canExecute() || run.executing()"
        (click)="run.openInputEditor()"
        [title]="executeTitle()"
        [attr.aria-label]="i18n.t('flow.run.execute.aria')"
      >
        @if (run.executing()) {
          <app-icon name="loader-2" [size]="14" class="ck-run__spin" /><span>{{
            i18n.t('flow.run.execute.running')
          }}</span>
        } @else {
          <app-icon name="play" [size]="14" /><span>{{ executeLabel() }}</span>
        }
      </button>

      @if (!compact()) {
        <button
          type="button"
          class="ck-run__btn"
          [class.is-on]="run.debugMode() !== 'off'"
          [disabled]="!run.canDebug() && run.debugMode() === 'off'"
          (click)="onCycleDebug()"
          [title]="debugTitle()"
          [attr.aria-label]="i18n.t('flow.run.debug.aria')"
        >
          <app-icon name="bug" [size]="14" /><span>{{
            i18n.t('flow.run.debug', { mode: run.debugMode() })
          }}</span>
          @if (breakpointCount() > 0) {
            <span class="ck-run__count">{{ breakpointCount() }}</span>
          }
        </button>
      }

      @if (!compact()) {
        <button
          type="button"
          class="ck-run__btn"
          [disabled]="!run.canReplay()"
          (click)="run.replayRun()"
          [title]="i18n.t('flow.run.replay.hint')"
          [attr.aria-label]="i18n.t('flow.run.replay.aria')"
        >
          <app-icon name="history" [size]="14" /><span>{{ i18n.t('flow.run.replay') }}</span>
        </button>
      }

      @if (!compact()) {
        <button
          type="button"
          class="ck-run__btn"
          [disabled]="!run.canUseSystemActions()"
          (click)="onVersions()"
          [title]="
            run.canUseSystemActions()
              ? i18n.t('flow.run.versions.hint')
              : i18n.t('flow.run.versions.blocked')
          "
          [attr.aria-label]="i18n.t('flow.run.versions')"
        >
          <app-icon name="git-commit" [size]="14" /><span>{{ i18n.t('flow.run.versions') }}</span>
        </button>
      }

      <button
        type="button"
        class="ck-run__btn ck-run__btn--icon"
        [class.is-on]="run.terminalOpen()"
        (click)="run.toggleTerminal()"
        [title]="i18n.t('flow.run.terminal')"
        [attr.aria-label]="i18n.t('flow.run.terminal.aria')"
      >
        <app-icon name="terminal" [size]="14" />
      </button>
    </div>

    @if (run.inputEditorOpen()) {
      <div class="ck-run-input" role="presentation">
        <button
          type="button"
          class="ck-run-input__backdrop"
          [attr.aria-label]="i18n.t('flow.run.input.close')"
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
              <h2 id="ck-run-input-title">{{ i18n.t('flow.run.input.title') }}</h2>
            </div>
            <button
              type="button"
              class="ck-run-input__close"
              [attr.aria-label]="i18n.t('flow.run.input.close')"
              [disabled]="run.executing()"
              (click)="run.closeInputEditor()"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </header>

          <p class="ck-run-input__hint">{{ i18n.t('flow.run.input.hint') }}</p>
          @if (prefillSource(); as entry) {
            <p class="ck-run-input__hint" data-testid="run-input-prefill-source">
              {{ i18n.t('flow.run.input.prefill') }} <code>{{ entry }}</code>
            </p>
          }
          @if (run.draftTestMode()) {
            <label class="ck-run-input__label" for="ck-run-input-entry">
              {{ i18n.t('flow.run.input.entry') }}
            </label>
            <select
              id="ck-run-input-entry"
              class="ck-run-input__select"
              [value]="run.selectedDraftIngressId()"
              (change)="onDraftIngressChange($event)"
              data-testid="draft-test-entry-select"
            >
              <option value="" disabled>{{ i18n.t('flow.run.input.entry.choose') }}</option>
              @for (entry of run.draftTestIngresses(); track entry.ingress_id) {
                <option [value]="entry.ingress_id">
                  {{ entry.label }} · {{ entry.kind }} · {{ entry.ingress_id }}
                </option>
              }
            </select>
            @if (run.draftIngressSelectionError(); as selectionError) {
              <p
                class="ck-run-input__selection-error"
                role="alert"
                data-testid="draft-test-entry-error"
              >
                {{ selectionError }}
              </p>
            } @else if (run.selectedDraftTestIngress(); as entry) {
              <p class="ck-run-input__selection-evidence">
                {{ i18n.t('flow.run.input.entry.authority') }}
                <code>{{ entry.ingress_id }}</code>
                (<code>{{ entry.kind }}</code>)
              </p>
            }
          }
          <label class="ck-run-input__label" for="ck-run-input-json">{{
            i18n.t('flow.run.input.json')
          }}</label>
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
              {{ i18n.t('flow.run.input.cancel') }}
            </button>
            <button
              type="button"
              class="is-primary"
              [disabled]="!run.canSubmitInput()"
              (click)="run.submitInputEditor()"
            >
              @if (run.executing()) {
                <app-icon name="loader-2" [size]="14" class="ck-run__spin" />
                {{ i18n.t('flow.run.input.dispatching') }}
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
  readonly i18n = inject(I18nService);
  private readonly store = inject(FlowStore);
  private readonly toastr = inject(ToastrService);
  readonly compact = input(false);

  /** Asks the shell to open the Versions drawer (gated on a saved System). */
  readonly openVersions = output<void>();

  protected readonly breakpointCount = computed(() => this.run.breakpoints().length);

  /** Label of the entry point whose contract produced the current prefill, when
   * one did. An auto-filled editor has to say where its content came from. */
  protected readonly prefillSource = computed<string | null>(() => {
    if (!this.run.inputEditorOpen()) return null;
    const node = resolveIngressNode(this.store.snapshot(), this.selectedIngressId());
    if (!node || !ingressPrefillText(this.store.snapshot(), node.id)) return null;
    return node.label || node.id;
  });

  /** Untouched text: the service's own empty default, or the last skeleton
   * this component wrote. Anything else is operator authorship. */
  private lastPrefill = '';

  constructor() {
    effect(() => {
      if (!this.run.inputEditorOpen()) return;
      const prefill = ingressPrefillText(this.store.snapshot(), this.selectedIngressId());
      if (!prefill) return;
      untracked(() => {
        const current = this.run.inputText().trim();
        if (current !== '{}' && current !== this.lastPrefill) return;
        this.lastPrefill = prefill;
        this.run.updateInputText(prefill);
      });
    });
  }

  /** In draft test-runs the operator picks the ingress explicitly; a published
   * run enters through the Flow's only source or through none unambiguously. */
  private selectedIngressId(): string | null {
    return this.run.draftTestMode()
      ? this.run.selectedDraftTestIngress()?.ingress_id ?? null
      : null;
  }

  protected executeTitle(): string {
    if (this.compact()) {
      return this.run.canExecute()
        ? this.i18n.t('flow.run.execute.automation.hint')
        : this.run.executionBlockReason() ?? this.i18n.t('flow.run.execute.unavailable');
    }
    if (!this.run.canExecute()) {
      return this.run.executionBlockReason() ?? this.i18n.t('flow.run.execute.unavailable');
    }
    return this.run.debugMode() === 'off'
      ? this.i18n.t('flow.run.execute.hint', {
          surface: this.run.executionSurfaceLabel(),
        })
      : this.i18n.t('flow.run.execute.hint.debug');
  }

  protected executeLabel(dialog = false): string {
    if (this.compact()) {
      return this.i18n.t(
        dialog ? 'flow.run.input.submit.automation' : 'flow.run.execute.automation',
      );
    }
    if (this.run.debugMode() !== 'off') {
      return this.i18n.t(dialog ? 'flow.run.input.submit.debug' : 'flow.run.execute.debug');
    }
    if (!this.run.draftTestMode()) {
      return this.i18n.t(dialog ? 'flow.run.input.submit' : 'flow.run.execute');
    }
    return this.i18n.t(dialog ? 'flow.run.input.submit.draft' : 'flow.run.execute.draft');
  }

  protected debugTitle(): string {
    if (!this.run.canDebug()) {
      return this.run.runtimeMode() === 'sequential_legacy'
        ? this.i18n.t('flow.run.debug.unavailable.sequential')
        : this.run.executionBlockReason() ?? this.i18n.t('flow.run.debug.unavailable');
    }
    return this.i18n.t('flow.run.debug.hint', { mode: this.run.debugMode() });
  }

  protected onCycleDebug(): void {
    const next = this.run.cycleDebugMode();
    if (next === 'breakpoints' && this.run.breakpoints().length === 0) {
      this.toastr.info(
        this.i18n.t('flow.run.debug.breakpoints.toast'),
        this.i18n.t('flow.run.debug.breakpoints.title'),
      );
    }
  }

  protected onVersions(): void {
    if (!this.run.canUseSystemActions()) {
      this.toastr.info(
        this.i18n.t('flow.run.versions.toast'),
        this.i18n.t('flow.run.versions'),
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
