import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from "@angular/core";
import { RouterLink } from "@angular/router";
import { AdoptionService, type AdoptionStep } from "@app/core/adoption.service";
import {
  CLIENT_STEPS,
  NORTHFORGE_STEPS,
  chosenSource,
  currentClientStep,
  sourceHasDocuments,
} from "@app/core/adoption-journey";
import { I18nService } from "@app/core/i18n.service";
import { ThemeService } from "@app/core/theme.service";
import { WorkspaceService } from "@app/core/workspace.service";
import { NavigationProfileService } from "@app/core/navigation-profile.service";
import { ChatPanelComponent } from "@app/features/chat/chat-panel.component";
import { NavLinkDirective } from "@app/shared/cockpit";
import { WorkBarComponent } from "./work-bar.component";
import { WorkAppHeaderComponent } from "./work-app-header.component";
import { ClientOnboardingComponent } from "./client-onboarding.component";
@Component({
  selector: "app-adoption-journey",
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ChatPanelComponent, NavLinkDirective, ClientOnboardingComponent],
  template: `@if (adoption.enabled()) {
    @if (compact()) {
      @if (adoption.isClientJourney()) {
        <!-- L34 — the workspace's own sources: shown only when the server says the member can read or fill one. -->
        @if (adoption.compactVisible() && clientStep(); as step) {
          <aside class="xp-work-adoption-card" aria-labelledby="adoption-compact-title" data-testid="onboarding-card">
            <div>
              <h2 id="adoption-compact-title">{{ i18n.t("experience.work.onboarding.compact.title") }}</h2>
              <p>{{ i18n.t("experience.work.onboarding.compact.step", { n: clientStepNumber(), step: i18n.t("experience.work.onboarding.step." + step + ".title") }) }}</p>
            </div>
            <div class="xp-work-adoption-card-actions">
              <a class="xp-work-btn" [routerLink]="['/work', 'getting-started']">
                {{ i18n.t(adoption.progress()?.completed_steps?.length ? "experience.work.onboarding.resume" : "experience.work.onboarding.start") }}
              </a>
              <button
                type="button"
                class="xp-work-btn xp-work-btn-icon"
                [attr.aria-label]="i18n.t('experience.adoption.dismiss')"
                [disabled]="adoption.saving()"
                (click)="adoption.update({ dismissed: true })"
              ><span aria-hidden="true">×</span></button>
            </div>
          </aside>
        }
      } @else if (adoption.exampleAvailable() && !adoption.progress()?.dismissed) {
      <!-- The card only promises what this workspace can run: the example needs the Showcase corpus. -->
        <aside class="xp-work-adoption-card" aria-labelledby="adoption-compact-title">
          <div>
            <h2 id="adoption-compact-title">{{ i18n.t("experience.adoption.title") }}</h2>
            <p>{{ i18n.t("experience.adoption.compact.body") }}</p>
          </div>
          <div class="xp-work-adoption-card-actions">
            <a class="xp-work-btn xp-work-btn-primary" [routerLink]="['/work', 'getting-started']">
              {{ i18n.t(adoption.progress()?.completed_steps?.length ? "experience.adoption.resume" : "experience.adoption.start") }}
            </a>
            <button
              type="button"
              class="xp-work-btn xp-work-btn-icon"
              [attr.aria-label]="i18n.t('experience.adoption.dismiss')"
              [disabled]="adoption.saving()"
              (click)="adoption.update({ dismissed: true })"
            >×</button>
          </div>
        </aside>
      }
    } @else if (full() && !adoption.progress()) {
      @if (adoption.error()) {
        <p role="alert">{{ i18n.t("experience.adoption.error") }}</p>
        <button type="button" class="xp-onb-retry" (click)="adoption.load()">{{ i18n.t("common.retry") }}</button>
      } @else {
        <p role="status">{{ i18n.t("common.loading") }}</p>
      }
    } @else if (full() && adoption.isClientJourney()) {
      <app-client-onboarding />
    } @else {
    <section
      class="ck-surface journey"
      style="padding:1.5rem;margin:1rem 0"
      aria-labelledby="adoption-title"
    >
      <h2 id="adoption-title">{{ i18n.t("experience.adoption.title") }}</h2>
      <p>{{ i18n.t("experience.adoption.intro") }}</p>
      <a [routerLink]="['/help', 'start']">{{
        i18n.t("experience.adoption.help")
      }}</a>
      @if (adoption.error()) {
        <p role="alert">{{ i18n.t("experience.adoption.error") }}</p>
        <button type="button" (click)="adoption.load()">
          {{ i18n.t("common.retry") }}
        </button>
      }
      @if (!full()) {
        <a class="ck-btn-soft" [routerLink]="['/work', 'getting-started']">{{
          i18n.t(adoption.progress()?.completed_steps?.length ? "experience.adoption.resume" : "experience.adoption.start")
        }}</a>
      } @else {
        <fieldset>
          <legend>{{ i18n.t("experience.adoption.persona") }}</legend>
          @for (p of personas; track p) {
            <button
              type="button"
              [attr.aria-pressed]="adoption.progress()?.persona === p"
              [disabled]="adoption.saving()"
              (click)="adoption.update({ persona: p })"
            >
              {{ i18n.t("experience.adoption." + p) }}
            </button>
          }
        </fieldset>
        <ol>
          @for (step of steps; track step) {
            <li>
              <span
                [attr.aria-label]="
                  adoption.progress()?.completed_steps?.includes(step)
                    ? i18n.t('experience.adoption.done')
                    : null
                "
                >{{
                  adoption.progress()?.completed_steps?.includes(step)
                    ? "✓"
                    : "○"
                }}</span
              >
              {{ i18n.t("experience.adoption." + step) }}
            </li>
          }
        </ol>
        @if (adoption.exampleAvailable()) {
          <button
            type="button"
            class="ck-btn-soft"
            [disabled]="started()"
            (click)="start()"
          >
            {{ i18n.t("experience.adoption.start") }}
          </button>
          @if (started()) {
            <div style="height:65vh;min-height:24rem">
              <app-chat-panel
                [compact]="true"
                [freshSession]="true"
                [resumeSessionId]="adoption.progress()?.session_id || null"
                [initialPrompt]="
                  adoption.progress()?.session_id
                    ? null
                    : i18n.t('experience.adoption.question_text')
                "
                [knowledgeScopeOverride]="'agentium-showcase-notices'"
                [assistantProfileKey]="'showcase_advisor'"
                (adoptionInteraction)="onInteraction($event)"
              />
            </div>
          }
          @if (runId() || adoption.progress()?.run_id; as id) {
            <button type="button" (click)="recoverResult()">
              {{ i18n.t("experience.adoption.result") }}
            </button>
            @if (
              !profile.effective().active ||
              profile.effective().advancedAccess === "link" ||
              workspace.isAdmin()
            ) {
              <a [navLink]="{ type: 'run', lens: 'operate', ref: id }">{{
                i18n.t("experience.adoption.inspect_run")
              }}</a>
            }
          }
        } @else {
          <p>{{ i18n.t("experience.adoption.unavailable") }}</p>
        }
      }
      <button
        type="button"
        [disabled]="adoption.saving()"
        (click)="
          adoption.update({ dismissed: !adoption.progress()?.dismissed })
        "
      >
        {{
          i18n.t(
            adoption.progress()?.dismissed
              ? "experience.adoption.resume"
              : "experience.adoption.dismiss"
          )
        }}
      </button>
    </section>
    }
  }`,
  styles: [
    `
      .xp-work-adoption-card {
        display: flex;
        flex-direction: column;
        gap: 12px;
        max-width: 320px;
        padding: 16px;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 6px;
        background: var(--ck-bg-panel);
        color: var(--ck-fg-1);
      }
      .xp-work-adoption-card h2 {
        margin: 0 0 6px;
        font-size: 15px;
        font-weight: 650;
      }
      .xp-work-adoption-card p {
        margin: 0;
        color: var(--ck-fg-3);
        font-size: 13px;
        line-height: 1.45;
      }
      .xp-work-adoption-card-actions {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .xp-work-adoption-card .xp-work-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 32px;
        padding: 0 12px;
        border: 1px solid var(--ck-stroke-3);
        border-radius: 4px;
        background: transparent;
        color: var(--ck-fg-1);
        font: 600 13px/1.2 var(--ck-font-sans);
        text-decoration: none;
        cursor: pointer;
      }
      .xp-work-adoption-card .xp-work-btn-icon {
        width: 32px;
        padding: 0;
      }
      .xp-work-adoption-card :focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 2px;
      }
      .journey h2 {
        font-size: 1.25rem;
        font-weight: 650;
        margin-bottom: 0.5rem;
      }
      .journey p {
        line-height: 1.6;
        margin: 0.5rem 0 1rem;
      }
      .journey a,
      .journey button {
        display: inline-flex;
        align-items: center;
        min-height: 2.75rem;
        padding: 0.55rem 0.9rem;
        margin: 0.5rem 0.6rem 0.5rem 0;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 0.4rem;
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel);
        font-weight: 550;
      }
      .journey a:hover,
      .journey button:hover {
        border-color: var(--ck-signal-cool);
      }
      .journey button:disabled {
        opacity: 0.55;
        cursor: default;
      }
      .journey fieldset {
        margin: 1rem 0;
        padding: 0.75rem;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 0.4rem;
      }
      .journey [aria-pressed="true"] {
        background: var(--ck-signal-cool);
        color: var(--ck-on-signal);
      }
      .journey ol {
        display: grid;
        gap: 0.6rem;
        margin: 1rem 0;
      }
      .journey li {
        line-height: 1.5;
      }
      .journey :focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 3px;
      }
    `,
  ],
})
export class AdoptionJourneyComponent {
  readonly adoption = inject(AdoptionService);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);
  readonly profile = inject(NavigationProfileService);
  readonly chat = viewChild(ChatPanelComponent);
  readonly full = input(false);
  readonly compact = input(false);
  readonly started = signal(false);
  readonly runId = signal<string | null>(null);
  readonly steps: readonly AdoptionStep[] = NORTHFORGE_STEPS;
  /** L34 — the client journey's current step; `null` once decided (the card then leaves). */
  readonly clientStep = computed(() => {
    const progress = this.adoption.progress();
    return currentClientStep(progress?.completed_steps ?? [], sourceHasDocuments(chosenSource(progress)));
  });
  readonly clientStepNumber = computed(() => {
    const step = this.clientStep();
    return step ? CLIENT_STEPS.indexOf(step) + 1 : CLIENT_STEPS.length;
  });
  readonly personas = ["operator", "builder", "executive"] as const;
  start(): void {
    this.adoption.update({ completed_step: "example", dismissed: false });
    this.started.set(true);
  }
  recoverResult(): void {
    const id = this.adoption.progress()?.session_id;
    if (id && this.chat()) {
      this.chat()!.openChatSession(id);
      this.adoption.update({ completed_step: "result" });
    } else this.started.set(true);
  }
  onInteraction(e: {
    step: "question" | "source" | "answer" | "decision";
    runId?: string;
    sessionId?: string;
  }): void {
    // The NorthForge example has no decision step.
    if (e.step === "decision") return;
    if (e.step === "answer") {
      this.runId.set(e.runId || null);
      this.adoption.update({ session_id: e.sessionId, run_id: e.runId });
    } else this.adoption.update({ completed_step: e.step });
  }
}
@Component({
  selector: "app-adoption-page",
  standalone: true,
  imports: [AdoptionJourneyComponent, RouterLink, WorkBarComponent, WorkAppHeaderComponent],
  styleUrl: "./work.scss",
  template: `
    <div class="xp-work" data-brand-scope [attr.data-theme]="theme.resolved()">
      <app-work-bar />
      <app-work-app-header
        [title]="i18n.t(!adoption.isClientJourney() ? 'experience.adoption.resume' : adoption.journeyAvailable() ? 'experience.work.onboarding.title' : 'experience.work.onboarding.title_unavailable')"
        [eyebrow]="i18n.t('experience.work.eyebrow.getting_started')"
        [description]="adoption.isClientJourney() && adoption.journeyAvailable() ? i18n.t('experience.work.onboarding.intro') : null"
        defaultBackKey="experience.work.back_apps"
      />
      <main
        class="xp-work-main"
        [style.max-width]="adoption.isClientJourney() ? '78rem' : '70rem'"
        style="margin:auto;padding:1rem"
        role="main"
        aria-labelledby="work-app-title"
      >
        <app-adoption-journey [full]="true" />
      </main>
    </div>
  `,
})
export class AdoptionPageComponent {
  readonly i18n = inject(I18nService);
  readonly adoption = inject(AdoptionService);
  readonly theme = inject(ThemeService);
}
