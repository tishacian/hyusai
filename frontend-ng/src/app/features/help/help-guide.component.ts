import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from "@angular/core";
import { toSignal } from "@angular/core/rxjs-interop";
import { ActivatedRoute } from "@angular/router";
import { NavLinkDirective } from "@app/shared/cockpit";
import { ApiService } from "@app/core/api.service";
import { I18nService } from "@app/core/i18n.service";
import { HelpService } from "@app/core/help.service";
@Component({
  selector: "app-help-guide",
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective],
  template: `<main class="ck-surface guide">
    <nav>
      <a [navLink]="{ surface: 'work' }">{{ i18n.t("experience.adoption.back") }}</a>
      @for (lang of languages; track lang) {
        <button
          type="button"
          [attr.aria-pressed]="help.language() === lang"
          (click)="help.setLanguage(lang)"
        >
          {{ lang.toUpperCase() }}
        </button>
      }
    </nav>
    @if (guide(); as g) {
      <h1>{{ g.title }}</h1>
      @for (p of g.paragraphs; track $index) {
        <p>{{ p }}</p>
      }
    } @else if (error()) {
      <p role="alert">{{ i18n.t("experience.adoption.guide_error") }}</p>
      <button type="button" (click)="load()">
        {{ i18n.t("common.retry") }}
      </button>
    } @else {
      <p role="status">{{ i18n.t("common.loading") }}</p>
    }
  </main>`,
  styles: [
    `
      .guide {
        max-width: 48rem;
        margin: 2rem auto;
        padding: 2rem;
      }
      p {
        line-height: 1.7;
        margin: 1rem 0;
      }
      h1 {
        font-size: 1.7rem;
        margin: 1rem 0;
      }
      nav {
        display: flex;
        gap: 1rem;
        align-items: center;
      }
      button {
        min-height: 2.5rem;
        padding: 0.5rem;
      }
      @media (max-width: 600px) {
        .guide {
          padding: 1rem;
          margin: 0.5rem;
        }
      }
    `,
  ],
})
export class HelpGuideComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  readonly help = inject(HelpService);
  private readonly params = toSignal(this.route.paramMap, {
    initialValue: this.route.snapshot.paramMap,
  });
  private readonly guideId = computed(() => this.params().get("guideId") || "");
  readonly languages = ["en", "fr"] as const;
  readonly guide = signal<{ title: string; paragraphs: string[] } | null>(null);
  readonly error = signal(false);
  constructor() {
    effect(() => {
      this.help.language();
      this.guideId();
      this.load();
    });
  }
  load(): void {
    const id = this.guideId(),
      language = this.help.language();
    this.error.set(false);
    this.guide.set(null);
    this.api
      .get<{
        title: string;
        paragraphs: string[];
      }>(`/help-content/guides/${encodeURIComponent(id)}`, { language })
      .subscribe({
        next: (v) => {
          if (id === this.guideId() && language === this.help.language())
            this.guide.set(v);
        },
        error: () => {
          if (id === this.guideId() && language === this.help.language())
            this.error.set(true);
        },
      });
  }
}
