/**
 * NAWA WE — the service desk knowledge assistant.
 *
 * What this screen is for, in one sentence: the requests that need an answer
 * rather than an action. The password-reset surface next door executes; this one
 * quotes. They share a source of truth — the identity rule the agent enforces is
 * a paragraph in the same library this panel cites — which is the point worth
 * making in front of a service desk team.
 *
 * Every answer is shown with the passages it stood on, and an answer the library
 * does not support is shown as unsupported. Both are deliberate: a desk that
 * cannot tell a sourced answer from a fluent one will eventually act on a
 * fluent one.
 */
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  NAWA_APP_NAME,
  NAWA_APP_SUBTITLE,
  NAWA_LOGO,
} from './nawa-itsd.model';
import { NawaThemeToggleComponent } from './nawa-theme-toggle.component';
import { NawaAssistantService } from './nawa-assistant.service';
import { projectTurn, SUGGESTED_QUESTIONS, type AssistantTurn } from './nawa-assistant';

@Component({
  selector: 'app-nawa-assistant',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent, NawaThemeToggleComponent],
  styleUrls: ['./nawa-theme.scss', './nawa-assistant.component.scss'],
  host: { '[attr.data-theme]': 'theme()' },
  template: `
    <header class="nawa-header">
      <img class="nawa-logo" [src]="logo()" alt="NAWA" />
      <div class="nawa-header-copy">
        <h1 class="nawa-title">{{ appName }} · IT Service Desk</h1>
        <span class="nawa-subtitle">{{ subtitle }} — knowledge assistant</span>
      </div>
      <div class="nawa-header-spacer"></div>
      <app-nawa-theme-toggle />
      <a class="nawa-link" routerLink="/nawa/itsd">
        <ck-glyph name="focus" [size]="12" />
        Service catalogue
      </a>
      @if (platform()) {
        <a class="nawa-link" routerLink="/knowledge">
          <ck-glyph name="cube" [size]="12" />
          Library view
        </a>
      }
    </header>

    <div class="as-body">
      <section class="as-main">
        <div class="as-transcript" #transcript>
          @if (turns().length === 0 && !pending()) {
            <div class="as-empty">
              <strong>Ask the service desk library.</strong>
              <span>
                Answers are drawn from the published service desk policies and shown with the
                passage they rest on. When the library does not cover a question, the assistant
                says so instead of answering.
              </span>
            </div>
          }

          @for (turn of turns(); track $index) {
            <article class="as-turn">
              <p class="as-question">
                <ck-glyph name="focus" [size]="12" />
                {{ turn.question }}
              </p>
              <div
                class="as-answer"
                [class.as-answer-unsupported]="turn.unsupported"
              >{{ turn.answer }}</div>

              <div class="as-meta">
                @if (turn.unsupported) {
                  <span class="as-meta-strong">No supporting passage in the library</span>
                } @else {
                  <span class="as-meta-strong">
                    {{ turn.citations.length }}
                    {{ turn.citations.length === 1 ? 'passage' : 'passages' }} cited
                  </span>
                }
                @if (turn.elapsed) {
                  <span>· answered in {{ turn.elapsed }}</span>
                }
              </div>

              @if (turn.citations.length) {
                <ul class="as-sources">
                  @for (citation of turn.citations; track citation.index) {
                    <li class="as-source">
                      <span class="as-source-index">[{{ citation.index }}]</span>
                      <div>
                        <div class="as-source-document">{{ citation.document }}</div>
                        <div class="as-source-passage">{{ citation.passage }}</div>
                      </div>
                    </li>
                  }
                </ul>
              }
            </article>
          }

          @if (pending()) {
            <div class="as-pending">
              <span class="as-pending-dot"></span>
              Searching the service desk library…
            </div>
          }
        </div>

        <div class="as-composer">
          <textarea
            [value]="draft()"
            (input)="draft.set($any($event.target).value)"
            (keydown.enter)="onEnter($event)"
            placeholder="Ask about passwords, access, joiners, priorities…"
            rows="2"
            aria-label="Ask the service desk library"
          ></textarea>
          <button
            type="button"
            class="nawa-button"
            [disabled]="pending() || !draft().trim()"
            (click)="ask(draft())"
          >
            <ck-glyph name="pulse" [size]="13" />
            Ask
          </button>
        </div>
      </section>

      <aside class="as-side">
        <span class="as-side-label">Frequent questions</span>
        @for (question of suggestions; track question) {
          <button
            type="button"
            class="as-suggestion"
            [disabled]="pending()"
            (click)="ask(question)"
          >
            {{ question }}
          </button>
        }

        <div class="as-library">
          <div class="as-library-title">What it reads</div>
          The published service desk library: password and account policy, multi-factor
          authentication, remote access, joiners/movers/leavers, priorities and targets, software
          and licences.
        </div>
      </aside>
    </div>
  `,
})
export class NawaAssistantComponent {
  private readonly assistant = inject(NawaAssistantService);
  private readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);

  protected readonly appName = NAWA_APP_NAME;
  protected readonly subtitle = NAWA_APP_SUBTITLE;
  protected readonly suggestions = SUGGESTED_QUESTIONS;

  protected readonly theme = inject(ThemeService).businessResolved;
  protected readonly logo = computed(() => NAWA_LOGO[this.theme()]);

  /** The pivot into the platform belongs to whoever administers the workspace. */
  protected readonly platform = computed(
    () => this.workspace.isAdmin() || this.route.snapshot.queryParamMap.get('platform') === '1',
  );

  protected readonly turns = signal<AssistantTurn[]>([]);
  protected readonly pending = signal(false);
  protected readonly draft = signal('');

  protected onEnter(event: Event): void {
    // Enter sends, Shift+Enter breaks the line: what everyone expects of a
    // single-line-ish composer.
    if ((event as KeyboardEvent).shiftKey) return;
    event.preventDefault();
    this.ask(this.draft());
  }

  protected ask(question: string): void {
    const query = question.trim();
    if (!query || this.pending()) return;
    this.draft.set('');
    this.pending.set(true);
    const started = Date.now();

    this.assistant.ask(query).subscribe({
      next: (payload) => {
        const turn = payload
          ? projectTurn(query, payload, Date.now() - started)
          : {
              question: query,
              answer:
                'The assistant is unavailable right now. The service desk library was not searched, ' +
                'so nothing here should be treated as an answer.',
              citations: [],
              elapsed: '',
              unsupported: true,
            };
        this.turns.update((list) => [...list, turn]);
        this.pending.set(false);
      },
      error: () => this.pending.set(false),
    });
  }
}
