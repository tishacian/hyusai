import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from "@angular/core";
import { JsonPipe } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { I18nService } from "@app/core/i18n.service";
import { CanonicalApiService } from "@app/core/canonical-api.service";
import { NavigationProfileService } from "@app/core/navigation-profile.service";
import { NavLinkDirective } from "@app/shared/cockpit";
import { AssistantPilotService } from "./assistant-pilot.service";
import {
  AssistantObjectContextService,
  type AssistantObjectContext,
} from "./assistant-object-context.service";
import type { NavLinkInput } from "@app/core/navigation.catalog";

@Component({
  selector: "app-assistant-pilot",
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NavLinkDirective, JsonPipe],
  template: ` <section class="pilot" [attr.aria-label]="t('companion')">
    @if (activeContext(); as context) {
      <div class="object-context">
        <div>
          <span>{{ t("object_context." + context.type) }}</span>
          <strong>{{ context.id }}</strong>
          @if (context.node_id) {
            <small>· {{ context.node_id }}</small>
          }
        </div>
        <a [navLink]="contextLink(context)">{{ t("object_context.open") }}</a>
        <button type="button" (click)="togglePin(context)">
          {{ isPinned(context) ? t("object_context.unpin") : t("object_context.pin") }}
        </button>
      </div>
    }
    <fieldset [disabled]="pilot.busy()">
      <legend>{{ t("scope") }}</legend>
      <p>{{ t("scope_hint") }}</p>
      @for (system of pilot.systems(); track system.system_id) {
        <label class="system"
          ><input
            type="checkbox"
            [checked]="pilot.systemIds().includes(system.system_id)"
            (change)="toggle(system.system_id)"
          />
          {{ system.name }}</label
        >
        @if (canInspect()) {
          <a
            [navLink]="{ type: 'system', lens: 'build', ref: system.system_id }"
            >{{ t("inspect") }}</a
          >
        }
      }
      @if (!pilot.systemIds().length) {
        <p>{{ t("empty_scope") }}</p>
      }
      @if (proofText()) {
        <p role="status">{{ proofText() }}</p>
      }
    </fieldset>
    <div class="turns" aria-live="polite" aria-relevant="additions">
      @for (turn of pilot.turns(); track $index) {
        <article>
          @if (turn.object_context; as context) {
            <p class="turn-context">
              {{ t("object_context." + context.type) }} · {{ context.id }}
            </p>
          }
          <p class="question">{{ turn.question }}</p>
          <p class="answer">{{ turn.response.answer }}</p>
          @if (turn.response.finish_reason === "tool_turn_limit") {
            <p role="status">{{ t("tools_limited") }}</p>
          }
          @for (call of turn.response.tool_calls; track $index) {
            <section class="evidence">
              <strong>{{ t("proof") }} · {{ call.name }}</strong>
              <p>
                {{ call.ok ? "✓" : "!" }} {{ call.error || call.result.status }}
              </p>
              @if (call.name === "read_automation_proof") {
                <p>{{ toolProofLine(call.result) }}</p>
              }
              @if (canInspect()) {
                @if (call.result.system_id; as id) {
                  <a [navLink]="{ type: 'system', lens: 'build', ref: id }">{{
                    t("inspect")
                  }}</a>
                  @if (call.name === "inspect_system") {
                    <a
                      [navLink]="{
                        type: 'system',
                        lens: 'build',
                        ref: id,
                        facet: 'design',
                      }"
                      >{{ t("inspect_design") }}</a
                    >
                    <a [navLink]="{ leaf: 'help-guide', ref: 'systems' }">{{
                      t("build_guide")
                    }}</a>
                  }
                }
                @if (call.result.run_id; as id) {
                  <a [navLink]="{ type: 'run', lens: 'operate', ref: id }"
                    >{{ t("inspect_run") }} · {{ id.slice(0, 8) }}</a
                  >
                }
                @for (run of call.result.runs || []; track run.run_id) {
                  @if (run.run_id; as id) {
                    <a [navLink]="{ type: 'run', lens: 'operate', ref: id }"
                      >{{ t("inspect_run") }} · {{ id.slice(0, 8) }}</a
                    >
                  }
                }
              }
              @if (call.result.awaiting_gate; as gate) {
                <p>{{ gate.prompt }}</p>
                <button
                  type="button"
                  [disabled]="pilot.busy()"
                  (click)="pilot.decide(call.result, 'accept')"
                >
                  {{ t("accept") }}
                </button>
                <button
                  type="button"
                  [disabled]="pilot.busy()"
                  (click)="pilot.decide(call.result, 'reject')"
                >
                  {{ t("reject") }}
                </button>
              }
              <details>
                <summary>{{ t("detail") }}</summary>
                <pre>{{ call.result | json }}</pre>
              </details>
            </section>
          }
        </article>
      }
    </div>
    @if (pilot.error(); as error) {
      <p role="alert">{{ t(error) }}</p>
      @if (pilot.retryRequest()) {
        <button type="button" [disabled]="pilot.busy()" (click)="pilot.retry()">
          {{ t("retry_turn") }}
        </button>
      }
    }
    <form (ngSubmit)="submit()">
      <label for="pilot-prompt">{{ t("request") }}</label>
      <textarea
        id="pilot-prompt"
        name="prompt"
        [(ngModel)]="prompt"
        maxlength="8000"
        rows="3"
        [disabled]="pilot.busy()"
        required
      ></textarea>
      <button
        class="ck-btn-soft"
        type="submit"
        [disabled]="pilot.busy() || !!pilot.retryRequest() || !prompt.trim()"
      >
        {{ pilot.busy() ? i18n.t("common.loading") : t("send") }}
      </button>
      <button type="button" [disabled]="pilot.busy()" (click)="pilot.reset()">
        {{ t("new") }}
      </button>
    </form>
  </section>`,
  styles: [
    `
      button {
        border: 1px solid var(--ck-stroke-2);
        border-radius: 0.4rem;
        padding: 0.5rem 0.85rem;
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel);
        font-weight: 550;
      }
      button[type="submit"]:not(:disabled) {
        background: var(--ck-signal-cool);
        color: var(--ck-on-signal);
      }
      button:disabled {
        opacity: 0.5;
        cursor: default;
      }
      a {
        text-decoration: underline;
        text-underline-offset: 3px;
      }
      :focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 3px;
      }
      :host {
        display: block;
        overflow: auto;
        min-height: 0;
      }
      .pilot {
        padding: 1rem;
        display: grid;
        gap: 1rem;
      }
      fieldset {
        padding: 0.8rem;
        border: 1px solid var(--ck-stroke-2);
      }
      .system {
        display: block;
        margin-top: 0.5rem;
      }
      p {
        line-height: 1.5;
      }
      .answer {
        white-space: pre-wrap;
      }
      .question {
        font-weight: 600;
      }
      .object-context {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.55rem 0.65rem;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 0.4rem;
        background: var(--ck-bg-panel);
        font-size: 0.78rem;
      }
      .object-context > div {
        min-width: 0;
        flex: 1;
      }
      .object-context strong,
      .object-context small {
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .object-context span {
        display: block;
        text-transform: uppercase;
        font-size: 0.65rem;
        letter-spacing: 0.04em;
        opacity: 0.75;
      }
      .turn-context {
        margin: 0 0 0.2rem;
        font-size: 0.72rem;
        opacity: 0.75;
      }
      .evidence {
        padding: 0.6rem;
        margin: 0.6rem 0;
        border: 1px solid var(--ck-stroke-2);
      }
      a {
        display: inline-block;
        margin: 0.3rem;
      }
      pre {
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        font-size: 0.75rem;
      }
      textarea {
        display: block;
        width: 100%;
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-base);
        color: inherit;
      }
      button {
        margin: 0.4rem 0.4rem 0.4rem 0;
        min-height: 2.5rem;
      }
      form {
        position: sticky;
        bottom: 0;
        background: var(--ck-bg-base);
        padding: 0.5rem 0;
      }
    `,
  ],
})
export class AssistantPilotComponent {
  readonly pilot = inject(AssistantPilotService);
  readonly i18n = inject(I18nService);
  private readonly profile = inject(NavigationProfileService);
  readonly canInspect = computed(() => {
    const profile = this.profile.effective();
    return (
      !profile.active || profile.advancedAccess === "link" || profile.admin
    );
  });
  readonly initialSystemId = input<string | null>(null);
  private readonly objectContext = inject(AssistantObjectContextService);
  private readonly canonical = inject(CanonicalApiService);
  readonly activeContext = this.objectContext.effective;
  readonly proofText = signal("");
  private proofTicket = 0;
  prompt = "";
  constructor() {
    this.pilot.load();
    effect(() => {
      const id = this.initialSystemId();
      if (id) this.pilot.select([id]);
    });
    effect(() => {
      const context = this.activeContext();
      if (context?.system_id && !this.pilot.systemIds().includes(context.system_id)) {
        this.pilot.select([...this.pilot.systemIds(), context.system_id]);
      }
    });
    effect(() => {
      const ids = this.pilot.systemIds();
      const ticket = ++this.proofTicket;
      if (ids.length !== 1) {
        this.proofText.set("");
        return;
      }
      const systemId = ids[0];
      this.canonical.automationProof(systemId).subscribe({
        next: (proof) => {
          if (ticket === this.proofTicket) this.proofText.set(this.automationProofLine(proof));
        },
        error: () => {
          if (ticket === this.proofTicket) this.proofText.set(this.i18n.t("flow.proof.absent"));
        },
      });
    });
  }
  t(key: string): string {
    return this.i18n.t("experience.adoption." + key);
  }
  automationProofLine(proof: { status?: string } | null | undefined): string {
    return this.i18n.t(proof?.status === "present" ? "flow.proof.present" : "flow.proof.absent");
  }
  toolProofLine(result: { [key: string]: unknown }): string {
    const proof = result["proof"];
    if (!proof || typeof proof !== "object") return this.automationProofLine(null);
    return this.automationProofLine(proof as { status?: string });
  }
  toggle(id: string): void {
    const ids = this.pilot.systemIds();
    this.pilot.select(
      ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id],
    );
  }
  submit(): void {
    this.pilot.send(this.prompt, this.activeContext());
    this.prompt = "";
  }

  isPinned(context: AssistantObjectContext | null): boolean {
    return this.objectContext.isPinned(context);
  }

  togglePin(context: AssistantObjectContext | null): void {
    if (!context) return;
    if (this.objectContext.isPinned(context)) this.objectContext.unpin();
    else this.objectContext.pin(context);
  }

  contextLink(context: AssistantObjectContext): NavLinkInput {
    if (context.type === "system") return { type: "system", ref: context.id };
    if (context.type === "run") return { type: "run", ref: context.id };
    if (context.run_id)
      return { type: "skill_invocation", ref: context.id, runId: context.run_id };
    return { type: "system", ref: context.system_id || context.id };
  }
}
