import {
  ChangeDetectionStrategy,
  Component,
  inject,
  input,
  signal,
  viewChild,
} from "@angular/core";
import { RouterLink } from "@angular/router";
import { AdoptionService, type AdoptionStep } from "@app/core/adoption.service";
import { I18nService } from "@app/core/i18n.service";
import { WorkspaceService } from "@app/core/workspace.service";
import { NavigationProfileService } from "@app/core/navigation-profile.service";
import { ChatPanelComponent } from "@app/features/chat/chat-panel.component";
import { NavLinkDirective } from "@app/shared/cockpit";
import { WorkBarComponent } from "./work-bar.component";
import { WorkAppHeaderComponent } from "./work-app-header.component";
@Component({
  selector: "app-adoption-journey",
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ChatPanelComponent, NavLinkDirective],
  template: `@if (adoption.enabled()) {
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
  }`,
  styles: [
    `
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
  readonly started = signal(false);
  readonly runId = signal<string | null>(null);
  readonly steps: AdoptionStep[] = ["example", "question", "source", "result"];
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
    step: "question" | "source" | "answer";
    runId?: string;
    sessionId?: string;
  }): void {
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
    <div class="xp-work" data-brand-scope data-theme="light">
      <app-work-bar />
      <app-work-app-header
        [title]="i18n.t('experience.adoption.resume')"
        [eyebrow]="i18n.t('experience.work.eyebrow.getting_started')"
        defaultBackKey="experience.work.back_apps"
      />
      <main class="xp-work-main" style="max-width:70rem;margin:auto;padding:1rem" role="main" aria-labelledby="work-app-title">
        <app-adoption-journey [full]="true" />
      </main>
    </div>
  `,
})
export class AdoptionPageComponent {
  readonly i18n = inject(I18nService);
}
