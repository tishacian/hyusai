import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { HelpService } from '@app/core/help.service';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkBarComponent } from '@app/features/experience/work/work-bar.component';
import {
  HelpOverlayService,
  helpPrefersPanel,
  type HelpNavigationState,
  type HelpOrigin,
} from './help-overlay.service';

/**
 * Full-page help fallback (L16 / UX-045 h2): keeps the Work chrome and names
 * the return origin. Shared links and viewports under 768 px land here;
 * desktop in-app « ? » / `help-guide` links open the panel instead.
 */
@Component({
  selector: 'app-help-guide',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, WorkBarComponent],
  styleUrl: '../experience/work/work.scss',
  template: `
    <div class="xp-work" data-brand-scope [attr.data-theme]="themeMode()">
      <app-work-bar [appContext]="originLabel()" />
      <main class="xp-work-main help-guide" role="main">
        <a class="help-guide-back" [routerLink]="originUrl()">
          {{ i18n.t('experience.help.back', { origin: originLabel() }) }}
        </a>
        <p class="help-guide-crumb ck-mono">
          {{ i18n.t('experience.help.crumb', { name: guideShortLabel() }) }}
        </p>
        <nav class="help-guide-langs" [attr.aria-label]="i18n.t('common.help.language')">
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
          <!-- The guide may be in another language than the interface (WCAG 3.1.2). -->
          <h1 [attr.lang]="help.language()">{{ g.title }}</h1>
          @for (p of g.paragraphs; track $index) {
            <p [attr.lang]="help.language()">{{ p }}</p>
          }
        } @else if (error()) {
          <p role="alert">{{ i18n.t('experience.adoption.guide_error') }}</p>
          <button type="button" class="xp-work-btn" (click)="load()">
            {{ i18n.t('common.retry') }}
          </button>
        } @else {
          <p role="status">{{ i18n.t('common.loading') }}</p>
        }
        @if (canOpenPanel()) {
          <button type="button" class="help-guide-panel-link" (click)="openPanel()">
            {{ i18n.t('experience.help.panel.open_panel') }}
          </button>
        }
      </main>
    </div>
  `,
  styles: `
    .help-guide {
      max-width: 48rem;
      margin: 0 auto;
      padding: 1.5rem 2rem 3rem;
    }
    .help-guide-back {
      display: inline-flex;
      margin-bottom: 1rem;
      color: var(--ck-signal-cool, #67d5f6);
      text-decoration: none;
      font-size: 0.95rem;
    }
    .help-guide-back:hover { text-decoration: underline; }
    .help-guide-crumb {
      margin: 0 0 0.75rem;
      font-size: 10px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ck-fg-4);
    }
    .help-guide-langs {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 1rem;
    }
    .help-guide-langs button {
      min-height: 2.25rem;
      padding: 0.35rem 0.7rem;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-inset);
      color: var(--ck-fg-2);
      cursor: pointer;
    }
    .help-guide-langs button[aria-pressed='true'] {
      color: var(--ck-fg-1);
      border-color: var(--ck-stroke-3);
      background: var(--ck-bg-panel);
    }
    .help-guide h1 {
      font-size: 1.85rem;
      font-weight: 650;
      letter-spacing: -0.02em;
      margin: 0.25rem 0 1rem;
    }
    .help-guide > p {
      line-height: 1.7;
      margin: 0.85rem 0;
      color: var(--ck-fg-2);
    }
    .help-guide-panel-link {
      margin-top: 1.5rem;
      border: 0;
      background: transparent;
      color: var(--ck-signal-cool, #67d5f6);
      text-decoration: underline;
      cursor: pointer;
      padding: 0;
      font-size: 0.95rem;
    }
    @media (max-width: 600px) {
      .help-guide { padding: 1rem; }
    }
  `,
})
export class HelpGuideComponent {
  readonly i18n = inject(I18nService);
  readonly help = inject(HelpService);
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly overlay = inject(HelpOverlayService);
  private readonly workspace = inject(WorkspaceService);
  private readonly theme = inject(ThemeService);

  private readonly params = toSignal(this.route.paramMap, {
    initialValue: this.route.snapshot.paramMap,
  });
  private readonly guideId = computed(() => this.params().get('guideId') || 'start');
  readonly languages = ['en', 'fr'] as const;
  readonly guide = signal<{ title: string; paragraphs: string[] } | null>(null);
  readonly error = signal(false);
  readonly themeMode = computed(() => this.theme.resolved());

  private readonly origin = signal<HelpOrigin>(this.resolveOrigin());

  readonly originLabel = computed(() => this.origin().label);
  readonly originUrl = computed(() => this.origin().url);

  readonly guideShortLabel = computed(() => {
    const key = `experience.help.guide.${this.guideId()}`;
    const label = this.i18n.t(key);
    return label === key ? this.guideId() : label;
  });

  readonly canOpenPanel = computed(() => helpPrefersPanel());

  constructor() {
    effect(() => {
      this.help.language();
      this.guideId();
      this.load();
    });
  }

  openPanel(): void {
    const origin = this.origin();
    void this.router.navigateByUrl(origin.url).then((ok) => {
      if (!ok) return;
      this.overlay.open({
        guideId: this.guideId(),
        originLabel: origin.label,
        originUrl: origin.url,
      });
    });
  }

  load(): void {
    const id = this.guideId();
    const language = this.help.language();
    this.error.set(false);
    this.guide.set(null);
    this.api
      .get<{ title: string; paragraphs: string[] }>(
        `/help-content/guides/${encodeURIComponent(id)}`,
        { language },
      )
      .subscribe({
        next: (v) => {
          if (id === this.guideId() && language === this.help.language()) {
            this.guide.set(v);
          }
        },
        error: () => {
          if (id === this.guideId() && language === this.help.language()) {
            this.error.set(true);
          }
        },
      });
  }

  private resolveOrigin(): HelpOrigin {
    const state = (this.router.currentNavigation()?.extras.state
      ?? (typeof history !== 'undefined' ? history.state : null)) as HelpNavigationState | null;
    if (state?.helpOrigin?.label && state.helpOrigin.url) {
      return state.helpOrigin;
    }
    const workspace = this.workspace.current()?.name?.trim();
    return {
      label: workspace || this.i18n.t('experience.work.title'),
      url: '/work',
    };
  }
}
